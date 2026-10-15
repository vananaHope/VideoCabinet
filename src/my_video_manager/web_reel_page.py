"""웹 모아보기 목록과 기존 ReelControls의 연결."""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox

from .reel_ui import ReelControls
from .web_contract import REEL
from .web_json import encode
from .web_page import WebPageController
from .web_reel_data import entries_data, guidance


class WebReelControls(ReelControls):
    """웹 태그를 코어로 넘기고, 엔진 전환은 기존 sync에 맡긴다."""
    def start(self, highlight_id=None, *, tag_id=None):
        page = self.window.web_host.controllers['reel']
        page.status = ''
        try:
            self.window.end_playback()
            self.core.start_reel(tag_id, highlight_id)
            self.sync()
        except Exception as error:
            self.open()
            QMessageBox.warning(self.window, '모아보기 재생 실패', str(error))

    def sync(self):
        completed = self.shown is not None and self.core.reel_playback is None
        super().sync()
        if completed:
            page = self.window.web_host.controllers['reel']
            page.status = '모아보기를 마쳤습니다. 다시 재생할 하이라이트를 고르세요.'
            page.refresh_guidance()

    def open(self):
        self.window.navigate_web_tab('reel')
        self.window._return_to_gems = False

    def refresh_guidance(self):
        super().refresh_guidance()
        self.window.web_host.controllers['reel'].refresh_guidance()


class ReelBridge(QObject):
    changed = REEL.signal('changed')
    focusRequested = REEL.signal('focusRequested')
    error = REEL.signal('error')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @REEL.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @REEL.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @REEL.slot('refresh')
    def refresh(self):
        self.page.refresh()
        return encode({'ok': True})

    @REEL.slot('filter')
    def filter(self, tag_id):
        self.page.tag_id = tag_id
        return self.refresh()

    @REEL.slot('select')
    def select(self, highlight_id):
        if not any(e['id'] == highlight_id for e in self.page.entries):
            return encode({'error': '현재 목록에 없는 하이라이트입니다.'})
        self.page.selected_id = highlight_id
        return encode({'ok': True})

    @REEL.slot('play')
    def play(self, highlight_id):
        entries = self.page.entries
        if self.busy or not any(e['playable'] and (not highlight_id or e['id'] == highlight_id) for e in entries):
            return encode({'error': '재생할 수 있는 하이라이트를 선택하세요.'})
        if highlight_id:
            self.page.selected_id = highlight_id
        self.busy = True
        QTimer.singleShot(0, lambda: self.perform_play(highlight_id))
        return encode({'ok': True})

    def perform_play(self, highlight_id):
        try:
            controls = self.page.window.reel
            self.page.host.remember_playback_tab()
            controls.start(highlight_id or None, tag_id=self.page.tag_id or None)
        except (ValueError, OSError, RuntimeError) as error:
            self.error.emit(str(error))
        finally:
            self.busy = False


class WebReelPage(WebPageController):
    tab = 'reel'
    default_focus = 'reel-list'

    def __init__(self, host):
        super().__init__(host)
        self.tag_id, self.selected_id = 0, None
        self.entries, self.tags = [], []
        self.status = ''
        self.bridge = ReelBridge(self)
        self.focus_requested = self.bridge.focusRequested
        host.register_page(self)

    def payload(self):
        title, description = guidance(self.core, self.tag_id)
        return dict(entries=self.entries, tags=self.tags, tagId=self.tag_id,
                    selectedId=self.selected_id, emptyTitle=title, emptyDescription=description,
                    status=self.status)

    def refresh(self):
        self.status = ''
        self.tags = [dict(id=t.id, name=t.name) for t in self.core.tags()]
        if self.tag_id not in {t['id'] for t in self.tags}:
            self.tag_id = 0
        self.entries = entries_data(self.core, self.tag_id)
        if self.selected_id not in {e['id'] for e in self.entries}:
            self.selected_id = self.entries[0]['id'] if self.entries else None
        self.refresh_guidance()

    def refresh_guidance(self):
        self.bridge.changed.emit(encode(self.payload()))
