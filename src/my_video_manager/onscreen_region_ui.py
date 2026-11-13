"""재생 화면에서 화면 자막 영역 정하기: 일시정지한 장면 위에서 영역을 새로 끌거나, 이미 정한 영역을 골라 고친다.

영상은 mpv의 네이티브 창에 그려지므로, 이 덮개도 네이티브 창으로 만들어 그 위에 올린다.
덮개는 멈춘 장면(영상 프레임)을 직접 그리고, 끈 사각형을 그 프레임 기준 비율로 바꾼다.
한 번 열면 동작 하나(새 영역, 영역 하나 고치기, 영역 하나 지우기)만 고르고, 확인은 이어 여는 대화상자가 받는다.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .onscreen_subtitles import MIN_REGION_SIZE, OnScreenSubtitleRegion, RegionRect, onscreen_language_name
from .theme import PLAYBACK_COLORS, playback_font


DRAW_HINT = "영상 위를 끌어 화면 자막 영역을 정하세요 · Esc 취소"
REGIONS_HINT = "빈 곳을 끌어 새 영역 · 정한 영역을 눌러 고르기 · Esc 취소"
PICKED_HINT = "끌어 옮기기 · 모서리를 끌어 크기 바꾸기 · Enter 읽을 언어 · Delete 지우기 · Esc 취소"
SMALL_HINT = "영역이 너무 작습니다. 글자가 들어가게 다시 끌어 주세요 · Esc 취소"
CHOSEN_HINT = "읽을 언어를 고른 뒤 확인하세요"
DELETE_HINT = "영역을 지울지 확인하세요"
# 모서리 손잡이의 한 변(px). 고른 영역의 네 모서리에 그리고, 이 안을 누르면 크기 바꾸기다.
HANDLE = 10


def frame_image(frame) -> QImage | None:
    """재생 어댑터가 준 bgr0 장면을 그릴 수 있는 이미지로. 장면이 없으면 None."""
    if frame is None:
        return None
    return QImage(frame.data, frame.width, frame.height, frame.stride, QImage.Format.Format_RGB32).copy()


@dataclass(frozen=True)
class _Drawing:
    """빈 곳에서 새 영역을 끄는 중. 좌표는 프레임 기준 비율이다."""
    anchor: QPointF
    current: QPointF


@dataclass(frozen=True)
class _Picked:
    """정한 영역 하나를 고른 상태. 끄는 중이면 press(누른 화면 좌표)와 corner(크기 바꿀 모서리, 옮기기면 None)가 있다."""
    region: OnScreenSubtitleRegion
    rect: RegionRect
    press: QPointF | None = None
    corner: tuple[int, int] | None = None


def _bounds(rect: RegionRect) -> tuple[float, float, float, float]:
    return rect.x, rect.y, rect.x + rect.width, rect.y + rect.height


def _rect(left, top, right, bottom) -> RegionRect | None:
    """비율 좌표 사각형. 너무 작으면 None."""
    if right - left < MIN_REGION_SIZE or bottom - top < MIN_REGION_SIZE:
        return None
    return RegionRect(round(left, 6), round(top, 6), round(right - left, 6), round(bottom - top, 6))


class RegionSelector(QWidget):
    selected = Signal(object)  # 새 영역 RegionRect
    changed = Signal(object, object)  # (고친 OnScreenSubtitleRegion, 새 RegionRect). 언어만 바꾸면 rect는 그대로다.
    delete_requested = Signal(object)  # 지울 OnScreenSubtitleRegion
    cancelled = Signal()

    def __init__(self, surface: QWidget, image: QImage | None, aspect: float,
                 regions: tuple[OnScreenSubtitleRegion, ...] = ()):
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
        self.regions = tuple(regions)
        # 지금 하는 일: None(아무것도 고르지 않음) · _Drawing · _Picked. 동작을 내보내면 done이 되어 입력을 받지 않는다.
        self.state: _Drawing | _Picked | None = None
        self.done = False
        self.selection: RegionRect | None = None  # 새로 끈 영역(내보낸 뒤)
        self.hint = REGIONS_HINT if self.regions else DRAW_HINT
        surface.installEventFilter(self)
        self.setGeometry(surface.rect())

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            # 창 크기·전체 화면이 바뀌어도 고른 영역은 비율이라 같은 자리를 가리킨다.
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    @property
    def picked(self) -> OnScreenSubtitleRegion | None:
        return self.state.region if isinstance(self.state, _Picked) else None

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

    def screen_rect(self, rect: RegionRect) -> QRectF:
        frame = self.video_rect()
        return QRectF(frame.x() + rect.x * frame.width(), frame.y() + rect.y * frame.height(),
                      rect.width * frame.width(), rect.height * frame.height())

    def _corner_at(self, rect: RegionRect, position) -> tuple[int, int] | None:
        """누른 자리가 모서리 손잡이면 (가로 끝, 세로 끝): 0은 왼쪽·위, 1은 오른쪽·아래."""
        shown = self.screen_rect(rect)
        for horizontal, x in ((0, shown.left()), (1, shown.right())):
            for vertical, y in ((0, shown.top()), (1, shown.bottom())):
                if abs(position.x() - x) <= HANDLE and abs(position.y() - y) <= HANDLE:
                    return horizontal, vertical
        return None

    def _active(self) -> tuple[float, float, float, float] | None:
        """밝게 보일 사각형 (x, y, 가로, 세로): 새로 끄는 영역, 고른 영역(옮기는 중이면 옮긴 자리)."""
        rect = self.selection or (self.state.rect if isinstance(self.state, _Picked) else None)
        if rect is not None:
            return rect.x, rect.y, rect.width, rect.height
        if isinstance(self.state, _Drawing):
            left, right = sorted((self.state.anchor.x(), self.state.current.x()))
            top, bottom = sorted((self.state.anchor.y(), self.state.current.y()))
            return left, top, right - left, bottom - top
        return None

    def _dragged(self, position) -> RegionRect | None:
        """고른 영역을 지금 마우스 자리까지 옮기거나 크기를 바꾼 사각형. 너무 작아지면 None."""
        picked = self.state
        left, top, right, bottom = _bounds(picked.region.rect)
        start, now = self._ratio(picked.press), self._ratio(position)
        if picked.corner is None:
            # 옮기기: 크기는 그대로, 프레임 밖으로 나가지 않는다.
            width, height = right - left, bottom - top
            x = min(1 - width, max(0.0, left + now.x() - start.x()))
            y = min(1 - height, max(0.0, top + now.y() - start.y()))
            return RegionRect(round(x, 6), round(y, 6), round(width, 6), round(height, 6))
        horizontal, vertical = picked.corner
        # 잡은 모서리의 맞은편 모서리는 그 자리에 둔다.
        fixed_x, fixed_y = left if horizontal else right, top if vertical else bottom
        x1, x2 = sorted((fixed_x, now.x()))
        y1, y2 = sorted((fixed_y, now.y()))
        return _rect(x1, y1, x2, y2)

    def mousePressEvent(self, event):
        event.accept()
        if event.button() != Qt.MouseButton.LeftButton or self.done:
            return
        position = event.position()
        picked = self.picked
        if picked is not None and (corner := self._corner_at(picked.rect, position)) is not None:
            self.state = _Picked(picked, picked.rect, position, corner)
        else:
            # 겹치면 고른 영역, 그다음 나중에 정한 영역(위에 그린 것)을 고른다.
            hit = next((region for region in ((picked,) if picked else ()) + tuple(reversed(self.regions))
                        if self.screen_rect(region.rect).contains(position)), None)
            if hit is not None:
                self.state = _Picked(hit, hit.rect, position)
                self.hint = PICKED_HINT
            else:
                ratio = self._ratio(position)
                self.state = _Drawing(ratio, ratio)
                self.hint = DRAW_HINT
        self.update()

    def mouseMoveEvent(self, event):
        event.accept()
        if self.done or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if isinstance(self.state, _Drawing):
            self.state = _Drawing(self.state.anchor, self._ratio(event.position()))
        elif isinstance(self.state, _Picked) and self.state.press is not None:
            rect = self._dragged(event.position())
            if rect is not None:
                self.state = _Picked(self.state.region, rect, self.state.press, self.state.corner)
        self.update()

    def mouseReleaseEvent(self, event):
        event.accept()
        if event.button() != Qt.MouseButton.LeftButton or self.done:
            return
        if isinstance(self.state, _Drawing):
            self.state = _Drawing(self.state.anchor, self._ratio(event.position()))
            left, top, width, height = self._active()
            rect = _rect(left, top, left + width, top + height)
            if rect is None:
                self.state, self.hint = None, SMALL_HINT
                self.update()
                return
            self.selection, self.done, self.hint = rect, True, CHOSEN_HINT
            self.update()
            self.selected.emit(rect)
        elif isinstance(self.state, _Picked) and self.state.press is not None:
            picked, travel = self.state, event.position() - self.state.press
            moved = abs(travel.x()) + abs(travel.y()) >= QApplication.startDragDistance()
            rect = self._dragged(event.position()) if moved else None
            if rect is None or rect == picked.region.rect:
                # 누르기만 했거나 너무 작게 줄였으면 고른 채로 둔다. 작은 끌기는 영역을 바꾸지 않는다.
                self.state = _Picked(picked.region, picked.region.rect)
                self.hint = SMALL_HINT if moved and rect is None else PICKED_HINT
                self.update()
                return
            self._change(picked.region, rect)

    def _change(self, region, rect):
        self.state, self.done, self.hint = _Picked(region, rect), True, CHOSEN_HINT
        self.update()
        self.changed.emit(region, rect)

    def mouseDoubleClickEvent(self, event):
        event.accept()  # 영상의 두 번 클릭(전체 화면)으로 넘기지 않는다.

    def handle_key(self, event) -> bool:
        """재생 화면의 키 처리 대신 받는다. Esc는 취소, 고른 영역의 Enter는 읽을 언어 바꾸기, Delete는 지우기다.
        재생 키는 영역을 정하는 동안 쓰지 않는다."""
        if event.isAutoRepeat():
            return True
        key, picked = event.key(), self.picked
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif self.done or picked is None or self.state.press is not None:
            pass
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._change(picked, picked.rect)
        elif key == Qt.Key.Key_Delete:
            self.done, self.hint = True, DELETE_HINT
            self.update()
            self.delete_requested.emit(picked)
        return True

    def paintEvent(self, event):
        c = PLAYBACK_COLORS
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        frame = self.video_rect()
        if self.image is not None:
            painter.drawImage(frame, self.image)
        active = self._active()
        shade = QColor("black")
        shade.setAlphaF(0.45)
        if active is None:
            painter.fillRect(frame, shade)
            chosen = None
        else:
            x, y, width, height = active
            chosen = QRectF(frame.x() + x * frame.width(), frame.y() + y * frame.height(),
                            width * frame.width(), height * frame.height())
            # 고른 자리만 밝게 두고 나머지는 어둡게 덮는다.
            for part in (QRectF(frame.left(), frame.top(), frame.width(), chosen.top() - frame.top()),
                         QRectF(frame.left(), chosen.bottom(), frame.width(), frame.bottom() - chosen.bottom()),
                         QRectF(frame.left(), chosen.top(), chosen.left() - frame.left(), chosen.height()),
                         QRectF(chosen.right(), chosen.top(), frame.right() - chosen.right(), chosen.height())):
                painter.fillRect(part, shade)
        # 이미 정한 영역은 점선과 읽을 언어로 보인다. 고른 영역은 밝은 테두리와 모서리 손잡이로 대신 그린다.
        metrics = painter.fontMetrics()
        for region in self.regions:
            if region == self.picked:
                continue
            shown = self.screen_rect(region.rect)
            painter.setPen(QPen(QColor(c['popover-foreground']), 1, Qt.PenStyle.DashLine))
            painter.drawRect(shown)
            painter.drawText(shown.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             onscreen_language_name(region.language))
        if chosen is not None:
            painter.setPen(QPen(QColor(c['primary']), 2))
            painter.drawRect(chosen)
            if isinstance(self.state, _Picked) and not self.done:
                for point in (chosen.topLeft(), chosen.topRight(), chosen.bottomLeft(), chosen.bottomRight()):
                    painter.fillRect(QRectF(point.x() - HANDLE / 2, point.y() - HANDLE / 2, HANDLE, HANDLE),
                                     QColor(c['primary']))
        band = QRectF(0, 0, self.width(), metrics.height() + 16)
        backdrop = QColor(c['popover'])
        backdrop.setAlphaF(0.85)  # 위쪽 영역을 고를 때도 아래 장면이 비쳐 보인다.
        painter.fillRect(band, backdrop)
        painter.setPen(QColor(c['popover-foreground']))
        painter.drawText(band, Qt.AlignmentFlag.AlignCenter, self.hint)
        painter.end()
