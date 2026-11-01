"""화면 자막 작업자와 대기열 연결. 받아쓰기 작업자와 따로 돌아 서로를 기다리지 않는다. 정책은 AppCore에 둔다."""

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .onscreen_subtitles import NO_TEXT_NOTICE
from .subtitle_queue_kind import ONSCREEN_SUBTITLE


class OnScreenSubtitleWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core

    def run(self):
        try:
            self.completed.emit(self.core.process_next_onscreen_subtitle())
        except Exception as error:
            self.failed.emit(str(error))


class OnScreenSubtitleControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.worker = None
        self.stopping = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def process_queue(self):
        if self.stopping or self.worker:
            return
        if not any(entry.state == "queued" for entry in self.core.subtitle_queue(kind=ONSCREEN_SUBTITLE)):
            return
        self.worker = OnScreenSubtitleWorker(self.core, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda error: self.window.statusBar().showMessage(f"화면 자막 처리 실패: {error}"))
        self.worker.finished.connect(self.finished)
        self.window.statusBar().showMessage("화면 자막을 만드는 중입니다.")
        self.worker.start()

    def completed(self, result):
        if result is None or result.state not in ("completed", "failed"):
            return
        bar = self.window.statusBar()
        if result.state == "failed":
            bar.setToolTip(result.error_detail or result.error)
            bar.showMessage(f"화면 자막 실패 — {result.retry_guidance}: {result.error_detail or result.error}")
        else:
            bar.setToolTip("")
            bar.showMessage(f"화면 자막 · {NO_TEXT_NOTICE}" if result.no_text else f"화면 자막 완료 · {result.line_count}줄")

    def finished(self):
        self.worker.deleteLater()
        self.worker = None

    def shutdown(self):
        """멈춘 작업은 대기로 돌아가 다음 실행에서 처음부터 다시 읽는다."""
        self.timer.stop()
        self.stopping = True
        self.core.stop_onscreen_subtitle_processing()
        if self.worker:
            self.worker.wait()
