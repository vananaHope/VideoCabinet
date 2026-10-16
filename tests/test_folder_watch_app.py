"""앱 수명과 검사 작업자에 연결한 폴더 감시의 공개 동작."""
from datetime import datetime, timezone
import json
import threading

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_folder_watch import FakeWatcher
from test_library_return_ui import Player
from test_startup_scan import Media, settle

FAST = dict(debounce_seconds=0.1, stable_seconds=0.3, poll_seconds=0.1)


class RecordingWatcher(FakeWatcher):
    def __init__(self, order):
        super().__init__()
        self.order = order
        self.failed_folders = ()

    def start(self, folders, on_change):
        self.order.append('watch')
        super().start(folders, on_change)


@pytest.fixture
def app(tmp_path, monkeypatch, qapp):
    media = Media()
    folder = tmp_path / 'videos'
    (folder / 'a').mkdir(parents=True)
    (folder / 'b').mkdir()
    core = AppCore(database=tmp_path / 'data/library.sqlite3', media=media,
                   clock=lambda: datetime.now(timezone.utc))
    (folder / 'existing.mkv').write_bytes(b'existing')
    core.add_watched_folder(folder)
    order, scans = [], []
    gate = threading.Event()
    gate.set()
    scan = core.scan

    def recorded_scan(*, folders=None):
        order.append('scan')
        scans.append(None if folders is None else tuple(folders))
        assert gate.wait(20), '검사 중 조작이 끝나지 않았습니다.'
        return scan(folders=folders)

    monkeypatch.setattr(core, 'scan', recorded_scan)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []

    def create(watcher=None, **options):
        window = MainWindow(core, player_factory=Player,
                            folder_watch_options=dict(watcher=watcher, **options))
        windows.append(window)
        window.subtitles.timer.stop()
        window.translations.timer.stop()
        window.show()
        return window

    yield core, folder, scans, order, gate, create
    gate.set()
    for window in windows:
        wait_for(lambda: window.worker is None)
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def titles(core):
    return {video.title for video in core.videos()}


def settings_bridge(window):
    return window.web_host.controllers['settings'].bridge


def test_real_watch_reflects_changes_and_setting_toggle(app):
    core, folder, scans, _, _, create = app
    window = create(**FAST)
    wait_for(lambda: scans == [None] and window.worker is None)

    (folder / 'a' / 'added.mkv').write_bytes(b'added while running')
    wait_for(lambda: 'added' in titles(core))
    assert scans[-1] == ((folder / 'a').resolve(),)
    added = next(video for video in core.videos() if video.title == 'added')
    (folder / 'a' / 'added.mkv').unlink()
    wait_for(lambda: core.video(added.id).missing and window.worker is None)

    state = json.loads(settings_bridge(window).setAutomaticDetection(False))
    assert state['automaticDetection'] is False and not core.automatic_detection_enabled()
    count = len(scans)
    (folder / 'b' / 'while-off.mkv').write_bytes(b'copied while off')
    settle(1500)
    assert len(scans) == count and 'while-off' not in titles(core)

    state = json.loads(settings_bridge(window).setAutomaticDetection(True))
    assert state['automaticDetection'] is True
    # 다시 켜면 꺼진 동안의 변경을 인자 없는 전체 검사 한 번으로 반영한다.
    wait_for(lambda: 'while-off' in titles(core) and window.worker is None)
    assert scans[count:] == [None]
    (folder / 'b' / 'after-on.mkv').write_bytes(b'after enabling again')
    wait_for(lambda: 'after-on' in titles(core) and window.worker is None)
    assert scans[-1] == ((folder / 'b').resolve(),)


def test_watch_starts_before_startup_scan_and_batches_merge_during_a_scan(app):
    core, folder, scans, order, gate, create = app
    watcher = RecordingWatcher(order)
    gate.clear()
    window = create(watcher)
    # 작업자 스레드의 실행 시점과 무관하게 메인 스레드에서 검사를 시작한 순서를 본다.
    window.library_page.scan_state_changed.connect(lambda scanning: scanning and order.append('scanning'))
    wait_for(lambda: scans == [None])
    assert order.index('watch') < order.index('scanning')
    controls = window.folder_watch
    # 감시 타이머 스레드에서 온 묶음은 queued signal로 메인 스레드에서 처리한다.
    for batch in ((folder / 'a',), (folder / 'b', folder / 'a')):
        thread = threading.Thread(target=controls.batch_ready.emit, args=(batch,))
        thread.start()
        thread.join()
    settle(300)
    assert scans == [None] and window.worker.isRunning()
    gate.set()
    wait_for(lambda: len(scans) == 2 and window.worker is None)
    settle(300)
    assert scans == [None, (folder / 'a', folder / 'b')]


def test_disabled_detection_skips_startup_scan_and_enabling_scans_once(app):
    core, folder, scans, order, _, create = app
    core.set_automatic_detection_enabled(False)
    watcher = RecordingWatcher(order)
    window = create(watcher)
    wait_for(lambda: window.web_host._loaded_notified)
    settle(800)
    assert scans == [] and watcher.starts == 0
    window.folder_watch.batch_ready.emit((folder / 'a',))
    settle(300)
    assert scans == []

    bridge = settings_bridge(window)
    assert json.loads(bridge.snapshot())['automaticDetection'] is False
    json.loads(bridge.setAutomaticDetection(True))
    wait_for(lambda: scans == [None] and window.worker is None)
    assert watcher.starts == 1
    # 같은 값으로 다시 켜도 전체 검사를 반복하지 않는다.
    json.loads(bridge.setAutomaticDetection(True))
    settle(300)
    assert scans == [None]


