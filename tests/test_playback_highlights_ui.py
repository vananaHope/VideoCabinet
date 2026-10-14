"""재생 하이라이트 패널의 스크롤·선택·따라가기 공개 동작."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractSlider

from my_video_manager.highlights import Highlight
from my_video_manager.highlight_ui import PlaybackHighlights, HIGHLIGHT_FOLLOW_IDLE_SECONDS


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    widget = PlaybackHighlights(clock=clock)
    widget.resize(280, 400)
    widget.show()
    highlights = tuple(Highlight(i + 1, 1, i, None, None) for i in range(60))
    widget.show_highlights(highlights, 0, video_id=1)
    app.processEvents()
    yield widget, clock, highlights
    widget.close()
    widget.deleteLater()
    app.processEvents()


def visible(widget, row):
    return widget.list.viewport().rect().contains(widget.list.visualItemRect(widget.list.item(row)))


def test_idle_panel_follows_nearest_without_selecting_it(panel):
    widget, clock, highlights = panel
    current = widget.list.currentItem()
    selected = widget.list.selectedItems()
    assert not visible(widget, 40)
    widget.show_highlights(highlights, 40, video_id=1)
    assert visible(widget, 40)
    assert widget.list.currentItem() is current
    assert widget.list.selectedItems() == selected
    # 따라가기의 스크롤 자체를 사용자 조작으로 오인하면 연속 이동이 멈춘다.
    widget.show_highlights(highlights, 10, video_id=1)
    assert visible(widget, 10)


@pytest.mark.parametrize('interaction', ['selection', 'wheel', 'scrollbar'])
def test_recent_interaction_delays_follow_until_next_nearest_change(panel, interaction):
    widget, clock, highlights = panel
    if interaction == 'selection':
        widget.list.setCurrentRow(0)
        QTest.keyClick(widget.list, Qt.Key.Key_Down)
    elif interaction == 'wheel':
        pos = widget.list.viewport().rect().center()
        event = QWheelEvent(QPointF(pos), QPointF(widget.list.viewport().mapToGlobal(pos)),
                            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget.list.viewport(), event)
    else:
        widget.list.verticalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd)
    selected = widget.list.currentItem()
    scroll = widget.list.verticalScrollBar().value()
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS - 0.01
    widget.show_highlights(highlights, 40, video_id=1)
    assert widget.list.verticalScrollBar().value() == scroll
    assert not visible(widget, 40)
    clock.now += 0.01
    widget.show_highlights(highlights, 41, video_id=1)
    assert visible(widget, 41)
    assert widget.list.currentItem() is selected


def test_dragging_scrollbar_suppresses_follow_until_after_release(panel):
    widget, clock, highlights = panel
    scrollbar = widget.list.verticalScrollBar()
    scrollbar.setSliderDown(True)
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS * 2
    widget.show_highlights(highlights, 40, video_id=1)
    assert scrollbar.value() == 0
    scrollbar.setSliderDown(False)
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS - 0.01
    widget.show_highlights(highlights, 41, video_id=1)
    assert scrollbar.value() == 0
    clock.now += 0.01
    widget.show_highlights(highlights, 42, video_id=1)
    assert visible(widget, 42)


def test_same_video_add_delete_preserves_scroll_and_surviving_selection(panel):
    widget, clock, highlights = panel
    widget.list.setCurrentRow(40)
    widget.list.scrollToBottom()
    scroll = widget.list.verticalScrollBar().value()
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS
    added = (*highlights, Highlight(100, 1, 61, None, None))
    widget.show_highlights(added, 61, video_id=1)
    assert widget.list.verticalScrollBar().value() == scroll
    assert widget.list.currentItem().data(Qt.ItemDataRole.UserRole).id == 41
    widget.show_highlights(highlights, 0, video_id=1)
    assert widget.list.verticalScrollBar().value() == scroll
    assert widget.list.currentItem().data(Qt.ItemDataRole.UserRole).id == 41
    without_selected = tuple(h for h in highlights if h.id != 41)
    widget.show_highlights(without_selected, 0, video_id=1)
    assert widget.list.currentItem() is None
    assert widget.list.verticalScrollBar().value() == min(scroll, widget.list.verticalScrollBar().maximum())


def test_video_change_resets_even_when_new_nearest_is_at_end(panel):
    widget, clock, highlights = panel
    widget.list.setCurrentRow(40)
    widget.list.scrollToBottom()
    other = tuple(Highlight(h.id + 100, 2, h.start, None, None) for h in highlights)
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS
    widget.show_highlights(other, 59, video_id=2)
    QApplication.processEvents()
    assert widget.list.verticalScrollBar().value() == 0
    assert widget.list.currentItem() is None
    # 이전 영상의 사용자 조작은 새 영상의 이후 따라가기를 막지 않는다.
    widget.show_highlights(other, 58, video_id=2)
    assert visible(widget, 58)


def test_data_refresh_does_not_select_focused_row_or_delay_follow(panel):
    widget, clock, highlights = panel
    widget.list.setCurrentRow(1)
    widget.list.clearSelection()
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS
    added = (*highlights, Highlight(100, 1, 61, None, None))
    widget.show_highlights(added, 0, video_id=1)
    assert widget.list.currentRow() == 1
    assert widget.list.selectedItems() == []
    widget.show_highlights(added, 40, video_id=1)
    assert visible(widget, 40)
    assert widget.list.selectedItems() == []


def test_each_user_scroll_restarts_follow_cooldown(panel):
    widget, clock, highlights = panel
    scrollbar = widget.list.verticalScrollBar()
    scrollbar.triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd)
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS - 0.01
    scrollbar.triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd)
    scroll = scrollbar.value()
    clock.now += 0.02
    widget.show_highlights(highlights, 50, video_id=1)
    assert scrollbar.value() == scroll
    clock.now += HIGHLIGHT_FOLLOW_IDLE_SECONDS
    widget.show_highlights(highlights, 51, video_id=1)
    assert visible(widget, 51)
