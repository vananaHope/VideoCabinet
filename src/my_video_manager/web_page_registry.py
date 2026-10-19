"""앱의 웹 페이지 조립 지점. 호스트는 구체적인 페이지 모듈을 알지 못한다."""

from .web_library_page import WebLibraryPage
from .web_recommend_page import WebRecommendPage
from .web_queue_page import WebQueuePage
from .web_statistics_page import WebStatisticsPage
from .web_reel_page import WebReelPage
from .web_search_page import WebSearchPage
from .web_shell import WebShellHost
from .web_folders_page import WebFoldersPage
from .web_settings_page import WebSettingsPage


WEB_PAGES = (
    WebLibraryPage,
    WebRecommendPage,
    WebQueuePage,
    WebStatisticsPage,
    WebReelPage,
    WebSearchPage,
    WebFoldersPage,
    WebSettingsPage,
)


def create_web_shell(window):
    host = WebShellHost(window, initial_tab='library')
    for factory in WEB_PAGES:
        factory(host)
    host.start()
    return host
