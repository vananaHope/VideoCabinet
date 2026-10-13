"""자막 줄 목록. 저장·검수·내보내기 정책은 AppCore에 맡긴다."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .review import ReviewConfirmationRequired


class ReviewDialog(QDialog):
    def __init__(self, core, video_id, jump, changed, parent=None):
        super().__init__(parent)
        self.core, self.video_id = core, video_id
        self.jump, self.changed = jump, changed
        self.rows = ()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("자막 검수 · SRT 내보내기")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("줄 클릭 또는 Enter: 장면 이동 · 방향키: 줄 선택 · Tab: 버튼 이동 · Esc: 닫기"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["시각(초)", "원어 자막", "번역 자막", "검수"])
        self.table.setAccessibleName("원어와 번역 자막 줄 목록")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setTabKeyNavigation(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(lambda row, column: self.activate(row))
        self.table.itemActivated.connect(lambda item: self.activate(item.row()))
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for label, callback in (
            ("원어 줄 수정", lambda: self.edit(False)),
            ("번역 줄 수정", lambda: self.edit(True)),
            ("구간 다시 생성", self.regenerate_range),
            ("전체 다시 생성", self.regenerate_all),
            ("원어 SRT 저장", lambda: self.export(False)),
            ("번역 SRT 저장", lambda: self.export(True)),
            ("닫기", self.accept),
        ):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()
        self.table.setFocus()

    def refresh(self):
        rows = self.core.review_lines(self.video_id)
        if rows == self.rows:
            return
        previous = self.selected()
        index = self.table.currentRow()
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            state = " · ".join(label for flag, label in (
                (row.original_reviewed, "원어 검수됨"), (row.translation_reviewed, "번역 검수됨")) if flag)
            values = (f"{row.original.start:.3f}–{row.original.end:.3f}", row.original.text,
                      row.translation if row.translation is not None else "미번역", state)
            for column, value in enumerate(values):
                self.table.setItem(i, column, QTableWidgetItem(value))
            if previous and previous.original.id == row.original.id:
                index = i
        self.table.resizeRowsToContents()
        if rows:
            self.table.selectRow(max(0, min(index, len(rows) - 1)))

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def activate(self, index):
        if 0 <= index < len(self.rows):
            try:
                self.jump(self.video_id, self.rows[index].original.id)
            except Exception as error:
                QMessageBox.warning(self, "장면 이동", str(error))

    def edit(self, translated):
        row = self.selected()
        if row is None:
            return
        text, accepted = QInputDialog.getMultiLineText(
            self, "번역 줄 수정" if translated else "원어 줄 수정", "자막 텍스트",
            row.translation or "" if translated else row.original.text)
        if not accepted:
            return
        try:
            if translated:
                self.core.edit_translation_line(self.video_id, row.original.id, text)
            else:
                try:
                    self.core.edit_transcript_line(self.video_id, row.original.id, text)
                except ReviewConfirmationRequired as warning:
                    if not self.confirm(str(warning)):
                        return
                    self.core.edit_transcript_line(self.video_id, row.original.id, text, overwrite_reviewed=True)
            self.changed(self.video_id)
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "자막 수정", str(error))

    def confirm(self, message):
        return QMessageBox.question(self, "자막 검수", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def regenerate_range(self):
        video = next(v for v in self.core.videos() if v.id == self.video_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("구간 원어 자막 다시 생성")
        layout = QFormLayout(dialog)
        row = self.selected()
        start, end = QDoubleSpinBox(), QDoubleSpinBox()
        for widget, value in ((start, row.original.start if row else 0),
                              (end, row.original.end if row else video.duration)):
            widget.setRange(0, video.duration)
            widget.setDecimals(3)
            widget.setValue(value)
        layout.addRow("시작(초)", start)
        layout.addRow("끝(초)", end)
        note = QLabel()
        layout.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        def update_range():
            try:
                actual_start, actual_end = self.core.subtitle_range_bounds(self.video_id, start.value(), end.value())
                note.setText(f"실제로 받아쓸 범위: {actual_start:.3f}–{actual_end:.3f}초\n"
                             "경계에 걸친 줄 전체를 포함하도록 넓혀 원어와 번역을 교체합니다.")
                buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            except ValueError as error:
                note.setText(str(error))
                buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        start.valueChanged.connect(update_range)
        end.valueChanged.connect(update_range)
        update_range()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.core.request_subtitle_range(self.video_id, start.value(), end.value())
        except Exception as error:
            QMessageBox.warning(self, "구간 재생성", str(error))

    def regenerate_all(self):
        if not self.confirm(self.core.subtitle_regeneration_warning(self.video_id)):
            return
        transcript = self.core.transcript(self.video_id)
        try:
            self.core.request_subtitles(self.video_id,
                                        transcript.spoken_language if transcript and transcript.language_specified else None)
        except Exception as error:
            QMessageBox.warning(self, "전체 재생성", str(error))

    def export(self, translated):
        try:
            export = self.core.subtitle_export(self.video_id, translated=translated)
            if translated and (export.missing_lines or export.pending_retranslation_lines) and not self.confirm(export.warning):
                return
            path, _ = QFileDialog.getSaveFileName(self, "SRT 저장", str(export.default_path), "SRT 자막 (*.srt)")
            if path:
                self.core.write_subtitle_export(export, path)
        except Exception as error:
            QMessageBox.warning(self, "SRT 저장", str(error))


def review_button(window):
    button = QPushButton("자막 검수 / SRT 내보내기")
    button.clicked.connect(window.show_review)
    return button
