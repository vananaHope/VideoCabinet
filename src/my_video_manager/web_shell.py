"""페이지 구현과 독립적인 단일 웹 셸 호스트."""

import os
import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QLocale, QPoint, QUrl, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QStackedLayout
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtQuickWidgets import QQuickWidget

from .web_library_data import thumbnail_video_id
from .web_json import encode
from .web_shell_bridge import ShellBridge
from .web_contract import CONTRACTS, TABS
from .web_tokens import web_tokens
from .web_update_data import shell_update_data, update_install_data
from .web_thumbnail import ThumbnailHandler, register_thumbnail_scheme


def use_korean_locale():
    """화면 언어를 한국어로 고정한다(#232).

    웹 엔진은 처음 뜰 때의 QLocale로 화면 언어를 정하고, 날짜 입력 칸은 그 언어의 연·월·일 순서를 따른다.
    Windows 표시 언어가 영어면 `mm/dd/yyyy`가 되므로 웹 엔진보다 먼저 정한다.
    """
    QLocale.setDefault(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))


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
        self._return_generation = 0
        self._return_token = None
        self._return_focus_ready = False
        self.bridge = ShellBridge(self)
        register_thumbnail_scheme()
        use_korean_locale()
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
        window.pages.currentChanged.connect(lambda _: self.sync_activation())
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
        self.view.loadFinished.connect(self.load_finished)
        self.engine_page.renderProcessTerminated.connect(lambda *_: self.load_finished(False))
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
        tab_names = {name for name, _ in TABS}
        if len(tab_names) != len(TABS):
            raise ValueError('TABS에 중복 웹 탭이 있습니다.')
        if set(self.routes) != tab_names:
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

    def return_from_playback(self):
        self.show_page(self._playback_return_tab, returning=True)

    @property
    def return_pending(self):
        return self._return_token is not None

    def cancel_return(self):
        self._return_generation += 1
        self._return_token = None
        self.window.playback_page.setEnabled(True)
        self.window.pages.layout().setStackingMode(QStackedLayout.StackingMode.StackOne)
        if self.window.pages.currentWidget() is self:
            self.window.playback_page.hide()
        self.window.player_shutdown.release()

    def show_page(self, tab, *, returning=False):
        """웹을 보이는 크기로 먼저 그린다. 준비 응답까지 이전 재생 표면이 앞을 덮는다."""
        cover = self.window.isVisible() and (self.return_pending or
                    self.window.pages.currentWidget() is self.window.playback_page)
        self._return_generation += 1
        self._return_token = self._return_generation if cover else None
        self._return_focus_ready = False
        try:
            self.window.end_playback()
            self.set_tab(tab)
            self.dialogs.restore_page()
            if cover:
                # 현재 페이지를 바꾸면서 native mpv 자식을 숨겼다가 보이면
                # 일시정지된 마지막 프레임도 지워진다. 준비 동안 두 페이지를
                # 모두 표시하고 기존 재생 페이지를 위에 둔다.
                self.window.pages.layout().setStackingMode(QStackedLayout.StackingMode.StackAll)
            self.window.pages.setCurrentWidget(self)
            if cover:
                self.window.playback_page.show()
                self.window.playback_page.raise_()
                self.window.playback_page.setEnabled(False)
            route = self.routes[tab]
            if returning:
                route.return_from_playback()
            else:
                route.refresh()
                self.focus_content()
            self._return_focus_ready = True
            self.apply_pending_focus()
            self.prepare_return()
        except Exception:
            self.cancel_return()
            raise

    def prepare_return(self):
        controller = self.controllers.get(self.active_tab)
        ready = controller is None or controller.bridge is None or self.active_tab in self._ready_pages
        if (self.return_pending and self._return_focus_ready and self._frontend_ready
                and ready):
            self.bridge.shellPrepareReturn.emit(self._return_token)

    def fail_return(self, token):
        if token == self._return_token:
            self.cancel_return()

    def finish_return(self, token):
        # 새 재생·탭 이동·창 닫기 뒤 도착한 웹 응답은 현재 화면을 덮지 않는다.
        if token != self._return_token or self.window.pages.currentWidget() is not self:
            return
        try:
            renderers = self.view.findChildren(QQuickWidget)
            if renderers:
                # 가려진 위젯은 update가 생략될 수 있어 프레임을 명시적으로
                # 렌더한다. Qt 내부 위임 위젯이 달라져도 정상 웹을 오류로 보지 않는다.
                renderers[0].grabFramebuffer()
            # FBO 렌더와 native 부모 창의 합성은 다른 경계다. 준비된 웹을
            # 올리고 repaint한 뒤 합성을 기다려야 이전 재생 표면을 걷을 수 있다.
            self.raise_()
            self.view.raise_()
            self.view.repaint()
            self.window.composition_waiter()
        finally:
            # 렌더·합성 준비 실패에도 덮개 아래 오류를 가둬 두지 않는다.
            self.fail_return(token)

    def close_return_tab(self):
        """재생 중 창을 닫아 트레이로 숨길 때 둘 탭. 출발한 페이지가 원하면 그 탭, 아니면 라이브러리."""
        tab = self._playback_return_tab
        return tab if self.controllers[tab].keeps_tab_after_close else 'library'

    def navigate(self, tab):
        self.show_page(tab)

    def handle_key(self, event):
        return False  # 예약 키는 창, 나머지는 Chromium/React가 처리한다.

    def open_key_guide(self):
        """F1 예약 키. 키 안내 창은 웹이 띄우고 내용은 keyGuide 슬롯에서 읽는다."""
        self.bridge.shellKeyGuideRequested.emit(self.active_tab)

    def focus_content(self):
        controller = self.controllers.get(self.active_tab)
        self.request_focus(controller.default_focus if controller else 'shell')

    def request_focus(self, target):
        self._pending_focus = target
        self.apply_pending_focus()

    def apply_pending_focus(self):
        if self.return_pending and not self._return_focus_ready:
            return
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
        if self.return_pending:
            self._return_generation += 1
            self._return_token = self._return_generation
        self._frontend_ready = False
        self._loaded_notified = False
        self._ready_pages.clear()
        controller = self.controllers.get(self.active_tab)
        self._pending_focus = self._pending_focus or (controller.default_focus if controller else 'shell')

    def load_finished(self, ok):
        self.load_error.setVisible(not ok)
        if not ok and self.return_pending:
            self.cancel_return()

    def frontend_ready(self):
        self._frontend_ready = True
        self.apply_pending_focus()
        self.notify_loaded()

    def page_ready(self, tab):
        self._ready_pages.add(tab)
        self.apply_pending_focus()
        self.notify_loaded()

    def notify_loaded(self):
        self.prepare_return()
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

    def settings_menu_point(self, rect=None):
        """설정 메뉴를 열 전역 좌표. rect는 웹 설정 탭의 CSS 좌표이고 없으면 창 우측 위를 쓴다."""
        window, menu = self.window, self.window.settings_menu
        if self.isVisible() and rect:
            zoom = self.view.zoomFactor()
            return self.view.mapToGlobal(QPoint(round(rect[0] * zoom) - menu.sizeHint().width(), round(rect[1] * zoom)))
        return window.mapToGlobal(QPoint(window.width() - menu.sizeHint().width() - 16, 12))

    def close_popups(self):
        """긴급 탈출: 웹 선택 목록·우클릭 메뉴·자동 완성 목록을 숨기기 전에 닫는다.

        창이 초점을 잃을 때와 같은 blur를 보낸다. 목록은 고르던 항목을 확정하지 않고 닫히며
        웹 대화상자와 입력 내용은 그대로다. 실창의 blur가 늦게 와도 결과가 같다.
        """
        self.engine_page.runJavaScript(
            "document.activeElement?.dispatchEvent(new FocusEvent('focusout', {bubbles: true}));"
            " window.dispatchEvent(new Event('blur'))")

    def popup_settings_menu(self):
        """웹 설정 탭의 실제 CSS 좌표를 Qt 전역 좌표로 바꾼다. 숨은 웹은 창 우측 위를 쓴다."""
        window = self.window
        menu = window.settings_menu

        def popup(rect=None):
            from shiboken6 import isValid
            if not isValid(self) or not isValid(window) or not window.isActiveWindow():
                return
            menu.popup(self.settings_menu_point(json.loads(rect) if rect else None))

        if self.isVisible() and self._frontend_ready:
            self.engine_page.runJavaScript("""JSON.stringify((() => {
              const tab = document.querySelector('nav [data-tab="settings"]');
              if (!tab) return null;
              const rect = tab.getBoundingClientRect(); return [rect.right, rect.bottom];
            })())""", popup)
        else:
            popup()
