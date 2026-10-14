"""앱의 웹 페이지 조립 지점. 호스트는 구체적인 페이지 모듈을 알지 못한다."""

from .web_library_page import WebLibraryPage
from .web_statistics_page import WebStatisticsPage
from .web_shell import WebShellHost


WEB_PAGES = (
    WebLibraryPage,
    WebStatisticsPage,
)
# Qt 번호는 웹 탭 순서에서 계산하지 않는다. 전환할 때 해당 줄을 제거하고 위에 등록한다.
NATIVE_PAGES = {
    'reel': 1,
    'search': 2,
    'queue': 3,
    'folders': 4,
    'settings': 5,
}


def create_web_shell(window):
    host = WebShellHost(window, initial_tab='library')
    for factory in WEB_PAGES:
        factory(host)
    for tab, index in NATIVE_PAGES.items():
        host.register_native(tab, index)
    host.start()
    return host
