"""영상 클릭 판정. 한 번 클릭은 두 번 클릭 판정 시간이 지나야 확정한다.

Qt와 mpv에 묶이지 않도록 시계와 단발 타이머를 주입받는다. 두 번째 누름이 판정 시간 안에 오면
두 번 클릭 하나만 알리고, 첫 누름의 한 번 클릭은 버린다.
"""

from enum import Enum


class VideoClick(Enum):
    SINGLE = "single"
    DOUBLE = "double"


class VideoClickJudge:
    """누른 시각으로 한 번/두 번 클릭을 가른다.

    clock은 누른 시각과 같은 기준(초)의 지금 시각, timer는 start(초)·stop()을 가진 단발 타이머다.
    타이머가 끝나면 expire()를 부른다. 판정이 끝나면 on_click(VideoClick)을 부른다.
    """

    def __init__(self, interval, *, clock, timer, on_click):
        self.interval = interval
        self._clock = clock
        self._timer = timer
        self._on_click = on_click
        self._pending = None

    def press(self, at):
        if self._pending is not None and at - self._pending <= self.interval:
            self.cancel()
            self._on_click(VideoClick.DOUBLE)
            return
        # 늦게 전달된 누름은 남은 판정 시간만 기다린다.
        self._pending = at
        self._timer.start(max(0.0, at + self.interval - self._clock()))

    def expire(self):
        if self._pending is not None:
            self._pending = None
            self._on_click(VideoClick.SINGLE)

    def cancel(self):
        """확정 전의 한 번 클릭을 버린다."""
        self._pending = None
        self._timer.stop()
