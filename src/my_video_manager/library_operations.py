"""라이브러리 작업과 검사 수명주기 연결."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .web_dialogs_entries import TagEditor, TagManager


# 조용한 시작 검사가 끝난 뒤 복원할지 판단하는 기준 문구.
SCAN_RUNNING_MESSAGE = "영상을 검사하고 썸네일을 만드는 중입니다…"


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent, operation=None):
        super().__init__(parent)
        self.operation = operation or core.scan

    def run(self):
        try:
            self.completed.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class LibraryOperations:
    """웹 라이브러리의 업무 대화상자와 검사 수명주기."""

    def edit_video_tags(self):
        if (video_id := self.selected_video_id()) is not None:
            TagEditor(self.core, video_id=video_id, parent=self).exec()
            self.refresh()

    def manage_tags(self):
        TagManager(self.core, self).exec()
        self.refresh()

    def request_subtitles(self):
        self.window.subtitles.request()

    def show_review(self):
        self.window.show_review()
        self.refresh_details()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "감시 폴더 선택")
        if folder:
            try:
                self.core.add_watched_folder(folder)
                self.refreshed.emit()
                self.scan()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "감시 폴더", str(error))

    def scan(self, checked=False, *, operation=None, quiet_if_unchanged=False):
        if self.worker is not None:
            if operation is not None:
                # 대화상자에서 고른 작업은 안내 대신 예외로 올려 각 화면의 오류 자리에 보여 준다.
                raise ValueError("진행 중인 검사가 끝난 뒤 다시 시도하세요.")
            return
        self._quiet_scan = quiet_if_unchanged
        if quiet_if_unchanged:
            self._previous_scan_report = self.window.web_host.controllers['folders'].report
        self.worker = ScanWorker(self.core, self, operation)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(lambda error: self.report_scan(f"검사 실패: {error}"))
        self.worker.finished.connect(self.scan_finished)
        self.scan_state_changed.emit(True)
        self.selection_changed()
        self.report_scan(SCAN_RUNNING_MESSAGE)
        self.worker.start()

    def report_scan(self, text):
        self.window.show_status(text)
        self.scan_message.emit(text)

    def scan_completed(self, result):
        self.refresh()
        if self._quiet_scan and result.added == 0 and not result.issues:
            # 검사 중 다른 안내가 들어왔으면 그것을 덮어쓰지 않는다.
            if self.window.web_host.controllers['folders'].report == SCAN_RUNNING_MESSAGE:
                self.scan_message.emit(self._previous_scan_report)
                self.window.show_status("")
            return
        summary = f"영상 {result.added}개 등록 · 전체 {len(self.cards)}개 · 안내 {len(result.issues)}개"
        self.scan_message.emit(summary + "\n" + "\n".join(f"{i.path}: {i.message}" for i in result.issues))
        self.window.show_status(summary)

    def scan_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.scan_state_changed.emit(False)
        self.selection_changed()

    def show_series(self):
        video_id = self.selected_video_id()
        series = next((s for s in self.snapshot.series if video_id in s.video_ids), None)
        self.window.web_host.dialogs.run('series', series_id=series.id if series else None)
        self.refresh()

    def show_status(self, text):
        self.window.show_status(text)
