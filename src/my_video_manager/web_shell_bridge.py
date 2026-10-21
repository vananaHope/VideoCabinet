"""셸 공통 탐색·상태·포커스·새 버전 알림·키 안내 계약. 페이지 데이터에는 접근하지 않는다."""

import sqlite3
from dataclasses import asdict

from PySide6.QtCore import QObject, QTimer

from .key_guide import app_key_guide
from .web_shell_contract import SHELL
from .web_tabs import TABS
from .web_json import encode
from .web_update_data import shell_update_data


class ShellBridge(QObject):
    shellChanged = SHELL.signal('shellChanged')
    shellStatusChanged = SHELL.signal('shellStatusChanged')
    shellFocusRequested = SHELL.signal('shellFocusRequested')
    shellUpdateChanged = SHELL.signal('shellUpdateChanged')
    shellUpdateInstallChanged = SHELL.signal('shellUpdateInstallChanged')
    shellKeyGuideRequested = SHELL.signal('shellKeyGuideRequested')

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

    @SHELL.slot('updateSnapshot')
    def updateSnapshot(self):
        try:
            return encode(shell_update_data(self.host.window.updates))
        except (OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SHELL.slot('updateChoice')
    def updateChoice(self, name, version):
        try:
            self.host.window.updates.choose(name, version)
            return encode(shell_update_data(self.host.window.updates))
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SHELL.slot('updateAction')
    def updateAction(self, name):
        try:
            self.host.window.updates.install.act(name)
            return encode(shell_update_data(self.host.window.updates))
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SHELL.slot('keyGuide')
    def keyGuide(self):
        # 열 때마다 읽으므로 설정에서 바꾼 키 배치가 바로 보인다.
        return encode({'app': [asdict(entry) for entry in app_key_guide(self.host.core.key_bindings(), TABS)]})

    @SHELL.slot('navigate')
    def navigate(self, tab):
        if tab not in self.host.routes:
            return encode({'error': '없는 페이지입니다.'})
        QTimer.singleShot(0, lambda: self.host.navigate(tab))
        return encode({'ok': True})
