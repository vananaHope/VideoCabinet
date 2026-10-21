"""영상 클릭 판정: 시계와 타이머를 주입해 Qt·mpv 없이 검사한다."""

from my_video_manager.video_click import VideoClick, VideoClickJudge


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Timer:
    """단발 타이머. 지금 시각이 정해진 시각을 넘기면 run()이 판정기를 깨운다."""

    def __init__(self, clock):
        self.clock = clock
        self.due = None

    def start(self, seconds):
        self.due = self.clock.now + seconds

    def stop(self):
        self.due = None

    def run(self, judge, until):
        self.clock.now = until
        if self.due is not None and self.due <= until:
            self.due = None
            judge.expire()


def judge():
    clock = Clock()
    timer = Timer(clock)
    clicks = []
    return VideoClickJudge(0.4, clock=clock, timer=timer, on_click=clicks.append), clock, timer, clicks


def test_single_click_runs_only_after_double_click_interval():
    clicks_judge, clock, timer, clicks = judge()
    clicks_judge.press(0.0)
    timer.run(clicks_judge, 0.39)
    assert clicks == []
    timer.run(clicks_judge, 0.4)
    assert clicks == [VideoClick.SINGLE]


def test_double_click_never_runs_single_click():
    clicks_judge, clock, timer, clicks = judge()
    clicks_judge.press(0.0)
    clock.now = 0.3
    clicks_judge.press(0.3)
    assert clicks == [VideoClick.DOUBLE]
    timer.run(clicks_judge, 5)
    assert clicks == [VideoClick.DOUBLE]


def test_slow_second_press_is_another_single_click():
    clicks_judge, clock, timer, clicks = judge()
    clicks_judge.press(0.0)
    timer.run(clicks_judge, 0.45)
    clicks_judge.press(0.45)
    timer.run(clicks_judge, 0.9)
    assert clicks == [VideoClick.SINGLE, VideoClick.SINGLE]


def test_third_press_after_double_click_starts_new_judgement():
    clicks_judge, clock, timer, clicks = judge()
    clicks_judge.press(0.0)
    clicks_judge.press(0.2)
    clicks_judge.press(0.3)
    assert clicks == [VideoClick.DOUBLE]
    timer.run(clicks_judge, 0.69)
    assert clicks == [VideoClick.DOUBLE]
    timer.run(clicks_judge, 0.7)
    assert clicks == [VideoClick.DOUBLE, VideoClick.SINGLE]


def test_late_delivered_press_waits_only_remaining_interval():
    clicks_judge, clock, timer, clicks = judge()
    clock.now = 0.25
    clicks_judge.press(0.1)  # 누른 지 0.15초 뒤에 전달됐다.
    timer.run(clicks_judge, 0.49)
    assert clicks == []
    timer.run(clicks_judge, 0.5)
    assert clicks == [VideoClick.SINGLE]


def test_cancel_drops_pending_single_click_and_next_press_is_fresh():
    clicks_judge, clock, timer, clicks = judge()
    clicks_judge.press(0.0)
    clicks_judge.cancel()
    timer.run(clicks_judge, 1)
    assert clicks == []
    clicks_judge.press(1.1)
    assert clicks == []  # 취소한 누름과 짝을 이루지 않는다.
    timer.run(clicks_judge, 1.5)
    assert clicks == [VideoClick.SINGLE]
