"""페이지 구현과 독립적인 단일 웹 셸 호스트."""

import os
import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QPoint, QUrl, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

from .web_library_data import thumbnail_video_id
from .web_json import encode
from .web_shell_bridge import ShellBridge
from .web_contract import CONTRACTS, TABS
from .web_tokens import web_tokens
from .web_update_data import shell_update_data, update_install_data
from .web_thumbnail import ThumbnailHandler, register_thumbnail_scheme


class ShellWebEnginePage(QWebEnginePage):
    def __init__(self, profile, parent, entry):
        super().__init__(profile, parent)
        self.entry = entry

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # WebChannel을 등록한 페이지가 외부 문서로 이동하지 않게 한다.
        target = QUrl(url)
        target.setFragment(None)
        return is_main_frame and target == self.entry


class ShellRequests(QWebEngineUrlRequestInterceptor):
    """패키지 자산·썸네일·명시한 개발 서버 외 요청은 차단한다."""

    def __init__(self, root, entry, parent):
        super().__init__(parent)
        self.root, self.entry = root.resolve(), entry

    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.toString() == 'qrc:///qtwebchannel/qwebchannel.js'
        if url.scheme() == 'mvm-thumb':
            allowed = thumbnail_video_id(url.toString()) is not None
        elif url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to(self.root)
        elif url.scheme() in ('http', 'https', 'ws', 'wss') and self.entry.scheme() in ('http', 'https'):
            allowed = (url.scheme() in (self.entry.scheme(), 'ws' if self.entry.scheme() == 'http' else 'wss')
                       and url.host() == self.entry.host() and url.port() == self.entry.port())
        info.block(not allowed)


