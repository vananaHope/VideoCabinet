"""통계 준비 중 페이지. 실제 데이터와 화면은 후속 이슈에서 구현한다."""

from .web_page import WebPageController


class WebStatisticsPage(WebPageController):
    tab = 'statistics'

    def __init__(self, host):
        super().__init__(host)
        host.register_page(self)
