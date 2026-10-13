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
        self.closing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def button(self):
        button = QPushButton("자막 만들기 / 원어 지정")
        button.clicked.connect(self.request)
        return button

    def request(self):
        video_id = self.window.playing_video_id
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
            prompt += f"\n현재 원어: {existing.spoken_language} ({source})"
        language, accepted = QInputDialog.getItem(
            self.window, "원어 자막 만들기", prompt,
            languages, languages.index(initial), True,
        )
        if not accepted:
            return
        if existing and QMessageBox.question(
            self.window, "원어 자막 다시 생성", "다시 생성하면 기존 원어 자막과 검수한 줄이 교체됩니다. 계속할까요?",
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
        if self.worker or self.closing:
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
        elif result.state == "completed":
            transcript = self.core.transcript(result.video_id)
            self.window.statusBar().showMessage(
                f"원어 자막 완료 · 원어 {transcript.spoken_language} · {len(transcript.lines)}줄")
            if self.window.player and self.window.playing_video_id == result.video_id:
                try:
                    self.window.player.set_subtitle(self.core.playback_subtitle(result.video_id))
                except Exception as error:
                    self.window.statusBar().showMessage(f"자막은 저장됐지만 표시에 실패했습니다: {error}")

    def finished(self):
        self.worker.deleteLater()
        self.worker = None
        if self.closing:
            self.window.close()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        if self.worker:
            self.window.statusBar().showMessage("현재 자막 처리가 끝나면 종료합니다. 남은 대기열은 다음 실행에 이어집니다.")
            return False
        return True
