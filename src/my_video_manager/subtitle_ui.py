"""자막 요청과 작업자 연결. 자막 정책은 AppCore 공개 메서드에 맡긴다."""

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton


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
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.core = window.core
        self.worker = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def button(self):
        button = QPushButton("자막 만들기 / 원어 지정")
        button.clicked.connect(self.request)
        return button

    def request(self):
        session = self.core.playback.session
        video_id = session.video_id if session else None
        if video_id is None:
            item = self.window.list.currentItem()
            if item is None:
                return
            video_id = item.data(Qt.ItemDataRole.UserRole)
        existing = self.core.transcript(video_id)
        languages = ["자동 감지", "ko", "en", "ja", "zh", "de", "fr", "es"]
        initial = existing.spoken_language if existing and existing.language_specified else "자동 감지"
        if initial not in languages:
            languages.append(initial)
        prompt = "원어를 고르거나 언어 코드를 입력하세요 (예: en, ko, ja)."
        if existing:
            source = "직접 지정" if existing.language_specified else "자동 감지"
            prompt += f"\n현재 원어: {existing.spoken_language or '알 수 없음'} ({source})"
        language, accepted = QInputDialog.getItem(
            self.window, "원어 자막 만들기", prompt,
            languages, languages.index(initial), True,
        )
        if not accepted:
            return
        if existing and QMessageBox.question(
            self.window, "원어 자막 다시 생성", self.core.subtitle_regeneration_warning(video_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.core.request_subtitles(video_id, None if language == "자동 감지" else language)
            self.window.statusBar().showMessage("자막 대기열에 추가했습니다. 재생 중에도 계속 처리합니다.")
        except Exception as error:
            QMessageBox.warning(self.window, "자막 요청 실패", str(error))

    def process_queue(self):
        if self.worker:
            return
        if not any(entry.state == "queued" for entry in self.core.subtitle_queue()):
            return
        self.worker = SubtitleWorker(self.core, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda error: self.window.statusBar().showMessage(f"자막 처리 실패: {error}"))
        self.worker.finished.connect(self.finished)
        self.window.statusBar().showMessage("원어 자막을 만드는 중입니다. 첫 실행은 모델을 내려받습니다…")
        self.worker.start()

    def completed(self, result):
        if result is None:
            return
        if result.error:
            self.window.statusBar().showMessage(f"자막 실패 — 다시 요청하면 재시도합니다: {result.error}")
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
        self.core.stop_subtitle_processing()
        if self.worker:
            self.worker.wait()  # 취소 신호가 프로세스 트리를 즉시 종료한 뒤 스레드를 회수한다.
        return True
