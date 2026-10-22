"""GPU 웹 표면을 교체하는 동안 준비된 목록을 독립 raster 표면으로 표시한다."""

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QBackingStore, QPainter, QRegion, QSurface, QWindow
from PySide6.QtWidgets import QApplication, QWidget


class RasterWindow(QWindow):
    def __init__(self, owner):
        super().__init__(owner.window.windowHandle())
        self.owner = owner
        self.setObjectName('playback-return-cover')
        self.setSurfaceType(QSurface.SurfaceType.RasterSurface)
        self.setFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint
                      | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)

    def exposeEvent(self, event):
        if self.isExposed():
            self.owner.paint()


class WebReturnCover(QObject):
    """raster flush → 웹 교체 → 주 창 UpdateRequest 처리 완료 순서를 보장한다.

    Qt의 처리 완료는 DWM의 per-window present 확인 신호가 아니다. 독립 raster
    표면이 그 사이 완성된 목록을 유지한다. expose/update가 없으면 상한으로 복귀한다.
    """

    def __init__(self, parent, image, commit, completed, *, timeout_ms=1500):
        super().__init__(parent)
        self.window = parent.window
        self.image = image
        self.commit_callback = commit
        self.completed = completed
        self.painted = False
        self.submitted = False
        self.surface = RasterWindow(self)
        self.surface.setGeometry(self.window.rect())
        self.store = QBackingStore(self.surface)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(timeout_ms)
        self.deadline.timeout.connect(self.finish)

    def start(self):
        QApplication.instance().installEventFilter(self)
        self.deadline.start()
        self.surface.show()
        self.surface.raise_()

    def paint(self):
        if self.completed is None:
            return
        try:
            self.store.resize(self.surface.size())
            region = QRegion(0, 0, self.surface.width(), self.surface.height())
            self.store.beginPaint(region)
            painter = QPainter(self.store.paintDevice())
            try:
                painter.drawImage(region.boundingRect(), self.image)
            finally:
                painter.end()
                self.store.endPaint()
            self.store.flush(region)
            if not self.painted:
                self.painted = True
                QTimer.singleShot(0, self.commit)
        except Exception:
            self.finish()

    def commit(self):
        callback, self.commit_callback = self.commit_callback, None
        if self.completed is None or callback is None:
            return
        try:
            callback()
            if self.completed is not None:
                self.submitted = True
                self.window.update()
        except Exception:
            self.finish()

    def eventFilter(self, watched, event):
        if self.completed is None:
            return False
        kind = event.type()
        if watched is self.window:
            if self.submitted and kind == QEvent.Type.UpdateRequest:
                self.submitted = False
                QTimer.singleShot(0, self.finish)
            elif kind in (QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.Close):
                self.finish()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            if isinstance(watched, QWidget) and watched.window() is self.window:
                # 새 입력은 정지 이미지를 보며 처리되지 않는다. 입력 자체는 소비하지 않는다.
                self.finish()
        return False

    def finish(self):
        completed = self.completed
        if completed is None:
            return
        commit = self.commit_callback
        self.cancel()
        try:
            if commit is not None:
                commit()
        finally:
            completed()

    def cancel(self):
        if self.completed is None:
            return
        self.completed = None
        self.commit_callback = None
        self.deadline.stop()
        QApplication.instance().removeEventFilter(self)
        self.surface.hide()
        # QBackingStore는 QObject 자식이 아닌 Python 소유 객체다.
        # 마지막 Python 참조를 먼저 버리고 그 뒤 native 창의 삭제를 예약한다.
        self.store = None
        self.surface.deleteLater()
        self.deleteLater()
