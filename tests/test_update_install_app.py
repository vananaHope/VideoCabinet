"""업데이트 선택 뒤의 앱 흐름: 내려받기(진행률·취소) → 설치 전 확인 → 설치 넘기기 → 완전 종료, 다음 실행의 결과 안내.

내려받기는 가짜 http, 보조 프로세스는 가짜 실행기, 앱 종료는 기록만 하는 함수로 바꾼다.
"""
from datetime import datetime, timezone
import itertools
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from my_video_manager.update_check import LAST_CHECK_KEY, InstalledUpdateInfo
from my_video_manager.update_http import UpdateCheckError
from my_video_manager.update_install import HELPER_SCRIPT, update_busy_state
from my_video_manager import update_install_controls
from my_video_manager.web_update_data import (
    DOWNLOAD_FAILURE_MESSAGES, FAILURE_MESSAGES, INSTALL_RESULT_MESSAGES, download_failure_message,
)
from qt_wait import wait_for
from test_library_return_ui import Player
from test_startup_scan import Media
from test_update_install import FINGERPRINT, FULL, PATCH, RELAUNCH, FakeHttp, FakeLauncher, key  # noqa: F401

SOURCE = Path(__file__).resolve().parents[1] / 'src/my_video_manager'
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


class GatedHttp(FakeHttp):
    """작은 조각으로 나눠 보내고, 첫 조각 뒤 gate가 열릴 때까지 기다린다. 조각 사이마다 취소를 본다."""

    def __init__(self, key, **options):
        super().__init__(key, **options)
        self.gate = threading.Event()
        self.gate.set()
        self.downloads = []
        self.chunk = 4

    def download(self, url, *, size, write, cancellation=None):
        self.calls.append(url)
        self.downloads.append(url.rsplit('/', 1)[1])
        body = self.bodies[url.rsplit('/', 1)[1]]
        for start in range(0, len(body), self.chunk):
            if start:
                assert self.gate.wait(20), '내려받기 대기가 풀리지 않았습니다.'
            if cancellation is not None and cancellation.is_set():
                raise UpdateCheckError('cancelled')
            write(body[start:start + self.chunk])
        if self.failure is not None:
            raise self.failure


@pytest.fixture
def app(tmp_path, monkeypatch, qapp, key):
    core = AppCore(database=tmp_path / 'data/library.sqlite3', media=Media(),
                   clock=lambda: datetime.now(timezone.utc),
                   update_installation=lambda: InstalledUpdateInfo('1.0.0', FINGERPRINT))
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    state = SimpleNamespace(core=core, http=GatedHttp(key), launcher=FakeLauncher(), quits=[], windows=[], notes=[])

    def quit_app(confirmed):
        # confirmed: 설치 전 확인에서 받아들인 작업만 있다(받아쓰기 종료를 다시 묻지 않는다).
        state.quits.append(confirmed)
        return True

    def create(*, show=False, restart=False):
        # restart: 같은 데이터로 앱을 다시 시작한다. 코어는 실행마다 새로 만든다.
        current = AppCore(database=core.database, media=Media(), clock=core._clock,
                          update_installation=core.update_installation) if restart else core
        window = MainWindow(current, player_factory=Player, update_check_options=dict(
            startup_delay_ms=600_000, check=lambda: None,
            install=dict(http=state.http, prepare=dict(launcher=state.launcher, relaunch=RELAUNCH), quit_app=quit_app,
                         closing_notice_ms=0)))
        state.windows.append(window)
        window.tray.notify = state.notes.append  # 트레이 풍선 대신 기록한다
        window.subtitles.timer.stop()
        window.translations.timer.stop()
        if show:
            window.show()
        return window

    state.create = create
    yield state
    state.http.gate.set()
    for window in state.windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def offer(core, kind='patch', version='1.2.3'):
    """확인 결과를 저장하고 알린다(지금 확인이 끝났을 때와 같다)."""
    size = len(PATCH) if kind == 'patch' else len(FULL)
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'kind': kind, 'current_version': '1.0.0',
                                       'latest_version': version, 'download_size': size, 'failure_reason': None})


