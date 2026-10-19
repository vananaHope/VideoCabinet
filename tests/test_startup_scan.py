"""실제 웹 셸 시작과 기존 검사 작업자 경로의 동작 계약."""
from datetime import datetime, timezone
import json
import threading
import time

import pytest
from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QSystemTrayIcon

from my_video_manager.core import AppCore, ScanResult
from my_video_manager.library import MediaInfo
from my_video_manager.ui import MainWindow
from my_video_manager.web_contract import TABS
from qt_wait import wait_for
from test_library_return_ui import Player


class Media:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.slow_path = None

    def read(self, path):
        if path == self.slow_path:
            self.started.set()
            assert self.release.wait(20), '검사 중 첫 조작이 끝나지 않았습니다.'
        return MediaInfo(120, 'matroska', 1280, 720)

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


def settle(ms=400):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def javascript(window, source):
    values = []
    window.web_host.engine_page.runJavaScript(source, values.append)
    wait_for(lambda: bool(values))
    return values[0]


@pytest.fixture
def startup(tmp_path, monkeypatch, qapp):
    media = Media()
    folder = tmp_path / 'videos'
    folder.mkdir()
    core = AppCore(database=tmp_path / 'data/library.sqlite3', media=media,
                   clock=lambda: datetime.now(timezone.utc))
    existing = folder / 'existing.mkv'
    existing.write_bytes(b'existing')
    core.add_file(existing)
    calls = []
    scan = core.scan

    def counted_scan():
        calls.append(threading.get_ident())
        return scan()

    monkeypatch.setattr(core, 'scan', counted_scan)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []

    def create(*, watched=True, show=True):
        if watched:
            core.add_watched_folder(folder)
        window = MainWindow(core, player_factory=Player)
        windows.append(window)
        window.subtitles.timer.stop()
        window.translations.timer.stop()
        if show:
            window.show()
        return window

    yield core, folder, media, calls, create
    media.release.set()
    for window in windows:
        wait_for(lambda: window.worker is None)
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_startup_imports_offline_addition_and_removal_once(startup):
    core, folder, _, calls, create = startup
    old_id = core.videos()[0].id
    (folder / 'existing.mkv').unlink()
    (folder / 'new.mkv').write_bytes(b'new')
    window = create()
    states = []
    window.library_page.scan_state_changed.connect(states.append)
    wait_for(lambda: states == [True, False])
    assert len(calls) == 1 and calls[0] != threading.get_ident()
    assert core.video(old_id).missing
    assert {v['title'] for v in window.library_page.payload()['videos']} == {'existing', 'new'}
    assert window.web_host.controllers['folders'].report

    window.close()
    window.tray.open()
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    window.web_host.view.reload()
    wait_for(lambda: bool(loaded))
    settle()
    assert len(calls) == 1


def test_no_watched_folders_does_not_start_worker(startup):
    _, _, _, calls, create = startup
    window = create(watched=False)
    states = []
    window.library_page.scan_state_changed.connect(states.append)
    wait_for(lambda: window.web_host._loaded_notified)
    settle()
    assert calls == [] and states == []


def test_loaded_hidden_window_waits_until_shown(startup):
    _, _, _, calls, create = startup
    window = create(show=False)
    wait_for(lambda: window.web_host._loaded_notified)
    settle()
    assert calls == []
    window.show()
    assert calls == []
    wait_for(lambda: len(calls) == 1 and window.worker is None)


def test_visible_window_waits_for_frontend_and_defers_first_input(startup):
    _, _, _, calls, create = startup
    window = create(show=False)
    # 실제 readiness 연결을 지연하여 느린 첫 웹 로드를 재현한다.
    window.web_host.frontend_loaded.disconnect(window.startup_frontend_loaded)
    window.show()
    wait_for(lambda: window.web_host._loaded_notified)
    settle()
    assert calls == []
    window.web_host.frontend_loaded.connect(window.startup_frontend_loaded)
    window.web_host.frontend_loaded.emit()
    # 같은 이벤트 차례의 탭 이동은 검사 시작보다 먼저 끝나야 한다.
    window.navigate_web_tab('folders')
    assert calls == [] and window.web_host.active_tab == 'folders'
    wait_for(lambda: len(calls) == 1 and window.worker is None)


