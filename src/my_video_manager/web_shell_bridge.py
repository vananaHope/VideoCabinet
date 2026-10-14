"""셸 공통 탐색·상태·포커스 계약. 페이지 데이터에는 접근하지 않는다."""

from PySide6.QtCore import QObject, QTimer

from .web_contract import SHELL
from .web_bridge import encode


class ShellBridge(QObject):
    shellChanged = SHELL.signal('shellChanged')
    shellStatusChanged = SHELL.signal('shellStatusChanged')
    shellFocusRequested = SHELL.signal('shellFocusRequested')

    def __init__(self, host):
        super().__init__(host)
        self.host = host

    @SHELL.slot('ready')
    def ready(self):
        self.host.frontend_ready()
        return encode({'ok': True})

    @SHELL.slot('shellSnapshot')
    def shellSnapshot(self):
        return encode({'tab': self.host.active_tab, 'status': self.host.window.statusBar().currentMessage()})

    @SHELL.slot('navigate')
    def navigate(self, tab):
        if tab not in self.host.routes:
            return encode({'error': '없는 페이지입니다.'})
        QTimer.singleShot(0, lambda: self.host.navigate(tab))
        return encode({'ok': True})
