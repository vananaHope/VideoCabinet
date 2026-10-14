"""격자·상세·폴더 화면에서 사용자가 관찰할 수 있는 선택과 작업 경로."""

from threading import Event

from PySide6.QtCore import Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_library_return_ui import app, library_window


def add_videos(core, count=7):
    for i in range(count):
        path = core.database.parent / f"추가 영상 {i}.mkv"
        path.write_bytes(f"video {i}".encode())
        core.add_file(path)


def test_combined_title_and_tag_filters_use_snapshot_and_keep_typing_focus(library_window, app, monkeypatch):
    window, core, first = library_window
    add_videos(core, 2)
    second, third = core.videos()[1:]
    core.rename_video(first.id, "Python 기초")
    core.rename_video(second.id, "Python 응용")
    core.rename_video(third.id, "다른 강의")
    tag = core.add_video_tag(second.id, "강의")
    core.add_video_tag(third.id, "강의")
    window.refresh()
    page = window.library_page
    monkeypatch.setattr(core, "library_snapshot", lambda: (_ for _ in ()).throw(AssertionError("필터 중 재조회")))
    page.quick_search.setFocus()
    page.quick_search.setText("PYTHON")
    assert set(page.visible_video_ids()) == {first.id, second.id}
    assert page.quick_search.hasFocus()
    page.tag_filter.setCurrentIndex(page.tag_filter.findData(tag.id))
    assert page.visible_video_ids() == (second.id,)
    assert page.detail.title.text() == "Python 응용"
    page.quick_search.setText("없는 제목")
    assert page.selected_video_id() is None
    assert page.detail.empty.isVisible()
    assert "조건에 맞는" in page.empty.text()
    assert all(not a.isEnabled() for a in page.actions)


def test_grid_four_direction_navigation_enter_and_filtered_playback(library_window, app):
    window, core, first = library_window
    add_videos(core)
    window.refresh()
    page, grid = window.library_page, window.library_page.grid
    app.processEvents()
    grid.setCurrentIndex(grid.model().index(0, 0))
    grid.setFocus()
    QTest.keyClick(grid, Qt.Key.Key_Right)
    right = grid.currentIndex().row()
    assert right == 1
    QTest.keyClick(grid, Qt.Key.Key_Down)
    assert grid.currentIndex().row() > right
    QTest.keyClick(grid, Qt.Key.Key_Up)
    assert grid.currentIndex().row() == right
    QTest.keyClick(grid, Qt.Key.Key_Left)
    assert grid.currentIndex().row() == 0
    page.quick_search.setText("추가 영상")
    selected, visible = page.selected_video_id(), page.visible_video_ids()
    grid.setFocus()
    QTest.keyClick(grid, Qt.Key.Key_Return)
    assert core.playback.session.video_id == selected
    assert window.playback_list == visible
    assert window.pages.currentWidget() is window.playback_page


def test_context_menu_targets_clicked_card_and_keyboard_opens_same_actions(library_window, app, monkeypatch):
    window, core, first = library_window
    add_videos(core, 2)
    window.refresh()
    page, grid = window.library_page, window.library_page.grid
    app.processEvents()
    opened = []
    monkeypatch.setattr(page, "show_context_menu", lambda pos: opened.append(page.selected_video_id()))
    # 시그널은 기존 바운드 메서드이므로 연결도 교체한다.
    grid.menu_requested.disconnect()
    grid.menu_requested.connect(page.show_context_menu)
    index = grid.model().index(1, 0)
    point = grid.visualRect(index).center()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, grid.viewport().mapToGlobal(point))
    QApplication.sendEvent(grid.viewport(), event)
    assert opened == [index.data(Qt.ItemDataRole.UserRole)]
    assert core.playback.session is None
    grid.setFocus()
    QTest.keyClick(grid, Qt.Key.Key_Menu)
    QTest.keyClick(grid, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert len(opened) == 3
    menu = page.create_context_menu()
    assert menu.actions() == page.actions
    assert [a.text() for a in menu.actions()] == [b.text() for b in page.detail.buttons]
    menu.deleteLater()


def test_selection_refresh_preserves_video_and_updates_details_without_per_video_reads(library_window, app, monkeypatch):
    window, core, first = library_window
    add_videos(core, 2)
    window.refresh()
    page = window.library_page
    page.grid.setCurrentIndex(page.grid.model().index(1, 0))
    selected = page.selected_video_id()
    core.rename_video(selected, "바뀐 제목")
    window.refresh()
    assert page.selected_video_id() == selected
    assert page.detail.title.text() == "바뀐 제목"
    for method in ("transcript", "translation", "highlights", "viewing_status", "video_tags"):
        monkeypatch.setattr(core, method, lambda *_: (_ for _ in ()).throw(AssertionError("영상별 조회")))
    page.grid.setCurrentIndex(page.grid.model().index(0, 0))
    assert page.detail.title.text() == page.grid.model().cards[0].video.title
    assert "하이라이트 0개" in page.detail.metadata.text()


def test_folder_scan_keeps_unrelated_actions_enabled_and_reports_globally(library_window, app):
    from my_video_manager.core import ScanIssue, ScanResult
    window, core, video = library_window
    folder = window.navigation_pages[4]
    window.navigate(4)
    release = Event()
    def operation():
        release.wait(5)
        return ScanResult(0, (ScanIssue(core.database, "검사 안내", False),))
    window.scan(operation=operation)
    try:
        assert all(not button.isEnabled() for button in folder.scan_buttons)
        assert all(button.isEnabled() for button in folder.other_buttons[2:])
        assert all(not action.isEnabled() for action in window.library_page.actions[5:])
        assert all(action.isEnabled() for action in window.library_page.actions[:5])
        assert folder.progress.isVisible()
        assert "검사하고" in window.statusBar().currentMessage()
    finally:
        worker = window.worker
        release.set()
        worker.wait(5000)
        app.processEvents()
    assert window.worker is None
    assert "안내 1개" in window.statusBar().currentMessage()
    assert "검사 안내" in folder.report.toPlainText()
    assert "제목 변경" not in [b.text() for b in folder.findChildren(type(folder.scan_buttons[0]))]


def test_empty_library_shows_add_guidance_and_no_selection(library_window):
    window, core, video = library_window
    core.exclude_video(video.id)
    window.refresh()
    assert not window.library_page.visible_video_ids()
    assert "폴더 관리" in window.library_page.empty.text()
    assert window.library_page.detail.empty.isVisible()


def test_background_refresh_preserves_search_input_focus(library_window):
    window, core, video = library_window
    search = window.library_page.quick_search
    search.setFocus()
    search.setText("영상")
    window.refresh()
    assert search.hasFocus()
    assert search.text() == "영상"


def test_double_click_plays_and_gem_backspace_only_dismisses_recommendation(library_window, app):
    window, core, video = library_window
    gems = window.library_page.hidden_gems.list
    gems.setFocus()
    QTest.keyClick(gems, Qt.Key.Key_Backspace)
    assert gems.count() == 0
    assert video.id in window.library_page.visible_video_ids()
    grid = window.library_page.grid
    grid.setFocus()
    point = grid.visualRect(grid.currentIndex()).center()
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert core.playback.session.video_id == video.id
