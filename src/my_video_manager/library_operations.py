"""라이브러리 작업과 검사 수명주기 연결."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .tag_ui import TagEditor, TagManager
from .series_ui import SeriesEditor


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
    """Qt·웹 페이지가 공유하는 대화상자와 검사 수명주기."""

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

    def scan(self, checked=False, *, operation=None):
        if self.worker is not None:
            return
        self.worker = ScanWorker(self.core, self, operation)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(lambda error: self.report_scan(f"검사 실패: {error}"))
        self.worker.finished.connect(self.scan_finished)
        self.scan_state_changed.emit(True)
        self.selection_changed()
        self.report_scan("영상을 검사하고 썸네일을 만드는 중입니다…")
        self.worker.start()

    def report_scan(self, text):
        self.window.show_status(text)
        self.scan_message.emit(text)

    def scan_completed(self, result):
        self.refresh()
        summary = f"영상 {result.added}개 등록 · 전체 {len(self.cards)}개 · 안내 {len(result.issues)}개"
        self.scan_message.emit(summary + "\n" + "\n".join(f"{i.path}: {i.message}" for i in result.issues))
        self.window.show_status(summary)

    def scan_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.scan_state_changed.emit(False)
        self.selection_changed()

    def show_series(self):
        editor = SeriesEditor(self.core, self)
        video_id = self.selected_video_id()
        series = next((s for s in self.snapshot.series if video_id in s.video_ids), None)
        if series:
            editor.selector.setCurrentIndex(editor.selector.findData(series.id))
        editor.exec()
        self.refresh()

    def show_status(self, text):
        self.window.show_status(text)


