"""가려진 웹 셸의 cleared FBO를 준비된 목록으로 취급하지 않는다."""

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QImage


def has_frame_content(image):
    """셸에는 항상 탭 줄 또는 오류 문구가 있다. 단색은 아직 내용 없는 FBO다."""
    if image.isNull():
        return False
    blank = QImage(image.size(), image.format())
    blank.setDevicePixelRatio(image.devicePixelRatio())
    blank.fill(image.pixelColor(0, 0))
    return image != blank


class WebReturnFrame(QObject):
    """Paint 처리 뒤 readback을 확인한다. 시간은 성공 조건이 아닌 실패 상한이다."""

    def __init__(self, parent, renderer, completed, *, timeout_ms=1500):
        super().__init__(parent)
        self.renderer = renderer
        self.completed = completed
        self.queued = False
        self.image = QImage()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.finish)
        renderer.installEventFilter(self)
        renderer.destroyed.connect(self.finish)
        self.deadline.start(timeout_ms)

    def check(self):
        self.queued = False
        if self.completed is None:
            return
        try:
            image = self.renderer.grabFramebuffer()
            if has_frame_content(image):
                self.image = image
                self.finish()
            else:
                self.renderer.update()
        except Exception:
            # WebChannel 호출이 끝난 뒤 발생한 렌더 실패도 덮개를 남기지 않는다.
            self.finish()

    def eventFilter(self, watched, event):
        if self.completed is not None and event.type() == QEvent.Type.Paint and not self.queued:
            self.queued = True
            # eventFilter는 paintEvent보다 먼저 호출된다. 처리 완료 후 확인한다.
            QTimer.singleShot(0, self.check)
        return False

    def finish(self, *_):
        completed = self.completed
        self.cancel()
        if completed is not None:
            completed(self.image)

    def cancel(self):
        self.completed = None
        self.deadline.stop()
        try:
            self.renderer.removeEventFilter(self)
            self.renderer.destroyed.disconnect(self.finish)
        except RuntimeError:
            pass  # renderer의 destroyed 신호 안에서도 실패 복귀한다.
        self.deleteLater()
