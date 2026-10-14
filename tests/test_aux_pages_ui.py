"""페이지 이동 뒤 상태 보존과 숨긴 대기열의 갱신 경계를 검증한다."""

from types import SimpleNamespace
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QProgressBar

from my_video_manager.queue_ui import PROGRESS_ROLE, SubtitleQueuePage, SubtitleQueueView
from my_video_manager.subtitle_queue import SubtitleQueueItem
from my_video_manager.search import SearchResponse, SearchResult
from my_video_manager.search_ui import SearchPage, highlighted_text
from my_video_manager.theme import ACCENT
from test_library_return_ui import app, library_window
from test_subtitles import setup


@pytest.mark.parametrize("entry_key", [Qt.Key.Key_Down, Qt.Key.Key_Return])
def test_search_keyboard_playback_returns_to_query_results_and_selection(library_window, app, entry_key):
    window, core, video = library_window
    core.add_video_tag(video.id, "영상 태그")
    core.prepare_search()
    window.show_search()
    page = window.navigation_pages[2]
    assert isinstance(page, SearchPage) and not isinstance(page, QDialog)
    page.query.setText("영상")
    page.query.setFocus()
    QTest.keyClick(page.query, entry_key)
    app.processEvents()
    assert page.results.hasFocus()
    assert page.results.count() >= 2
    page.results.setCurrentRow(1)
    chosen = page.results.currentItem()
    result = chosen.data(Qt.ItemDataRole.UserRole)
    QTest.keyClick(page.results, Qt.Key.Key_Return)
    assert core.playback.session.video_id == result.video_id
    assert window.playback_list == page.video_ids
    assert window.pages.currentWidget() is window.playback_page
    QTest.keyClick(window.surface, Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is page
    assert page.query.text() == "영상"
    assert page.results.currentItem() is chosen
    assert page.results.currentRow() == 1
    assert page.results.hasFocus()


def test_search_preparation_accepts_input_and_missing_result_does_not_play(app):
    ready = SimpleNamespace(ready=lambda: False)
    core = SimpleNamespace(search=lambda query: SearchResponse((
        SearchResult(1, "파일 없는 영상", "note", "기억할 장면", 12, True),)))
    page = SearchPage(core, preparation=ready)
    chosen = []
    page.result_chosen.connect(chosen.append)
    page.show()
    page.query.setText("장면")
    page.refresh()
    assert page.query.isEnabled() and page.status.text() == "검색 색인 준비 중…"
    assert page.timer.isActive()
    ready.ready = lambda: True
    page.refresh()
    page.choose(page.results.item(0))
    assert not chosen
    assert "파일 없음" in page.status.text()
    page.hide()
    assert not page.timer.isActive()
    page.deleteLater()
    app.processEvents()


def test_search_empty_and_capped_results_keep_guidance(app):
    core = SimpleNamespace(search=lambda query: SearchResponse())
    page = SearchPage(core, preparation=SimpleNamespace(ready=lambda: True))
    page.query.setText("없음")
    page.refresh()
    assert page.results.count() == 0
    assert page.status.text() == "검색 결과 0개"
    core.search = lambda query: SearchResponse((SearchResult(1, "영상", "title", "영상"),), True)
    page.refresh()
    assert "더 길게 입력" in page.status.text()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("text,query,match", [
    ("앞 Hello World 뒤", "helloworld", "Hello World"),
    ("앞 ＡＢＣ 뒤", "abc", "ＡＢＣ"),
    ("앞 Straße 뒤", "strasse", "Straße"),
    ("앞 가 뒤", "가", "가"),
    ("😀 <장면>", "장면", "장면"),
])
def test_search_highlight_matches_normalized_query_and_escapes_markup(text, query, match):
    html = highlighted_text(text, query)
    assert f'color:{ACCENT}' in html
    assert f'>{match}</span>' in html
    assert "<장면>" not in html


def test_queue_filters_actions_and_unchanged_snapshot_preserve_selection(setup, app):
    core, adapter, (a, b) = setup
    core.request_subtitles(a.id, "ko")
    core.process_next_subtitle()
    core.request_subtitles(b.id, "ko")
    page = SubtitleQueuePage(core)
    page.show()
    app.processEvents()
    queue = page.queue
    queue.state_filter.setCurrentIndex(queue.state_filter.findData("queued"))
    assert queue.list.topLevelItemCount() == 1
    item = queue.list.topLevelItem(0)
    assert item.text(0) == b.title
    assert queue.list.itemWidget(item, 2) is None
    assert item.data(2, PROGRESS_ROLE) == 0
    queue.refresh()
    assert queue.list.currentItem() is item
    queue.promote()
    assert core.subtitle_queue()[0].video_id == b.id
    queue.remove()
    assert queue.list.topLevelItemCount() == 0
    queue.state_filter.setCurrentIndex(queue.state_filter.findData("completed"))
    assert queue.list.topLevelItem(0).text(0) == a.title
    page.close()
    page.deleteLater()
    app.processEvents()


def test_queue_polls_only_visible_tab_and_rules_refresh_targets(setup, app, monkeypatch):
    core, _, (a, b) = setup
    calls = []
    original = core.subtitle_queue_items
    monkeypatch.setattr(core, "subtitle_queue_items", lambda: (calls.append(1), original())[1])
    page = SubtitleQueuePage(core)
    assert not calls
    page.show()
    app.processEvents()
    assert calls and page.queue.timer.isActive()
    page.tabs.setCurrentIndex(1)
    assert not page.queue.timer.isActive()
    count = len(calls)
    QTest.qWait(550)
    assert len(calls) == count
    page.hide()
    tag = core.create_tag("새로 만든 태그")
    page.show()
    app.processEvents()
    assert any(page.rules.target.itemData(i) == {"tag_id": tag.id}
               for i in range(page.rules.target.count()))
    page.rules.target.setCurrentIndex(page.rules.target.count() - 1)
    page.rules.language.setCurrentText("ja")
    page.rules.save()
    rule, = core.auto_subtitle_rules()
    assert rule.tag_id == tag.id and rule.spoken_language == "ja"
    page.rules.list.setCurrentRow(0)
    page.rules.remove()
    assert core.auto_subtitle_rules() == ()
    page.tabs.setCurrentIndex(0)
    assert page.queue.timer.isActive()
    page.hide()
    count = len(calls)
    QTest.qWait(550)
    assert len(calls) == count
    page.deleteLater()
    app.processEvents()


def test_tray_queue_opens_page_and_stops_polling_when_leaving(library_window, app):
    window, core, video = library_window
    window.hide()
    window.tray.show_queue()
    app.processEvents()
    page = window.navigation_pages[3]
    assert window.isVisible() and window.pages.currentWidget() is page
    assert page.queue.timer.isActive()
    window.navigate(0)
    assert not page.queue.timer.isActive()


def test_queue_progress_updates_only_changed_row_without_losing_selection_or_scroll(app):
    entries = tuple(SubtitleQueueItem(i, f"영상 {i}", "transcribing" if i == 0 else "queued", 0)
                    for i in range(300))
    view = SubtitleQueueView(SimpleNamespace(subtitle_queue_items=lambda: entries))
    view.resize(800, 450)
    view.show()
    view.timer.stop()
    app.processEvents()
    first = view.list.topLevelItem(0)
    selected = view.list.topLevelItem(120)
    view.list.setCurrentItem(selected)
    view.list.scrollToItem(selected)
    app.processEvents()
    scroll = view.list.verticalScrollBar().value()
    changes = []
    view.list.model().dataChanged.connect(lambda start, end, roles: changes.append((start.row(), end.row())))
    for progress in (.25, .5, .75):
        entries = (replace(entries[0], progress=progress),) + entries[1:]
        view.refresh()
        app.processEvents()
        assert view.list.topLevelItem(0) is first
        assert view.list.currentItem() is selected
        assert view.list.verticalScrollBar().value() == scroll
        assert first.data(2, PROGRESS_ROLE) == progress
        assert first.text(2) == f"{progress:.0%}"
    assert changes and set(changes) == {(0, 0)}
    assert view.findChildren(QProgressBar) == []
    view.close()
    view.deleteLater()
    app.processEvents()


def test_queue_reorders_and_removes_rows_while_retaining_surviving_items(app):
    entries = tuple(SubtitleQueueItem(i, f"영상 {i}", "queued", 0) for i in range(3))
    view = SubtitleQueueView(SimpleNamespace(subtitle_queue_items=lambda: entries))
    view.show()
    view.timer.stop()
    app.processEvents()
    selected = view.list.topLevelItem(1)
    view.list.setCurrentItem(selected)
    entries = (entries[1], entries[2], SubtitleQueueItem(4, "새 영상", "queued", 0))
    view.refresh()
    assert view.list.topLevelItemCount() == 3
    assert view.list.topLevelItem(0) is selected
    assert view.list.currentItem() is selected
    assert [view.list.topLevelItem(i).text(0) for i in range(3)] == ["영상 1", "영상 2", "새 영상"]
    view.close()
    view.deleteLater()
    app.processEvents()


def test_search_repaint_and_resize_reuse_highlights_but_new_query_and_content_refresh(app, monkeypatch):
    import my_video_manager.search_ui as search_ui

    response = SearchResponse((SearchResult(1, "장면 영상", "note", "중요한 장면"),))
    core = SimpleNamespace(search=lambda query: response)
    calls = []
    original = search_ui.highlighted_text
    monkeypatch.setattr(search_ui, "highlighted_text", lambda text, query: (calls.append((text, query)), original(text, query))[1])
    documents = []
    document_class = search_ui.QTextDocument

    def new_document():
        document = document_class()
        documents.append(document)
        return document

    monkeypatch.setattr(search_ui, "QTextDocument", new_document)
    page = SearchPage(core, preparation=SimpleNamespace(ready=lambda: True))
    page.resize(800, 600)
    page.query.setText("장면")
    page.show()
    app.processEvents()
    previous_calls = len(calls)
    assert previous_calls > 0
    previous_documents = len(documents)
    page.results.viewport().repaint()
    app.processEvents()
    assert len(documents) == previous_documents
    for width in (800, 900, 800):
        page.resize(width, 600)
        page.results.viewport().repaint()
        app.processEvents()
    assert len(calls) == previous_calls
    previous_documents = len(documents)
    page.results.viewport().repaint()
    app.processEvents()
    assert len(documents) == previous_documents
    page.query.setText("중요")
    page.refresh()
    app.processEvents()
    assert calls[-1] == ("중요한 장면", "중요")
    response = SearchResponse((SearchResult(1, "장면 영상", "note", "내용 수정"),))
    page.refresh()
    app.processEvents()
    assert calls[-1] == ("내용 수정", "중요")
    assert page.results.item(0).data(Qt.ItemDataRole.UserRole).text == "내용 수정"
    page.close()
    page.deleteLater()
    app.processEvents()


def test_tray_queue_during_playback_finishes_viewing_like_sidebar_navigation(library_window, app):
    window, core, video = library_window
    window.play_video(video.id)
    window.tray.show_queue()
    app.processEvents()
    assert core.playback.session is None
    assert window.pages.currentWidget() is window.navigation_pages[3]
