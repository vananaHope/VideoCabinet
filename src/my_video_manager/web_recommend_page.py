"""추천 줄 목록과 재생·관심 없음 작업. 재생 뒤에는 셸이 이 탭으로 돌려보낸다."""
from PySide6.QtCore import QObject, QTimer

from .web_json import encode
from .web_page import WebPageController
from .web_recommend_contract import RECOMMEND
from .web_recommend_data import rows_data


class RecommendBridge(QObject):
    changed = RECOMMEND.signal('changed')
    focusRequested = RECOMMEND.signal('focusRequested')
    error = RECOMMEND.signal('error')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @RECOMMEND.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @RECOMMEND.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @RECOMMEND.slot('play')
    def play(self, video_id):
        if self.page.row_ids(video_id) is None:
            return encode({'error': '현재 추천에 없는 영상입니다.'})
        if self.busy:
            return encode({'error': '진행 중인 작업이 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        # WebChannel 응답을 먼저 돌려준 뒤 재생 실패 경고의 중첩 이벤트 루프를 연다.
        QTimer.singleShot(0, lambda: self.perform_play(video_id))
        return encode({'ok': True})

    def perform_play(self, video_id):
        page = self.page
        try:
            ids = page.row_ids(video_id)
            if ids is None:
                raise ValueError('현재 추천에 없는 영상입니다.')
            # 재생 중 이전·다음 영상은 같은 추천 줄 안에서 고른다.
            page.window.set_playback_list(ids, "추천")
            page.window.play_video(video_id)
        except (ValueError, OSError, RuntimeError) as error:
            self.error.emit(str(error))
        finally:
            self.busy = False
            if page.is_active():
                page.focus_content()

    @RECOMMEND.slot('dismiss')
    def dismiss(self, video_id):
        if self.page.row_ids(video_id) is None:
            return encode({'error': '현재 추천에 없는 영상입니다.'})
        try:
            self.page.core.dismiss_video(video_id)
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})
        self.page.refresh()
        return encode({'ok': True})

    @RECOMMEND.slot('restore')
    def restore(self, video_id):
        try:
            if video_id not in {video.id for video in self.page.core.dismissed_videos()}:
                raise ValueError('관심 없음 목록에 없는 영상입니다.')
            self.page.core.restore_dismissed_video(video_id)
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})
        self.page.refresh()
        return encode({'ok': True})

    @RECOMMEND.slot('showDismissed')
    def showDismissed(self):
        QTimer.singleShot(0, self.page.show_dismissed)
        return encode({'ok': True})


class WebRecommendPage(WebPageController):
    tab = 'recommend'
    default_focus = 'recommendations'
    keeps_tab_after_close = True

    def __init__(self, host):
        super().__init__(host)
        self.loaded = False
        self.rows, self.error = [], ''
        self.bridge = RecommendBridge(self)
        self.focus_requested = self.bridge.focusRequested
        # 검사·파일 다시 연결처럼 목록이 바뀌면 보이는 동안 추천도 다시 계산한다.
        host.controllers['library'].refreshed.connect(self.refresh_if_active)
        host.register_page(self)

    def payload(self):
        return dict(loaded=self.loaded, rows=self.rows, error=self.error)

    def refresh(self):
        try:
            snapshot = self.core.library_snapshot()
            self.rows = rows_data(self.core.recommendations(snapshot=snapshot), snapshot,
                                  self.core.subtitled_video_ids())
            self.error = ''
        except Exception as error:
            # 추천 계산이 실패해도 다른 탭과 재생은 계속 쓴다. 안내는 이 탭에만 두고,
            # 보던 줄은 비우지 않고 그대로 둔다(하던 자리를 잃지 않는다).
            self.error = str(error)
        self.loaded = True
        self.bridge.changed.emit(encode(self.payload()))

    def refresh_if_active(self):
        if self.is_active():
            self.refresh()

    def row_ids(self, video_id):
        """영상이 든 추천 줄의 영상 ID 순서. 지금 추천에 없으면 None."""
        for row in self.rows:
            ids = tuple(item['video']['id'] for item in row['items'])
            if video_id in ids:
                return ids
        return None

    def show_dismissed(self):
        self.host.controllers['folders'].open_section('dismissed')
