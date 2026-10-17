"""앱 수명과 설정 화면에 연결한 업데이트 확인의 공개 동작."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from my_video_manager import update_manifest
from my_video_manager.core import AppCore
from my_video_manager.update_check import LAST_CHECK_KEY, InstalledUpdateInfo
from my_video_manager.update_http import UpdateCheckError
from my_video_manager.web_update_data import FAILURE_MESSAGES, failure_message
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_library_return_ui import Player
from test_startup_scan import Media, settle

SOURCE = Path(__file__).resolve().parents[1] / 'src/my_video_manager'
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


class GatedCheck:
    """작업자에서 부르는 check_for_update. gate가 열릴 때까지 네트워크 대기를 흉내 낸다."""

    def __init__(self, core):
        self.core = core
        self.gate = threading.Event()
        self.gate.set()
        self.threads = []
        self.failure = None
        self.http = None

    def __call__(self):
        self.threads.append(threading.get_ident())
        assert self.gate.wait(20), '업데이트 확인 대기가 풀리지 않았습니다.'
        if self.failure is not None:
            raise self.failure
        return self.core.check_for_update(http=self.http)


class Downloads:
    """내려받기 http 대신 넘긴다. 요청만 기록하고 연결 실패로 끝내 실제 네트워크에 닿지 않는다."""

    def __init__(self):
        self.urls = []

    def get(self, url, *, max_bytes):
        self.urls.append(url)
        raise UpdateCheckError('network')

    def download(self, url, *, size, write, cancellation=None):
        self.urls.append(url)
        raise UpdateCheckError('network')


@pytest.fixture
def app(tmp_path, monkeypatch, qapp):
    core = AppCore(database=tmp_path / 'data/library.sqlite3', media=Media(),
                   clock=lambda: datetime.now(timezone.utc),
                   update_installation=lambda: InstalledUpdateInfo('1.0.0', None))
    check = GatedCheck(core)
    downloads = Downloads()
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []

    def create(*, delay=0, show=True, restart=False):
        # restart: 같은 데이터로 앱을 다시 시작한다. 코어는 실행마다 새로 만든다.
        window = MainWindow(reopen(core) if restart else core, player_factory=Player,
                            update_check_options=dict(startup_delay_ms=delay, check=check,
                                                      install=dict(http=downloads, quit_app=lambda confirmed: False)))
        window.downloads = downloads
        windows.append(window)
        window.subtitles.timer.stop()
        window.translations.timer.stop()
        if show:
            window.show()
        return window

    yield core, check, create
    check.gate.set()
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def reopen(core):
    return AppCore(database=core.database, media=Media(), clock=lambda: datetime.now(timezone.utc),
                   update_installation=lambda: core.update_installation())


def settings(window):
    return window.web_host.controllers['settings']


def update_payload(window):
    return settings(window).payload()['update']


def save(core, **values):
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'current_version': '1.0.0',
                                       'latest_version': '1.0.0', 'download_size': None,
                                       'failure_reason': None, 'kind': 'none', **values})


def test_startup_check_runs_on_worker_after_startup_scan_and_is_saved(app):
    core, check, create = app
    window = create(delay=60_000)
    wait_for(lambda: window._startup_scan_scheduled and not window._startup_scan_timer.isActive())
    # 시작 검사를 띄운 뒤에야 업데이트 확인을 예약하고, 첫 화면을 막지 않게 미룬다.
    assert window.updates._startup.isActive() and check.threads == []
    window.updates._startup.timeout.emit()
    wait_for(lambda: not window.updates.checking)
    assert len(check.threads) == 1 and check.threads[0] != threading.get_ident()
    # 실제 서명 키가 없는 기본 빌드는 요청 없이 조용한 실패로 남는다.
    last = update_payload(window)['last']
    assert last['kind'] == 'failed' and last['failureReason'] == 'invalid_public_key'
    assert last['failureQuiet'] and '서명 키' in last['failureMessage']
    assert not last['stale']


@pytest.mark.parametrize('state', ['recent', 'disabled'])
def test_startup_skips_check_when_not_due(app, state):
    core, check, create = app
    if state == 'recent':
        core.settings.set(LAST_CHECK_KEY, {'checked_at': datetime.now(timezone.utc).isoformat(),
                                           'kind': 'failed', 'current_version': '1.0.0',
                                           'latest_version': None, 'download_size': None,
                                           'failure_reason': 'invalid_public_key'})
    else:
        core.set_automatic_update_check_enabled(False)
    window = create()
    wait_for(lambda: window._startup_scan_scheduled and not window._startup_scan_timer.isActive())
    settle(200)
    assert check.threads == [] and not window.updates.checking


def test_manual_check_does_not_overlap_running_check(app):
    core, check, create = app
    window = create(delay=60_000)
    bridge = settings(window).bridge
    check.gate.clear()
    window.navigate_web_tab('settings')
    assert settings(window).is_active()
    snapshot = json.loads(bridge.checkUpdate())
    assert snapshot['update']['checking']
    wait_for(lambda: len(check.threads) == 1)
    # 진행 중 두 번째 요청(시작 확인 포함)은 새 작업자를 만들지 않고 같은 결과를 기다린다.
    assert json.loads(bridge.checkUpdate())['update']['checking']
    assert not window.updates.start()
    window.updates.check_on_startup()
    settle(100)
    assert len(check.threads) == 1
    changes = []
    bridge.settingsChanged.connect(lambda value: changes.append(json.loads(value)))
    check.gate.set()
    wait_for(lambda: not window.updates.checking)
    assert changes and not changes[-1]['update']['checking']
    assert changes[-1]['update']['last']['failureReason'] == 'invalid_public_key'
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    assert len(check.threads) == 2


def test_quit_does_not_wait_for_pending_check(app):
    core, check, create = app
    window = create(show=False)
    check.gate.clear()
    assert window.updates.start()
    wait_for(lambda: len(check.threads) == 1)
    started = time.monotonic()
    window.tray.quit()
    assert time.monotonic() - started < 2
    assert window.updates.closed and window.updates.checking
    # 종료 뒤 늦게 끝난 확인은 화면 상태를 바꾸지 않고, 시작 확인도 다시 하지 않는다.
    check.gate.set()
    settle(200)
    assert window.updates.checking
    assert not window.updates.start()
    window.updates.check_on_startup()
    assert len(check.threads) == 1


def test_settings_write_failure_is_reported_and_next_check_allowed(app):
    core, check, create = app
    window = create(show=False)
    check.failure = sqlite3.OperationalError('database is locked')
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    status = update_payload(window)
    assert status['error'] == '업데이트 확인 결과를 저장하지 못했습니다: database is locked'
    assert status['last'] is None
    check.failure = None
    assert window.updates.start()
    assert update_payload(window)['error'] == ''
    wait_for(lambda: not window.updates.checking)
    assert update_payload(window)['last']['kind'] == 'failed'


def test_startup_decision_failure_does_not_start_or_raise(app, monkeypatch):
    core, check, create = app
    window = create(show=False)
    monkeypatch.setattr(core, 'should_check_for_update', lambda: (_ for _ in ()).throw(sqlite3.OperationalError('locked')))
    window.updates.check_on_startup()
    assert check.threads == [] and not window.updates.checking


def test_payload_passes_stale_explicitly_and_hides_nothing_else(app):
    core, check, create = app
    window = create(show=False)
    assert update_payload(window) == dict(installedVersion='1.0.0', automatic=True, checking=False,
                                          error='', last=None, skipped=False, noticeVisible=False,
                                          updateAllowed=True)
    save(core, kind='patch', current_version='0.9.0', latest_version='1.2.3', download_size=12)
    last = update_payload(window)['last']
    assert last == dict(checkedAt=NOW.isoformat(), kind='patch', currentVersion='0.9.0',
                        latestVersion='1.2.3', downloadSize=12, failureReason=None,
                        failureMessage='', releaseNotes=None, failureQuiet=False, stale=True)
    # 이전 버전에서 확인한 "업데이트 있음"은 셸 알림으로 쓰지 않는다.
    assert update_payload(window)['noticeVisible'] is False
    assert shell_update(window) == {'notice': None}
    core.update_installation = lambda: InstalledUpdateInfo('0.9.0', None)
    assert update_payload(window)['last']['stale'] is False
    assert update_payload(window)['noticeVisible'] is True
    assert update_payload(window)['installedVersion'] == '0.9.0'


def test_check_slot_reports_storage_error_like_other_slots(app, monkeypatch):
    core, check, create = app
    window = create(show=False)
    monkeypatch.setattr(core, 'last_update_check', lambda: (_ for _ in ()).throw(sqlite3.OperationalError('disk I/O error')))
    assert json.loads(settings(window).bridge.checkUpdate()) == {'error': 'disk I/O error'}
    wait_for(lambda: not window.updates.checking)


def test_automatic_toggle_persists_and_rejects_bad_value(app):
    core, check, create = app
    window = create(show=False)
    bridge = settings(window).bridge
    window.navigate_web_tab('settings')
    assert json.loads(bridge.setAutomaticUpdateCheck(False))['update']['automatic'] is False
    assert not AppCore(database=core.database, media=Media(), clock=lambda: NOW).automatic_update_check_enabled()
    assert json.loads(bridge.setAutomaticUpdateCheck(True))['update']['automatic'] is True


def test_every_failure_code_has_its_own_message():
    codes = set()
    for name in ('update_http.py', 'update_check.py', 'update_manifest.py'):
        text = (SOURCE / name).read_text(encoding='utf-8')
        codes |= set(re.findall(r"(?:UpdateCheckError\(|ManifestError\(|failure_reason=)'([a-z0-9_]+)'", text))
    assert {'network', 'timeout', 'invalid_public_key', 'check_failed', 'unsafe_redirect'} <= codes
    assert codes - set(FAILURE_MESSAGES) == set()


@pytest.mark.parametrize('reason,expected', [
    ('http_503', 'GitHub 서버에 일시적인 문제가 있습니다(HTTP 503). 잠시 뒤 다시 확인하세요.'),
    ('http_418', 'GitHub가 오류를 돌려주었습니다(HTTP 418).'),
    ('future_reason', '확인하지 못했습니다(future_reason).'),
])
def test_unlisted_failure_codes_still_read_as_sentences(reason, expected):
    assert failure_message(reason) == expected


def test_real_public_key_path_is_offline_in_tests(app, monkeypatch):
    core, check, create = app
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'k' * 32)
    window = create(show=False)
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    assert update_payload(window)['last']['failureReason'] == 'network'
    assert update_payload(window)['last']['failureMessage'] == FAILURE_MESSAGES['network']


def notice_only(data):
    """새 버전 알림만 본다. 내려받기·설치 진행(install)은 test_update_install_app에서 확인한다."""
    return {key: value for key, value in data.items() if key != 'install'}


def shell_update(window):
    return notice_only(json.loads(window.web_host.bridge.updateSnapshot()))


def choose(window, name, version):
    return notice_only(json.loads(window.web_host.bridge.updateChoice(name, version)))


@pytest.fixture
def releases(app, monkeypatch):
    """서명한 가짜 릴리스. 버전을 바꿔 가며 "더 새 버전"을 흉내 낸다."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from test_update_check import FakeHttp
    core, check, create = app
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', key.public_key().public_bytes_raw())
    core.update_installation = lambda: InstalledUpdateInfo('1.0.0', 'a' * 64)

    def publish(version, *, patch=True, body='## 수정\n- 재생 문제를 고쳤습니다'):
        check.http = FakeHttp(key, version=version, patch=patch)
        check.http.release['body'] = body
    return publish


