"""앱의 웹 페이지 조립 지점. 호스트는 구체적인 페이지 모듈을 알지 못한다."""

from .web_library_page import WebLibraryPage
from .web_queue_page import WebQueuePage
from .web_statistics_page import WebStatisticsPage
from .web_reel_page import WebReelPage
from .web_search_page import WebSearchPage
from .web_shell import WebShellHost
from .web_folders_page import WebFoldersPage
from .web_settings_page import WebSettingsPage


WEB_PAGES = (
    WebLibraryPage,
    WebQueuePage,
    WebStatisticsPage,
    WebReelPage,
    WebSearchPage,
    WebFoldersPage,
    WebSettingsPage,
)
# 기존 Qt 페이지의 고정 번호표. 웹 페이지를 추가할 때는 이 표를 수정하지 않는다.
QT_PAGE_INDEX = {
    'reel': 1,
    'search': 2,
    'queue': 3,
    'folders': 4,
    'settings': 5,
}
NATIVE_PAGES = {
    tab: index for tab, index in QT_PAGE_INDEX.items()
    if tab not in {page.tab for page in WEB_PAGES}
}


def create_web_shell(window):
    host = WebShellHost(window, initial_tab='library')
    for factory in WEB_PAGES:
        factory(host)
    for tab, index in NATIVE_PAGES.items():
        host.register_native(tab, index)
    host.start()
    return host