def shell(window):
    return json.loads(window.web_host.bridge.updateSnapshot())


def choose(window, name, version='1.2.3'):
    return json.loads(window.web_host.bridge.updateChoice(name, version))


def act(window, name):
    return json.loads(window.web_host.bridge.updateAction(name))


def phase(window):
    return window.updates.install.phase


def downloads(core):
    folder = core.database.parent / 'updates' / 'download'
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def test_update_choice_downloads_on_worker_then_hands_off_and_quits_once(app):
    window = app.create()
    offer(app.core)
    app.http.gate.clear()
    threads = []
    original = app.core.download_update

    def recording(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    app.core.download_update = recording
    changes = []
    window.web_host.bridge.shellUpdateInstallChanged.connect(lambda value: changes.append(json.loads(value)))
    assert choose(window, 'update')['notice'] is None
    wait_for(lambda: threads)
    assert threads[0] != threading.get_ident() and phase(window) == 'downloading'
    # 같은 업데이트를 다시 눌러도 두 번째 내려받기는 없다.
    assert choose(window, 'update') == {'error': update_install_controls.IN_PROGRESS}
    assert shell(window)['install']['phase'] == 'downloading'
    install = shell(window)['install']
    assert (install['version'], install['kind']) == ('1.2.3', 'patch')
    app.http.gate.set()
    wait_for(lambda: app.quits)
    assert app.http.downloads == ['MyVideoManager-Patch-1.2.3.exe'] and len(threads) == 1
    # 막는 작업이 없으면 묻지 않고 넘긴다. 보조 프로세스는 한 번, 앱 종료도 한 번.
    assert len(app.launcher.commands) == 1 and app.quits == [True]
    assert phase(window) == 'preparing' and window.updates.install.handed
    assert app.launcher.plan['installer'].endswith('MyVideoManager-Patch-1.2.3.exe')
    assert changes and changes[-1]['received'] == changes[-1]['total'] == len(PATCH)
    # 넘긴 뒤에는 이번 실행에서 다시 받지 않는다.
    assert not window.updates.install.start(window.updates.core.last_update_check())


def test_progress_reaches_ui_throttled(app, monkeypatch, key):
    app.http = GatedHttp(key, patch=False)
    window = app.create()
    offer(app.core, kind='full')
    app.http.chunk = 64  # FULL은 약 100KB: 1,500번 넘게 불린다
    emitted = []
    window.updates.install.progressed.connect(lambda: emitted.append(window.updates.install.received))
    times = itertools.count()
    # 콜백마다 시계가 10ms씩 간다고 본다: 약 100ms마다 하나만 화면으로 보낸다.
    monkeypatch.setattr(update_install_controls, 'monotonic', lambda: next(times) / 100)
    assert choose(window, 'update')['notice'] is None
    wait_for(lambda: app.quits)
    calls = -(-len(FULL) // 64)
    # 약 100ms마다 하나와 정수 퍼센트가 바뀔 때(최대 101번)만 보낸다. 마지막 값은 반드시 간다.
    assert calls // 10 <= len(emitted) <= calls // 10 + 101 + 2 < calls // 5 and emitted[-1] == len(FULL)
    assert emitted == sorted(emitted)
    percents = {value * 100 // len(FULL) for value in emitted}
    assert percents == set(range(101))  # 받기가 멈춰도 화면 값이 1% 넘게 뒤지지 않는다


def test_progress_callback_swallows_ui_errors(app, monkeypatch):
    window = app.create()
    offer(app.core)

    real = window.updates.install._signals

    class Broken:
        def emit(self, *args):
            raise RuntimeError('Signal source has been deleted')

    # 진행률 신호만 실패시킨다. 완료 신호는 그대로 둔다.
    monkeypatch.setattr(window.updates.install, '_signals',
                        SimpleNamespace(progress=Broken(), downloaded=real.downloaded, handed_off=real.handed_off))
    choose(window, 'update')
    wait_for(lambda: app.quits)  # 콜백이 실패해도 내려받기는 끝까지 간다


def test_cancel_removes_partial_file_and_announces_again(app):
    window = app.create()
    offer(app.core)
    app.http.gate.clear()
    choose(window, 'update')
    wait_for(lambda: downloads(app.core))
    assert downloads(app.core) == ['MyVideoManager-Patch-1.2.3.exe.partial']
    assert act(window, 'cancel')['install']['phase'] == 'cancelling'
    assert 'error' in act(window, 'cancel')  # 취소 중에는 다시 받지 않는다
    app.http.gate.set()
    wait_for(lambda: phase(window) == 'idle')
    assert downloads(app.core) == [] and app.launcher.commands == [] and app.quits == []
    assert window.statusBar().currentMessage() == update_install_controls.CANCELLED
    # 같은 버전의 새 버전 알림이 돌아와 다시 고를 수 있다.
    assert shell(window)['notice']['version'] == '1.2.3'


def test_verification_failure_is_reported_and_retry_downloads_again(app):
    window = app.create()
    offer(app.core)
    app.http.bodies['MyVideoManager-Patch-1.2.3.exe'] = b'x' * len(PATCH)
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    install = shell(window)['install']
    assert install['failureMessage'] == DOWNLOAD_FAILURE_MESSAGES['hash_mismatch'] and install['canRetry']
    assert shell(window)['notice'] is None and downloads(app.core) == [] and app.launcher.commands == []
    app.http.bodies['MyVideoManager-Patch-1.2.3.exe'] = PATCH
    act(window, 'retry')
    wait_for(lambda: app.quits)
    assert app.http.downloads == ['MyVideoManager-Patch-1.2.3.exe'] * 2


def test_dismissed_failure_brings_the_notice_back(app):
    window = app.create()
    offer(app.core)
    app.http.failure = UpdateCheckError('network')
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    assert shell(window)['install']['failureMessage'] == DOWNLOAD_FAILURE_MESSAGES['network']
    assert act(window, 'dismiss')['install']['phase'] == 'idle'
    assert shell(window)['notice']['version'] == '1.2.3'


@pytest.mark.parametrize('busy,expected', [
    (dict(playing=True), ('playback',)),
    (dict(transcribing=True), ('transcription',)),
    (dict(translating='translation'), ('translation',)),
    (dict(translating='refinement'), ('refinement',)),
    (dict(preparing=True), ('preparation',)),
])
def test_running_work_is_confirmed_before_install(app, monkeypatch, busy, expected):
    window = app.create()
    offer(app.core)
    entry = lambda state, kind='translation': SimpleNamespace(state=state, kind=kind)  # noqa: E731
    translating = busy.get('translating')
    # 재생·대기열 읽기는 test_update_install에서 확인한다. 여기서는 앱이 그 결과로 묻는지만 본다.
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=bool(busy.get('playing')),
        transcriptions=(entry('transcribing' if busy.get('transcribing') else 'queued'), entry('queued')),
        translations=(*((entry('translating', translating),) if translating else ()), entry('held'))))
    if busy.get('preparing'):
        window.subtitles.preparation_worker = object()
    try:
        choose(window, 'update')
        wait_for(lambda: phase(window) == 'confirm')
        assert window.updates.install.busy.blocking == expected and app.launcher.commands == []
        text = shell(window)['install']['confirmation']
        assert '대기 중인 받아쓰기' in text and '번역·다듬기 1개' in text and '이어서 처리합니다' in text
        # 나중에: 받은 파일은 남고, 지금 설치를 다시 고르면 다시 묻는다.
        assert act(window, 'later')['install']['phase'] == 'ready'
        assert downloads(app.core) == ['MyVideoManager-Patch-1.2.3.exe'] and app.launcher.commands == []
        assert act(window, 'install')['install']['phase'] == 'confirm'
        act(window, 'install')
        wait_for(lambda: app.quits)
        assert len(app.launcher.commands) == 1
    finally:
        window.subtitles.preparation_worker = None


def test_confirmation_lists_reasons_and_restart_details():
    from my_video_manager.update_install import UpdateBusyState
    from my_video_manager.web_update_data import busy_confirmation
    text = busy_confirmation(UpdateBusyState(('playback', 'transcription', 'preparation'), 2, 0))
    assert text == ('지금 설치하면 진행 중인 작업을 멈추고 앱을 닫습니다: 영상 재생, 받아쓰기, 자막 기능 준비. '
                    '설치가 끝나면 앱을 다시 실행합니다. 받아쓰던 영상은 다시 실행한 뒤 처음부터 다시 받아씁니다. '
                    '대기 중인 받아쓰기 2개는 다시 실행한 뒤 이어서 처리합니다.')


def test_unreadable_running_work_is_a_failure_not_a_silent_install(app, monkeypatch):
    window = app.create()
    offer(app.core)
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: (_ for _ in ()).throw(OSError('locked')))
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    assert shell(window)['install']['failureMessage'] == DOWNLOAD_FAILURE_MESSAGES['busy_check_failed']
    assert app.launcher.commands == [] and downloads(app.core) == ['MyVideoManager-Patch-1.2.3.exe']
    monkeypatch.undo()
    act(window, 'retry')  # 받은 파일로 확인부터 다시 한다
    wait_for(lambda: app.quits)
    assert app.http.downloads == ['MyVideoManager-Patch-1.2.3.exe']


