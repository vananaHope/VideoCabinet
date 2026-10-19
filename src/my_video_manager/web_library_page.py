"""라이브러리 데이터·작업 컨트롤러. 웹 뷰의 소유와 탐색은 셸에 맡긴다."""

from PySide6.QtCore import Signal
from .library_operations import LibraryOperations
from .library_controls import LibraryControls
from .web_library_data import snapshot_data, tag_usage_data
from .library_views import filter_chips
from .web_library_bridge import LibraryBridge
from .web_json import encode
from .web_page import WebPageController


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
        self.selected_id = None
        self.options = self.core.library_view_options()
        self.index = None
        self.tags = []
        self.pending_thumbnails = set()
        self.library_controls = LibraryControls(window)
        self.bridge = LibraryBridge(self)
        self.focus_requested = self.bridge.libraryFocusRequested
        host.register_page(self)
        window.subtitles.video_changed.connect(self.refresh_details)
        window.translations.video_changed.connect(self.refresh_details)

    def payload(self):
        return dict(videos=self.cards, tags=self.tags, scanning=self.worker is not None, folders=self.index.folders if self.index else [],
                    **self.view_payload())

    def view_payload(self):
        return dict(visibleIds=self.visible_ids, selectedId=self.selected_id, options=self.options,
                    chips=filter_chips(self.options, {t['id']: t['name'] for t in self.tags}))

    def set_view(self, options):
        self.options = self.core.save_library_view_options(options)
        self.apply_filters()

    # 이전 공개 filter 슬롯도 동일한 코어 판정으로 통한다.
    @property
    def query(self):
        return self.options['query']

    @query.setter
    def query(self, value):
        self.options['query'] = value

    @property
    def tag_id(self):
        return next(iter(self.options['tags']), None)

    @tag_id.setter
    def tag_id(self, value):
        self.options['tags'] = [value] if value is not None else []

    def refresh(self, *, focus=False):
        self.snapshot = self.core.library_snapshot()
        self.index = self.core.library_view_index(self.snapshot)
        self.cards = snapshot_data(self.snapshot, self.index.original)
        self.video_ids = {v['id'] for v in self.cards}
        self.tags = tag_usage_data(self.core.tag_usage())
        self.options['tags'] = [tid for tid in self.options['tags'] if tid in {t['id'] for t in self.tags}]
        if self.options['folder'] not in self.index.members:
            self.options['folder'] = ''
        self.apply_filters()
        self.bridge.libraryChanged.emit(encode(self.payload()))
        self.refreshed.emit()
        if focus and self.is_active():
            self.request_focus('grid')

    def apply_filters(self):
        self.visible_ids = self.core.library_view_ids(self.options, index=self.index) if self.index else []
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)

    def return_from_playback(self):
        self.refresh(focus=True)

    def refresh_details(self, changed_video_id=None):
        # 자막·번역·하이라이트 변경은 현재 조건의 결과에도 즉시 반영한다.
        if changed_video_id is not None and self.snapshot is not None:
            self.index = self.core.library_view_index(self.snapshot)
            self.apply_filters()
            for card in self.cards:
                card['hasSubtitles'] = card['id'] in self.index.original
            self.bridge.libraryChanged.emit(encode(self.payload()))
        if self.selected_id is not None and (changed_video_id is None or changed_video_id == self.selected_id):
            self.bridge.libraryDetailsChanged.emit(self.selected_id)
        self.flush_thumbnails()

    def refresh_thumbnails(self, video_ids):
        for card in self.cards:
            if card['id'] in video_ids:
                card['thumbnail'] = f"mvm-thumb://video/{card['id']}?v=640"
        self.pending_thumbnails.update(video_ids)
        self.flush_thumbnails()

    def flush_thumbnails(self):
        if self.is_active() and self.pending_thumbnails:
            self.bridge.thumbnailsChanged.emit(encode(sorted(self.pending_thumbnails)))
            self.pending_thumbnails.clear()

    def activated(self):
        self.flush_thumbnails()

    def selection_changed(self):
        self.bridge.libraryChanged.emit(encode(self.payload()))

    def selected_video_id(self):
        return self.selected_id

    def visible_video_ids(self):
        return tuple(self.visible_ids)
