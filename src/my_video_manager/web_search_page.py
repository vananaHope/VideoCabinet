"""검색 상태는 컨트롤러에 보존하고 색인 준비만 기존 작업자에 맡긴다."""
from PySide6.QtCore import QObject, QTimer

from .search_preparation import SearchPreparation
from .search import SEARCH_LIMIT
from .web_search_contract import SEARCH
from .web_json import encode
from .web_page import WebPageController
from .web_search_data import result_data


class SearchBridge(QObject):
    changed = SEARCH.signal('changed')
    focusRequested = SEARCH.signal('focusRequested')
    error = SEARCH.signal('error')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @SEARCH.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @SEARCH.slot('snapshot')
    def snapshot(self):
        return self.page.stamp(self.page.payload())

    @SEARCH.slot('find')
    def find(self, query):
        self.page.query = query
        self.page.results = []
        self.page.selected_index = -1
        self.page.dirty = True
        self.page.refresh()
        return encode({'ok': True})

    @SEARCH.slot('select')
    def select(self, index):
        if not 0 <= index < len(self.page.results):
            return encode({'error': '현재 목록에 없는 검색 결과입니다.'})
        self.page.selected_index = index
        return encode({'ok': True})

    @SEARCH.slot('play')
    def play(self, index):
        if self.busy or not 0 <= index < len(self.page.results):
            return encode({'error': '현재 목록에 없는 검색 결과입니다.'})
        result = self.page.results[index]
        if result.missing:
            return encode({'error': '파일 없음: 영상의 위치를 다시 연결한 뒤 재생하세요.'})
        self.page.selected_index = index
        self.busy = True
        QTimer.singleShot(0, lambda: self.perform_play(result))
        return encode({'ok': True})

    def perform_play(self, result):
        try:
            self.page.window.set_playback_list(tuple(dict.fromkeys(r.video_id for r in self.page.results)), "검색 결과")
            self.page.window.play_video(result.video_id, start=result.start)
        finally:
            self.busy = False


class WebSearchPage(WebPageController):
    tab = 'search'
    default_focus = 'search-content'

    def __init__(self, host):
        super().__init__(host)
        self.query, self.results, self.selected_index = '', [], -1
        self.state, self.error, self.truncated, self.dirty = 'empty', '', False, True
        self.preparation = SearchPreparation(self.core, self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.bridge = SearchBridge(self)
        self.focus_requested = self.bridge.focusRequested
        host.register_page(self)

    def payload(self):
        return dict(query=self.query, results=[result_data(r, self.query) for r in self.results],
                    selectedIndex=self.selected_index, state=self.state,
                    truncated=self.truncated, error=self.error, limit=SEARCH_LIMIT)

    def refresh(self):
        # 검색어가 바뀌었거나, 숨어 있던 동안 제목·태그·자막처럼 찾는 내용이 바뀌었을 때만 다시 찾는다(#265).
        if not self.dirty and not self.outdated:
            return
        # 같은 검색어를 다시 찾으면 고르던 결과를 지킨다. 검색어가 바뀌면 첫 결과부터다.
        kept = None if self.dirty or not 0 <= self.selected_index < len(self.results) else self.results[self.selected_index]
        self.timer.stop()
        self.truncated, self.error = False, ''
        try:
            if not self.preparation.ready():
                self.state = 'preparing'
                if self.is_active():
                    self.timer.start()
            else:
                response = self.core.search(self.query)
                self.results, self.truncated = list(response.results), response.truncated
                self.selected_index = next((i for i, result in enumerate(self.results) if kept is not None
                                            and (result.video_id, result.source, result.start) == (kept.video_id, kept.source, kept.start)),
                                           0 if self.results else -1)
                self.state = 'results' if self.results else 'no-results' if self.query.strip() else 'empty'
                self.dirty = False
        except Exception as error:
            self.error, self.state = str(error), 'error'
        self.publish(self.bridge.changed, self.payload())
        if self.state in ('preparing', 'error'):
            # 준비 중이거나 실패한 검색은 다시 보일 때 다시 시도한다.
            self.synced_change = None

    def deactivated(self):
        self.timer.stop()