def run_check(window):
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)


def test_startup_and_manual_results_raise_shell_notice_on_any_tab(app, releases):
    core, check, create = app
    releases('1.2.3')
    window = create(delay=60_000)
    changes = []
    window.web_host.bridge.shellUpdateChanged.connect(lambda value: changes.append(notice_only(json.loads(value))))
    window.navigate_web_tab('queue')
    window.updates._startup.timeout.emit()
    wait_for(lambda: not window.updates.checking)
    notice = {'version': '1.2.3', 'kind': 'patch', 'downloadSize': 12, 'releaseNotes': '수정\n· 재생 문제를 고쳤습니다'}
    assert changes[-1] == {'notice': notice} and shell_update(window) == {'notice': notice}
    # "지금 확인"의 결과에도 반응한다. 전체 설치이고 노트가 없으면 노트 없이 알린다.
    releases('1.2.4', patch=False, body=None)
    window.navigate_web_tab('settings')
    json.loads(settings(window).bridge.checkUpdate())
    wait_for(lambda: not window.updates.checking)
    assert changes[-1] == {'notice': {'version': '1.2.4', 'kind': 'full', 'downloadSize': 100, 'releaseNotes': None}}
    assert update_payload(window)['noticeVisible'] is True and update_payload(window)['skipped'] is False