def test_work_that_blocks_quitting_stops_before_the_helper(app):
    window = app.create()
    offer(app.core)
    window.web_host.controllers['settings'].backups.busy = True
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    assert shell(window)['install']['failureMessage'] == '백업 작업이 끝난 뒤 완전 종료해 주세요.'
    assert app.launcher.commands == [] and app.quits == []
    window.web_host.controllers['settings'].backups.busy = False
    act(window, 'retry')
    wait_for(lambda: app.quits)


def test_retry_after_install_failure_asks_again_when_work_started_meanwhile(app, monkeypatch):
    window = app.create()
    offer(app.core)
    window.web_host.controllers['settings'].backups.busy = True
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    # 실패 안내를 보는 사이 재생과 받아쓰기가 시작됐다.
    entry = lambda state: SimpleNamespace(state=state, kind='translation')  # noqa: E731
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=True, transcriptions=(entry('transcribing'),), translations=()))
    window.web_host.controllers['settings'].backups.busy = False
    assert act(window, 'retry')['install']['phase'] == 'confirm'
    assert window.updates.install.busy.blocking == ('playback', 'transcription')
    assert app.launcher.commands == [] and app.quits == []
    act(window, 'install')
    wait_for(lambda: app.quits)
    assert app.quits == [True]  # 대화에서 받아들인 받아쓰기는 종료 때 다시 묻지 않는다


