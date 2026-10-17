"""Update download, verification and installer handoff with fake transports and processes."""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib import error, response

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from my_video_manager import update_manifest
from my_video_manager.core import AppCore
from my_video_manager.update_check import InstalledUpdateInfo, UpdateCheckResult
from my_video_manager.update_http import UpdateCheckError, UrllibUpdateHttp
from my_video_manager.update_install import (
    INSTALLER_ARGUMENTS, INSTALLER_TIMEOUT_MS, PreparedUpdate, SubprocessHelperLauncher, UpdateInstallError,
    helper_environment, start_install, update_busy_state,
)


NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
FINGERPRINT = 'a' * 64
BASE = 'https://github.com/vananaHope/my-video-manager-releases/releases/download/v1.2.3'
PATCH = b'patch installer'
FULL = b'full installer bytes' * 5000  # several 64 KiB reads through the real transport


def asset(name, body):
    return {'filename': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


class FakeHttp:
    """Serves one signed release; download writes the asset body in two chunks."""

    def __init__(self, key, *, version='1.2.3', patch=True):
        self.calls = []
        self.document = {
            'schema_version': 1, 'version': version, 'runtime_fingerprint': FINGERPRINT,
            'previous_runtime_fingerprint': FINGERPRINT if patch else None, 'patch_available': patch,
            'patch': asset('MyVideoManager-Patch-1.2.3.exe', PATCH) if patch else None,
            'full': asset('MyVideoManager-Setup-1.2.3.exe', FULL),
        }
        self.bodies = {'MyVideoManager-Patch-1.2.3.exe': PATCH, 'MyVideoManager-Setup-1.2.3.exe': FULL}
        self.key = key
        self.sign()
        self.failure = None

    def sign(self):
        self.data = json.dumps(self.document).encode()
        self.signature = self.key.sign(self.data)

    def get(self, url, *, max_bytes):
        self.calls.append(url)
        return self.signature if url.endswith('.sig') else self.data

    def download(self, url, *, size, write, cancellation=None):
        self.calls.append(url)
        body = self.bodies[url.rsplit('/', 1)[1]]
        write(body[:len(body) // 2])
        if self.failure is not None:
            raise self.failure
        write(body[len(body) // 2:])


@pytest.fixture
def key(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', key.public_key().public_bytes_raw())
    return key


@pytest.fixture
def http(key):
    return FakeHttp(key)


def installed(version='1.0.0', fingerprint=FINGERPRINT):
    return lambda: InstalledUpdateInfo(version, fingerprint)


def make_core(directory):
    return AppCore(media=object(), clock=lambda: NOW, database=directory / 'library.sqlite3',
                   update_installation=installed())


@pytest.fixture
def core(tmp_path):
    return make_core(tmp_path)


def checked(kind='patch', version='1.2.3', *, stale=False):
    return UpdateCheckResult(NOW, kind, '1.0.0', version, 12, stale=stale)


def downloads(core):
    return core.database.parent / 'updates' / 'download'


def files(core):
    folder = downloads(core)
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def test_patch_is_ready_only_after_size_and_hash_match(core, http):
    progress = []
    result = core.download_update(checked(), http=http, progress=lambda done, total: progress.append((done, total)))
    assert result.status == 'ready' and result.failure_reason is None
    update = result.update
    assert (update.version, update.kind, update.size) == ('1.2.3', 'patch', len(PATCH))
    assert update.path == downloads(core) / 'MyVideoManager-Patch-1.2.3.exe'
    assert update.path.read_bytes() == PATCH
    assert progress[-1] == (len(PATCH), len(PATCH)) and len(progress) == 2
    assert files(core) == ['MyVideoManager-Patch-1.2.3.exe']


def test_urls_come_from_signed_filename_and_the_same_tag(core, http):
    core.download_update(checked(), http=http)
    assert http.calls == [f'{BASE}/update-manifest.json', f'{BASE}/update-manifest.json.sig',
                          f'{BASE}/MyVideoManager-Patch-1.2.3.exe']


@pytest.mark.parametrize('fingerprint,full,expected', [
    (FINGERPRINT, False, 'patch'),
    ('d' * 64, False, 'full'),   # the runtime changed since the check: never trust result.kind
    (None, False, 'full'),
    (FINGERPRINT, True, 'full'),  # retry after a failed patch
])
def test_asset_choice_uses_verified_manifest_and_installed_runtime(core, http, fingerprint, full, expected):
    core.update_installation = installed(fingerprint=fingerprint)
    result = core.download_update(checked(), http=http, full=full)
    assert result.status == 'ready' and result.update.kind == expected


def test_full_kind_downloads_full_even_when_check_said_patch_unavailable(core, key):
    http = FakeHttp(key, patch=False)
    result = core.download_update(checked('full'), http=http)
    assert result.update.kind == 'full' and result.update.path.read_bytes() == FULL


@pytest.mark.parametrize('damage,reason', [
    (lambda document: document['patch'].update(sha256='f' * 64), 'hash_mismatch'),
    (lambda document: document['patch'].update(size=len(PATCH) + 1), 'size_mismatch'),
    (lambda document: document['patch'].update(size=len(PATCH) - 1), 'size_mismatch'),
])
def test_mismatched_file_is_not_ready_and_is_deleted(core, http, damage, reason):
    damage(http.document)
    http.sign()
    result = core.download_update(checked(), http=http)
    assert result == type(result)('failed', failure_reason=reason)
    assert files(core) == []


def test_unsigned_or_other_release_is_rejected_before_asset_request(core, http):
    http.signature = bytes(64)
    assert core.download_update(checked(), http=http).failure_reason == 'invalid_signature'
    other = FakeHttp(http.key, version='1.2.4')
    assert core.download_update(checked(), http=other).failure_reason == 'release_version_mismatch'
    assert not any(url.endswith('.exe') for url in http.calls + other.calls)
    assert files(core) == []


@pytest.mark.parametrize('result,version,reason', [
    (None, '1.0.0', 'no_update'),
    (checked('none'), '1.0.0', 'no_update'),
    (checked('failed', None), '1.0.0', 'no_update'),
    (checked(stale=True), '1.0.0', 'no_update'),
    (checked(), '1.2.3', 'not_newer'),
    (checked(), '2.0.0', 'not_newer'),
])
def test_no_download_without_a_current_newer_update(core, http, result, version, reason):
    core.update_installation = installed(version)
    assert core.download_update(result, http=http).failure_reason == reason
    assert http.calls == []


@pytest.mark.parametrize('failure,status,reason', [
    (UpdateCheckError('cancelled'), 'cancelled', None),
    (UpdateCheckError('network'), 'failed', 'network'),
    (TimeoutError(), 'failed', 'timeout'),
    (RuntimeError('C:\\secret path'), 'failed', 'download_failed'),
])
def test_cancel_or_failure_mid_download_removes_partial_file(core, http, failure, status, reason):
    http.failure = failure
    result = core.download_update(checked(), http=http)
    assert (result.status, result.failure_reason, result.update) == (status, reason, None)
    assert files(core) == []


def test_new_download_replaces_leftovers(core, http):
    downloads(core).mkdir(parents=True)
    (downloads(core) / 'old.exe.partial').write_bytes(b'x')
    (downloads(core) / 'MyVideoManager-Patch-1.2.2.exe').write_bytes(b'x')
    core.download_update(checked(), http=http)
    assert files(core) == ['MyVideoManager-Patch-1.2.3.exe']


class FakeOpener:
    def __init__(self, *steps):
        self.steps = iter(steps)

    def open(self, req, *, timeout):
        step = next(self.steps)
        if isinstance(step, Exception):
            raise step
        return step


def reply(data, *, headers=None):
    result = response.addinfourl(BytesIO(data), headers or {}, BASE, 200)
    result.msg = 'test response'
    return result


class RealTransport(FakeHttp):
    """Metadata from FakeHttp; the installer through UrllibUpdateHttp.download."""

    def __init__(self, key, opener):
        super().__init__(key)
        self.transport = UrllibUpdateHttp(opener=opener)

    def download(self, url, **options):
        self.calls.append(url)
        return self.transport.download(url, **options)


def test_cancellation_through_real_transport_stops_reading_and_cleans_up(core, key):
    stream = reply(FULL, headers={'Content-Length': str(len(FULL))})
    http = RealTransport(key, FakeOpener(stream))
    core.update_installation = installed(fingerprint=None)
    cancellation = threading.Event()
    progress = []

    def report(done, total):
        progress.append(done)
        cancellation.set()

    result = core.download_update(checked(), http=http, progress=report, cancellation=cancellation)
    assert result.status == 'cancelled'
    assert progress == [65536] and stream.closed
    assert files(core) == []


def test_real_transport_streams_full_installer_with_redirect(core, key):
    moved = error.HTTPError(BASE, 302, 'found', {'Location': 'https://release-assets.githubusercontent.com/x'},
                            BytesIO())
    http = RealTransport(key, FakeOpener(moved, reply(FULL)))
    core.update_installation = installed(fingerprint=None)
    result = core.download_update(checked(), http=http)
    assert result.status == 'ready' and result.update.path.read_bytes() == FULL


@pytest.mark.parametrize('body,headers,reason', [
    (FULL + b'x', {}, 'response_too_large'),
    (FULL[:-1], {}, 'invalid_response'),
    (FULL, {'Content-Length': str(len(FULL) + 1)}, 'response_too_large'),
], ids=['longer', 'shorter', 'declared-longer'])
def test_real_transport_caps_at_manifest_size(core, key, body, headers, reason):
    http = RealTransport(key, FakeOpener(reply(body, headers=headers)))
    core.update_installation = installed(fingerprint=None)
    assert core.download_update(checked(), http=http).failure_reason == reason
    assert files(core) == []


def test_transport_reports_local_write_failure_as_storage():
    def write(chunk):
        raise OSError('disk full')
    with pytest.raises(UpdateCheckError, match='^storage$'):
        UrllibUpdateHttp(opener=FakeOpener(reply(b'abc'))).download(BASE, size=3, write=write)


def entry(state, kind='translation'):
    return SimpleNamespace(state=state, kind=kind)


@pytest.mark.parametrize('playing,transcriptions,translations,blocking,waiting', [
    (False, [], [], (), (0, 0)),
    (True, [], [], ('playback',), (0, 0)),
    (False, [entry('transcribing'), entry('queued')], [], ('transcription',), (1, 0)),
    (False, [], [entry('translating')], ('translation',), (0, 0)),
    (False, [], [entry('translating', 'refinement')], ('refinement',), (0, 0)),
    # queued and held work resumes after the restart: information, not a blocker
    (False, [entry('queued'), entry('failed')], [entry('queued'), entry('held'), entry('failed')], (), (1, 2)),
    (True, [entry('transcribing')], [entry('translating'), entry('translating', 'refinement')],
     ('playback', 'transcription', 'translation', 'refinement'), (0, 0)),
])
def test_busy_state_separates_running_work_from_waiting_items(playing, transcriptions, translations,
                                                              blocking, waiting):
    state = update_busy_state(playing=playing, transcriptions=transcriptions, translations=translations)
    assert state.blocking == blocking
    assert (state.waiting_transcriptions, state.waiting_translations) == waiting


def test_core_busy_state_reads_playback_and_queues(core, monkeypatch):
    assert core.busy_reasons_for_update().blocking == ()
    monkeypatch.setattr(core, 'playback', SimpleNamespace(session=object()))
    monkeypatch.setattr(core, 'subtitle_queue', lambda: (entry('transcribing'),))
    monkeypatch.setattr(core, 'translation_queue', lambda: (entry('held'),))
    state = core.busy_reasons_for_update()
    assert state.blocking == ('playback', 'transcription') and state.waiting_translations == 1


class FakeHelper:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.killed = False

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True


class FakeLauncher:
    """Simulates the helper: it reads the plan and signals ready, unless told not to."""

    def __init__(self, *, ready=True, exit_code=None):
        self.ready, self.helper = ready, FakeHelper(exit_code)
        self.commands = []

    def start(self, command, *, cwd):
        self.commands.append((list(command), cwd))
        self.plan = json.loads(Path(command[command.index('-PlanPath') + 1]).read_text())
        self.record_existed = (Path(cwd) / 'install.json').exists()
        if self.ready:
            Path(self.plan['ready']).write_text('ready')
        return self.helper


@pytest.fixture
def prepared(core, http):
    return core.download_update(checked(), http=http).update


RELAUNCH = ('C:/Programs/MyVideoManager/my-video-manager.exe', ['--data-dir', 'C:/data with space'])


def tokens(command_line):
    """Windows command-line tokens; these tests never embed quotes inside a token."""
    return [token[1:-1] if token.startswith('"') else token for token in shlex.split(command_line, posix=False)]


def installer_tokens(core):
    return [*INSTALLER_ARGUMENTS, f'/LOG={(core.database.parent / "updates").resolve() / "installer.log"}']


@pytest.mark.parametrize('folder', ['data', 'data dir with space'])
def test_handoff_starts_helper_with_silent_installer_and_relaunch(tmp_path, http, folder):
    core = make_core(tmp_path / folder)
    prepared = core.download_update(checked(), http=http).update
    launcher = FakeLauncher()
    core.prepare_update_install(prepared, launcher=launcher, relaunch=RELAUNCH, pid=4242)
    command, cwd = launcher.commands[0]
    assert command[0].lower().endswith('system32\\windowspowershell\\v1.0\\powershell.exe')
    assert command[command.index('-ExecutionPolicy') + 1] == 'Bypass'
    script = Path(command[command.index('-File') + 1])
    assert script.read_text(encoding='ascii').startswith('# Written by my-video-manager')
    plan = launcher.plan
    assert plan['app_pid'] == 4242
    assert Path(plan['installer']) == prepared.path.resolve()
    assert tokens(plan['installer_arguments']) == installer_tokens(core)
    assert (plan['sha256'], plan['installer_timeout_ms']) == (prepared.sha256, INSTALLER_TIMEOUT_MS)
    assert plan['program'] == RELAUNCH[0]
    assert plan['arguments'] == '--data-dir "C:/data with space"'
    assert launcher.record_existed  # recorded before the helper could run
    outcome = core.last_update_install()
    assert (outcome.version, outcome.kind, outcome.status, outcome.started_at) == ('1.2.3', 'patch', 'incomplete', NOW)


@pytest.mark.parametrize('launcher,reason', [
    (FakeLauncher(ready=False, exit_code=1), 'helper_failed'),
    (FakeLauncher(ready=False), 'helper_not_ready'),
])
def test_helper_that_never_gets_ready_is_killed_and_forgotten(core, prepared, launcher, reason):
    with pytest.raises(UpdateInstallError, match=f'^{reason}$'):
        core.prepare_update_install(prepared, launcher=launcher, relaunch=RELAUNCH, pid=1, ready_timeout=0.05)
    assert launcher.helper.killed
    assert core.last_update_install() is None


def test_handoff_rejects_missing_or_changed_installer(core, prepared, tmp_path):
    launcher = FakeLauncher()
    outside = tmp_path / prepared.path.name
    outside.write_bytes(PATCH)
    for update in (PreparedUpdate('1.2.3', 'patch', outside, prepared.size, prepared.sha256),
                   PreparedUpdate('1.2.3', 'patch', prepared.path, prepared.size + 1, prepared.sha256)):
        with pytest.raises(UpdateInstallError, match='^installer_missing$'):
            core.prepare_update_install(update, launcher=launcher, relaunch=RELAUNCH, pid=1)
    prepared.path.unlink()
    with pytest.raises(UpdateInstallError, match='^installer_missing$'):
        core.prepare_update_install(prepared, launcher=launcher, relaunch=RELAUNCH, pid=1)
    assert launcher.commands == []


def test_source_run_never_hands_off(core, prepared):
    launcher = FakeLauncher()
    with pytest.raises(UpdateInstallError, match='^source_run$'):
        core.prepare_update_install(prepared, launcher=launcher)
    assert launcher.commands == []


def finish(core, prepared, result):
    core.prepare_update_install(prepared, launcher=FakeLauncher(), relaunch=RELAUNCH, pid=1)
    if result is not None:
        (core.database.parent / 'updates' / 'install-result.json').write_text(json.dumps(result))
    return core.last_update_install()


def test_patch_rejection_is_recorded_for_full_retry(core, prepared):
    outcome = finish(core, prepared, {'exit_code': 7})
    assert (outcome.status, outcome.failure_reason, outcome.exit_code) == ('failed', 'patch_rejected', 7)
    assert outcome.retry_full


@pytest.mark.parametrize('result,installed_version,status,reason,retry', [
    ({'exit_code': 0}, '1.0.0', 'installed', None, False),
    ({'exit_code': 4}, '1.0.0', 'failed', 'installer_failed', True),
    # the patch never ran: retry the same (small) patch, not the full installer
    ({'error': 'app_did_not_exit'}, '1.0.0', 'failed', 'app_did_not_exit', False),
    ({'error': 'installer_start_failed'}, '1.0.0', 'failed', 'installer_start_failed', False),
    ({'error': 'installer_timeout'}, '1.0.0', 'failed', 'installer_timeout', False),
    ({'error': 'hash_mismatch'}, '1.0.0', 'failed', 'hash_mismatch', False),
    ({'error': 'installer_unreadable'}, '1.0.0', 'failed', 'installer_unreadable', False),
    ({'error': 'C:\\not a code'}, '1.0.0', 'incomplete', 'no_result', False),
    (None, '1.0.0', 'incomplete', 'no_result', False),
    (None, '1.2.3', 'installed', None, False),  # result lost, but the new version runs
])
def test_install_outcomes(core, prepared, result, installed_version, status, reason, retry):
    core.update_installation = installed(installed_version)
    outcome = finish(core, prepared, result)
    assert (outcome.status, outcome.failure_reason, outcome.retry_full) == (status, reason, retry)


def test_full_installer_failure_does_not_offer_full_retry(core, key):
    core.update_installation = installed(fingerprint=None)
    update = core.download_update(checked('full'), http=FakeHttp(key)).update
    outcome = finish(core, update, {'exit_code': 7})
    assert (outcome.failure_reason, outcome.retry_full) == ('installer_failed', False)


def test_clear_forgets_outcome_and_removes_installers(core, prepared):
    finish(core, prepared, {'exit_code': 0})
    core.clear_update_install()
    assert core.last_update_install() is None
    assert not (core.database.parent / 'updates').exists()


@pytest.mark.parametrize('record', ['not json', '{}', '{"version": "1.2.3", "kind": "other", '
                                    '"started_at": "2026-10-17T12:00:00+00:00"}',
                                    '{"version": "x", "kind": "patch", "started_at": "2026-10-17T12:00:00+00:00"}'])
def test_damaged_record_reads_as_none(core, record):
    (core.database.parent / 'updates').mkdir()
    (core.database.parent / 'updates' / 'install.json').write_text(record)
    assert core.last_update_install() is None


# The real helper script with stand-in processes: a fake app, a fake installer
# (.cmd) and a fake relaunched app. No real installer or network is involved.
windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell helper')

FAKE_APP = '''
import pathlib, sys, time
ready, order = map(pathlib.Path, sys.argv[1:3])
go = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
deadline = time.monotonic() + 30
while not ready.exists() and time.monotonic() < deadline:
    time.sleep(0.05)
time.sleep(0.5)  # an installer started without waiting would log first
# The test creates go once it has changed files; only then may the app exit.
while go is not None and not go.exists() and time.monotonic() < deadline:
    time.sleep(0.05)
if sys.argv[3] == 'exit':
    with order.open('a') as log:
        log.write('app-exit\\n')
else:
    time.sleep(30)
'''


def stand_ins(core, tmp_path, installer_body='@exit /b 0'):
    order = tmp_path / 'order.log'
    downloads(core).mkdir(parents=True, exist_ok=True)
    installer = downloads(core) / 'MyVideoManager-Patch-1.2.3.exe.cmd'
    installer.write_text(f'@echo install %*>>"{order}"\r\n{installer_body}\r\n')
    relaunch = core.database.parent / 'relaunch.cmd'
    relaunch.write_text(f'@echo relaunch %*>>"{order}"\r\n')
    update = PreparedUpdate('1.2.3', 'patch', installer, installer.stat().st_size,
                            hashlib.sha256(installer.read_bytes()).hexdigest())
    return order, update, (str(relaunch), ['--data-dir', str(core.database.parent)])


def fake_app(core, order, mode, go=None):
    ready = core.database.parent / 'updates' / 'helper-ready'
    return subprocess.Popen([sys.executable, '-c', FAKE_APP, str(ready), str(order), mode,
                             *([] if go is None else [str(go)])])


def wait_for(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'helper did not finish'
        time.sleep(0.1)


def lines(order):
    return [tokens(line) for line in order.read_text().splitlines()] if order.exists() else []


def relaunched(order):
    return any(line[0] == 'relaunch' for line in lines(order))


@windows_only
@pytest.mark.parametrize('exit_code,status,folder', [(0, 'installed', 'data'), (7, 'failed', 'data'),
                                                     (0, 'installed', 'data dir with space')])
def test_real_helper_waits_for_app_then_installs_then_relaunches(tmp_path, exit_code, status, folder):
    core = make_core(tmp_path / folder)
    order, update, relaunch = stand_ins(core, tmp_path, f'@exit /b {exit_code}')
    app = fake_app(core, order, 'exit')
    try:
        core.prepare_update_install(update, relaunch=relaunch, pid=app.pid)
        wait_for(lambda: relaunched(order))
    finally:
        app.kill()
    assert lines(order) == [['app-exit'], ['install', *installer_tokens(core)],
                            ['relaunch', '--data-dir', str(core.database.parent)]]
    outcome = core.last_update_install()
    assert (outcome.status, outcome.exit_code) == (status, exit_code)
    assert outcome.retry_full == (exit_code == 7)


@windows_only
def test_real_helper_does_not_install_while_app_keeps_running(core, tmp_path):
    order, update, relaunch = stand_ins(core, tmp_path)
    app = fake_app(core, order, 'stay')
    result = core.database.parent / 'updates' / 'install-result.json'
    try:
        start_install(core.database.parent, update, pid=app.pid, relaunch=relaunch, started_at=NOW,
                      launcher=SubprocessHelperLauncher(), app_exit_timeout_ms=1500)
        wait_for(result.exists)
    finally:
        app.kill()
    assert not order.exists()  # neither installed nor relaunched
    outcome = core.last_update_install()
    assert (outcome.status, outcome.failure_reason) == ('failed', 'app_did_not_exit')


@windows_only
def test_real_helper_relaunches_even_if_the_result_cannot_be_saved(core, tmp_path):
    order, update, relaunch = stand_ins(core, tmp_path)
    # A directory where the result's temporary file goes makes the write fail.
    (core.database.parent / 'updates' / 'install-result.json.tmp').mkdir(parents=True)
    app = fake_app(core, order, 'exit')
    try:
        core.prepare_update_install(update, relaunch=relaunch, pid=app.pid)
        wait_for(lambda: relaunched(order))
    finally:
        app.kill()
    assert [line[0] for line in lines(order)] == ['app-exit', 'install', 'relaunch']
    assert core.last_update_install().status == 'incomplete'


@windows_only
def test_real_helper_refuses_installer_changed_after_handoff(core, tmp_path):
    order, update, relaunch = stand_ins(core, tmp_path)
    go = tmp_path / 'go'
    app = fake_app(core, order, 'exit', go)
    try:
        core.prepare_update_install(update, relaunch=relaunch, pid=app.pid)
        # The fake app waits for go, so the helper hashes the file only after this change.
        update.path.write_text(f'@echo tampered>>"{order}"\r\n')
        go.write_text('')
        wait_for(lambda: relaunched(order))
    finally:
        app.kill()
    assert [line[0] for line in lines(order)] == ['app-exit', 'relaunch']
    outcome = core.last_update_install()
    assert (outcome.status, outcome.failure_reason, outcome.retry_full) == ('failed', 'hash_mismatch', False)


@windows_only
def test_real_helper_refuses_installer_it_cannot_read(core, tmp_path):
    order, update, relaunch = stand_ins(core, tmp_path)
    go = tmp_path / 'go'
    app = fake_app(core, order, 'exit', go)
    try:
        core.prepare_update_install(update, relaunch=relaunch, pid=app.pid)
        update.path.unlink()
        go.write_text('')
        wait_for(lambda: relaunched(order))
    finally:
        app.kill()
    assert [line[0] for line in lines(order)] == ['app-exit', 'relaunch']
    outcome = core.last_update_install()
    assert (outcome.status, outcome.failure_reason, outcome.retry_full) == ('failed', 'installer_unreadable', False)


POWERSHELL7_MODULES = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'PowerShell' / '7' / 'Modules'


class PowerShell7ModulePathLauncher(SubprocessHelperLauncher):
    """Starts the helper as an app started from PowerShell 7 did before helper_environment."""

    def start(self, command, *, cwd):
        env = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
        # With PowerShell 7's modules first, Windows PowerShell 5.1 has no Get-FileHash.
        env['PSModulePath'] = f'{POWERSHELL7_MODULES};{os.environ.get("PSModulePath", "")}'
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(list(command), cwd=cwd, env=env, creationflags=flags, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@windows_only
@pytest.mark.skipif(not POWERSHELL7_MODULES.is_dir(), reason='PowerShell 7 is not installed')
def test_real_helper_verifies_with_powershell7_module_path(core, tmp_path):
    order, update, relaunch = stand_ins(core, tmp_path)
    app = fake_app(core, order, 'exit')
    try:
        start_install(core.database.parent, update, pid=app.pid, relaunch=relaunch, started_at=NOW,
                      launcher=PowerShell7ModulePathLauncher())
        wait_for(lambda: relaunched(order))
    finally:
        app.kill()
    assert [line[0] for line in lines(order)] == ['app-exit', 'install', 'relaunch']
    assert core.last_update_install().status == 'installed'


def test_helper_environment_drops_inherited_powershell_module_path(monkeypatch):
    monkeypatch.setenv('PSModulePath', r'C:\Program Files\PowerShell\7\Modules')
    monkeypatch.setenv('MVM_KEEP', '1')
    env = helper_environment()
    assert 'PSMODULEPATH' not in {key.upper() for key in env} and env['MVM_KEEP'] == '1'


@windows_only
def test_real_helper_records_stuck_installer_and_does_not_relaunch(core, tmp_path):
    done = f'@ping -n 4 127.0.0.1 >nul\r\n@echo install-done>>"{tmp_path / "order.log"}"'
    order, update, relaunch = stand_ins(core, tmp_path, done)
    app = fake_app(core, order, 'exit')
    result = core.database.parent / 'updates' / 'install-result.json'
    try:
        start_install(core.database.parent, update, pid=app.pid, relaunch=relaunch, started_at=NOW,
                      launcher=SubprocessHelperLauncher(), installer_timeout_ms=1000)
        wait_for(result.exists)
        assert core.last_update_install().failure_reason == 'installer_timeout'
        # The installer is left running; once it ends, still no relaunch has happened.
        wait_for(lambda: ['install-done'] in lines(order))
    finally:
        app.kill()
    assert [line[0] for line in lines(order)] == ['app-exit', 'install', 'install-done']
