"""재생 페이지의 키 우선순위·창 상태·공개 표시 동작."""

from dataclasses import replace
from datetime import datetime, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo, playback_speed
from my_video_manager.ui import MainWindow
from qt_wait import wait_for


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
        self.paused = False

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
        if command.kind == CommandType.TOGGLE_PAUSE:
            self.paused = not self.paused
        elif command.kind == CommandType.TOGGLE_SUBTITLES:
            self.options = (self.options[0], not self.options[1])
        elif command.kind == CommandType.CHANGE_SPEED:
            self.options = (playback_speed(self.options[0], command.amount), self.options[1])


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


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
    # processEvents만으로는 DeferredDelete가 처리되지 않는다. WebEngine을
    # QApplication/인터프리터 종료까지 남기지 않고 fixture 안에서 파괴한다.
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
    key(window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
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
    page = window.playback_page
    assert (page.list_button.text(), page.list_button.toolTip()) == ("모아보기 목록", "모아보기 목록 · Esc")
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
    visited = []
    while not page.menu_button.hasFocus() and len(visited) < 20:
        key(window, Qt.Key.Key_Tab)
        visited.append(QApplication.focusWidget())
    # 창 모드에서는 전체 화면 전용 '목록으로'를 건너뛰고 조작 줄 왼쪽부터 메뉴까지 간다.
    assert visited == [page.previous_button, page.pause_button, page.next_button,
                       page.point_button, page.range_button, page.speed_button, page.subtitles_button,
                       page.subtitle_language_button, page.key_guide_button, page.fullscreen_button,
                       page.menu_button]
    key(window, Qt.Key.Key_Space)
    assert page.menu.isVisible()
    assert len(page.menu.actions()) == 5
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
    wait_for(page.bottom_bar.isVisible)
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
    assert page.speed_button.label == "속도 1.5×"
    assert page.subtitles_button.label == "자막 꺼짐"
    assert not page.subtitles_button.isChecked()
    assert page.subtitle_language_button.label == "자막 없음"
    page._details = replace(page._details, original_lines=3, translation_state="held")
    window.player.options = (1.5, True)
    page.update_controls()
    assert page.subtitles_button.label == "자막 켜짐"
    assert page.subtitles_button.isChecked()
    assert page.subtitle_language_button.label == "원어 자막"
    assert page.subtitle_work_label.text() == "번역 보류"


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
    # 만료 시간 계약은 부하와 무관하게 검사하고, 실제 만료는 조건으로 기다린다.
    assert page.notice_timer.interval() == 5000
    assert page.notice_timer.isSingleShot()
    assert page.notice_timer.isActive()
    wait_for(lambda: not page.message_label.isVisible())
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


@pytest.mark.parametrize('fullscreen', [False, True])
def test_progress_click_keeps_focus_and_fullscreen_drag_keeps_bar(window, fullscreen):
    page = window.playback_page
    if fullscreen:
        key(window, Qt.Key.Key_Apostrophe)
        page.reveal_bar()
    QApplication.processEvents()
    progress = page.progress
    assert progress.focusPolicy() == Qt.FocusPolicy.NoFocus
    QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=QPoint(5, 7))
    assert window.player.seeks == [(0, False)]
    assert window.surface.hasFocus()
    page.hide_temporary_bar()
    assert page.bottom_bar.isVisible()
    QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=QPoint(progress.width() + 20, 7))
    assert window.player.seeks[-1] == (120, False)
    key(window, Qt.Key.Key_Return)
    assert window.player.commands[-1].kind == CommandType.TOGGLE_PAUSE


