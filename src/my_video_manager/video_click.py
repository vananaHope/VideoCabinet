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
    타이머가 끝나면 expire()를 부른다. 판정이 끝나면 on_click(VideoClick, 주인)을 부른다.
    주인은 누름을 받은 재생 엔진처럼 클릭이 속한 대상이다. 주인이 다른 두 누름은 한 클릭으로 묶지 않는다.
    """

    def __init__(self, interval, *, clock, timer, on_click):
        self.interval = interval
        self._clock = clock
        self._timer = timer
        self._on_click = on_click
        self._pending = None  # (누른 시각, 주인)

    def press(self, at, owner=None):
        if self._pending is not None:
            first, first_owner = self._pending
            if first_owner is not owner:
                self.cancel()  # 다른 영상·엔진의 누름은 이어 붙이지 않고 버린다.
            elif at - first <= self.interval:
                self.cancel()
                self._on_click(VideoClick.DOUBLE, owner)
                return
            else:
                # 타이머가 늦어 판정 시간이 지난 누름이 아직 남았다. 새 판정 전에 확정한다.
                self.cancel()
                self._on_click(VideoClick.SINGLE, first_owner)
        self._pending = (at, owner)
        self._wait()

    def expire(self):
        if self._pending is None:
            return
        if self._clock() < self._pending[0] + self.interval:
            self._wait()  # 타이머가 판정 시간보다 일찍 깨웠다.
            return
        _, owner = self._pending
        self._pending = None
        self._on_click(VideoClick.SINGLE, owner)

    def cancel(self):
        """확정 전의 한 번 클릭을 버린다."""
        self._pending = None
        self._timer.stop()

    def _wait(self):
        # 늦게 전달된 누름이나 일찍 깬 타이머는 남은 판정 시간만 기다린다.
        self._timer.start(max(0.0, self._pending[0] + self.interval - self._clock()))