def test_work_started_while_handing_off_is_asked_again_at_quit(app, monkeypatch):
    window = app.create()
    offer(app.core)
    started = []
    original = app.launcher.start

    def start(command, *, cwd):
        started.append(True)  # 보조 프로세스를 기다리는 사이 대기열이 받아쓰기를 시작한다
        return original(command, cwd=cwd)

    app.launcher.start = start
    entry = lambda state: SimpleNamespace(state=state, kind='translation')  # noqa: E731
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=False, transcriptions=(entry('transcribing' if started else 'queued'),), translations=()))
    choose(window, 'update')
    wait_for(lambda: app.quits)
    assert app.quits == [False]  # 받아쓰기 중 종료 확인 대화를 거친다


def test_playback_started_while_handing_off_does_not_ask_about_transcription(app, monkeypatch):
    window = app.create()
    offer(app.core)
    started = []
    original = app.launcher.start

    def start(command, *, cwd):
        started.append(True)  # 보조 프로세스를 기다리는 사이 재생을 시작한다
        return original(command, cwd=cwd)

    app.launcher.start = start
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=bool(started), transcriptions=(), translations=()))
    choose(window, 'update')
    wait_for(lambda: app.quits)
    assert app.quits == [True]  # 받아쓰기 확인 대화는 받아쓰기에만 뜬다


