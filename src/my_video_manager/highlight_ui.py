"""하이라이트 표시와 편집. 도메인 변경은 AppCore 공개 API에 맡긴다."""

import sqlite3
from time import monotonic

from PySide6.QtCore import QEvent, QItemSelectionModel, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget, QStyledItemDelegate, QStyle, QSizePolicy,
)

from .highlight_editing import initial_time_input, resolve_time_input, time_input_maximum
from .highlights import nearest_highlight
from .dialog_ui import dialog_buttons, primary_button, space_layout
from .tag_ui import TagEditor
from .theme import PLAYBACK_COLORS, playback_font, playback_pixels


HIGHLIGHT_FOLLOW_IDLE_SECONDS = 3.0


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
        c = PLAYBACK_COLORS
        left, width = 5, max(1, self.width() - 10)
        painter.fillRect(left, 5, width, 4, QColor(c['border']))
        if self.duration <= 0:
            return

        def x(seconds):
            return left + round(width * max(0, min(1, seconds / self.duration)))

        # 위는 진행, 아래는 하이라이트: 짧은 구간도 재생 위치에 가리지 않는다.
        painter.fillRect(left, 5, x(self.position) - left, 4, QColor(c['ring']))
        for highlight in self.highlights:
            if highlight.end is None:
                painter.fillRect(x(highlight.start) - 2, 16, 4, 10, QColor(c['highlight']))
            else:
                painter.fillRect(x(highlight.start), 18,
                                 max(3, x(highlight.end) - x(highlight.start)), 6, QColor(c['status-success']))
        if self.open_start is not None:
            start, end = sorted((x(self.open_start), x(self.position)))
            painter.fillRect(start, 18, max(3, end - start), 6, QColor(c['highlight-open']))
        painter.setPen(QPen(QColor(c['foreground']), 2))
        painter.drawLine(x(self.position), 2, x(self.position), 12)


class _PlaybackHighlightDelegate(QStyledItemDelegate):
    """시각과 한 줄 메모를 고정 높이로 그려 긴 메모도 영상 폭을 밀지 않는다."""

    def sizeHint(self, option, index):
        return QSize(0, playback_pixels('layout', 'spacing') * 18)

    def paint(self, painter, option, index):
        painter.save()
        c = PLAYBACK_COLORS
        nearest = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, QColor(c['secondary'] if selected else c['card']))
        if nearest:
            painter.fillRect(option.rect.left(), option.rect.top() + 8, 3,
                             option.rect.height() - 16, QColor(c['highlight']))
        rect = option.rect.adjusted(12, 8, -12, -8)
        painter.setFont(playback_font('text-xs'))
        painter.setPen(QColor(c['highlight'] if nearest else c['foreground']))
        text = index.data(Qt.ItemDataRole.DisplayRole).split('\n', 1)
        painter.drawText(rect.left(), rect.top() + 16, text[0])
        painter.setFont(playback_font())
        painter.setPen(QColor(c['muted-foreground']))
        note = ' '.join(text[1].split()) if len(text) > 1 else '메모 없음'
        painter.drawText(rect.left(), rect.top() + 40,
                         painter.fontMetrics().elidedText(note, Qt.TextElideMode.ElideRight, rect.width()))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor(c['ring']), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
        painter.restore()


