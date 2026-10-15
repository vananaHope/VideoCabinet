"""자막 준비 작업자의 수명과 웹 표시 상태. 다운로드 정책은 코어가 소유한다."""
from threading import Event
from time import monotonic

from PySide6.QtCore import QThread, Signal

from .cuda_runtime import PreparationError


class PreparationWorker(QThread):
    progress = Signal(object)
    result = Signal(str, str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core
        self.cancellation = Event()
        self.last_report = 0.0

    def report(self, value):
        now = monotonic()
        if now - self.last_report >= 0.1 or value.completed == value.total:
            self.last_report = now
            self.progress.emit(value)

    def run(self):
        try:
            self.core.prepare_subtitle_support(cancellation=self.cancellation, progress=self.report)
            self.result.emit('ready', '자막 기능 준비를 마쳤습니다.')
        except PreparationError as error:
            self.result.emit(error.kind, str(error))
        except Exception as error:
            self.result.emit('other', f'자막 기능 준비에 실패했습니다: {error}')


def preparation_state(state='idle', *, message='', phase='', asset='', completed=0, total=0, kind=''):
    return dict(state=state, message=message, phase=phase, asset=asset,
                completed=completed, total=total, kind=kind)