class WebShellHost(QWidget):
    frontend_loaded = Signal()

    def __init__(self, window, *, initial_tab):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.controllers = {}
        self.routes = {}
        self.active_tab = initial_tab
        self._playback_return_tab = initial_tab
        self._active_controller = None
        self._frontend_ready = False
        self._loaded_notified = False
        self._ready_pages = set()
        self._pending_focus = None
        self.bridge = ShellBridge(self)
        register_thumbnail_scheme()
        self.view = QWebEngineView(self)
        self.view.setAccessibleName('웹 셸')
        self.setFocusProxy(self.view)
        self.profile = QWebEngineProfile(self)  # view/page보다 나중에 파괴한다. off-the-record 프로필.
        self.thumbnails = ThumbnailHandler(self.core, self.profile)
        self.profile.installUrlSchemeHandler(b'mvm-thumb', self.thumbnails)
        dev_url = os.environ.get('MVM_WEB_DEV_URL')
        entry = QUrl(dev_url) if dev_url else QUrl.fromLocalFile(str(Path(__file__).parent / 'web/index.html'))
        if dev_url and not entry.path():
            entry.setPath('/')
        self.requests = ShellRequests(Path(__file__).parent / 'web', entry, self.profile)
        self.profile.setUrlRequestInterceptor(self.requests)
        self.engine_page = ShellWebEnginePage(self.profile, self.view, entry)
        self.engine_page.setBackgroundColor(QColor(web_tokens()['colors']['background']))
        self.view.setPage(self.engine_page)
        self.channel = QWebChannel(self.engine_page)
        self.channel.registerObject('shell', self.bridge)
        from .web_dialogs_host import WebDialogs
        self.dialogs = WebDialogs(self)
        self.channel.registerObject('dialogs', self.dialogs.bridge)
        self.engine_page.setWebChannel(self.channel)
        # file 페이지에서 비-file 썸네일 스킴 접근에 필요하다. 외부 네트워크는 interceptor가 차단한다.
        self.engine_page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.engine_page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.load_error = QLabel('웹 라이브러리를 불러오지 못했습니다. scripts/setup.ps1로 빌드한 뒤 다시 실행하세요.')
        self.load_error.setWordWrap(True)
        self.load_error.hide()
        layout.addWidget(self.load_error)
        layout.addWidget(self.view)
        self.view.loadFinished.connect(lambda ok: self.load_error.setVisible(not ok))
        self.view.loadStarted.connect(self.frontend_loading)
        self.entry = entry
        window.settings_menu.aboutToHide.connect(self.settings_closed)
        window.statusBar().messageChanged.connect(self.bridge.shellStatusChanged.emit)
        # 자동 확인·지금 확인의 결과와 알림 선택이 바뀌면 어느 탭에서든 새 버전 알림을 갱신한다.
        window.updates.changed.connect(self.update_changed)
        # 내려받기 진행률은 설정을 읽지 않는 작은 값만 따로 보낸다(약 100ms마다).
        window.updates.install.progressed.connect(self.update_progressed)

    def update_changed(self):
        try:
            self.bridge.shellUpdateChanged.emit(encode(shell_update_data(self.window.updates)))
        except (OSError, sqlite3.Error):
            pass  # 설정을 읽지 못하면 이전 알림을 둔다. 다음 변경이나 새로 연 화면에서 다시 읽는다.

    def update_progressed(self):
        self.bridge.shellUpdateInstallChanged.emit(encode(update_install_data(self.window.updates.install)))

    def register_page(self, controller):
        self._register_route(controller.tab, controller)
        self.controllers[controller.tab] = controller
        if controller.bridge is not None:
            self.channel.registerObject(controller.tab, controller.bridge)

    def _register_route(self, tab, route):
        if tab in self.routes:
            raise ValueError(f'중복 웹 탭: {tab}')
        self.routes[tab] = route

    def start(self):
        if set(self.routes) != {name for name, _ in TABS}:
            raise ValueError('TABS와 페이지 등록부가 일치하지 않습니다.')
        if self.active_tab not in self.controllers:
            raise ValueError('첫 탭은 웹 페이지여야 합니다.')
        if set(self.channel.registeredObjects()) != {contract.name for contract in CONTRACTS}:
            raise ValueError('브리지 계약과 채널 등록부가 일치하지 않습니다.')
        self._pending_focus = self.controllers[self.active_tab].default_focus
        self.view.load(self.entry)

    def set_tab(self, tab):
        if tab not in self.routes:
            raise ValueError(f'없는 웹 탭: {tab}')
        self.active_tab = tab
        self.sync_activation()
        self.bridge.shellChanged.emit(encode({'tab': tab}))

    def sync_activation(self):
        controller = self.controllers.get(self.active_tab) if self.isVisible() else None
        if controller is self._active_controller:
            return
        previous, self._active_controller = self._active_controller, controller
        if previous is not None:
            previous.deactivated()
        if controller is not None:
            controller.activated()

    def remember_playback_tab(self):
        self._playback_return_tab = self.active_tab

    def return_from_playback(self, *, focus_gems=False):
        self.window.end_playback()
        self.set_tab(self._playback_return_tab)
        self.window.pages.setCurrentWidget(self)
        self.controllers[self.active_tab].return_from_playback(focus_gems=focus_gems)

    def navigate(self, tab):
        route = self.routes[tab]
        self.window.end_playback()
        self.set_tab(tab)
        self.window.pages.setCurrentWidget(self)
        route.refresh()
        self.focus_content()

    def handle_key(self, event):
        return False  # 예약 키는 창, 나머지는 Chromium/React가 처리한다.

    def focus_content(self):
        controller = self.controllers.get(self.active_tab)
        self.request_focus(controller.default_focus if controller else 'shell')

    def request_focus(self, target):
        self._pending_focus = target
        self.apply_pending_focus()

    def apply_pending_focus(self):
        controller = self.controllers.get(self.active_tab)
        ready = controller is None or controller.bridge is None or self.active_tab in self._ready_pages
        if self._frontend_ready and ready and self._pending_focus and self.isVisible():
            target, self._pending_focus = self._pending_focus, None
            self.view.setFocus()
            if controller and controller.focus_requested is not None:
                controller.focus_requested.emit(target)
            else:
                self.bridge.shellFocusRequested.emit('shell')

    def frontend_loading(self):
        self._frontend_ready = False
        self._loaded_notified = False
        self._ready_pages.clear()
        controller = self.controllers.get(self.active_tab)
        self._pending_focus = self._pending_focus or (controller.default_focus if controller else 'shell')

    def frontend_ready(self):
        self._frontend_ready = True
        self.apply_pending_focus()
        self.notify_loaded()

    def page_ready(self, tab):
        self._ready_pages.add(tab)
        self.apply_pending_focus()
        self.notify_loaded()

    def notify_loaded(self):
        controller = self.controllers.get(self.active_tab)
        if (not self._loaded_notified and self._frontend_ready
                and (controller is None or controller.bridge is None or self.active_tab in self._ready_pages)):
            self._loaded_notified = True
            self.frontend_loaded.emit()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_activation()
        controller = self.controllers.get(self.active_tab)
        if controller:
            controller.refresh_details()
        self.apply_pending_focus()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.sync_activation()

    def settings_closed(self):
        if self.window.pages.currentWidget() is self:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.focus_content)

    def popup_settings_menu(self):
        """웹 설정 탭의 실제 CSS 좌표를 Qt 전역 좌표로 바꾼다. 숨은 웹은 창 우측 위를 쓴다."""
        window = self.window
        menu = window.settings_menu

        def popup(rect=None):
            from shiboken6 import isValid
            if not isValid(self) or not isValid(window) or not window.isActiveWindow():
                return
            rect = json.loads(rect) if rect else None
            if self.isVisible() and rect:
                zoom = self.view.zoomFactor()
                point = self.view.mapToGlobal(QPoint(round(rect[0] * zoom) - menu.sizeHint().width(),
                                                    round(rect[1] * zoom)))
            else:
                point = window.mapToGlobal(QPoint(window.width() - menu.sizeHint().width() - 16, 12))
            menu.popup(point)

        if self.isVisible() and self._frontend_ready:
            self.engine_page.runJavaScript("""JSON.stringify((() => {
              const tab = document.querySelector('nav [data-tab="settings"]');
              if (!tab) return null;
              const rect = tab.getBoundingClientRect(); return [rect.right, rect.bottom];
            })())""", popup)
        else:
            popup()
