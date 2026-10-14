"""화면에 보이는 카드만 그리는 라이브러리 모델·격자·공유 카드 delegate."""

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from . import theme

CARD_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def duration_text(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def viewing_text(status):
    label = "다 봄" if status.finished else "보다 만" if status.abandoned else "아직 안 봄"
    return label + (" · 즐겨 보는 영상" if status.favorite else "")


@dataclass(frozen=True)
class VideoCard:
    video: object
    status: object
    tags: tuple = ()
    series: str = ""
    reason: str = ""

    @property
    def description(self):
        return "\n".join(filter(None, (self.video.title, duration_text(self.video.duration),
            viewing_text(self.status), "파일 없음" if self.video.missing else "", self.series,
            ", ".join(tag.name for tag in self.tags), self.reason)))


class LibraryModel(QAbstractListModel):
    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.icons = icons
        self.cards = ()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cards)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.cards):
            return None
        card = self.cards[index.row()]
        if role == CARD_ROLE:
            return card
        if role == Qt.ItemDataRole.UserRole:
            return card.video.id
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.AccessibleTextRole):
            return card.description
        if role == Qt.ItemDataRole.DecorationRole:
            return self.icons.get(card.video.thumbnail)

    def replace(self, cards):
        self.beginResetModel()
        self.cards = tuple(cards)
        self.endResetModel()


class VideoCardDelegate(QStyledItemDelegate):
    def __init__(self, icons, parent=None, *, compact=False):
        super().__init__(parent)
        self.icons, self.compact = icons, compact
        self.card_size = QSize(192, 204) if compact else QSize(216, 260)

    def sizeHint(self, option, index):
        return self.card_size

    def paint(self, painter, option, index):
        card = index.data(CARD_ROLE)
        if card is None:
            return
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect.adjusted(4, 4, -4, -4)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active = option.widget is not None and option.widget.hasFocus()
        color = (theme.ACCENT_TINT if active else theme.INACTIVE_SELECTION) if selected else theme.SURFACE
        painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor(theme.ACCENT if focused else theme.BORDER), 2 if focused else 1))
        painter.drawRoundedRect(rect, 6, 6)
        inner = rect.adjusted(8, 8, -8, -8)
        thumb_height = 88 if self.compact else 108
        thumb = QRect(inner.x(), inner.y(), inner.width(), thumb_height)
        painter.fillRect(thumb, QColor(theme.BACKGROUND))
        if card.video.missing:
            painter.setOpacity(0.45)
        icon = self.icons.get(card.video.thumbnail)
        if icon.isNull():
            painter.setPen(QColor(theme.MUTED_TEXT))
            painter.drawText(thumb, Qt.AlignmentFlag.AlignCenter, "썸네일 없음")
        else:
            icon.paint(painter, thumb, Qt.AlignmentFlag.AlignCenter)
        painter.setOpacity(1)
        if card.status.abandoned:
            progress = QRect(thumb.x(), thumb.bottom() + 1, thumb.width(), 4)
            painter.fillRect(progress, QColor(theme.BORDER))
            progress.setWidth(int(progress.width() * max(0, min(100, card.status.stopped_percent or 0)) / 100))
            painter.fillRect(progress, QColor(theme.PROGRESS_PLAYED))
        painter.setFont(option.font)
        painter.setPen(QColor(theme.MUTED_TEXT if card.video.missing else theme.TEXT))
        y = thumb.bottom() + 9
        y = self.draw_title(painter, card.video.title, option.font, inner.x(), y, inner.width())
        painter.setPen(QColor(theme.MUTED_TEXT))
        status = "파일 없음" if card.video.missing else viewing_text(card.status)
        text = f"{duration_text(card.video.duration)} · {status}"
        metrics = painter.fontMetrics()
        painter.drawText(QRect(inner.x(), y, inner.width(), 22), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(text, Qt.TextElideMode.ElideRight, inner.width()))
        y += 22
        if self.compact:
            painter.drawText(QRect(inner.x(), y, inner.width(), 22), Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(card.reason, Qt.TextElideMode.ElideRight, inner.width()))
        else:
            if card.series:
                painter.drawText(QRect(inner.x(), y, inner.width(), 22), Qt.AlignmentFlag.AlignVCenter,
                                 metrics.elidedText(card.series, Qt.TextElideMode.ElideRight, inner.width()))
            self.draw_tags(painter, card.tags, inner.x(), y + 24, inner.width())
        painter.restore()

    @staticmethod
    def draw_title(painter, text, font, x, y, width):
        layout = QTextLayout(text.replace("\n", " "), font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        first = layout.createLine()
        first.setLineWidth(width)
        second = layout.createLine()
        if second.isValid():
            second.setLineWidth(width)
        layout.endLayout()
        first.draw(painter, QPointF(x, y))
        height = painter.fontMetrics().height()
        if second.isValid():
            remaining = text.replace("\n", " ")[second.textStart():]
            painter.drawText(x, y + height + painter.fontMetrics().ascent(),
                             painter.fontMetrics().elidedText(remaining, Qt.TextElideMode.ElideRight, width))
        return y + height * 2

    @staticmethod
    def draw_tags(painter, tags, x, y, width):
        shown = tags[:2]
        metrics = painter.fontMetrics()
        for tag in shown:
            available = max(24, (width - 42) // 2)
            text = metrics.elidedText(tag.name, Qt.TextElideMode.ElideRight, available - 10)
            size = metrics.horizontalAdvance(text) + 10
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.INACTIVE_SELECTION))
            painter.drawRoundedRect(QRect(x, y, size, 22), 4, 4)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRect(x, y, size, 22), Qt.AlignmentFlag.AlignCenter, text)
            x += size + 4
        if len(tags) > len(shown):
            painter.drawText(QRect(x, y, 36, 22), Qt.AlignmentFlag.AlignVCenter, f"+{len(tags) - len(shown)}")


class LibraryGrid(QListView):
    menu_requested = Signal(object)

    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.setAccessibleName("라이브러리 영상 격자")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(VideoCardDelegate(icons, self))
        self.setModel(LibraryModel(icons, self))

    def contextMenuEvent(self, event):
        from PySide6.QtGui import QContextMenuEvent
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            index = self.currentIndex()
        else:
            index = self.indexAt(event.pos())
        if index.isValid():
            self.setCurrentIndex(index)
            self.menu_requested.emit(self.viewport().mapToGlobal(self.visualRect(index).center()))
        event.accept()
