"""긴급 탈출: 실제 키 입력으로 숨기고 트레이 열기·두 번째 실행으로 같은 화면에 돌아온다."""

from datetime import datetime, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.single_instance import SingleInstance
from my_video_manager.ui import MainWindow
from qt_wait import wait_for


class Media:
    def read(self, path):
        return MediaInfo(120, "matroska")

    def capture(self, path, destination, seconds):
        pass


class Player:
    """일시정지 중에는 mpv처럼 같은 위치만 보고한다."""

    def __init__(self, surface):
        self.paused = False
        self.position = 0
        self.positions = []
        self.played = 0

    def play(self, path, start, *, subtitle):
        self.played += 1
        self.paused = False

    def advance(self, position):
        self.position = position if not self.paused else self.position
        self.positions.append((self.position, False))

    def pause(self):
        self.paused = True

    def execute(self, command):
        if command.kind == CommandType.TOGGLE_PAUSE:
            self.paused = not self.paused

    def seek_to(self, position, *, resume=False):
        self.position = position
        self.paused = self.paused and not resume

    def close(self):
        pass

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        return False


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


@pytest.fixture
def window(tmp_path, app, monkeypatch):
    yield from open_window(tmp_path, app, monkeypatch)


def open_window(tmp_path, app, monkeypatch, *, transcriber=None):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=transcriber)
    for index in (1, 2):
        path = tmp_path / f"강의 {index:02}강.mkv"
        path.write_bytes(bytes([index]))
        core.add_file(path)
    window = MainWindow(core, player_factory=Player)
    window.balloons = []
    monkeypatch.setattr(window.tray.icon, "showMessage", lambda *args: window.balloons.append(args))
    window.show()
    window.activateWindow()
    app.processEvents()
    yield window
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def key(window, key, modifiers=Qt.KeyboardModifier.NoModifier):
    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(QApplication.focusWidget() or window, key, modifiers)
    QApplication.processEvents()


def emergency_key(window):
    key(window, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)


def play_to_twenty_seconds(window):
    video = window.core.videos()[0]
    window.play(video.id)
    player = window.player
    for position in (10, 20):
        player.advance(position)
        window.sync_position()
    return video, player


def second_launch(window, core):
    instance = SingleInstance(core.database.parent)
    assert instance.start()
    instance.activated.connect(window.tray.open)
    try:
        assert not SingleInstance(core.database.parent).start()
        wait_for(window.isVisible)
    finally:
        instance.close()
        instance.deleteLater()


@pytest.mark.parametrize("restore", ["tray", "second_launch"])
def test_playback_emergency_hide_returns_to_same_paused_scene(window, restore):
    core = window.core
    video, player = play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()

    emergency_key(window)
    assert not window.isVisible()
    assert not window.isFullScreen()
    assert player.paused
    assert window.balloons == []
    # 숨긴 동안 멈춘 엔진은 같은 위치만 보고하므로 시청 시간이 늘지 않는다.
    for _ in range(3):
        player.advance(90)
        window.sync_position()
    assert core.playback.session.video_id == video.id
    viewing = core.viewings(video.id)[-1]
    assert viewing.ended_at is None and viewing.played_seconds == 20

    if restore == "tray":
        window.tray.open()
    else:
        second_launch(window, core)
    QApplication.processEvents()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.playback_page
    assert not window.isFullScreen()
    assert window.player is player and player.played == 1 and player.paused
    assert core.playback.session.video_id == video.id
    assert core.playback.position == 20
    assert window.balloons == []
    assert QApplication.focusWidget() is window.surface

    # 복귀 뒤 같은 시청이 이어진다.
    key(window, Qt.Key.Key_Return)
    player.advance(30)
    window.sync_position()
    assert core.viewings(video.id)[-1].id == viewing.id
    assert core.viewings(video.id)[-1].played_seconds == 30


def test_emergency_hide_keeps_open_range_and_first_tray_notice(window):
    core = window.core
    play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Delete)
    assert core.open_highlight_start == 20
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    assert core.open_highlight_start == 20
    assert window.balloons == []
    # 첫 트레이 안내는 긴급 탈출에서 소모되지 않고 다음 창 닫기에서 한 번 보인다.
    window.close()
    assert not window.isVisible()
    assert len(window.balloons) == 1 and "트레이에서 계속 처리" in window.balloons[0][1]
    window.tray.open()
    window.close()
    assert len(window.balloons) == 1


@pytest.mark.parametrize("tab", ["library", "search", "statistics", "queue", "folders", "reel", "settings"])
def test_web_tab_emergency_hide_returns_to_same_tab_without_refresh(window, monkeypatch, tab):
    window.navigate_web_tab(tab)
    QApplication.processEvents()
    refreshed = []
    monkeypatch.setattr(window.library_page, "refresh", lambda **kwargs: refreshed.append(kwargs))
    emergency_key(window)
    assert not window.isVisible()
    assert window.balloons == []
    window.tray.open()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == tab
    assert refreshed == []


def test_rebound_emergency_key_hides_and_old_key_does_nothing(window):
    core = window.core
    bindings = {row.command: row.keys for row in core.key_bindings()}
    bindings[Command(CommandType.EMERGENCY_HIDE)] = ("Ctrl+Alt+B",)
    core.save_key_bindings(bindings)
    emergency_key(window)
    assert window.isVisible()
    key(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert not window.isVisible()


def test_subtitle_queue_keeps_processing_after_emergency_hide(tmp_path, app, monkeypatch):
    from test_subtitles import FakeTranscriber
    transcriber = FakeTranscriber()
    opened = open_window(tmp_path, app, monkeypatch, transcriber=transcriber)
    window = next(opened)
    try:
        video = window.core.videos()[0]
        window.core.request_subtitles(video.id)
        emergency_key(window)
        assert not window.isVisible()
        wait_for(lambda: window.core.library_details(video.id).original_lines)
        assert transcriber.calls and not window.isVisible()
    finally:
        opened.close()


def test_maximized_window_returns_maximized_after_fullscreen_emergency_hide(window):
    play_to_twenty_seconds(window)
    window.showMaximized()
    QApplication.processEvents()
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.isMaximized() and not window.isFullScreen()
