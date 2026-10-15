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
        self.seeks = []
        self.positions = []

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        self.closed = True

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        return False

    def playback_options(self):
        if self.closed:
            raise RuntimeError("종료된 mpv 속성 조회")
        return self.options

    def apply_playback_options(self, options):
        self.options = options

    def seek_to(self, position, *, resume=False):
        self.seeks.append((position, resume))

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
    assert not window.statusBar().isVisible()


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
    assert window.web_host.active_tab == 'search'


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


@pytest.mark.parametrize("fullscreen", [False, True])
def test_settings_menu_shortcut_and_return_to_playback_focus(window, fullscreen):
    if fullscreen:
        key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    assert QApplication.activePopupWidget() is window.settings_menu
    assert window.isFullScreen() is fullscreen
    QTest.keyClick(window.settings_menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not window.settings_menu.isVisible()
    assert window.surface.hasFocus()
    assert window.isFullScreen() is fullscreen
    assert window.core.playback.session is not None


def test_open_range_start_is_visible_until_range_is_finished(window):
    window.core.playback.report(10)
    key(window, Qt.Key.Key_Delete)
    page = window.playback_page
    assert page.open_range_label.isVisible()
    assert page.open_range_label.text() == "구간 시작 00:00:10"
    assert "Delete: 끝내기" in page.position_label.toolTip()
    window.core.playback.report(15)
    key(window, Qt.Key.Key_Delete)
    assert not page.open_range_label.isVisible()


def test_general_notice_expires_and_does_not_change_fullscreen_bar(window):
    page = window.playback_page
    window.statusBar().showMessage("자막 대기열에 추가했습니다")
    assert page.message_label.isVisible()
    QTest.qWait(5200)
    assert not page.message_label.isVisible()
    assert page.message_label.text() == ""
    key(window, Qt.Key.Key_Apostrophe)
    window.statusBar().showMessage("번역 진행 · 10/100줄")
    assert not page.bottom_bar.isVisible()
    key(window, Qt.Key.Key_Right)
    assert page.bottom_bar.isVisible()
    assert not page.message_label.isVisible()
    page.show_error("재생 위치 확인 실패")
    window.statusBar().showMessage("번역 완료")
    assert page.bottom_bar.isVisible()
    assert page.message_label.isVisible()
    assert page.message_label.text() == "재생 위치 확인 실패"
    assert not page.notice_timer.isActive()


@pytest.mark.parametrize(("pressed", "command"), [
    (Qt.Key.Key_Return, Command(CommandType.TOGGLE_PAUSE)),
    (Qt.Key.Key_Down, Command(CommandType.CHANGE_SPEED, -0.25)),
])
def test_back_button_focus_keeps_playback_commands(window, pressed, command):
    window.playback_page.back_button.setFocus()
    key(window, pressed)
    assert window.player.commands == [command]
    assert window.core.playback.session is not None


def test_space_activates_focused_back_button(window):
    window.playback_page.back_button.setFocus()
    key(window, Qt.Key.Key_Space)
    assert window.core.playback.session is None
    assert window.pages.currentWidget() is window.web_host


def add_highlight(window, start, end=None, note=''):
    core = window.core
    core.playback.report(start, seeked=True)
    core.execute_highlight_command(core.command_for_key('Insert'))
    highlight = next(h for h in core.highlights(core.playback.session.video_id) if h.start == start)
    core.update_highlight(highlight.id, start=start, end=end, note=note)
    window.refresh_highlights()
    return highlight.id


def test_highlight_click_seeks_engine_without_inventing_position_reports(window):
    add_highlight(window, 20, note='다시 볼 장면')
    window.core.playback.report(1, seeked=True)
    window.sync_position()
    panel = window.playback_page.highlights_panel
    session = window.core.playback.session
    QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton,
                     pos=panel.list.visualItemRect(panel.list.item(0)).center())
    assert window.player.seeks == [(20, True)]
    assert window.core.playback.position == 1
    assert window.core.playback.session is session
    window.player.positions = [(20, True)]
    window.sync_position()
    assert window.core.playback.position == 20
    assert window.surface.hasFocus()


def test_playback_position_changes_preserve_highlight_selection(window):
    add_highlight(window, 10)
    add_highlight(window, 20, end=30, note='구간')
    panel = window.playback_page.highlights_panel
    panel.list.setCurrentRow(0)
    for position in (15, 25, 100):
        window.core.playback.report(position, seeked=True)
        window.sync_position()
        assert panel.list.currentRow() == 0


