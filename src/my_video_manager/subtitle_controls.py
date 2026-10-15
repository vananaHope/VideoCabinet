"""웹 자막 요청 진입과 작업자·대기열 연결. 자막 정책은 AppCore에 맡긴다."""

import sys

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from .subtitle_preparation_ui import PreparationWorker, preparation_state, failure_message


class SubtitleWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core

    def run(self):
        try:
            self.completed.emit(self.core.process_next_subtitle())
        except Exception as error:
            self.failed.emit(str(error))


class SubtitleControls(QObject):
    video_changed = Signal(int)
    preparation_changed = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.core = window.core
        self.worker = None
        self.preparation_worker = None
        self.preparation = preparation_state()
        self.support_ready = not getattr(sys, 'frozen', False)
        self.previous_preparation = self.core.subtitle_support_status() if not self.support_ready else None
        if self.previous_preparation and self.previous_preparation['kind'] == 'ready':
            self.support_ready = True
        self.stopping = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def request(self):
        session = self.core.playback.session
        video_id = session.video_id if session else self.window.library_page.selected_video_id()
        if video_id is not None:
            self.window.web_host.dialogs.run('subtitles', video_id=video_id)

    def process_queue(self):
        if self.stopping or self.worker or self.preparation_worker:
            return
        if not any(entry.state == "queued" for entry in self.core.subtitle_queue()):
            if self.preparation['state'] == 'failed':
                self.set_preparation(preparation_state())
            return
        if not self.support_ready:
            if self.preparation['state'] == 'idle':
                previous = self.previous_preparation
                if previous and previous['kind'] not in ('idle', 'ready'):
                    self.set_preparation(preparation_state('failed', kind=previous['kind'],
                        message=failure_message(**previous)))
                else:
                    self.prepare()
            return
        self.worker = SubtitleWorker(self.core, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda error: self.window.statusBar().showMessage(f"자막 처리 실패: {error}"))
        self.worker.finished.connect(self.finished)
        self.window.statusBar().showMessage("원어 자막을 만드는 중입니다.")
        self.worker.start()

    def set_preparation(self, value):
        self.preparation = value
        self.preparation_changed.emit(value)

    def prepare(self):
        if self.stopping or self.preparation_worker or self.support_ready:
            return
        if not any(entry.state == 'queued' for entry in self.core.subtitle_queue()):
            self.set_preparation(preparation_state())
            return
        self.set_preparation(preparation_state('preparing', message='자막 기능 준비 중…'))
        self.preparation_worker = PreparationWorker(self.core, self)
        self.preparation_worker.progress.connect(self.preparation_progress)
        self.preparation_worker.result.connect(self.preparation_result)
        self.preparation_worker.finished.connect(self.preparation_finished)
        self.preparation_worker.start()

    def preparation_progress(self, value):
        # 취소 요청 뒤 늦게 도착한 진행 신호로 취소 중 상태를 덮지 않는다.
        if self.preparation['state'] == 'cancelling':
            return
        self.set_preparation(preparation_state('preparing', phase=value.phase, asset=value.asset,
                            completed=value.completed, total=value.total, file_index=value.file_index,
                            file_count=value.file_count, overall_completed=value.overall_completed,
                            overall_total=value.overall_total))

    def preparation_result(self, kind, message):
        self.support_ready = kind == 'ready'
        self.previous_preparation = dict(kind=kind, message=message, detail='')
        self.set_preparation(preparation_state('ready' if self.support_ready else 'failed',
                                              kind=kind, message=message))

    def preparation_finished(self):
        self.preparation_worker.deleteLater()
        self.preparation_worker = None
        self.process_queue()

    def cancel_preparation(self):
        if self.preparation_worker:
            self.preparation_worker.cancellation.set()
            self.set_preparation(preparation_state('cancelling', message='취소 중… 네트워크 응답은 최대 10초 기다립니다.'))

    def completed(self, result):
        if result is None:
            return
        if result.error:
            self.window.statusBar().showMessage(f"자막 실패 — {result.retry_guidance}: {result.error}")
            self.window.statusBar().setToolTip(result.error_detail or result.error)
        elif result.state == "completed":
            transcript = self.core.transcript(result.video_id)
            self.window.statusBar().setToolTip("")
            self.window.statusBar().showMessage(
                f"원어 자막 완료 · 원어 {transcript.spoken_language or '알 수 없음'} · {len(transcript.lines)}줄")
            session = self.core.playback.session
            if self.window.player and session and session.video_id == result.video_id:
                try:
                    self.window.player.set_subtitle(self.core.playback_subtitle(result.video_id))
                except Exception as error:
                    self.window.statusBar().showMessage(f"자막은 저장됐지만 표시에 실패했습니다: {error}")
        self.video_changed.emit(result.video_id)

    def finished(self):
        self.worker.deleteLater()
        self.worker = None

    def shutdown(self):
        if self.worker and self.worker.isRunning():
            dialog = QMessageBox(QMessageBox.Icon.Question, "받아쓰기 중 종료",
                                 "받아쓰기 중입니다. 지금 종료하면 다음 실행 때 처음부터 다시 받아씁니다.",
                                 parent=self.window)
            quit_button = dialog.addButton("지금 종료", QMessageBox.ButtonRole.AcceptRole)
            cancel_button = dialog.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(cancel_button)
            dialog.exec()
            if dialog.clickedButton() != quit_button:
                return False
        self.timer.stop()
        self.stopping = True
        if self.preparation_worker:
            self.preparation_worker.cancellation.set()
            self.preparation_worker.wait()
        self.core.stop_subtitle_processing()
        if self.worker:
            self.worker.wait()  # 취소 신호가 프로세스 트리를 즉시 종료한 뒤 스레드를 회수한다.
        return True
