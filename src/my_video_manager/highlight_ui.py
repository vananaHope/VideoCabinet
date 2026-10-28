"""하이라이트 표시와 편집. 도메인 변경은 AppCore 공개 API에 맡긴다."""

from time import monotonic

from PySide6.QtCore import QEvent, QItemSelectionModel, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
    QStyledItemDelegate, QStyle, QSizePolicy, QToolTip,
)

from .highlights import nearest_highlight
from .theme import PLAYBACK_COLORS, playback_font, playback_pixels
from .time_display import timestamp


HIGHLIGHT_FOLLOW_IDLE_SECONDS = 3.0
PROGRESS_MARGIN = 5


def progress_time(x: float, width: float, duration: float) -> float | None:
    """그려진 막대의 좌표를 영상 시각으로 바꾸고 양 끝에 고정한다."""
    if duration <= 0 or width <= 2 * PROGRESS_MARGIN:
        return None
    fraction = (x - PROGRESS_MARGIN) / (width - 2 * PROGRESS_MARGIN)
    return max(0.0, min(1.0, fraction)) * duration


class HighlightProgress(QWidget):
    seek_requested = Signal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(30)
        self.setAccessibleName("재생 진행과 하이라이트 위치")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QToolTip {{ color: {PLAYBACK_COLORS['foreground']}; "
            f"background-color: {PLAYBACK_COLORS['popover']}; "
            f"border: 1px solid {PLAYBACK_COLORS['border']}; }}"
        )
        self.duration = 0
        self.position = 0
        self.highlights = ()
        self.open_start = None
        self._drag_position = None
        self._press_position = None
        self._drag_moved = False

    @property
    def dragging(self):
        return self._drag_position is not None

    @property
    def displayed_position(self):
        return self._drag_position if self.dragging else self.position

    def cancel_drag(self):
        self._drag_position = self._press_position = None
        self._drag_moved = False
        QToolTip.hideText()
        self.update()

    def hideEvent(self, event):
        self.cancel_drag()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        target = progress_time(event.position().x(), self.width(), self.duration)
        if event.button() != Qt.MouseButton.LeftButton or target is None:
            event.ignore()
            return
        # Qt는 누른 위젯에 마우스를 잡아 두므로 막대 밖 release도 전달된다.
        self._drag_position = self._press_position = target
        self.update()
        self.seek_requested.emit(target)
        event.accept()

    def mouseMoveEvent(self, event):
        target = progress_time(event.position().x(), self.width(), self.duration)
        if target is None:
            self.cancel_drag()
            return
        QToolTip.showText(event.globalPosition().toPoint(), timestamp(target), self)
        if self.dragging:
            # 드래그 중에는 미리보기만 갱신한다. 엔진 탐색은 놓을 때 한 번 한다.
            self._drag_position = target
            self._drag_moved = self._drag_moved or target != self._press_position
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.dragging:
            event.ignore()
            return
        target = progress_time(event.position().x(), self.width(), self.duration)
        start = self._press_position
        moved = self._drag_moved
        self.cancel_drag()
        if target is not None and (moved or target != start):
            self.seek_requested.emit(target)
        event.accept()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        c = PLAYBACK_COLORS
        left, width = PROGRESS_MARGIN, max(1, self.width() - 2 * PROGRESS_MARGIN)
        painter.fillRect(left, 5, width, 4, QColor(c['border']))
        if self.duration <= 0:
            return

        def x(seconds):
            return left + round(width * max(0, min(1, seconds / self.duration)))

        # 위는 진행, 아래는 하이라이트: 짧은 구간도 재생 위치에 가리지 않는다.
        position = self.displayed_position
        painter.fillRect(left, 5, x(position) - left, 4, QColor(c['ring']))
        for highlight in self.highlights:
            if highlight.end is None:
                painter.fillRect(x(highlight.start) - 2, 16, 4, 10, QColor(c['highlight']))
            else:
                painter.fillRect(x(highlight.start), 18,
                                 max(3, x(highlight.end) - x(highlight.start)), 6, QColor(c['highlight-range']))
        if self.open_start is not None:
            start, end = sorted((x(self.open_start), x(position)))
            painter.fillRect(start, 18, max(3, end - start), 6, QColor(c['highlight-open']))
        painter.setPen(QPen(QColor(c['foreground']), 2))
        painter.drawLine(x(position), 2, x(position), 12)


class _PlaybackHighlightDelegate(QStyledItemDelegate):
    """시각과 한 줄 메모를 고정 높이로 그려 긴 메모도 영상 폭을 밀지 않는다."""

    def sizeHint(self, option, index):
        return QSize(0, playback_pixels('layout', 'spacing') * 18)

    def paint(self, painter, option, index):
        painter.save()
        c = PLAYBACK_COLORS
        nearest = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, QColor(c['accent'] if selected else c['card']))
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

    def follow_nearest(self):
        if (not self.isVisible() or self.list.verticalScrollBar().isSliderDown()
                or self._clock() - self._last_interaction < HIGHLIGHT_FOLLOW_IDLE_SECONDS):
            return
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole).id == self._nearest_id:
                self.list.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)
                break

    def showEvent(self, event):
        super().showEvent(event)
        self.list.doItemsLayout()
        self.follow_nearest()

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
            self.list.viewport().update()
            if video_changed or (nearest_changed and not content_changed):
                self.follow_nearest()