def test_highlight_toggle_custom_key_fullscreen_restore_and_next_video(window):
    page = window.playback_page
    panel = page.highlights_panel
    assert panel.empty.isVisible()
    add_highlight(window, 10)
    assert not panel.empty.isVisible()
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.TOGGLE_HIGHLIGHT_LIST)] = ('L',)
    window.core.save_key_bindings(bindings)
    window.refresh_key_help()
    assert 'L' in page.highlights_button.toolTip()
    key(window, Qt.Key.Key_L)
    assert not panel.isVisible()
    key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_L)
    assert not panel.isVisible()
    key(window, Qt.Key.Key_Escape)
    assert not panel.isVisible()
    key(window, Qt.Key.Key_L)
    assert panel.isVisible()
    key(window, Qt.Key.Key_Apostrophe)
    key(window, Qt.Key.Key_Escape)
    assert panel.isVisible()
    key(window, Qt.Key.Key_PageDown)
    window.sync_position()
    assert panel.list.count() == 0
    assert panel.empty.isVisible()


def test_highlight_list_keyboard_and_long_memo_do_not_cover_surface(window):
    for start in range(1, 60):
        add_highlight(window, start, note='<b>긴 메모</b>\n' * 100 if start == 2 else '')
    page = window.playback_page
    panel = page.highlights_panel
    QApplication.processEvents()
    panel.list.setFocus()
    panel.list.setCurrentRow(0)
    key(window, Qt.Key.Key_Down)
    assert panel.list.currentRow() == 1
    assert not window.player.commands
    assert '<b>긴 메모</b>' in panel.list.currentItem().toolTip()
    assert window.width() == 1100
    assert page.surface.geometry().right() < panel.geometry().left()
    assert panel.list.verticalScrollBar().maximum() > 0
    key(window, Qt.Key.Key_Return)
    assert window.player.seeks == [(2, True)]
    assert window.surface.hasFocus()


def test_highlight_click_exits_reel_preserves_revisit_and_starts_viewing(window):
    first = add_highlight(window, 10, end=40)
    add_highlight(window, 50)
    window.reel.open()
    window.reel.start(first)
    window.sync_position()
    core = window.core
    core.playback.report(11)
    core.playback.report(14)
    assert core.last_highlight_revisited_at(first) is not None
    revisit = core.last_highlight_revisited_at(first)
    panel = window.playback_page.highlights_panel
    QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton,
                     pos=panel.list.visualItemRect(panel.list.item(1)).center())
    assert core.reel_playback is None
    assert core.playback.session.record_viewing
    assert core.playback.position == 50
    assert core.last_highlight_revisited_at(first) == revisit
    assert not window.playback_page.reel_label.isVisible()
    assert window.reel.shown is None


@pytest.mark.parametrize('transition', ['series', 'reel'])
def test_video_transition_resets_highlight_scroll_and_selection(window, transition):
    core = window.core
    first, second = core.videos()
    # 공개 도메인 API로 두 영상에 충분히 긴 목록을 만든다.
    for video in (first, second):
        core.switch_to(video.id)
        for position in range(1, 61):
            core.playback.report(position, seeked=True)
            core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    if transition == 'reel':
        # 첫 영상 마지막 항목을 마치면 다음 영상으로 자동 전환한다.
        window.reel.open()
        window.reel.start(core.highlights(first.id)[-1].id)
    else:
        assert core.series_for_video(first.id).video_ids == (first.id, second.id)
        window.play(first.id)
    window.sync_position()
    QApplication.processEvents()
    panel = window.playback_page.highlights_panel
    panel.list.setCurrentRow(55)
    panel.list.scrollToBottom()
    assert panel.list.verticalScrollBar().value() > 0
    if transition == 'reel':
        window.player.positions = [(core.reel_playback.end, False)]
        window.poll_position()
    else:
        key(window, Qt.Key.Key_PageDown)
    window.sync_position()
    QApplication.processEvents()
    assert core.playback.session.video_id == second.id
    assert panel.list.count() == 60
    assert panel.list.verticalScrollBar().value() == 0
    assert panel.list.currentItem() is None
    assert panel.list.selectedItems() == []


def test_unassigned_point_key_guidance_and_panel_command_name(window):
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ()
    window.core.save_key_bindings(bindings)
    window.refresh_key_help()
    page = window.playback_page
    assert '키 설정에서 지점 하이라이트 키를 정하면' in page.highlights_panel.empty.text()
    assert '하이라이트 패널 접기 / 펴기' in page.highlights_button.toolTip()
    key(window, Qt.Key.Key_F1)
    assert '하이라이트 패널 접기 / 펴기' in page.help_panel.text.text()