@pytest.mark.parametrize('fullscreen', [False, True])
def test_progress_hover_through_window_input_after_click(window, fullscreen):
    from my_video_manager.highlight_ui import progress_time
    from my_video_manager.time_display import timestamp

    page = window.playback_page
    if fullscreen:
        key(window, Qt.Key.Key_Apostrophe)
        page.reveal_bar()
    QApplication.processEvents()
    progress = page.progress
    pos = QPoint(progress.width() // 3, 7)
    QTest.mouseClick(progress, Qt.MouseButton.LeftButton, pos=pos)
    # QWidget 오버로드의 OS 커서 이동에 기대지 않고 실제 창의 입력 경로로 보낸다.
    QTest.mouseMove(window.windowHandle(), progress.mapTo(window, pos))
    assert QToolTip.isVisible()
    assert QToolTip.text() == timestamp(progress_time(pos.x(), progress.width(), 120))
    assert window.surface.hasFocus()


@pytest.mark.parametrize('input_kind', ['mouse', 'keyboard'])
def test_progress_and_keyboard_seek_share_viewing_and_open_range_rules(window, input_kind):
    core, player = window.core, window.player
    video_id = core.playback.session.video_id
    player.positions = [(0, True), (55, False)]
    key(window, Qt.Key.Key_Delete)
    assert core.open_highlight_start == 55
    window.progress.setFixedWidth(110)
    if input_kind == 'mouse':
        QTest.mouseClick(window.progress, Qt.MouseButton.LeftButton, pos=QPoint(55, 7))
        assert player.seeks == [(60, False)]
    else:
        key(window, Qt.Key.Key_Right)
        assert player.commands[-1] == Command(CommandType.SEEK, 5)
    # 입력만으로 위치를 바꾸지 않고, 두 경로 모두 같은 엔진 보고를 기다린다.
    assert core.playback.position == 55
    assert core.open_highlight_start == 55
    player.positions = [(60, True), (70, False)]
    window.sync_position()
    key(window, Qt.Key.Key_Delete)
    highlight = core.highlights(video_id)[0]
    assert (highlight.start, highlight.end) == (55, 70)
    window.back_to_list()
    viewing = core.viewings(video_id)[-1]
    assert viewing.intervals == ((0, 55), (60, 70))
    assert viewing.last_position == 70
    assert core.resume_start(video_id) == 67


@pytest.mark.parametrize('input_kind', ['mouse', 'keyboard'])
def test_progress_and_keyboard_seek_keep_reel_until_normal_boundary(window, input_kind):
    first = add_highlight(window, 10, end=40)
    second = add_highlight(window, 50, end=80)
    window.reel.open()
    window.reel.start(first)
    window.sync_position()
    core, player = window.core, window.player
    viewings = core.viewings(core.playback.session.video_id)
    player.positions = [(10, True), (11, False)]
    window.sync_position()
    if input_kind == 'mouse':
        QTest.mouseClick(window.progress, Qt.MouseButton.LeftButton,
                         pos=QPoint(window.progress.width() // 2, 7))
    else:
        key(window, Qt.Key.Key_Right)
    assert core.reel_playback.entry.highlight.id == first
    assert not core.playback.session.record_viewing
    player.positions = [(45, True)]
    window.poll_position()
    assert core.reel_playback.entry.highlight.id == second
    assert core.last_highlight_revisited_at(first) is None
    assert core.viewings(core.playback.session.video_id) == viewings


def click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


@pytest.mark.parametrize(("button", "pressed"), [
    ("pause_button", Qt.Key.Key_Return),
    ("subtitles_button", Qt.Key.Key_Slash),
])
def test_control_button_sends_same_command_as_key_and_keeps_surface_focus(window, button, pressed):
    key(window, pressed)
    by_key = list(window.player.commands)
    assert len(by_key) == 1
    click(getattr(window.playback_page, button))
    assert window.player.commands == by_key * 2
    assert window.surface.hasFocus()


def test_previous_next_buttons_move_like_page_keys(window):
    page, videos = window.playback_page, window.core.videos()
    click(page.next_button)
    assert window.core.playback.session.video_id == videos[1].id
    click(page.previous_button)
    assert window.core.playback.session.video_id == videos[0].id


def test_pause_button_shape_and_accessible_name_follow_pause_state(window):
    page = window.playback_page
    window.sync_position()
    assert (page.pause_button.text(), page.pause_button.accessibleName()) == ("⏸", "일시정지")
    click(page.pause_button)
    assert (page.pause_button.text(), page.pause_button.accessibleName()) == ("▶", "재생")
    key(window, Qt.Key.Key_Return)
    window.sync_position()
    assert (page.pause_button.text(), page.pause_button.accessibleName()) == ("⏸", "일시정지")


def test_subtitle_buttons_show_state_and_language_notice_matches_period_key(window):
    page = window.playback_page
    click(page.subtitles_button)
    assert (page.subtitles_button.label, page.subtitles_button.isChecked()) == ("자막 꺼짐", False)
    key(window, Qt.Key.Key_Period)
    by_key = window.statusBar().currentMessage()
    assert by_key
    window.statusBar().clearMessage()
    assert not page.message_label.isVisible()
    click(page.subtitle_language_button)
    assert window.statusBar().currentMessage() == by_key
    assert page.message_label.isVisible() and page.message_label.text() == by_key


def test_tooltips_show_current_keys_and_follow_saved_bindings(window):
    page = window.playback_page
    assert page.pause_button.toolTip() == "재생/일시정지 · Enter"
    assert page.previous_button.toolTip() == "이전 영상 · Page Up"
    assert page.subtitle_language_button.toolTip() == "원어 / 번역 자막 전환 · . (마침표)"
    assert page.fullscreen_button.toolTip() == "전체 화면 켜기/끄기 · ' (작은따옴표)"
    assert page.key_guide_button.toolTip() == "키 안내 · F1"
    assert page.list_button.toolTip() == "목록으로 · Esc"
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("Space",)
    bindings[Command(CommandType.TOGGLE_SUBTITLES)] = ()
    bindings[Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)] = ("L",)
    window.core.save_key_bindings(bindings)
    window.refresh_key_help()
    assert page.pause_button.toolTip() == "재생/일시정지 · Space"
    assert page.subtitles_button.toolTip() == "자막 켜기/끄기 · 키 미할당"
    assert page.subtitle_language_button.toolTip() == "원어 / 번역 자막 전환 · L"


def tab_to(window, button):
    window.surface.setFocus()
    for _ in range(10):
        key(window, Qt.Key.Key_Tab)
        if button.hasFocus():
            return
    raise AssertionError("Tab으로 단추에 가지 못함")


def test_focused_control_button_keeps_playback_keys_and_presses_with_space(window):
    # 머리 줄 '목록으로'와 같은 규칙: Space는 초점 단추를 누르고, Enter 등은 지금 키 배치의 재생 명령이다.
    page, videos = window.playback_page, window.core.videos()
    tab_to(window, page.next_button)
    key(window, Qt.Key.Key_Right)
    key(window, Qt.Key.Key_Down)
    key(window, Qt.Key.Key_Return)
    assert window.player.commands == [Command(CommandType.SEEK, 5), Command(CommandType.CHANGE_SPEED, -0.25),
                                      Command(CommandType.TOGGLE_PAUSE)]
    assert window.core.playback.session.video_id == videos[0].id
    key(window, Qt.Key.Key_Space)
    assert window.core.playback.session.video_id == videos[1].id
    tab_to(window, page.subtitles_button)
    key(window, Qt.Key.Key_Enter)
    assert window.player.commands == [Command(CommandType.TOGGLE_PAUSE)]
    assert page.subtitles_button.isChecked()
    key(window, Qt.Key.Key_Space)
    assert window.player.commands == [Command(CommandType.TOGGLE_PAUSE), Command(CommandType.TOGGLE_SUBTITLES)]
    assert not page.subtitles_button.isChecked()


def test_key_guide_button_opens_and_mouse_closes_key_guide(window):
    page = window.playback_page
    click(page.key_guide_button)
    assert page.help_panel.isVisible() and page.key_guide_button.isChecked()
    assert not page.help_panel.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not page.help_panel.windowFlags() & Qt.WindowType.WindowTransparentForInput
    click(page.help_panel.close_button)
    assert not page.help_panel.isVisible() and not page.key_guide_button.isChecked()
    key(window, Qt.Key.Key_F1)
    assert page.help_panel.isVisible() and page.key_guide_button.isChecked()
    key(window, Qt.Key.Key_F1)
    assert not page.help_panel.isVisible() and not page.key_guide_button.isChecked()


def test_fullscreen_bar_turns_fullscreen_off_and_returns_to_list(window):
    page = window.playback_page
    assert not page.list_button.isVisible()
    click(page.fullscreen_button)
    assert window.isFullScreen() and page.fullscreen_button.isChecked()
    assert not page.bottom_bar.isVisible()
    page.reveal_bar()
    assert page.list_button.isVisible()
    assert page.list_button.toolTip() == "목록으로 · Esc"
    assert page.fullscreen_button.accessibleName() == "전체 화면"
    click(page.fullscreen_button)
    assert not window.isFullScreen() and not page.fullscreen_button.isChecked()
    assert window.core.playback.session is not None
    assert not page.list_button.isVisible() and page.header.isVisible()
    key(window, Qt.Key.Key_Apostrophe)
    page.reveal_bar()
    click(page.list_button)
    assert not window.isFullScreen()
    assert window.core.playback.session is None
    assert window.pages.currentWidget() is window.web_host


def test_control_bar_shortens_labels_only_while_narrow(window):
    # 1100×720 실제 글꼴 폭은 scripts/check_playback_controls.py --offscreen이 확인한다.
    page = window.playback_page
    row = page.controls.layout()
    window.resize(3000, 720)
    QApplication.processEvents()
    assert not any(button.compact for button in page.compact_order)
    full = row.minimumSize().width()
    labels = [button.text() for button in page.compact_order]
    window.resize(window.width() - (page.controls.width() - full) - 1, 720)
    QApplication.processEvents()
    assert page.controls.width() == full - 1
    assert any(button.compact for button in page.compact_order)
    assert row.minimumSize().width() <= page.controls.width()
    window.resize(3000, 720)
    QApplication.processEvents()
    assert [button.text() for button in page.compact_order] == labels
    # 창 크기가 그대로여도 단추 글자가 길어져 넘치면 다시 줄인다.
    window.resize(window.width() - (page.controls.width() - full), 720)
    QApplication.processEvents()
    assert not any(button.compact for button in page.compact_order)
    page.subtitle_language_button.set_label("다듬은 자막", "다듬은")
    QApplication.processEvents()
    assert page.subtitle_language_button.text() == "다듬은 자막"
    assert row.minimumSize().width() <= page.controls.width()
    # 하이라이트 단추부터 아이콘만 남긴다. 줄어도 기능 이름(툴팁·접근성 이름)은 그대로다.
    assert page.point_button.text() == "◆"
    assert page.point_button.toolTip() == "지점 하이라이트 추가 · Insert"
    assert page.point_button.accessibleName() == "지점 하이라이트 추가"


def test_highlight_buttons_run_same_commands_as_insert_and_delete(window):
    page, core = window.playback_page, window.core
    video_id = core.playback.session.video_id
    assert page.point_button.toolTip() == "지점 하이라이트 추가 · Insert"
    assert page.range_button.toolTip() == "구간 하이라이트 시작 · Delete"
    window.player.positions = [(10, True)]
    click(page.point_button)
    assert [(h.start, h.end) for h in core.highlights(video_id)] == [(10, None)]
    window.player.positions = [(20, False)]
    click(page.range_button)
    assert core.open_highlight_start == 20
    assert page.range_button.isChecked() and page.range_button.label == "】 구간 끝내기"
    assert page.range_button.accessibleName() == "구간 하이라이트 끝내기"
    assert page.range_button.toolTip() == "구간 하이라이트 끝내기 · Delete"
    assert window.surface.hasFocus()
    # 열린 구간은 키로도 끝낼 수 있고, 단추는 다시 '구간 시작'이 된다.
    window.player.positions = [(30, False)]
    key(window, Qt.Key.Key_Delete)
    assert [(h.start, h.end) for h in core.highlights(video_id)] == [(10, None), (20, 30)]
    assert not page.range_button.isChecked() and page.range_button.label == "【 구간 시작"
    # 키로 연 구간은 단추로 끝낸다.
    window.player.positions = [(40, False)]
    key(window, Qt.Key.Key_Delete)
    assert page.range_button.isChecked()
    window.player.positions = [(50, False)]
    click(page.range_button)
    assert (40, 50) in [(h.start, h.end) for h in core.highlights(video_id)]
    assert not page.range_button.isChecked()
    assert window.player.commands == []


def test_highlight_button_tooltips_follow_saved_bindings(window):
    page = window.playback_page
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ("P",)
    bindings[Command(CommandType.RANGE_HIGHLIGHT)] = ()
    bindings[Command(CommandType.CHANGE_SPEED, 0.25)] = ("]",)
    window.core.save_key_bindings(bindings)
    window.refresh_key_help()
    assert page.point_button.toolTip() == "지점 하이라이트 추가 · P"
    assert page.range_button.toolTip() == "구간 하이라이트 시작 · 키 미할당"
    assert page.speed_button.toolTip() == "재생 속도 · 올리기 ] (닫는 대괄호) / 내리기 ↓"


def with_menu(button, menu, action=None):
    """InstantPopup 단추의 메뉴는 exec 안에서 열린다. 열린 동안 action(눌러 고르기)을 하고, 남아 있으면 닫는다.

    메뉴가 열렸을 때의 활성 팝업과 체크된 항목을 돌려준다.
    """
    seen = {}
    timer = QTimer()
    timer.setInterval(10)

    def run():
        if not menu.isVisible():
            return
        timer.stop()
        seen['popup'] = QApplication.activePopupWidget()
        seen['checked'] = [item.text() for item in menu.actions() if item.isChecked()]
        try:
            if action is not None:
                item = next(item for item in menu.actions() if item.text() == action)
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(item).center())
        finally:
            if menu.isVisible():
                menu.close()

    timer.timeout.connect(run)
    timer.start()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    timer.stop()
    QApplication.processEvents()
    assert seen['popup'] is menu
    assert not menu.isVisible()
    return seen


def test_speed_button_list_and_keys_beyond_list(window):
    page = window.playback_page
    assert page.speed_button.toolTip() == "재생 속도 · 올리기 ↑ / 내리기 ↓"
    assert [action.text() for action in page.speed_menu.actions()] == [
        "0.5×", "0.75×", "1×", "1.25×", "1.5×", "1.75×", "2×"]
    assert with_menu(page.speed_button, page.speed_menu, "1.5×")['checked'] == ["1×"]
    assert window.player.commands == [Command(CommandType.CHANGE_SPEED, 0.5)]
    assert window.player.options[0] == 1.5
    assert (page.speed_button.label, page.speed_button.accessibleName()) == ("속도 1.5×", "재생 속도 1.5×")
    assert window.surface.hasFocus()
    assert with_menu(page.speed_button, page.speed_menu)['checked'] == ["1.5×"]
    # ↑ 키는 목록 끝(2×)을 넘어 갈 수 있고, 단추는 그 값을 그대로 보여 준다.
    for _ in range(5):
        key(window, Qt.Key.Key_Up)
    window.sync_position()
    assert page.speed_button.label == "속도 2.75×"
    assert with_menu(page.speed_button, page.speed_menu, "0.5×")['checked'] == []
    assert window.player.options[0] == 0.5
    assert page.speed_button.label == "속도 0.5×"
    assert window.player.commands[-1] == Command(CommandType.CHANGE_SPEED, -2.25)


@pytest.mark.parametrize("fullscreen", [False, True])
def test_playback_menu_settings_opens_same_menu_as_alt_s(window, fullscreen):
    page = window.playback_page
    if fullscreen:
        key(window, Qt.Key.Key_Apostrophe)
        page.reveal_bar()
    with_menu(page.menu_button, page.menu, "설정 · Alt+S")
    wait_for(lambda: QApplication.activePopupWidget() is window.settings_menu)
    assert window.isFullScreen() is fullscreen
    QTest.keyClick(window.settings_menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert window.surface.hasFocus()
    assert window.isFullScreen() is fullscreen
    assert window.core.playback.session is not None
