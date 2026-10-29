"""라이브러리 데이터·작업 컨트롤러. 웹 뷰의 소유와 탐색은 셸에 맡긴다."""

from PySide6.QtCore import Signal
from .library_operations import LibraryOperations
from .library_controls import LibraryControls
from .web_library_data import LibraryEntryData, key_bindings_data, snapshot_data, tag_usage_data
from .library_views import filter_chips
from .web_library_bridge import LibraryBridge
from .web_json import encode
from .web_page import WebPageController

# 한 번에 담는 카드 수(#267). 큰 창의 작은 카드로 보이는 줄과 위아래 여유 줄까지 덮는다.
# 스냅숏은 결과의 첫 화면을, 밀어 보내는 갱신은 바뀐 카드를 결과 앞쪽부터 이만큼만 담는다. 나머지는 웹이 화면을 그린 뒤 나눠 받는다.
SCREEN_VIDEOS = 60


class WebLibraryPage(LibraryOperations, WebPageController):
    tab = 'library'
    default_focus = 'grid'
    scan_state_changed = Signal(bool)
    scan_message = Signal(object)
    refreshed = Signal()

    def __init__(self, host):
        super().__init__(host)
        window = self.window
        self.worker = None
        self.snapshot = None
        self.cards = []
        self.card_index = {}
        self.video_ids = set()
        # 웹에 아직 알리지 않은 바뀐 카드. 다음 전체 상태가 담거나 다시 받으라고 알린다.
        self.unsent = set()
        self.visible_ids = []
        self.selected_id = None
        # 코어가 바꾼 선택을 웹이 아직 받지 않았다. 다음 전체 상태는 웹의 이전 선택을 보존하지 않는다.
        self.selection_moved = False
        # 목록 데이터를 마지막으로 다시 만든 때의 호스트 변경 번호. 숨어 있던 동안 이미 만든 목록은 다시 만들지 않는다.
        self.built_change = None
        self.options = self.core.library_view_options()
        self.index = None
        self.tags = []
        self.pending_thumbnails = set()
        self.library_controls = LibraryControls(window)
        self.bridge = LibraryBridge(self)
        self.focus_requested = self.bridge.libraryFocusRequested
        host.register_page(self)
        window.subtitles.video_changed.connect(self.refresh_subtitle_details)
        window.translations.video_changed.connect(self.refresh_subtitle_details)

    def payload(self, *, preserve_selection=False, changed=None):
        """changed가 없으면 결과 첫 화면의 카드를, 있으면 그중 바뀐 카드를 담는다. 담지 못한 바뀐 카드는 staleIds로 알린다."""
        if changed is None:
            ids = dict.fromkeys([*self.visible_ids[:SCREEN_VIDEOS], self.selected_id])
            videos, stale = [self.card_index[vid] for vid in ids if vid in self.card_index], []
        else:
            videos, stale = self.changed_videos(changed)
        return dict(videos=videos, staleIds=stale, videoCount=len(self.cards), tags=self.tags, scanning=self.worker is not None,
                    folders=self.index.folders if self.index else [], keyBindings=key_bindings_data(self.core.key_bindings()),
                    preserveSelection=preserve_selection, **self.view_payload())

    def changed_videos(self, changed):
        # 선택한 카드와 결과 앞쪽의 카드가 먼저다. 결과 밖의 카드는 뒤로 간다.
        order = {vid: index for index, vid in enumerate(self.visible_ids)}
        ids = sorted((vid for vid in changed if vid in self.card_index),
                     key=lambda vid: (vid != self.selected_id, order.get(vid, len(order)), vid))
        return [self.card_index[vid] for vid in ids[:SCREEN_VIDEOS]], ids[SCREEN_VIDEOS:]

    def snapshot_payload(self):
        """새로 읽은 웹이 처음 받는 전체 상태. 그 뒤의 카드는 웹이 지금 상태로 받으므로 알리지 않은 변경을 비운다."""
        self.unsent.clear()
        return self.payload()

    def entry_data(self):
        """웹이 처음 그릴 때 쓰는 저장된 보기 조건(#267). 첫 데이터 전의 자리 표시가 같은 카드 크기·칩·폴더 패널로 그려진다."""
        names = ({t['id']: t['name'] for t in self.tags} if self.index
                 else {usage.tag.id: usage.tag.name for usage in self.core.tag_usage()})
        return LibraryEntryData(options=self.options, chips=filter_chips(self.options, names))

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
        # 라이브러리를 다시 읽는 변경(검사·태그·제목·제외 등)은 다른 탭이 보이는 내용도 바꾼다.
        self.host.content_changed()
        self.rebuild()
        self.publish_library()
        self.refreshed.emit()
        if focus and self.is_active():
            self.request_focus('grid')

    def reshown(self):
        # 숨어 있던 동안 바뀐 것이 있을 때만 보낸다. 그 변경으로 이미 다시 만든 목록이면 다시 만들지 않는다.
        # 사용자가 하지 않은 갱신이므로 웹의 선택과 보던 자리를 지킨다(코어가 바꾼 선택은 예외).
        if self.outdated:
            if self.built_change != self.host.change:
                self.rebuild()
            self.publish_library(preserve_selection=True)

    def rebuild(self):
        self.snapshot = self.core.library_snapshot()
        self.index = self.core.library_view_index(self.snapshot)
        previous = self.card_index
        self.cards = snapshot_data(self.snapshot, self.index.original)
        self.card_index = {card['id']: card for card in self.cards}
        self.video_ids = set(self.card_index)
        self.unsent.update(vid for vid, card in self.card_index.items() if previous.get(vid) != card)
        self.tags = tag_usage_data(self.core.tag_usage())
        self.options['tags'] = [tid for tid in self.options['tags'] if tid in {t['id'] for t in self.tags}]
        if self.options['folder'] not in self.index.members:
            self.options['folder'] = ''
        self.apply_filters()
        self.built_change = self.host.change

    def publish_library(self, *, preserve_selection=False):
        preserve = preserve_selection and not self.selection_moved
        if self.publish(self.bridge.libraryChanged, self.payload(preserve_selection=preserve, changed=self.unsent)):
            self.selection_moved = False
            self.unsent.clear()

    def move_selection(self, video_id):
        """코어가 웹 모르게 바꾼 선택(무작위 연속 재생의 마지막 영상 등). 보이면 지금, 숨었으면 다시 보일 때 알린다."""
        self.selected_id = video_id
        self.selection_moved = True
        self.publish_library()

    def apply_filters(self):
        self.visible_ids = self.core.library_view_ids(self.options, index=self.index) if self.index else []
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)

    def return_from_playback(self):
        self.refresh(focus=True)

    def refresh_subtitle_details(self, video_id):
        # 완료 알림은 전송 중 사용자가 바꾼 선택을 되돌리지 않는다.
        # 전경 작업·재생 복귀의 명시적인 선택 변경과 구별한다.
        self.refresh_details(video_id, preserve_selection=True)

    def refresh_details(self, changed_video_id=None, *, preserve_selection=False):
        # 자막·번역·하이라이트 변경은 현재 조건의 결과에도 즉시 반영한다.
        if changed_video_id is not None and self.snapshot is not None:
            self.changed_here()
            self.index = self.core.library_view_index(self.snapshot)
            self.apply_filters()
            for card in self.cards:
                subtitled = card['id'] in self.index.original
                if card['hasSubtitles'] != subtitled:
                    card['hasSubtitles'] = subtitled
                    self.unsent.add(card['id'])
            self.publish_library(preserve_selection=preserve_selection)
        if self.selected_id is not None and (changed_video_id is None or changed_video_id == self.selected_id):
            self.bridge.libraryDetailsChanged.emit(self.selected_id)
        self.flush_thumbnails()

    def changed_here(self):
        """이 탭이 가진 목록을 그 자리에서 고쳐 반영하는 변경. 다른 탭만 다시 보일 때 갱신한다."""
        built = self.built_change == self.host.change
        self.host.content_changed(self)
        if built:
            self.built_change = self.host.change

    def refresh_key_bindings(self):
        # 키 배치를 저장하면 영상 목록을 다시 보내지 않고 키 표시만 바꾼다.
        self.bridge.libraryKeyBindingsChanged.emit(encode(key_bindings_data(self.core.key_bindings())))

    def refresh_thumbnails(self, video_ids):
        # 다른 탭의 카드 썸네일도 바뀐다. 이 탭은 아래 썸네일 신호로 따로 받는다.
        self.changed_here()
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
        self.publish_library()

    def selected_video_id(self):
        return self.selected_id

    def visible_video_ids(self):
        return tuple(self.visible_ids)
