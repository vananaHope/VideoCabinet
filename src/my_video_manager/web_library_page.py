"""라이브러리 데이터·작업 컨트롤러. 웹 뷰의 소유와 탐색은 셸에 맡긴다."""

from PySide6.QtCore import Signal
from .hidden_gems_ui import show_dismissed_dialog
from .library_page import LibraryOperations
from .library_ui import LibraryControls
from .web_library_data import snapshot_data, filter_ids
from .web_library_bridge import LibraryBridge
from .web_bridge import encode
from .web_page import WebPageController


class GemDialogs:
    def __init__(self, page):
        self.page = page

    def show_dismissed(self):
        show_dismissed_dialog(self.page, self.page.core, self.page.refresh)


class WebLibraryPage(LibraryOperations, WebPageController):
    tab = 'library'
    default_focus = 'grid'
    scan_state_changed = Signal(bool)
    scan_message = Signal(str)
    refreshed = Signal()

    def __init__(self, host):
        super().__init__(host)
        window = self.window
        self.worker = None
        self.snapshot = None
        self.cards = []
        self.video_ids = set()
        self.visible_ids = []
        self.gems, self.gem_ids = [], []
        self.gem_error = ''
        self.selected_id = None
        self.query, self.tag_id = '', None
        self.tags = []
        self.library_controls = LibraryControls(window)
        self.hidden_gems = GemDialogs(self)
        self.bridge = LibraryBridge(self)
        self.focus_requested = self.bridge.libraryFocusRequested
        host.register_page(self)
        window.subtitles.video_changed.connect(self.refresh_details)
        window.translations.video_changed.connect(self.refresh_details)

    def payload(self):
        return dict(videos=self.cards, tags=self.tags, gems=self.gems, gemError=self.gem_error,
                    visibleIds=self.visible_ids, selectedId=self.selected_id, scanning=self.worker is not None)

    def refresh(self, *, focus_gems=None):
        self.snapshot = self.core.library_snapshot()
        self.cards = snapshot_data(self.snapshot, self.core.subtitled_video_ids())
        self.video_ids = {v['id'] for v in self.cards}
        self.tags = [dict(id=t.id, name=t.name) for t in self.core.tags()]
        if self.tag_id not in {t['id'] for t in self.tags}:
            self.tag_id = None
        try:
            self.gems = [dict(videoId=g.video.id, reason=g.reason)
                         for g in self.core.hidden_gems(snapshot=self.snapshot)]
            self.gem_error = ''
        except Exception as error:
            self.gems, self.gem_error = [], str(error)
        self.gem_ids = [g['videoId'] for g in self.gems]
        self.apply_filters()
        self.bridge.libraryChanged.emit(encode(self.payload()))
        self.refreshed.emit()
        if focus_gems is not None and self.isVisible():
            self.request_focus('gems' if focus_gems else 'grid')

    def apply_filters(self):
        self.visible_ids = filter_ids(self.cards, self.query, self.tag_id)
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)
        self.window.library_count.setText(f'등록 영상 {len(self.cards)}개 · 표시 {len(self.visible_ids)}개')

    def refresh_details(self, changed_video_id=None):
        if changed_video_id is not None:
            card = next((card for card in self.cards if card['id'] == changed_video_id), None)
            if card is not None:
                has_subtitles = self.core.has_transcript(changed_video_id)
                if card['hasSubtitles'] != has_subtitles:
                    card['hasSubtitles'] = has_subtitles
                    self.bridge.libraryChanged.emit(encode(self.payload()))
        if self.selected_id is not None and (changed_video_id is None or changed_video_id == self.selected_id):
            self.bridge.libraryDetailsChanged.emit(self.selected_id)

    def selection_changed(self):
        self.bridge.libraryChanged.emit(encode(self.payload()))

    def selected_video_id(self):
        return self.selected_id

    def visible_video_ids(self):
        return tuple(self.visible_ids)