def test_later_hides_until_next_check_or_next_start(app, releases):
    core, check, create = app
    releases('1.2.3')
    window = create(show=False)
    run_check(window)
    assert choose(window, 'later', '1.2.3') == {'notice': None}
    assert shell_update(window) == {'notice': None}
    # 설정 구역에는 남고, 건너뛴 것은 아니다.
    assert update_payload(window)['last']['latestVersion'] == '1.2.3'
    assert update_payload(window)['skipped'] is False and update_payload(window)['noticeVisible'] is False
    assert core.skipped_update_version() is None
    # 다음 확인에서 같은 버전이 나오면 다시 알린다.
    run_check(window)
    assert shell_update(window)['notice']['version'] == '1.2.3'
    choose(window, 'later', '1.2.3')
    window.tray.quit()
    # 다음 시작은 확인 시기가 아니어도(24시간 안) 저장된 결과로 다시 알린다.
    restarted = create(show=False, restart=True)
    assert not restarted.core.should_check_for_update()
    assert shell_update(restarted)['notice']['version'] == '1.2.3'


def test_skip_remembers_version_and_newer_version_is_announced(app, releases):
    core, check, create = app
    releases('1.2.3')
    window = create(show=False)
    run_check(window)
    assert choose(window, 'skip', '1.2.3') == {'notice': None}
    assert core.skipped_update_version() == '1.2.3'
    assert update_payload(window)['skipped'] is True
    run_check(window)
    assert shell_update(window) == {'notice': None}
    window.tray.quit()
    restarted = create(show=False, restart=True)
    assert shell_update(restarted) == {'notice': None}
    assert restarted.core.skipped_update_version() == '1.2.3'
    releases('1.3.0')
    run_check(restarted)
    assert shell_update(restarted)['notice']['version'] == '1.3.0'
    assert update_payload(restarted)['skipped'] is False