def test_closed_app_ignores_a_late_handoff(app):
    window = app.create()
    install = window.updates.install
    install.phase = 'preparing'
    install.shutdown()
    install._handed_off('')
    assert app.quits == [] and not install.handed


def test_quit_failure_hides_update_and_explains_why(app):
    window = app.create()
    offer(app.core)
    window.updates.install._quit_app = lambda confirmed: False
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    assert shell(window)['install']['failureMessage'] == DOWNLOAD_FAILURE_MESSAGES['quit_failed']
    act(window, 'dismiss')
    # 보조 프로세스가 앱 종료를 기다리고 있어 두 번째 설치를 넘기지 않는다. 버튼을 숨기고 눌러도 이유를 보인다.
    assert shell(window)['notice'] is None
    assert window.web_host.controllers['settings'].payload()['update']['updateAllowed'] is False
    assert choose(window, 'update') == {'error': update_install_controls.HANDED}
    assert len(app.launcher.commands) == 1


def test_settings_hides_update_for_any_version_while_in_progress(app):
    window = app.create()
    offer(app.core)
    app.http.gate.clear()
    choose(window, 'update')
    offer(app.core, version='1.3.0')  # 받는 사이 더 새 버전이 확인됐다
    window.updates.changed.emit()
    update = window.web_host.controllers['settings'].payload()['update']
    assert update['last']['latestVersion'] == '1.3.0' and update['updateAllowed'] is False
    assert choose(window, 'update', '1.3.0') == {'error': update_install_controls.IN_PROGRESS}
    app.http.gate.set()
    wait_for(lambda: app.quits)


def test_ready_notice_can_be_dismissed_from_shell_and_newer_version_is_announced(app, monkeypatch, key):
    window = app.create()
    offer(app.core)
    entry = lambda state: SimpleNamespace(state=state, kind='translation')  # noqa: E731
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=True, transcriptions=(), translations=()))
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'confirm')
    act(window, 'later')
    install = act(window, 'dismiss')['install']
    # 셸에서만 내린다: 받은 파일과 준비됨 단계(설정의 지금 설치)는 남는다.
    assert (install['phase'], install['readyDismissed']) == ('ready', True)
    assert downloads(app.core) == ['MyVideoManager-Patch-1.2.3.exe']
    assert shell(window)['notice'] is None
    assert choose(window, 'update') == {'error': update_install_controls.ALREADY_READY}
    # 더 새 버전이 확인되면 셸 새 버전 알림이 다시 보이고, 받기 시작하면 받아 둔 파일은 정리한다.
    offer(app.core, version='1.3.0')
    assert shell(window)['notice']['version'] == '1.3.0'
    assert window.web_host.controllers['settings'].payload()['update']['updateAllowed'] is True
    newer = GatedHttp(key, version='1.3.0')
    newer.bodies = {'MyVideoManager-Patch-1.2.3.exe': PATCH, 'MyVideoManager-Setup-1.2.3.exe': FULL}
    newer.gate.clear()
    window.updates.install._http = newer
    assert 'error' not in choose(window, 'update', '1.3.0')
    assert phase(window) == 'downloading' and window.updates.install.version == '1.3.0'
    wait_for(lambda: newer.downloads)
    newer.gate.set()
    wait_for(lambda: phase(window) == 'confirm')


def test_tray_balloon_when_the_window_cannot_show_the_shell(app, monkeypatch):
    window = app.create()  # 트레이로 숨긴 창
    offer(app.core)
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=True, transcriptions=(), translations=()))
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'confirm')
    assert app.notes == [update_install_controls.CONFIRM_WAITING]
    monkeypatch.undo()
    act(window, 'later')
    act(window, 'install')  # 막는 작업이 없어 묻지 않고 넘긴다
    wait_for(lambda: app.quits)
    assert app.notes == [update_install_controls.CONFIRM_WAITING, update_install_controls.CLOSING_FOR_INSTALL]


