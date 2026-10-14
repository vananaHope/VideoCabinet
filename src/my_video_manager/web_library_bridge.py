"""단일 QWebChannel 객체. 웹에는 JSON 값과 제한된 작업 이름만 공개한다."""

import json

from PySide6.QtCore import QObject, Signal, Slot, QTimer

from .web_library_data import details_data


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class LibraryBridge(QObject):
    changed = Signal(str)
    detailsChanged = Signal(int)
    focusRequested = Signal(str)
    error = Signal(str)

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @Slot(result=str)
    def snapshot(self):
        return encode(self.page.payload())

    @Slot(result=str)
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @Slot(str, int, result=str)
    def filter(self, query, tag_id):
        self.page.query, self.page.tag_id = query, tag_id if tag_id > 0 else None
        self.page.apply_filters()
        return encode({'visibleIds': self.page.visible_ids, 'selectedId': self.page.selected_id})

    @Slot(int, result=str)
    def select(self, video_id):
        if video_id not in self.page.visible_ids:
            return encode({'error': '현재 목록에 없는 영상입니다.'})
        self.page.selected_id = video_id
        return encode({'selectedId': video_id})

    @Slot(int, result=str)
    def details(self, video_id):
        try:
            if video_id not in self.page.video_ids:
                raise ValueError('현재 라이브러리에 없는 영상입니다.')
            return encode(details_data(self.page.core.library_details(video_id)))
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})

    @Slot(str, int, result=str)
    def action(self, action, video_id):
        allowed = {'play', 'playGem', 'dismiss', 'tags', 'subtitles', 'review', 'series', 'rename', 'reconnect', 'exclude'}
        if action not in allowed or video_id not in self.page.video_ids:
            return encode({'error': '지원하지 않는 작업 또는 영상입니다.'})
        if action in {'playGem', 'dismiss'} and video_id not in self.page.gem_ids:
            return encode({'error': '현재 추천에 없는 영상입니다.'})
        if self.busy or (self.page.worker is not None and action in {'rename', 'reconnect', 'exclude'}):
            return encode({'error': '진행 중인 작업이 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        # WebChannel 응답을 먼저 돌려주고 Qt 대화상자의 중첩 이벤트 루프를 연다.
        QTimer.singleShot(0, lambda: self.perform(action, video_id))
        return encode({'ok': True})

    def perform(self, action, video_id):
        page = self.page
        try:
            if action not in {'playGem', 'dismiss'}:
                page.selected_id = video_id
            if action == 'play':
                page.window.play(video_id)
            elif action == 'playGem':
                page.window.playback_list = tuple(page.gem_ids)
                page.window.play_video(video_id, from_gems=True)
            elif action == 'dismiss':
                page.core.dismiss_video(video_id)
                page.refresh(focus_gems=True)
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
            self.error.emit(str(error))
        finally:
            self.busy = False
            if page.isVisible() and action != 'dismiss':
                page.focus_content()