def test_slow_scan_keeps_web_navigation_playback_and_manual_guard_responsive(startup, monkeypatch):
    core, folder, media, calls, create = startup
    folders_index = [name for name, _ in TABS].index('folders')
    media.slow_path = folder / 'new.mkv'
    media.slow_path.write_bytes(b'slow new video')
    window = create()
    wait_for(media.started.is_set)
    worker = window.worker
    assert worker is not None and worker.isRunning()
    assert javascript(window, 'document.querySelectorAll("header nav button").length') == len(TABS)
    started = time.monotonic()
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_1 + folders_index, Qt.KeyboardModifier.ControlModifier)
    assert window.web_host.active_tab == 'folders'
    bridge = window.web_host.controllers['folders'].bridge
    assert json.loads(bridge.snapshot())['scanning']
    assert 'error' in json.loads(bridge.action('scan', ''))
    window.scan()
    assert window.worker is worker and len(calls) == 1
    window.play(core.videos()[0].id)
    assert window.pages.currentWidget() is window.playback_page
    window.back_to_list()
    assert window.web_host.active_tab == 'folders'
    wait_for(lambda: javascript(window,
        f'document.querySelector("header nav [aria-current=page]") === document.querySelectorAll("header nav button")[{folders_index}]'))
    assert time.monotonic() - started < 5
    assert worker.isRunning()

    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    window.tray.quit()
    assert warnings and window.isVisible() and not window.tray.quitting
    assert window.worker is worker
    media.release.set()
    wait_for(lambda: window.worker is None)
    assert len(calls) == 1 and len(core.videos()) == 2


def test_startup_does_not_overlap_a_manual_scan_already_running(startup):
    _, folder, media, calls, create = startup
    media.slow_path = folder / 'new.mkv'
    media.slow_path.write_bytes(b'new')
    window = create()
    window.scan()
    wait_for(media.started.is_set)
    wait_for(lambda: window.web_host._loaded_notified)
    settle()
    assert len(calls) == 1
    media.release.set()
    wait_for(lambda: window.worker is None)
    # 수동 검사의 완료 안내는 시작 검사 시도가 덮어쓰지 않는다.
    assert window.web_host.controllers['folders'].report


@pytest.mark.parametrize('previous_report', [None, 'previous scan report'])
def test_unchanged_startup_is_quiet_but_manual_completion_is_reported(startup, previous_report):
    _, _, _, calls, create = startup
    window = create()
    folders = window.web_host.controllers['folders']
    if previous_report is not None:
        folders.report_scan(previous_report)
    previous_report = folders.report
    wait_for(lambda: len(calls) == 1 and window.worker is None)
    assert folders.report == previous_report
    assert window.statusBar().currentMessage() == ''
    window.scan()
    wait_for(lambda: len(calls) == 2 and window.worker is None)
    assert window.web_host.controllers['folders'].report


def test_file_dialog_racing_startup_scan_reports_retry(startup, monkeypatch):
    core, folder, media, calls, create = startup
    media.slow_path = folder / 'new.mkv'
    media.slow_path.write_bytes(b'new')
    direct = folder.parent / 'direct.mkv'
    direct.write_bytes(b'direct')
    window = create(show=False)
    folders = window.web_host.controllers['folders']
    errors = []
    folders.bridge.foldersError.connect(errors.append)

    def choose_file(*args):
        # 파일 선택의 중첩 이벤트 루프 중 시작 타이머가 발동한다.
        window.show()
        wait_for(media.started.is_set)
        return str(direct), ''

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose_file)
    assert json.loads(folders.bridge.action('addFile', '')) == {'ok': True}
    wait_for(lambda: media.started.is_set() and not folders.bridge.busy)
    assert errors == ['진행 중인 검사가 끝난 뒤 다시 시도하세요.']
    assert window.worker.isRunning() and len(calls) == 1
    media.release.set()
    wait_for(lambda: window.worker is None)
    assert {video.title for video in core.videos()} == {'existing', 'new'}
    # 안내에 따라 재시도하면 선택한 파일을 정상 등록한다.
    errors.clear()
    assert json.loads(folders.bridge.action('addFile', '')) == {'ok': True}
    wait_for(lambda: not folders.bridge.busy and window.worker is None)
    assert {video.title for video in core.videos()} == {'existing', 'new', 'direct'}


def stretch_quiet_startup_scan(core, calls, monkeypatch):
    """무변경(조용한) 시작 검사가 끝나지 않도록 멈춰 두는 도우미."""
    started, release = threading.Event(), threading.Event()

    def quiet_scan():
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(20), '검사 중 조작이 끝나지 않았습니다.'
        return ScanResult(0, ())

    monkeypatch.setattr(core, 'scan', quiet_scan)
    return started, release