def test_no_tray_balloon_while_the_shell_is_on_screen(app, monkeypatch):
    window = app.create(show=True)
    offer(app.core)
    monkeypatch.setattr(app.core, 'busy_reasons_for_update', lambda: update_busy_state(
        playing=True, transcriptions=(), translations=()))
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'confirm')
    act(window, 'install')
    wait_for(lambda: app.quits)
    assert app.notes == []


@pytest.mark.parametrize('failure,ready', [('helper_failed', False), ('source_run', True)])
def test_handoff_failure_keeps_the_app_running(app, failure, ready):
    window = app.create()
    offer(app.core)
    if failure == 'source_run':
        window.updates.install._prepare = dict(launcher=app.launcher)  # 소스 실행: relaunch 주입 없음
    else:
        app.launcher.ready, app.launcher.helper.exit_code = False, 1
    choose(window, 'update')
    wait_for(lambda: phase(window) == 'failed')
    install = shell(window)['install']
    assert install['failureMessage'] == DOWNLOAD_FAILURE_MESSAGES[failure]
    assert install['canRetry'] is (failure != 'source_run') and app.quits == []
    assert not window.updates.install.handed


def test_full_quit_skips_second_transcription_question(app, monkeypatch):
    window = app.create()
    asked = []
    monkeypatch.setattr(window.subtitles, 'shutdown', lambda *, confirm=True: asked.append(confirm) or True)
    window.updates.install._quit_app = window.updates.install._quit_for_install
    offer(app.core)
    choose(window, 'update')
    wait_for(lambda: window.tray.quitting or phase(window) == 'failed')
    assert asked == [False] and window.updates.install.closed and len(app.launcher.commands) == 1


def write_outcome(core, record, result=None, log=True):
    folder = core.database.parent / 'updates'
    (folder / 'download').mkdir(parents=True, exist_ok=True)
    (folder / 'download' / 'MyVideoManager-Patch-1.2.3.exe').write_bytes(PATCH)
    (folder / 'install.json').write_text(json.dumps({'started_at': NOW.isoformat(), **record}))
    if result is not None:
        (folder / 'install-result.json').write_text(json.dumps(result))
    if log:
        (folder / 'installer.log').write_text('log')
    return folder


def test_successful_install_is_announced_once_and_everything_is_cleared(app):
    folder = write_outcome(app.core, {'version': '1.0.0', 'kind': 'patch'}, {'exit_code': 0})
    window = app.create()
    result = shell(window)['install']['result']
    assert result == {'tone': 'success', 'title': '1.0.0 버전으로 업데이트했습니다', 'message': '', 'retry': None,
                      'logPath': None}
    assert not folder.exists()
    assert act(window, 'dismiss')['install']['result'] is None
    window.tray.quit()
    assert shell(app.create(restart=True))['install']['result'] is None


@pytest.mark.parametrize('result,retry,tone', [
    ({'exit_code': 7}, 'full', 'error'),
    ({'exit_code': 4}, 'full', 'error'),
    ({'error': 'hash_mismatch'}, 'same', 'error'),
    ({'error': 'installer_start_failed'}, 'same', 'error'),
    ({'error': 'app_did_not_exit'}, 'same', 'error'),
    ({'error': 'installer_timeout'}, None, 'warning'),
    (None, 'same', 'warning'),
])
def test_failed_install_is_explained_with_log_kept_until_success(app, result, retry, tone):
    folder = write_outcome(app.core, {'version': '1.2.3', 'kind': 'patch'}, result)
    offer(app.core)
    window = app.create()
    data = shell(window)
    shown = data['install']['result']
    assert (shown['retry'], shown['tone']) == (retry, tone)
    assert shown['logPath'] == str(folder / 'installer.log') and shown['message']
    # 같은 버전의 새 버전 알림은 결과 안내가 있는 동안 숨긴다(다시 시도 버튼이 대신한다).
    assert data['notice'] is None
    # 기록과 받은 파일은 지우고 설치 기록(log)만 남긴다.
    assert sorted(path.name for path in folder.iterdir()) == ['installer.log']
    if result == {'error': 'installer_timeout'}:
        assert '앱을 다시 켜 보세요' in shown['message']
        assert 'error' in act(window, 'retry')
        return
    act(window, 'retry')
    wait_for(lambda: app.quits)
    expected = 'MyVideoManager-Setup-1.2.3.exe' if retry == 'full' else 'MyVideoManager-Patch-1.2.3.exe'
    assert app.http.downloads == [expected]


