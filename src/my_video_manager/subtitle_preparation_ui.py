"""자막 준비 작업자의 수명과 웹 표시 상태. 다운로드 정책은 코어가 소유한다."""
from time import monotonic

from PySide6.QtCore import QThread, Signal

from .cuda_runtime import PreparationError, PreparationCancellation
from .runtime_assets import preparation_download_label
from .subtitle_preparation_state import safe_detail


PHASES = dict(probe='GPU 확인', download='내려받기', verify='해시 확인',
              extract='압축 풀기', reuse='기존 파일 확인', ready='완료')


def failure_message(kind, message='', detail=''):
    message = message or PreparationError.MESSAGES.get(kind, '자막 기능 준비에 실패했습니다.')
    message = safe_detail(message)
    short = ' '.join(safe_detail(detail).split())
    if len(short) > 180:
        short = short[:179] + '…'
    return f'{message} · {short}' if short else message


class PreparationWorker(QThread):
    progress = Signal(object)
    result = Signal(str, str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core
        self.cancellation = PreparationCancellation()
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
            self.result.emit(error.kind, failure_message(error.kind, str(error), error.detail))
        except Exception as error:
            self.result.emit('other', failure_message('other', detail=error))


def preparation_state(state='idle', *, message='', phase='', asset='', completed=0, total=0, kind='',
                      file_index=0, file_count=0, overall_completed=0, overall_total=0):
    percent = min(99, round(overall_completed / overall_total * 100)) if overall_total else None
    if state == 'ready':
        percent = 100
    if not message and phase:
        message = f'{PHASES.get(phase, "준비")} · {asset}'
    summary = f'전체 {preparation_download_label()}'
    if file_index and file_count:
        summary = f'파일 {file_index}/{file_count} · {summary}'
    return dict(state=state, message=message, phase=phase, asset=asset,
                completed=completed, total=total, kind=kind, summary=summary,
                percent=percent, percentLabel=f'{percent}%' if percent is not None else '',
                guidance='대기열은 보존됩니다. 다시 시도하면 준비 후 받아쓰기를 계속합니다.' if state == 'failed' else '')