def test_add_file_racing_quiet_startup_scan_reports_error_and_keeps_it(startup, monkeypatch):
    core, folder, _, calls, create = startup
    direct = folder.parent / 'direct.mkv'
    direct.write_bytes(b'direct')
    window = create(show=False)
    folders = window.web_host.controllers['folders']
    errors = []
    folders.bridge.foldersError.connect(errors.append)
    started, release = stretch_quiet_startup_scan(core, calls, monkeypatch)

    def choose_file(*args):
        window.show()
        wait_for(started.is_set)
        return str(direct), ''

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose_file)
    assert json.loads(folders.bridge.action('addFile', '')) == {'ok': True}
    wait_for(lambda: started.is_set() and not folders.bridge.busy)
    assert errors == ['진행 중인 검사가 끝난 뒤 다시 시도하세요.']
    assert window.worker.isRunning() and len(calls) == 1
    release.set()
    wait_for(lambda: window.worker is None)
    # 조용한 완료가 문구를 복원해도 거부된 파일이 등록되지 않았다는 사실은 오류에 남는다.
    assert errors == ['진행 중인 검사가 끝난 뒤 다시 시도하세요.']
    assert folders.report != '진행 중인 검사가 끝난 뒤 다시 시도하세요.'
    assert {video.title for video in core.videos()} == {'existing'}


def test_library_reconnect_racing_quiet_startup_scan_reports_error(startup, monkeypatch):
    core, folder, _, calls, create = startup
    replacement = folder.parent / 'replacement.mkv'
    replacement.write_bytes(b'replacement')
    window = create(show=False)
    video_id = core.videos()[0].id
    original = core.video(video_id).locations
    window.library_page.refresh()
    bridge = window.library_page.bridge
    errors = []
    bridge.libraryError.connect(errors.append)
    started, release = stretch_quiet_startup_scan(core, calls, monkeypatch)

    def choose_file(*args):
        window.show()
        wait_for(started.is_set)
        return str(replacement), ''

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose_file)
    assert json.loads(bridge.action('reconnect', video_id)) == {'ok': True}
    wait_for(lambda: started.is_set() and not bridge.busy)
    assert errors == ['진행 중인 검사가 끝난 뒤 다시 시도하세요.']
    assert window.worker.isRunning() and len(calls) == 1
    release.set()
    wait_for(lambda: window.worker is None)
    assert core.video(video_id).locations == original


def test_quiet_completion_does_not_overwrite_a_newer_notice(startup, monkeypatch):
    core, _, _, calls, create = startup
    window = create(show=False)
    folders = window.web_host.controllers['folders']
    started, release = stretch_quiet_startup_scan(core, calls, monkeypatch)
    window.show()
    wait_for(started.is_set)
    folders.report_scan('검사 중 들어온 안내')
    release.set()
    wait_for(lambda: window.worker is None)
    assert folders.report == '검사 중 들어온 안내'


def test_startup_warning_is_not_silenced(startup):
    core, folder, _, calls, create = startup
    core.add_watched_folder(folder)
    (folder / 'existing.mkv').unlink()
    folder.rmdir()
    window = create(watched=False)
    wait_for(lambda: len(calls) == 1 and window.worker is None)
    assert str(folder) in window.web_host.controllers['folders'].report


def test_failed_startup_releases_worker_and_manual_retry_works(startup, monkeypatch):
    core, _, _, calls, create = startup
    scan = core.scan

    def fail():
        calls.append(threading.get_ident())
        raise RuntimeError('injected scan failure')

    monkeypatch.setattr(core, 'scan', fail)
    window = create()
    wait_for(lambda: len(calls) == 1 and window.worker is None)
    assert 'injected scan failure' in window.web_host.controllers['folders'].report
    assert not window.library_page.payload()['scanning']
    monkeypatch.setattr(core, 'scan', scan)
    window.scan()
    wait_for(lambda: len(calls) == 2 and window.worker is None)
    assert 'injected scan failure' not in window.web_host.controllers['folders'].report


def test_full_exit_before_deferred_scan_prevents_worker_start(startup):
    _, _, _, calls, create = startup
    window = create()
    window.web_host.frontend_loaded.connect(window.tray.quit)
    wait_for(lambda: window.tray.quitting)
    settle()
    assert not window.isVisible() and calls == []