def test_toggle_is_locked_during_scan_and_disabling_drops_pending(app):
    core, folder, scans, order, gate, create = app
    gate.clear()
    window = create(RecordingWatcher(order))
    wait_for(lambda: scans == [None])
    bridge = settings_bridge(window)
    assert 'error' in json.loads(bridge.setAutomaticDetection(False))
    window.folder_watch.batch_ready.emit((folder / 'a',))
    settle(100)
    # 검사 중에 미룬 묶음은 그 사이 자동 감지를 끄면 실행하지 않는다.
    window.folder_watch.set_enabled(False)
    gate.set()
    wait_for(lambda: window.worker is None)
    settle(300)
    assert scans == [None]


def test_full_exit_stops_watch_before_pending_batches_run(app, monkeypatch):
    core, folder, scans, order, gate, create = app
    watcher = RecordingWatcher(order)
    gate.clear()
    window = create(watcher)
    wait_for(lambda: scans == [None])
    window.folder_watch.batch_ready.emit((folder / 'a',))
    settle(100)
    gate.set()
    stops = []
    stop = window.folder_watch.watch.stop
    monkeypatch.setattr(window.folder_watch.watch, 'stop', lambda: (stops.append(window.worker), stop()))
    wait_for(lambda: window.worker is None and len(scans) == 2)
    window.tray.quit()
    assert window.tray.quitting and stops == [None] and watcher.stops >= 1
    window.folder_watch.batch_ready.emit((folder / 'b',))
    settle(300)
    assert len(scans) == 2


def test_folder_page_warns_about_unwatched_folders(app):
    core, folder, scans, order, _, create = app
    watcher = RecordingWatcher(order)
    window = create(watcher)
    wait_for(lambda: scans == [None] and window.worker is None)
    page = window.web_host.controllers['folders']
    bridge = page.bridge
    state = json.loads(bridge.snapshot())
    assert state['unwatched'] == [] and state['automaticDetection'] is True
    sent = []
    bridge.foldersChanged.connect(lambda payload: sent.append(json.loads(payload)))
    window.navigate_web_tab('folders')
    watcher.failed_folders = (folder,)
    wait_for(lambda: sent and sent[-1]['unwatched'] == [str(folder)])
    count = len(sent)
    settle(1300)
    assert len(sent) == count  # 바뀌지 않으면 다시 보내지 않는다.

    window.folder_watch.set_enabled(False)
    assert json.loads(bridge.snapshot())['unwatched'] == []
    assert json.loads(bridge.snapshot())['automaticDetection'] is False


def test_start_failure_lists_all_folders_and_retries_when_enabled_again(app):
    core, folder, scans, order, _, create = app

    class FailingWatcher(RecordingWatcher):
        fail = True

        def start(self, folders, on_change):
            if self.fail:
                raise OSError('observer unavailable')
            super().start(folders, on_change)

    watcher = FailingWatcher(order)
    window = create(watcher)
    # 감시를 시작하지 못해도 시작 검사는 돌고 앱은 계속한다.
    wait_for(lambda: scans == [None] and window.worker is None)
    bridge = window.web_host.controllers['folders'].bridge
    assert json.loads(bridge.snapshot())['unwatched'] == [str(core.watched_folders()[0].path)]
    window.folder_watch.set_enabled(False)
    watcher.fail = False
    window.folder_watch.set_enabled(True)
    assert watcher.starts == 1 and json.loads(bridge.snapshot())['unwatched'] == []
    wait_for(lambda: scans == [None, None] and window.worker is None)


def test_folder_added_while_scan_runs_is_scanned_afterwards(app, monkeypatch, tmp_path):
    core, folder, scans, order, gate, create = app
    gate.clear()
    window = create(RecordingWatcher(order))
    wait_for(lambda: scans == [None])
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'late.mkv').write_bytes(b'late folder')
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: str(other))
    window.library_page.add_folder()
    gate.set()
    wait_for(lambda: 'late' in titles(core) and window.worker is None)
    assert scans == [None, None]


def test_failed_batch_scan_reports_and_next_batch_runs(app, monkeypatch):
    core, folder, scans, order, _, create = app
    window = create(RecordingWatcher(order))
    wait_for(lambda: scans == [None] and window.worker is None)
    scan = core.scan

    def failing(*, folders=None):
        scans.append(tuple(folders))
        raise RuntimeError('injected batch failure')

    monkeypatch.setattr(core, 'scan', failing)
    window.folder_watch.batch_ready.emit((folder / 'a',))
    wait_for(lambda: len(scans) == 2 and window.worker is None)
    assert 'injected batch failure' in window.web_host.controllers['folders'].report
    monkeypatch.setattr(core, 'scan', scan)
    window.folder_watch.batch_ready.emit((folder / 'b',))
    wait_for(lambda: len(scans) == 3 and window.worker is None)
    assert scans[-1] == (folder / 'b',)


def test_enabling_without_watched_folders_does_not_scan(app):
    core, folder, scans, order, _, create = app
    core.remove_watched_folder(core.watched_folders()[0].path)
    core.set_automatic_detection_enabled(False)
    window = create(RecordingWatcher(order))
    wait_for(lambda: window.web_host._loaded_notified)
    settle(800)
    window.folder_watch.set_enabled(True)
    settle(300)
    assert scans == [] and core.automatic_detection_enabled()
