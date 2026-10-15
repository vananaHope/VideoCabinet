"""통계 페이지 전용 공개 채널."""
from PySide6.QtCore import QObject, QTimer

from .web_contract import STATISTICS
from .web_json import encode


class StatisticsBridge(QObject):
    statisticsChanged = STATISTICS.signal('statisticsChanged')
    statisticsFocusRequested = STATISTICS.signal('statisticsFocusRequested')

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    @STATISTICS.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @STATISTICS.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @STATISTICS.slot('setPeriod')
    def setPeriod(self, days):
        if days not in (7, 30, 90, 365):
            return encode({'error': '통계 기간은 7·30·90·365일 중 하나여야 합니다.'})
        self.page.days = days
        self.page.refresh()
        return encode({'ok': True})

    @STATISTICS.slot('playVideo')
    def playVideo(self, video_id):
        result = self.page.result
        if result is None or not any(v['video_id'] == video_id for v in result['period']['top_videos']):
            return encode({'error': '현재 통계 목록에 없는 영상입니다.'})
        try:
            self.page.core.playback_location(video_id)
        except (ValueError, OSError) as error:
            return encode({'error': str(error)})
        # 기존 Python 재생 진입점이 복귀 탭과 mpv 수명주기를 함께 보존한다.
        QTimer.singleShot(0, lambda: self.page.window.play_video(video_id))
        return encode({'ok': True})
