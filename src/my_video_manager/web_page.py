"""셸에 등록하는 페이지 컨트롤러의 작은 공통 인터페이스."""

from PySide6.QtWidgets import QWidget


class WebPageController(QWidget):
    # QWidget은 기존 Qt 대화상자의 부모 수명주기를 위한 것이다. 화면은 호스트 하나에만 있다.
    default_focus = 'shell'
    bridge = None
    focus_requested = None

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.window, self.core = host.window, host.core
        self.hide()

    def isVisible(self):
        return self.host.isVisible() and self.host.active_tab == self.tab

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
