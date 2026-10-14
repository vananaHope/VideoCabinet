"""하이라이트 표시와 편집. 도메인 변경은 AppCore 공개 API에 맡긴다."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from .highlight_editing import initial_time_input, resolve_time_input, time_input_maximum
from .tag_ui import TagEditor
from .theme import ACCENT, BORDER, TEXT, HIGHLIGHT_POINT, HIGHLIGHT_RANGE, HIGHLIGHT_OPEN


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    return f"{hours:02}:{minutes:02}:{rest / 1000:06.3f}"


class HighlightProgress(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(30)
        self.setAccessibleName("재생 진행과 하이라이트 위치")
        self.duration = 0
        self.position = 0
        self.highlights = ()
        self.open_start = None

    def paintEvent(self, event):
        painter = QPainter(self)
        left, width = 5, max(1, self.width() - 10)
        painter.fillRect(left, 10, width, 12, QColor(BORDER))
        if self.duration <= 0:
            return

        def x(seconds):
            return left + round(width * max(0, min(1, seconds / self.duration)))

        painter.fillRect(left, 10, x(self.position) - left, 12, QColor(ACCENT))
        for highlight in self.highlights:
            if highlight.end is None:
                painter.fillRect(x(highlight.start) - 2, 5, 4, 22, QColor(HIGHLIGHT_POINT))
            else:
                painter.fillRect(x(highlight.start), 12,
                                 max(2, x(highlight.end) - x(highlight.start)), 8, QColor(HIGHLIGHT_RANGE))
        if self.open_start is not None:
            start, end = sorted((x(self.open_start), x(self.position)))
            painter.fillRect(start, 12, max(2, end - start), 8, QColor(HIGHLIGHT_OPEN))
        painter.setPen(QPen(QColor(TEXT), 2))
        painter.drawLine(x(self.position), 2, x(self.position), 28)


class HighlightEditor(QDialog):
    def __init__(self, core, highlight, duration, parent):
        super().__init__(parent)
        self.core, self.highlight = core, highlight
        self.setWindowTitle("하이라이트 시각·메모 편집")
        self.resize(470, 320)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for field in (self.start, self.end):
            field.setDecimals(3)
            field.setRange(0, time_input_maximum(duration))
            field.setSuffix(" 초")
        self.start.setValue(initial_time_input(highlight.start, duration))
        self.end.setValue(initial_time_input(highlight.end if highlight.end is not None else highlight.start, duration))
        self.initial_start = self.start.value()
        self.initial_end = self.end.value()
        self.range = QCheckBox("구간 하이라이트")
        self.range.setChecked(highlight.end is not None)
        self.end.setEnabled(self.range.isChecked())
        self.range.toggled.connect(self.end.setEnabled)
        form.addRow("시작", self.start)
        form.addRow(self.range)
        form.addRow("끝", self.end)
        self.note = QTextEdit()
        self.note.setPlainText(highlight.note.text if highlight.note else "")
        form.addRow("메모", self.note)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            start = resolve_time_input(self.highlight.start, self.initial_start, self.start.value())
            end = (resolve_time_input(self.highlight.end, self.initial_end, self.end.value())
                   if self.range.isChecked() else None)
            self.core.update_highlight(self.highlight.id, start=start, end=end,
                                       note=self.note.toPlainText())
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "하이라이트 저장 실패", str(error))
            return
        self.accept()


class HighlightList(QDialog):
    def __init__(self, core, video_id, duration, parent):
        super().__init__(parent)
        self.core, self.video_id, self.duration = core, video_id, duration
        self.setWindowTitle("현재 영상의 하이라이트")
        self.resize(660, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("항목을 더블클릭하거나 Enter를 누르면 시각과 메모를 편집합니다."))
        self.list = QListWidget()
        self.list.itemActivated.connect(self.edit)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.edit_button = QPushButton("시각·메모 편집")
        self.delete_button = QPushButton("하이라이트 삭제")
        self.tags_button = QPushButton("태그 편집")
        close = QPushButton("닫기")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button.clicked.connect(self.delete)
        self.tags_button.clicked.connect(self.edit_tags)
        close.clicked.connect(self.accept)
        for button in (self.edit_button, self.tags_button, self.delete_button, close):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        row = self.list.currentRow()
        self.list.clear()
        for highlight in self.core.highlights(self.video_id):
            end = f" – {timestamp(highlight.end)}" if highlight.end is not None else " (지점)"
            note = highlight.note.text if highlight.note else "메모 없음"
            item = QListWidgetItem(f"{timestamp(highlight.start)}{end}\n{note}")
            tags = self.core.highlight_tags(highlight.id)
            if tags:
                item.setText(item.text() + "\n태그: " + ", ".join(tag.name for tag in tags))
            item.setData(Qt.ItemDataRole.UserRole, highlight)
            self.list.addItem(item)
        self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        self.edit_button.setEnabled(self.list.count() > 0)
        self.delete_button.setEnabled(self.list.count() > 0)
        self.tags_button.setEnabled(self.list.count() > 0)

    def edit_tags(self):
        if item := self.list.currentItem():
            TagEditor(self.core, highlight_id=item.data(Qt.ItemDataRole.UserRole).id, parent=self).exec()
            self.refresh()

    def edit(self, *_):
        if item := self.list.currentItem():
            HighlightEditor(self.core, item.data(Qt.ItemDataRole.UserRole), self.duration, self).exec()
            self.refresh()

    def delete(self):
        if item := self.list.currentItem():
            try:
                self.core.delete_highlight(item.data(Qt.ItemDataRole.UserRole).id)
            except (ValueError, OSError, sqlite3.Error) as error:
                QMessageBox.warning(self, "하이라이트 삭제 실패", str(error))
            self.refresh()
