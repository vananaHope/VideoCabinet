"""라이브러리 전용 QWebChannel 객체. 웹에는 JSON 값과 제한된 작업 이름만 공개한다."""

from PySide6.QtCore import QObject, QTimer
import json

from .web_library_data import details_data, highlights_data, tag_candidates_data
from .web_library_contract import MENU_ACTIONS, SCAN_LOCKED_ACTIONS, LIBRARY
from .web_json import encode
from .random_play import NO_CANDIDATE_MESSAGE


class LibraryBridge(QObject):
    thumbnailsChanged = LIBRARY.signal('thumbnailsChanged')
    libraryChanged = LIBRARY.signal('libraryChanged')
    libraryDetailsChanged = LIBRARY.signal('libraryDetailsChanged')
    libraryFocusRequested = LIBRARY.signal('libraryFocusRequested')
    libraryError = LIBRARY.signal('libraryError')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @LIBRARY.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @LIBRARY.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @LIBRARY.slot('filter')
    def filter(self, query, tag_id):
        self.page.query, self.page.tag_id = query, tag_id if tag_id > 0 else None
        self.page.apply_filters()
        return encode({'visibleIds': self.page.visible_ids, 'selectedId': self.page.selected_id})

    @LIBRARY.slot('view')
    def view(self, options):
        try:
            self.page.set_view(json.loads(options))
            return encode(self.page.view_payload())
        except (ValueError, TypeError, OSError) as error:
            return encode({'error': str(error)})

    @LIBRARY.slot('select')
    def select(self, video_id):
        if video_id not in self.page.visible_ids:
            return encode({'error': '현재 목록에 없는 영상입니다.'})
        self.page.selected_id = video_id
        return encode({'selectedId': video_id})

    @LIBRARY.slot('details')
    def details(self, video_id):
        try:
            if video_id not in self.page.video_ids:
                raise ValueError('현재 라이브러리에 없는 영상입니다.')
            return encode(details_data(self.page.core.library_details(video_id),
                                       self.page.core.external_subtitle_summaries(video_id)))
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})

    @LIBRARY.slot('action')
    def action(self, action, video_id):
        if action not in MENU_ACTIONS or video_id not in self.page.video_ids:
            return encode({'error': '지원하지 않는 작업 또는 영상입니다.'})
        if self.busy or (self.page.worker is not None and action in SCAN_LOCKED_ACTIONS):
            return encode({'error': '진행 중인 작업이 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        # WebChannel 응답을 먼저 돌려주고 Qt 대화상자의 중첩 이벤트 루프를 연다.
        QTimer.singleShot(0, lambda: self.perform(action, video_id))
        return encode({'ok': True})

    @LIBRARY.slot('randomPlay')
    def randomPlay(self):
        # 범위는 페이지의 현재 결과다. 조건이 없으면 현재 결과가 곧 영상 전체다.
        return self.random_play(lambda: {'video_ids': self.page.visible_video_ids()})

    @LIBRARY.slot('randomTagCandidates')
    def randomTagCandidates(self):
        # 태그 고르기 창이 열릴 때 한 번 받아 후보 수(합집합 크기)를 화면에서 센다.
        # 페이지가 가진 스냅숏으로 계산해 DB를 다시 읽지 않는다.
        if self.page.snapshot is None:
            return encode({'tags': []})
        try:
            return encode({'tags': tag_candidates_data(self.page.core.random_tag_candidates(self.page.snapshot))})
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})

    @LIBRARY.slot('randomPlayTags')
    def randomPlayTags(self, tag_ids):
        # 고른 태그 중 하나라도 붙은 영상(OR)에서 고른다. 후보는 코어가 최신 DB로 다시 정한다.
        def scope():
            ids = json.loads(tag_ids)
            if not isinstance(ids, list) or not all(type(tag_id) is int for tag_id in ids):
                raise ValueError('태그 목록이 올바르지 않습니다.')
            return {'tag_ids': ids}
        return self.random_play(scope)

    def random_play(self, scope):
        # 재생은 상태를 바꾸지 않는 작업이라 검사 중에도 막지 않는다.
        if self.busy:
            return encode({'error': '진행 중인 작업이 끝난 뒤 다시 시도하세요.'})
        try:
            video_id = self.page.core.pick_random_video(**scope())
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})
        if video_id is None:
            return encode({'videoId': None, 'message': NO_CANDIDATE_MESSAGE})
        self.busy = True
        self.page.selected_id = video_id
        QTimer.singleShot(0, lambda: self.perform('play', video_id))
        return encode({'videoId': video_id})

    @LIBRARY.slot('highlights')
    def highlights(self, video_id):
        try:
            if video_id not in self.page.video_ids:
                raise ValueError('현재 라이브러리에 없는 영상입니다.')
            return encode(highlights_data(self.page.core, video_id))
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})

    @LIBRARY.slot('playHighlight')
    def playHighlight(self, video_id, highlight_id):
        return self.queue_highlight(video_id, highlight_id, edit=False)

    @LIBRARY.slot('editHighlight')
    def editHighlight(self, video_id, highlight_id):
        return self.queue_highlight(video_id, highlight_id, edit=True)

    def require_highlight(self, video_id, highlight_id):
        if video_id not in self.page.video_ids:
            raise ValueError('현재 라이브러리에 없는 영상입니다.')
        highlight = next((h for h in self.page.core.highlights(video_id) if h.id == highlight_id), None)
        if highlight is None:
            raise ValueError('현재 영상에 없는 하이라이트입니다.')
        return highlight

    def queue_highlight(self, video_id, highlight_id, *, edit):
        try:
            self.require_highlight(video_id, highlight_id)
            if self.busy:
                raise ValueError('진행 중인 작업이 끝난 뒤 다시 시도하세요.')
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})
        self.busy = True
        QTimer.singleShot(0, lambda: self.perform_highlight(video_id, highlight_id, edit=edit))
        return encode({'ok': True})

    def perform_highlight(self, video_id, highlight_id, *, edit):
        page = self.page
        try:
            highlight = self.require_highlight(video_id, highlight_id)
            page.selected_id = video_id
            if edit:
                from .web_dialogs_entries import HighlightEditor
                HighlightEditor(page.core, highlight, page.core.video(video_id).duration, page).exec()
                page.refresh_details(video_id)
            else:
                page.window.playback_list = page.visible_video_ids()
                page.window.play_video(video_id, start=highlight.start)
        except (ValueError, OSError, RuntimeError) as error:
            self.libraryError.emit(str(error))
        finally:
            self.busy = False
            if not edit and page.is_active():
                page.focus_content()

    def perform(self, action, video_id):
        page = self.page
        try:
            page.selected_id = video_id
            if action == 'play':
                page.window.play(video_id)
            else:
                callbacks = {
                    'tags': page.edit_video_tags, 'subtitles': page.request_subtitles,
                    'review': page.show_review, 'series': page.show_series,
                    'rename': page.library_controls.rename,
                    'reconnect': page.library_controls.reconnect,
                    'exclude': page.library_controls.exclude,
                }
                callbacks[action]()
                page.refresh_details(video_id)
        except (ValueError, OSError, RuntimeError) as error:
            self.libraryError.emit(str(error))
        finally:
            self.busy = False
            if page.is_active():
                page.focus_content()