def test_full_install_failure_retries_full(app):
    write_outcome(app.core, {'version': '1.2.3', 'kind': 'full'}, {'exit_code': 7})
    window = app.create()
    assert shell(window)['install']['result']['retry'] == 'same'
    act(window, 'retry')
    wait_for(lambda: app.quits)
    assert app.http.downloads == ['MyVideoManager-Setup-1.2.3.exe']


def test_failed_result_without_log_does_not_point_to_one(app):
    write_outcome(app.core, {'version': '1.2.3', 'kind': 'patch'}, {'error': 'app_did_not_exit'}, log=False)
    assert shell(app.create())['install']['result']['logPath'] is None


def test_leftover_download_without_record_is_removed_at_start_but_log_is_kept(app):
    folder = app.core.database.parent / 'updates'
    (folder / 'download').mkdir(parents=True)
    (folder / 'download' / 'x.exe.partial').write_bytes(b'x')
    (folder / 'installer.log').write_text('earlier failure')
    window = app.create()
    assert shell(window)['install']['result'] is None
    assert sorted(path.name for path in folder.iterdir()) == ['installer.log']


def test_every_download_and_install_code_has_its_own_message():
    install = (SOURCE / 'update_install.py').read_text(encoding='utf-8')
    controls = (SOURCE / 'update_install_controls.py').read_text(encoding='utf-8')
    core = (SOURCE / 'core.py').read_text(encoding='utf-8')
    download = set(re.findall(r"UpdateInstallError\('([a-z0-9_]+)'\)", install + core))
    download |= set(re.findall(r"reason = '([a-z0-9_]+)'", install))
    download |= set(re.findall(r"_fail\('[a-z]+', '([a-z0-9_]+)'", controls))
    download |= set(re.findall(r"error = '([a-z0-9_]+)'", controls))
    assert {'disk_full', 'hash_mismatch', 'size_mismatch', 'storage', 'download_failed', 'source_run',
            'helper_not_ready', 'quit_failed', 'quit_blocked', 'handoff_failed', 'busy_check_failed'} <= download
    for name in ('update_http.py', 'update_manifest.py'):
        text = (SOURCE / name).read_text(encoding='utf-8')
        download |= set(re.findall(r"(?:UpdateCheckError\(|ManifestError\()'([a-z0-9_]+)'", text))
    assert download - set(DOWNLOAD_FAILURE_MESSAGES) - set(FAILURE_MESSAGES) == set()
    # 확인 문구를 그대로 쓰는 코드는 "다시 확인하세요" 같은 확인 말투가 없는 것만 남긴다.
    assert not [code for code in download if '확인하세요' in download_failure_message(code)
                and code not in ('no_update', 'storage')]
    outcome = set(re.findall(r"error = '([a-z0-9_]+)'", HELPER_SCRIPT))
    outcome |= set(re.findall(r"'(patch_rejected|installer_failed)'", install))
    outcome |= set(re.findall(r"'incomplete', '([a-z0-9_]+)'", install))
    assert {'app_did_not_exit', 'hash_mismatch', 'installer_timeout', 'installer_start_failed',
            'patch_rejected', 'installer_failed', 'no_result'} <= outcome
    assert outcome - set(INSTALL_RESULT_MESSAGES) == set()
