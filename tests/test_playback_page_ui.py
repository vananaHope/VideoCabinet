"""재생 페이지의 키 우선순위·창 상태·공개 표시 동작."""

from dataclasses import replace
from datetime import datetime, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, "matroska")

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        self.options = (1, True)
        self.commands = []
        self.closed = False

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        self.closed = True

    def take_positions(self):
        return ()

    def take_eof(self):
        return False

    def playback_options(self):
        if self.closed:
            raise RuntimeError("종료된 mpv 속성 조회")
        return self.options

    def apply_playback_options(self, options):
        self.options = options

    def seek_to(self, position, *, resume=False):
        pass

    def execute(self, command):
        self.commands.append(command)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, app):
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3")
    for index in (1, 2):
        path = tmp_path / f"강의 {index:02}강.mkv"
        path.write_bytes(bytes([index]))
        core.add_file(path)
    window = MainWindow(core, player_factory=Player)
    window.show()
    window.activateWindow()
    app.processEvents()
    window.play(core.videos()[0].id)
    window.sync_position()
    app.processEvents()
    yield window
    window.tray.quit()
    window.deleteLater()
    app.processEvents()


def key(window, key, modifiers=Qt.KeyboardModifier.NoModifier):
    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(QApplication.focusWidget() or window.surface, key, modifiers)
    QApplication.processEvents()


def test_escape_closes_help_then_fullscreen_then_playback(window):
    page = window.playback_page
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()
    assert not page.header.isVisible()
    assert not page.bottom_bar.isVisible()
    assert not window.menuBar().isVisible()
    assert not window.statusBar().isVisible()
    key(window, Qt.Key.Key_F1)
    assert page.help_panel.isVisible()
    assert page.help_panel.isWindow()
    key(window, Qt.Key.Key_Escape)
    assert not page.help_panel.isVisible()
    assert window.isFullScreen()
    key(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()
    assert window.core.playback.session is not None
    assert page.header.isVisible() and page.bottom_bar.isVisible()
    key(window, Qt.Key.Key_Escape)
    assert window.core.playback.session is None
    assert window.statusBar().isVisible()


def test_next_episode_keeps_fullscreen_and_sidebar_navigation_exits(window):
    key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_PageDown)
    assert window.isFullScreen()
    assert window.core.playback.session.video_id == window.core.videos()[1].id
    window.sync_position()
    assert "2/2" in window.playback_page.title_label.text()
    key(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert not window.isFullScreen()
    assert window.core.playback.session is None
    assert window.sidebar.isVisible() and window.statusBar().isVisible()


def test_reel_next_item_preserves_fullscreen_and_shows_position(window):
    core = window.core
    for video in core.videos():
        core.switch_to(video.id)
        core.playback.report(10)
        core.execute_highlight_command(core.command_for_key("Insert"))
    window.reel.open()
    window.reel.start()
    window.sync_position()
    key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_End)
    assert window.isFullScreen()
    assert "하이라이트 2/2" in window.playback_page.reel_label.text()
    key(window, Qt.Key.Key_Backslash)
    assert "반복 켜짐" in window.playback_page.reel_label.text()
    key(window, Qt.Key.Key_F1)
    assert "다음 영상 첫 하이라이트" in window.playback_page.help_panel.text.text()


def test_help_reflects_saved_keys_and_menu_keyboard_restores_surface_focus(window):
    page = window.playback_page
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.NEXT_VIDEO)] = ("N",)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("Space",)
    window.core.save_key_bindings(bindings)
    key(window, Qt.Key.Key_F1)
    assert "<b>N</b>" in page.help_panel.text.text()
    key(window, Qt.Key.Key_F1)
    key(window, Qt.Key.Key_Tab)
    assert page.menu_button.hasFocus()
    key(window, Qt.Key.Key_Space)
    assert page.menu.isVisible()
    assert len(page.menu.actions()) == 4
    assert window.player.commands == []
    QTest.keyClick(page.menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert window.surface.hasFocus()
    key(window, Qt.Key.Key_Space)
    assert window.player.commands[-1].kind == CommandType.TOGGLE_PAUSE


def test_fullscreen_temporary_bar_and_error_remain_visible(window):
    page = window.playback_page
    key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_Right)
    assert page.bottom_bar.isVisible()
    page.hide_temporary_bar()
    assert not page.bottom_bar.isVisible()
    QTest.mouseMove(window.surface, window.surface.rect().center())
    QTest.qWait(200)
    assert page.bottom_bar.isVisible()
    page.show_error("재생 위치 확인 실패: 테스트")
    window.sync_position()
    page.hide_temporary_bar()
    assert page.bottom_bar.isVisible()
    assert "실패" in page.message_label.text()


def test_speed_subtitle_and_processing_status(window):
    page = window.playback_page
    window.player.options = (1.5, False)
    window.sync_position()
    assert page.speed_label.text() == "1.5×"
    assert "꺼짐" in page.subtitle_label.text()
    page._details = replace(page._details, original_lines=3, translation_state="held")
    window.player.options = (1.5, True)
    page.update_subtitle_label()
    assert page.subtitle_label.text() == "자막 원어 · 번역 보류"


def test_custom_tab_still_plays_on_surface_and_only_navigates_when_menu_focused(window):
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("Tab",)
    window.core.save_key_bindings(bindings)
    key(window, Qt.Key.Key_Tab)
    assert window.player.commands == [Command(CommandType.TOGGLE_PAUSE)]
    window.playback_page.menu_button.setFocus()
    key(window, Qt.Key.Key_Tab)
    assert window.player.commands == [Command(CommandType.TOGGLE_PAUSE)]


def test_reopening_same_video_clears_previous_playback_error(window):
    video_id = window.core.playback.session.video_id
    window.playback_page.show_error("재생 실패")
    window.back_to_list()
    window.play(video_id)
    window.sync_position()
    assert not window.playback_page.message_label.isVisible()


def test_inactive_window_does_not_handle_playback_keys(window):
    from PySide6.QtWidgets import QWidget
    other = QWidget()
    other.show()
    other.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(other, Qt.Key.Key_Apostrophe)
    QTest.keyClick(other, Qt.Key.Key_F1)
    assert not window.isFullScreen()
    assert not window.playback_page.help_panel.isVisible()
    other.close()
