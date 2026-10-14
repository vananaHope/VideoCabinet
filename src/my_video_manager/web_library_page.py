"""단일 웹 셸과 라이브러리 어댑터. 기존 Qt 페이지·대화상자 계약을 유지한다."""

import os
import json
from pathlib import Path

from PySide6.QtCore import QPoint, QUrl, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

from .hidden_gems_ui import show_dismissed_dialog
from .library_page import LibraryOperations
from .library_ui import LibraryControls
from .web_library_data import snapshot_data, filter_ids, thumbnail_video_id
from .web_library_bridge import LibraryBridge, encode
from .web_tokens import web_tokens
from .web_thumbnail import ThumbnailHandler, register_thumbnail_scheme


class LibraryWebEnginePage(QWebEnginePage):
    def __init__(self, profile, parent, entry):
        super().__init__(profile, parent)
        self.entry = entry

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # WebChannel을 등록한 페이지가 외부 문서로 이동하지 않게 한다.
        target = QUrl(url)
        target.setFragment(None)
        return is_main_frame and target == self.entry


class LibraryRequests(QWebEngineUrlRequestInterceptor):
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


class GemDialogs:
    def __init__(self, page):
        self.page = page

    def show_dismissed(self):
        show_dismissed_dialog(self.page, self.page.core, self.page.refresh)


class WebLibraryPage(LibraryOperations, QWidget):
    scan_state_changed = Signal(bool)
    scan_message = Signal(str)
    refreshed = Signal()
    frontend_loaded = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.worker = None
        self.snapshot = None
        self.cards = []
        self.video_ids = set()
        self.visible_ids = []
        self.gems, self.gem_ids = [], []
        self.gem_error = ''
        self.selected_id = None
        self.query, self.tag_id = '', None
        self.tags = []
        self._frontend_ready = False
        self._pending_focus = 'grid'
        self.library_controls = LibraryControls(window)
        self.hidden_gems = GemDialogs(self)
        self.active_tab = 'library'
        self.last_web_tab = 'library'
        self.bridge = LibraryBridge(self)
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
        self.requests = LibraryRequests(Path(__file__).parent / 'web', entry, self.profile)
        self.profile.setUrlRequestInterceptor(self.requests)
        self.engine_page = LibraryWebEnginePage(self.profile, self.view, entry)
        self.engine_page.setBackgroundColor(QColor(web_tokens()['colors']['background']))
        self.view.setPage(self.engine_page)
        self.channel = QWebChannel(self.engine_page)
        self.channel.registerObject('app', self.bridge)
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
        self.view.load(entry)
        window.settings_menu.aboutToHide.connect(self.settings_closed)
        window.subtitles.video_changed.connect(self.refresh_details)
        window.translations.video_changed.connect(self.refresh_details)

    def set_tab(self, tab):
        self.active_tab = tab
        if tab in ('library', 'statistics'):
            self.last_web_tab = tab
        self.bridge.shellChanged.emit(encode({'tab': tab}))

    def payload(self):
        return dict(videos=self.cards, tags=self.tags, gems=self.gems, gemError=self.gem_error,
                    visibleIds=self.visible_ids, selectedId=self.selected_id, scanning=self.worker is not None)

    def refresh(self, *, focus_gems=None):
        self.snapshot = self.core.library_snapshot()
        self.cards = snapshot_data(self.snapshot, self.core.subtitled_video_ids())
        self.video_ids = {v['id'] for v in self.cards}
        self.tags = [dict(id=t.id, name=t.name) for t in self.core.tags()]
        if self.tag_id not in {t['id'] for t in self.tags}:
            self.tag_id = None
        try:
            self.gems = [dict(videoId=g.video.id, reason=g.reason)
                         for g in self.core.hidden_gems(snapshot=self.snapshot)]
            self.gem_error = ''
        except Exception as error:
            self.gems, self.gem_error = [], str(error)
        self.gem_ids = [g['videoId'] for g in self.gems]
        self.apply_filters()
        self.bridge.libraryChanged.emit(encode(self.payload()))
        self.refreshed.emit()
        if focus_gems is not None and self.isVisible():
            self.request_focus('gems' if focus_gems else 'grid')

    def apply_filters(self):
        self.visible_ids = filter_ids(self.cards, self.query, self.tag_id)
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)
        self.window.library_count.setText(f'등록 영상 {len(self.cards)}개 · 표시 {len(self.visible_ids)}개')

    def refresh_details(self, changed_video_id=None):
        if changed_video_id is not None:
            card = next((card for card in self.cards if card['id'] == changed_video_id), None)
            if card is not None:
                has_subtitles = self.core.has_transcript(changed_video_id)
                if card['hasSubtitles'] != has_subtitles:
                    card['hasSubtitles'] = has_subtitles
                    self.bridge.libraryChanged.emit(encode(self.payload()))
        if self.selected_id is not None and (changed_video_id is None or changed_video_id == self.selected_id):
            self.bridge.libraryDetailsChanged.emit(self.selected_id)

    def selection_changed(self):
        self.bridge.libraryChanged.emit(encode(self.payload()))

    def selected_video_id(self):
        return self.selected_id

    def visible_video_ids(self):
        return tuple(self.visible_ids)

    def handle_key(self, event):
        return False  # 예약 키는 셸, 나머지는 Chromium/React가 처리한다.

    def focus_content(self):
        self.request_focus('grid')

    def request_focus(self, target):
        # 채널 연결과 React의 첫 스냅숏 렌더보다 먼저 온 요청도 잃지 않는다.
        self._pending_focus = target
        self.apply_pending_focus()

    def apply_pending_focus(self):
        if self._frontend_ready and self._pending_focus and self.isVisible():
            target, self._pending_focus = self._pending_focus, None
            self.view.setFocus()
            self.bridge.libraryFocusRequested.emit(target if self.active_tab == 'library' else 'shell')

    def frontend_loading(self):
        self._frontend_ready = False
        self._pending_focus = self._pending_focus or 'grid'

    def frontend_ready(self):
        self._frontend_ready = True
        self.apply_pending_focus()
        self.frontend_loaded.emit()

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

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_details()
        self.apply_pending_focus()
