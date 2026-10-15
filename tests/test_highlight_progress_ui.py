"""진행 막대의 좌표 경계와 마우스 입력 계약."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolTip

from my_video_manager.highlight_ui import HighlightProgress, progress_time
from my_video_manager.time_display import timestamp


@pytest.mark.parametrize('x,width,duration,expected', [
    (5, 110, 120, 0), (55, 110, 120, 60), (105, 110, 120, 120),
    (-100, 110, 120, 0), (500, 110, 120, 120), (5, 110, 0, None),
    (5, 110, -1, None), (5, 10, 120, None), (5, 0, 120, None),
])
def test_progress_time(x, width, duration, expected):
    assert progress_time(x, width, duration) == expected


@pytest.fixture
def progress(qapp):
    widget = HighlightProgress()
    widget.resize(110, 30)
    widget.duration = 120
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def test_drag_previews_without_repeated_seeks_and_release_clamps(progress, qapp):
    seeks = []
    progress.seek_requested.connect(seeks.append)
    QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=QPoint(30, 7))
    assert seeks == [30]
    for x in (40, 55, 75, 90, 150):
        QTest.mouseMove(progress, QPoint(x, 7))
    progress.position = 31  # 재생 위치 보고가 와도 드래그 미리보기를 덮지 않는다.
    assert progress.displayed_position == 120
    assert seeks == [30]
    QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=QPoint(-10, 7))
    assert seeks == [30, 0]
    assert not progress.dragging


def test_hover_and_click_and_unknown_duration(progress):
    seeks = []
    progress.seek_requested.connect(seeks.append)
    QTest.mouseMove(progress, QPoint(55, 7))
    assert QToolTip.text() == timestamp(60)
    QTest.mouseClick(progress, Qt.MouseButton.LeftButton, pos=QPoint(55, 7))
    assert seeks == [60]
    progress.duration = 0
    QTest.mouseClick(progress, Qt.MouseButton.LeftButton, pos=QPoint(55, 7))
    assert seeks == [60]
    assert not progress.dragging
    progress.duration = 120
    QTest.mouseClick(progress, Qt.MouseButton.RightButton, pos=QPoint(55, 7))
    assert seeks == [60]


def test_hidden_progress_cancels_drag(progress):
    seeks = []
    progress.seek_requested.connect(seeks.append)
    QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=QPoint(30, 7))
    progress.hide()
    progress.show()
    QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=QPoint(55, 7))
    assert seeks == [30]
    assert not progress.dragging
