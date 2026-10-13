"""번역 작업자와 최소 CLI 설정 입력. 정책은 AppCore에 둔다."""

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QInputDialog, QPushButton


class TranslationWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core

    def run(self):
        try:
            self.completed.emit(self.core.process_next_translation())
        except Exception as error:
            self.failed.emit(str(error))


class TranslationControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.worker = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def button(self):
        button = QPushButton("번역 CLI / 재시도")
        button.clicked.connect(self.settings)
        return button

    def settings(self):
        choices = ["codex", "claude"]
        waiting = [e for e in self.core.translation_queue() if e.state in ("failed", "held")]
        prompt = "한국어 번역에 사용할 구독 CLI를 고르세요. 설치와 로그인이 필요합니다."
        if waiting:
            prompt += f"\n확인하면 실패·보류 중인 번역 {len(waiting)}건을 저장한 묶음부터 재시도합니다."
        selected, accepted = QInputDialog.getItem(
            self.window, "번역 CLI", prompt, choices, choices.index(self.core.translation_cli), False)
        if accepted:
            self.core.set_translation_cli(selected)
            for entry in waiting:
                try:
                    self.core.request_translation(entry.video_id)
                except ValueError:
                    pass  # 대화상자를 연 사이 원어가 재생성된 영상은 새 요청을 따른다.
            self.window.statusBar().showMessage(f"번역 CLI: {selected}", 5000)

    def process_queue(self):
        if self.worker or not self.core.translation_ready():
            return
        self.worker = TranslationWorker(self.core, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda error: self.window.statusBar().showMessage(f"번역 처리 실패: {error}"))
        self.worker.finished.connect(self.finished)
        self.window.statusBar().showMessage("한국어 번역 중입니다. 원어 자막은 지금 볼 수 있습니다…")
        self.worker.start()

    def completed(self, result):
        if result is None:
            return
        bar = self.window.statusBar()
        bar.setToolTip(result.error_detail or "")
        if result.state == "held":
            bar.showMessage(f"번역 보류 · {result.retry_at.astimezone():%H:%M} 자동 재시도 · {result.error}")
        elif result.error:
            bar.showMessage(f"번역 실패 · {result.error} 번역 CLI / 재시도에서 다시 요청하세요.")
        else:
            bar.showMessage(f"번역 {'완료' if result.state == 'completed' else '진행'} · "
                            f"{result.completed_lines}/{result.total_lines}줄 · . 키로 원어/번역 전환")
            session = self.core.playback.session
            if result.state == "completed" and self.window.player and session and session.video_id == result.video_id:
                try:
                    self.window.player.set_subtitle(self.core.playback_subtitle(result.video_id))
                except Exception as error:
                    bar.showMessage(f"번역은 저장됐지만 표시에 실패했습니다: {error}")

    def toggle(self):
        changed, message = self.core.toggle_subtitle_language()
        if changed:
            self.window.player.set_subtitle(self.core.playback_subtitle(self.core.playback.session.video_id))
        self.window.statusBar().showMessage(message, 4000)

    def finished(self):
        self.worker.deleteLater()
        self.worker = None

    def shutdown(self):
        self.timer.stop()
        self.core.stop_translation_processing()
        if self.worker:
            self.worker.wait()
