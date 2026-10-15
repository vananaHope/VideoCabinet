"""기존 웹 뷰 한 개를 쓰는 모달 층과 숨은 셸의 네이티브 소유 창."""
from time import perf_counter

from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QVBoxLayout

from .web_dialogs_bridge import DialogsBridge
from .web_dialogs_models import DialogModel
from .web_json import encode


class DialogContainer(QDialog):
    def __init__(self, owner):
        super().__init__(owner.window)
        self.owner = owner
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def reject(self):
        self.owner.pop()

    def keyPressEvent(self, event):
        # Esc/Enter는 IME 조합 여부를 아는 React가 처리한다.
        event.ignore()


class WebDialogs(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host, self.window, self.core = host, host.window, host.core
        self.bridge = DialogsBridge(self)
        self.stack = []
        self.loop = None
        self.container = None
        self.result = 0
        self.moving = False
        self.web_modal = False
        self.native_busy = False
        self.metrics = []
        self.last_payload = None
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.publish)
        self.window.pages.currentChanged.connect(self.sync_container)
        self.window.pages.currentChanged.connect(self.reset_web_modal)
        self.host.view.loadStarted.connect(self.reset_web_modal)
        self.host.bridge.shellChanged.connect(self.reset_web_modal)
        QApplication.instance().installEventFilter(self)

    @property
    def active(self):
        return bool(self.stack)

    def eventFilter(self, watched, event):
        if (self.active or self.web_modal) and event.type() in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            reserved = (event.modifiers() == Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_7
                        or event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() == Qt.Key.Key_S)
            if reserved:
                event.accept()
                return True
        return False

    def reset_web_modal(self, *_):
        self.web_modal = False

    def snapshot(self):
        return {'dialog': self.stack[-1].snapshot() if self.stack else None}

    def publish(self):
        payload = encode(self.snapshot())
        if payload != self.last_payload:
            self.last_payload = payload
            self.bridge.dialogsChanged.emit(payload)

    def push(self, kind, **context):
        self.stack.append(DialogModel(self, kind, **context))
        self.publish()
        if self.container:
            self.container.setWindowTitle(self.stack[-1].snapshot()['title'])

    def run(self, kind, **context):
        if self.active:
            raise RuntimeError('대화상자 작업이 이미 진행 중입니다.')
        self.result = 0
        self.loop = QEventLoop(self)
        self.push(kind, **context)
        self.timer.start()
        self.sync_container()
        self.loop.exec()
        self.loop.deleteLater()
        self.loop = None
        return self.result

    def sync_container(self, *_):
        if not self.active or self.container or self.moving or self.window.pages.currentWidget() is self.host:
            return
        self.moving = True
        started = perf_counter()
        self.host.engine_page.runJavaScript("""window.mvmDialogScroll = Array.from(document.querySelectorAll('*'))
            .filter(e => e.scrollTop || e.scrollLeft).map(e => [e, e.scrollTop, e.scrollLeft]); true""",
            lambda _: self.detach(started))

    def detach(self, started):
        detached = perf_counter()
        self.moving = False
        if not self.active or self.container:
            return
        self.container = DialogContainer(self)
        self.container.setWindowTitle(self.stack[-1].snapshot()['title'])
        wide = self.stack[-1].kind in ('review', 'series', 'highlights')
        self.container.resize(min(980 if wide else 640, self.window.width()), min(600, self.window.height()))
        self.container.move(self.window.frameGeometry().center() - self.container.rect().center())
        self.host.layout().removeWidget(self.host.view)
        self.container.layout().addWidget(self.host.view)
        self.container.show()
        self.host.view.show()
        self.container.raise_()
        self.container.activateWindow()
        self.host.view.setFocus()
        self.metrics.append({'detach_ms': (perf_counter() - started) * 1000,
                             'scroll_capture_callback_ms': (detached - started) * 1000,
                             'native_reparent_layout_ms': (perf_counter() - detached) * 1000})

    def pop(self, accepted=False):
        if not self.stack:
            return
        self.stack.pop()
        if self.stack:
            self.publish()
            return
        self.result = int(accepted)
        self.timer.stop()
        self.publish()
        started = perf_counter()
        if self.container:
            container, self.container = self.container, None
            container.layout().removeWidget(self.host.view)
            self.host.layout().addWidget(self.host.view)
            self.host.view.show()
            container.hide()
            container.deleteLater()
            self.host.engine_page.runJavaScript("""requestAnimationFrame(() => requestAnimationFrame(() => {
                for (const [e, top, left] of window.mvmDialogScroll || []) {
                    if (e.isConnected) { e.scrollTop = top; e.scrollLeft = left; }
                }
                delete window.mvmDialogScroll;
            }))""")
            self.metrics.append({'attach_ms': (perf_counter() - started) * 1000})
        if self.loop:
            self.loop.quit()
        QTimer.singleShot(0, self.restore_focus)

    def restore_focus(self):
        if self.active:
            return
        self.window.activateWindow()
        if self.window.pages.currentWidget() is self.window.playback_page:
            self.window.playback_page.focus_content()
        elif self.window.pages.currentWidget() is self.host:
            self.host.view.setFocus()
        else:
            self.window.pages.currentWidget().focus_content()

    def act(self, identifier, action, data):
        if self.native_busy:
            raise ValueError('파일 저장 대화상자를 먼저 닫으세요.')
        if not self.stack or self.stack[-1].identifier != identifier:
            raise ValueError('대화상자가 바뀌었습니다. 현재 내용을 확인하세요.')
        self.stack[-1].act(action, data)
        self.publish()

    def save_export(self, export):
        # WebChannel 응답을 먼저 돌려주고 Windows 기본 저장 창을 연다.
        self.native_busy = True
        frame = self.stack[-1]
        def save():
            parent = self.container or self.window
            try:
                path, _ = QFileDialog.getSaveFileName(parent, 'SRT 저장', str(export.default_path), 'SRT 자막 (*.srt)')
                if path:
                    self.core.write_subtitle_export(export, path)
            except Exception as error:
                frame.message = f'SRT 저장 실패: {error}'
            finally:
                self.native_busy = False
                self.publish()
                self.host.view.setFocus()
        QTimer.singleShot(0, save)


def web_dialogs(parent):
    """기존 진입 함수의 부모 사슬에서 웹 셸을 찾는다. 웹을 끄면 None."""
    node = parent
    while node is not None:
        host = getattr(node, 'web_host', None)
        if host is not None:
            return host.dialogs
        node = node.parent()
    return None
