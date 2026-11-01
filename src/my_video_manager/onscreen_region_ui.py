"""재생 화면에서 화면 자막 영역 정하기: 일시정지한 장면 위에서 사각형을 끈다.

영상은 mpv의 네이티브 창에 그려지므로, 이 덮개도 네이티브 창으로 만들어 그 위에 올린다.
덮개는 멈춘 장면(영상 프레임)을 직접 그리고, 끈 사각형을 그 프레임 기준 비율로 바꾼다.
"""

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .onscreen_subtitles import MIN_REGION_SIZE, RegionRect
from .theme import PLAYBACK_COLORS, playback_font


DRAW_HINT = "영상 위를 끌어 화면 자막 영역을 정하세요 · Esc 취소"
SMALL_HINT = "영역이 너무 작습니다. 글자가 들어가게 다시 끌어 주세요 · Esc 취소"
CHOSEN_HINT = "읽을 언어를 고른 뒤 확인하세요"


def frame_image(frame) -> QImage | None:
    """재생 어댑터가 준 bgr0 장면을 그릴 수 있는 이미지로. 장면이 없으면 None."""
    if frame is None:
        return None
    return QImage(frame.data, frame.width, frame.height, frame.stride, QImage.Format.Format_RGB32).copy()


class RegionSelector(QWidget):
    selected = Signal(object)  # RegionRect
    cancelled = Signal()

    def __init__(self, surface: QWidget, image: QImage | None, aspect: float):
        super().__init__(surface)
        # mpv가 그리는 네이티브 자식 창 위에 보이려면 이 덮개도 네이티브 창이어야 한다.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("화면 자막 영역 정하기")
        self.setFont(playback_font())
        self.image = image
        self.aspect = image.width() / image.height() if image is not None and image.height() else aspect
        self._anchor = self._current = None  # 프레임 기준 비율 좌표
        self.selection: RegionRect | None = None
        self.hint = DRAW_HINT
        surface.installEventFilter(self)
        self.setGeometry(surface.rect())

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            # 창 크기·전체 화면이 바뀌어도 고른 영역은 비율이라 같은 자리를 가리킨다.
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def video_rect(self) -> QRectF:
        """덮개 안에서 영상 프레임이 놓인 자리(가운데 맞춤, 화면비 유지)."""
        width, height = self.width(), self.height()
        if width / max(1, height) > self.aspect:
            shown = height * self.aspect
            return QRectF((width - shown) / 2, 0, shown, height)
        shown = width / self.aspect
        return QRectF(0, (height - shown) / 2, width, shown)

    def _ratio(self, position) -> QPointF:
        frame = self.video_rect()
        return QPointF(min(1.0, max(0.0, (position.x() - frame.x()) / frame.width())),
                       min(1.0, max(0.0, (position.y() - frame.y()) / frame.height())))

    def _drawn(self) -> tuple[float, float, float, float] | None:
        if self.selection is not None:
            rect = self.selection
            return rect.x, rect.y, rect.width, rect.height
        if self._anchor is None or self._current is None:
            return None
        left, right = sorted((self._anchor.x(), self._current.x()))
        top, bottom = sorted((self._anchor.y(), self._current.y()))
        return left, top, right - left, bottom - top

    def mousePressEvent(self, event):
        event.accept()
        if event.button() != Qt.MouseButton.LeftButton or self.selection is not None:
            return
        self._anchor = self._current = self._ratio(event.position())
        self.hint = DRAW_HINT
        self.update()

    def mouseMoveEvent(self, event):
        event.accept()
        if self._anchor is not None and self.selection is None and event.buttons() & Qt.MouseButton.LeftButton:
            self._current = self._ratio(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        event.accept()
        if event.button() != Qt.MouseButton.LeftButton or self._anchor is None or self.selection is not None:
            return
        self._current = self._ratio(event.position())
        x, y, width, height = self._drawn()
        self._anchor = self._current = None
        if width < MIN_REGION_SIZE or height < MIN_REGION_SIZE:
            self.hint = SMALL_HINT
            self.update()
            return
        self.selection = RegionRect(round(x, 6), round(y, 6), round(width, 6), round(height, 6))
        self.hint = CHOSEN_HINT
        self.update()
        self.selected.emit(self.selection)

    def mouseDoubleClickEvent(self, event):
        event.accept()  # 영상의 두 번 클릭(전체 화면)으로 넘기지 않는다.

    def handle_key(self, event) -> bool:
        """재생 화면의 키 처리 대신 받는다. Esc는 취소이고 재생 키는 영역을 정하는 동안 쓰지 않는다."""
        if event.key() == Qt.Key.Key_Escape and not event.isAutoRepeat():
            self.cancelled.emit()
        return True

    def paintEvent(self, event):
        c = PLAYBACK_COLORS
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        frame = self.video_rect()
        if self.image is not None:
            painter.drawImage(frame, self.image)
        drawn = self._drawn()
        shade = QColor("black")
        shade.setAlphaF(0.45)
        if drawn is None:
            painter.fillRect(frame, shade)
        else:
            x, y, width, height = drawn
            chosen = QRectF(frame.x() + x * frame.width(), frame.y() + y * frame.height(),
                            width * frame.width(), height * frame.height())
            # 고른 자리만 밝게 두고 나머지는 어둡게 덮는다.
            for part in (QRectF(frame.left(), frame.top(), frame.width(), chosen.top() - frame.top()),
                         QRectF(frame.left(), chosen.bottom(), frame.width(), frame.bottom() - chosen.bottom()),
                         QRectF(frame.left(), chosen.top(), chosen.left() - frame.left(), chosen.height()),
                         QRectF(chosen.right(), chosen.top(), frame.right() - chosen.right(), chosen.height())):
                painter.fillRect(part, shade)
            painter.setPen(QPen(QColor(c['primary']), 2))
            painter.drawRect(chosen)
        metrics = painter.fontMetrics()
        band = QRectF(0, 0, self.width(), metrics.height() + 16)
        backdrop = QColor(c['popover'])
        backdrop.setAlphaF(0.85)  # 위쪽 영역을 고를 때도 아래 장면이 비쳐 보인다.
        painter.fillRect(band, backdrop)
        painter.setPen(QColor(c['popover-foreground']))
        painter.drawText(band, Qt.AlignmentFlag.AlignCenter, self.hint)
        painter.end()
