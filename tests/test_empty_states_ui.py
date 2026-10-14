"""목록이 비었을 때 목록 자리에 다음 할 일을 안내하는지 검증한다."""

from types import SimpleNamespace

from my_video_manager.key_display import display_key
from my_video_manager.search import SearchResponse, SearchResult
from my_video_manager.search_ui import SearchPage
from test_library_return_ui import app, library_window


def test_search_empty_states_follow_query_preparation_and_results(app):
    ready = SimpleNamespace(ready=lambda: True)
    core = SimpleNamespace(search=lambda query: SearchResponse())
    page = SearchPage(core, preparation=ready)
    page.show()
    assert "찾을 내용을 입력하세요" in page.empty.text()
    page.query.setText("없음")
    assert page.empty.isHidden()
    page.refresh()
    assert page.empty.isVisible() and "검색 결과가 없습니다" in page.empty.text()
    ready.ready = lambda: False
    page.refresh()
    assert "검색 색인을 준비하고 있습니다" in page.empty.text()
    ready.ready = lambda: True
    core.search = lambda query: SearchResponse((SearchResult(1, "영상", "title", "영상"),))
    page.refresh()
    assert page.empty.isHidden()
    page.deleteLater()
    app.processEvents()


def test_library_reel_and_queue_explain_what_to_do_when_empty(library_window, app):
    window, core, video = library_window
    reel = window.reel
    window.navigate(1)
    keys = {row.command.kind.value: row.keys for row in core.key_bindings()}
    assert "아직 하이라이트가 없습니다" in reel.empty.text()
    assert display_key(keys["point_highlight"][0]) in reel.empty.text()
    window.navigate(3)
    queue = window.navigation_pages[3].queue
    assert "자막 대기열이 비어 있습니다" in queue.empty.text() and queue.empty.isVisible()
    core.exclude_video(video.id)
    window.refresh()
    window.navigate(0)
    page = window.library_page
    assert page.empty.isVisible() and "폴더 관리" in page.empty.text()
    # 추천이 사라진 뒤에는 숨겨진 보석 줄이 격자 공간을 차지하지 않는다.
    assert page.hidden_gems.height() <= page.hidden_gems.sizeHint().height()


def test_empty_reel_guidance_follows_saved_key_bindings(library_window, app, monkeypatch):
    import my_video_manager.ui as ui
    from my_video_manager.core import Command, CommandType

    window, core, _ = library_window
    window.navigate(1)
    assert "Insert" in window.reel.empty.text()

    class SavingDialog:
        def __init__(self, core, parent):
            self.core = core

        def exec(self):
            bindings = {row.command: row.keys for row in self.core.key_bindings()}
            bindings[Command(CommandType.POINT_HIGHLIGHT)] = ("F8",)
            self.core.save_key_bindings(bindings)

    monkeypatch.setattr(ui, "SettingsDialog", SavingDialog)
    window.show_settings()
    assert "F8로 지점" in window.reel.empty.text()
