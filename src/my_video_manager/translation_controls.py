"""번역 작업자·대기열과 웹 CLI 선택·재시도 진입. 정책은 AppCore에 둔다."""

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .core import CommandType
from .key_display import display_keys
from .translation_source import ONSCREEN, TRANSCRIPT


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
    video_changed = Signal(int)

    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.worker = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(500)

    def settings(self):
        self.window.web_host.dialogs.run('translation')

    def process_queue(self):
        if self.worker or not self.core.translation_ready():
            return
        self.worker = TranslationWorker(self.core, self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(lambda error: self.window.statusBar().showMessage(f"번역 처리 실패: {error}"))
        self.worker.finished.connect(self.finished)
        self.window.statusBar().showMessage("한국어 자막 처리 중입니다. 원어 자막은 지금 볼 수 있습니다…")
        self.worker.start()

    def completed(self, result):
        if result is None:
            return
        task = self.core.subtitle_task(result.video_id, source=result.source)
        bar = self.window.statusBar()
        bar.setToolTip(result.error_detail or "")
        if result.state == "held":
            bar.showMessage(f"{task.label} 보류 · {result.retry_at.astimezone():%H:%M} 자동 재시도 · {result.error}")
        elif result.error:
            bar.showMessage(f"{task.label} 실패 · {result.error} 번역 방식 / 재시도에서 다시 요청하세요.")
        else:
            keys = next((display_keys(row.keys) for row in self.core.key_bindings()
                         if row.command.kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE), "키 미할당")
            bar.showMessage(f"{task.label} {'완료' if result.state == 'completed' else '진행'} · "
                            f"{result.completed_lines}/{result.total_lines}줄" +
                            ('' if result.source == ONSCREEN else f' · 원어/{task.short_label} 전환: {keys}'))
            session = self.core.playback.session
            if (result.source == TRANSCRIPT and result.state == "completed" and self.window.player
                    and session and session.video_id == result.video_id):
                try:
                    self.window.player.set_subtitle(self.core.playback_subtitle(result.video_id))
                except Exception as error:
                    bar.showMessage(f"{task.subtitle_label}은 저장됐지만 표시에 실패했습니다: {error}")
        if result.notice:
            bar.showMessage(f"{bar.currentMessage()} · {result.notice}")
        self.video_changed.emit(result.video_id)

    def toggle(self) -> bool:
        """원어/번역 자막을 바꾼다. 바꿀 수 없으면 이유를 안내하고 False를 돌려준다."""
        changed, message = self.core.toggle_subtitle_language()
        if not changed:
            self.window.statusBar().showMessage(message, 4000)
            return False
        self.window.player.set_subtitle(self.core.playback_subtitle(self.core.playback.session.video_id))
        return True

    def finished(self):
        self.worker.deleteLater()
        self.worker = None

    def shutdown(self):
        self.timer.stop()
        self.window.web_host.dialogs.shutdown()
        self.core.stop_translation_processing()
        if self.worker:
            self.worker.wait()