class PlaybackHighlights(QWidget):
    """현재 영상만 표시하는 읽기 전용 목록. 선택과 현재 위치 강조는 별개다."""

    activated = Signal(object)

    def __init__(self, *, clock=monotonic):
        super().__init__()
        self.setObjectName('playbackHighlights')
        self.setFixedWidth(280)
        self._highlights = ()
        self._nearest_id = None
        self._video_id = None
        self._clock = clock
        self._last_interaction = float('-inf')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        self.heading = QLabel('하이라이트 · 0')
        self.heading.setProperty('playbackRole', 'title')
        layout.addWidget(self.heading)
        self.empty = QLabel('아직 하이라이트가 없습니다.\nInsert로 지금 순간을 남겨 보세요.')
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.empty.setProperty('playbackRole', 'muted')
        layout.addWidget(self.empty)
        self.list = QListWidget()
        self.list.setAccessibleName('현재 영상의 하이라이트 시각과 메모')
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setItemDelegate(_PlaybackHighlightDelegate(self.list))
        self.list.itemClicked.connect(self.activate)
        self.list.itemSelectionChanged.connect(self.record_interaction)
        scrollbar = self.list.verticalScrollBar()
        scrollbar.sliderMoved.connect(self.record_interaction)
        scrollbar.sliderPressed.connect(self.record_interaction)
        scrollbar.sliderReleased.connect(self.record_interaction)
        scrollbar.actionTriggered.connect(self.record_interaction)
        for widget in (self.list, self.list.viewport(), scrollbar):
            widget.installEventFilter(self)
        layout.addWidget(self.list, 1)
        self.hint = QLabel('클릭 / Enter로 이동 · 노랑은 가까운 항목')
        self.hint.setWordWrap(True)
        self.hint.setProperty('playbackRole', 'muted')
        layout.addWidget(self.hint)

    def activate(self, item):
        if item is not None:
            self.activated.emit(item.data(Qt.ItemDataRole.UserRole))

    def record_interaction(self, *_):
        self._last_interaction = self._clock()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Wheel, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            self.record_interaction()
        return super().eventFilter(watched, event)

    def show_highlights(self, highlights, position, *, video_id):
        highlights = tuple(highlights)
        video_changed = video_id != self._video_id
        content_changed = video_changed or highlights != self._highlights
        if content_changed:
            selected = self.list.currentItem()
            selected_id = selected.data(Qt.ItemDataRole.UserRole).id if selected and not video_changed else None
            was_selected = selected is not None and selected.isSelected()
            scroll = self.list.verticalScrollBar().value() if not video_changed else 0
            self._video_id = video_id
            self._highlights = highlights
            if video_changed:
                self._last_interaction = float('-inf')
            # 데이터 갱신으로 선택을 복원하는 것은 사용자 조작이 아니다.
            with QSignalBlocker(self.list):
                self.list.clear()
                for highlight in highlights:
                    times = timestamp(highlight.start).split('.')[0]
                    times += (' – ' + timestamp(highlight.end).split('.')[0]
                              if highlight.end is not None else ' · 지점')
                    note = highlight.note.text if highlight.note else '메모 없음'
                    item = QListWidgetItem(times + '\n' + note)
                    item.setToolTip(timestamp(highlight.start) + '\n' + note)
                    item.setData(Qt.ItemDataRole.UserRole, highlight)
                    self.list.addItem(item)
                    if highlight.id == selected_id:
                        self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                                 if was_selected else QItemSelectionModel.SelectionFlag.NoUpdate)
            # 선택 복원 중 계산된 임시 스크롤 범위에 복원값이 잘리지 않게 한다.
            self.list.doItemsLayout()
            self.list.verticalScrollBar().setValue(scroll)
        self.heading.setText(f'하이라이트 · {len(highlights)}')
        self.empty.setVisible(not highlights)
        self.list.setVisible(bool(highlights))
        self.hint.setVisible(bool(highlights))
        nearest = nearest_highlight(highlights, position)
        nearest_id = nearest.id if nearest else None
        nearest_changed = nearest_id != self._nearest_id
        if content_changed or nearest_changed:
            self._nearest_id = nearest_id
            for row in range(self.list.count()):
                item = self.list.item(row)
                active = item.data(Qt.ItemDataRole.UserRole).id == nearest_id
                item.setData(Qt.ItemDataRole.UserRole + 1, active)
                item.setData(Qt.ItemDataRole.AccessibleTextRole,
                             ('현재 위치와 가까움 · ' if active else '') + item.text())
                if (active and nearest_changed and not content_changed and self.isVisible()
                        and not self.list.verticalScrollBar().isSliderDown()
                        and self._clock() - self._last_interaction >= HIGHLIGHT_FOLLOW_IDLE_SECONDS):
                    self.list.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)
            self.list.viewport().update()


class HighlightEditor(QDialog):
    def __init__(self, core, highlight, duration, parent):
        super().__init__(parent)
        self.core, self.highlight = core, highlight
        self.setWindowTitle("하이라이트 시각·메모 편집")
        self.resize(470, 320)
        layout = space_layout(QVBoxLayout(self))
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
        buttons = dialog_buttons(self.save, self.reject, save=True)
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
        layout = space_layout(QVBoxLayout(self))
        layout.addWidget(QLabel("더블클릭 또는 Enter로 시각·메모 편집"))
        self.list = QListWidget()
        self.list.itemActivated.connect(self.edit)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.edit_button = primary_button(QPushButton("시각·메모 편집"))
        self.delete_button = QPushButton("하이라이트 삭제")
        self.tags_button = QPushButton("태그 편집")
        close = QPushButton("닫기")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button.clicked.connect(self.delete)
        self.tags_button.clicked.connect(self.edit_tags)
        close.clicked.connect(self.accept)
        for button in (self.edit_button, self.tags_button, self.delete_button, close):
            if button is close:
                buttons.addStretch()
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
