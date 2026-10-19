"""셸에 등록하는 페이지 컨트롤러의 작은 공통 인터페이스."""

from PySide6.QtWidgets import QWidget


class WebPageController(QWidget):
    # QWidget은 부모 소유권과 이벤트 수명주기를 위한 것이다. 화면은 호스트 하나에만 있다.
    default_focus = 'shell'
    # 재생 중 창을 닫았다가 트레이로 열 때 라이브러리 대신 이 탭으로 돌아온다.
    keeps_tab_after_close = False
    bridge = None
    focus_requested = None

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.window, self.core = host.window, host.core
        self.hide()

    def is_active(self):
        return self.host.isVisible() and self.host.active_tab == self.tab

    def activated(self):
        pass

    def deactivated(self):
        pass

    def return_from_playback(self):
        self.refresh()
        self.focus_content()

    def focus_content(self):
        self.request_focus(self.default_focus)

    def request_focus(self, target):
        self.host.request_focus(target)

    def frontend_ready(self):
        self.host.page_ready(self.tab)

    def refresh(self):
        pass

    def refresh_details(self):
        pass