def test_unskip_from_settings_announces_again(app, releases):
    core, check, create = app
    releases('1.2.3')
    window = create(show=False)
    run_check(window)
    choose(window, 'skip', '1.2.3')
    assert choose(window, 'unskip', '1.2.3')['notice']['version'] == '1.2.3'
    assert core.skipped_update_version() is None
    assert update_payload(window)['skipped'] is False


def test_update_choice_starts_the_download_instead_of_opening_a_browser(app, releases):
    core, check, create = app
    releases('1.2.3')
    window = create(show=False)
    run_check(window)
    requested = []
    window.updates.update_requested.connect(requested.append)
    assert choose(window, 'update', '1.2.3') == {'notice': None}
    assert window.updates.install.phase == 'downloading'
    assert [result.latest_version for result in requested] == ['1.2.3']
    # 내려받기는 그 버전의 서명된 매니페스트부터 다시 받는다(가짜 http는 연결 실패로 끝낸다).
    wait_for(lambda: window.updates.install.phase == 'failed')
    assert window.downloads.urls == [
        'https://github.com/vananaHope/my-video-manager/releases/download/v1.2.3/update-manifest.json']
    assert core.skipped_update_version() is None
    assert not (SOURCE / 'update_controls.py').read_text(encoding='utf-8').count('openUrl')


@pytest.mark.parametrize('name,version', [('skip', '1.2.2'), ('later', '9.9.9'), ('update', '1.2.2'),
                                          ('unskip', '1.2.3'), ('install', '1.2.3')])
def test_choice_for_a_version_no_longer_announced_changes_nothing(app, releases, name, version):
    core, check, create = app
    releases('1.2.3')
    window = create(show=False)
    run_check(window)
    assert 'error' in choose(window, name, version)
    assert shell_update(window)['notice']['version'] == '1.2.3'
    assert core.skipped_update_version() is None and window.updates.install.phase == 'idle'


def test_stale_or_failed_results_never_raise_notice_or_accept_choices(app):
    core, check, create = app
    window = create(show=False)
    save(core, kind='patch', current_version='0.9.0', latest_version='1.2.3', download_size=12)
    assert shell_update(window) == {'notice': None}
    assert 'error' in choose(window, 'update', '1.2.3') and window.updates.install.phase == 'idle'
    run_check(window)  # 서명 키 없는 기본 빌드: 실패 결과
    assert shell_update(window) == {'notice': None}
