"""라이브러리 작업과 검사 수명주기 연결."""
from dataclasses import dataclass, replace

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .library import ScanIssue
from .web_dialogs_entries import TagEditor, TagManager


@dataclass(frozen=True)
class ScanReport:
    """검사 안내. message는 진행·요약·실패 문구, issues는 마지막 검사가 남긴 안내다.

    finished는 끝난 검사의 결과(작업 결과)라 닫을 수 있다는 뜻이다. 처음 설명과 검사 중 문구는 현재 상태라 닫지 않는다.
    닫은 묶음(dismissed)은 보고와 함께 다니므로, 조용한 검사가 이전 안내를 되돌려도 닫힌 채 남고 새 결과는 다시 보인다.
    """
    message: str
    failed: bool = False
    issues: tuple[ScanIssue, ...] = ()
    finished: bool = False
    dismissed: frozenset[str] = frozenset()

    def dismiss(self, group):
        return replace(self, dismissed=self.dismissed | {group})


SCAN_RUNNING_MESSAGE = "영상을 검사하고 썸네일을 만드는 중입니다…"
# 조용한 시작 검사가 끝난 뒤 복원할지 판단하는 기준 안내.
SCAN_RUNNING = ScanReport(SCAN_RUNNING_MESSAGE)


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
                if self.worker is None:
                    self.scan()
                else:
                    # 폴더 선택 중 시작된 검사는 새 폴더를 모르므로 끝난 뒤 다시 검사한다.
                    self.window.folder_watch.request_full_scan()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "감시 폴더", str(error))

    def scan(self, checked=False, *, operation=None, quiet_if_unchanged=False, known_issues=()):
        if self.worker is not None:
            if operation is not None:
                # 대화상자에서 고른 작업은 안내 대신 예외로 올려 각 화면의 오류 자리에 보여 준다.
                raise ValueError("진행 중인 검사가 끝난 뒤 다시 시도하세요.")
            return
        self._quiet_scan = quiet_if_unchanged
        # 조용한 검사에서 이미 알린 안내만 다시 나오면 새 안내가 없는 것으로 본다.
        self._known_issues = known_issues
        if quiet_if_unchanged:
            self._previous_scan_report = self.window.web_host.controllers['folders'].report
        self.worker = ScanWorker(self.core, self, operation)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(
            lambda error: self.report_scan(ScanReport(f"검사 실패: {error}", failed=True, finished=True)))
        self.worker.finished.connect(self.scan_finished)
        self.scan_state_changed.emit(True)
        self.selection_changed()
        self.report_scan(SCAN_RUNNING)
        self.worker.start()

    def report_scan(self, report):
        self.window.show_status(report.message)
        self.scan_message.emit(report)

    def scan_completed(self, result):
        self.refresh()
        if self._quiet_scan and result.added == 0 and all(i in self._known_issues for i in result.issues):
            # 검사 중 다른 안내가 들어왔으면 그것을 덮어쓰지 않는다.
            if self.window.web_host.controllers['folders'].report == SCAN_RUNNING:
                self.scan_message.emit(self._previous_scan_report)
                self.window.show_status("")
            return
        summary = f"영상 {result.added}개 등록 · 전체 {len(self.cards)}개"
        self.scan_message.emit(ScanReport(summary, issues=result.issues, finished=True))
        self.window.show_status(f"{summary} · 안내 {len(result.issues)}개")

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
