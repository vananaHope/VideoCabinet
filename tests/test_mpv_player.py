"""MpvPlayer 어댑터의 공개 동작. libmpv 대신 해제된 핸들을 흉내 내는 가짜 mpv 모듈을 쓴다."""

import sys
from types import SimpleNamespace

import pytest

from my_video_manager.adapters import MpvPlayer
from my_video_manager.onscreen_playback import OnScreenBand
from my_video_manager.onscreen_subtitles import RegionRect


class FakeMpv:
    created = []

    def __init__(self, **options):
        self.created.append(self)
        self.options = options
        self.commands = []
        self.terminated = False
        self.observers = {}

    def event_callback(self, *names):
        return lambda callback: callback

    def property_observer(self, name):
        def register(callback):
            self.observers[name] = callback
            return callback
        return register

    def observe(self, name, value):
        """mpv 이벤트 스레드가 속성 변경을 알리는 것처럼 등록된 관찰자를 부른다."""
        self.observers[name](name, value)

    def command(self, *arguments):
        if self.terminated:
            # 실제 python-mpv는 terminate 뒤 해제된 핸들을 넘겨 access violation이 난다.
            raise OSError("exception: access violation")
        self.commands.append(arguments)

    def terminate(self):
        self.terminated = True


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setitem(sys.modules, "mpv", SimpleNamespace(MPV=FakeMpv))
    monkeypatch.setattr(FakeMpv, "created", [])
    return MpvPlayer(1)


def engine():
    [created] = FakeMpv.created
    return created


def test_status_uses_korean_osd_font_and_milliseconds(player):
    player.show_status("⏸ 일시정지", 1.5)
    assert engine().options["osd_font"] == "Malgun Gothic"
    assert engine().commands == [("show-text", "⏸ 일시정지", 1500)]


def test_status_after_close_is_skipped(player):
    player.show_status("1.25×", 1.5)
    player.close()
    player.show_status("자막 꺼짐", 1.5)
    assert engine().commands == [("show-text", "1.25×", 1500)]


def test_status_after_prepare_close_is_skipped_before_native_termination(player):
    player.show_status("1.25×", 1.5)
    player.prepare_close()
    assert not engine().terminated
    player.show_status("자막 꺼짐", 1.5)
    assert engine().commands == [("show-text", "1.25×", 1500)]
    player.close()
    assert engine().terminated


# 1280×720 창에 4:3 영상을 그리면 좌우에 160px씩 검은 여백이 생긴다(osd-dimensions의 ml·mr).
PILLARBOX = {'w': 1280, 'h': 720, 'par': 1.0, 'aspect': 1280 / 720, 'mt': 0, 'mb': 0, 'ml': 160, 'mr': 160}
FULLSCREEN = {'w': 1920, 'h': 1080, 'par': 1.0, 'aspect': 1920 / 1080, 'mt': 0, 'mb': 0, 'ml': 240, 'mr': 240}
BOTTOM = RegionRect(0.1, 0.75, 0.8, 0.2)
TOP = RegionRect(0.0, 0.0, 0.5, 0.1)


def overlays():
    return [command for command in engine().commands if command[0] == 'osd-overlay']


def events(command):
    """osd-overlay 명령의 ASS 이벤트 줄들."""
    return command[3].split('\n')


def test_overlay_maps_region_ratios_into_the_drawn_video_area(player):
    engine().observe('osd-dimensions', PILLARBOX)
    player.show_onscreen_translation((OnScreenBand(BOTTOM, '안녕'), OnScreenBand(TOP, 'Hi')))
    [command] = overlays()
    # 오버레이 하나(같은 id)에 영역 목록 전체를 그리고, 좌표계는 창 픽셀 그대로다.
    assert command[1:3] == (1, 'ass-events') and command[4:6] == (1280, 720)
    box, text, top_box, top_text = events(command)
    # 영상은 x 160~1120(폭 960), y 0~720. 아래 영역은 x 256~1024, y 540~684.
    assert r'\pos(0,0)' in box and r'\1c&H000000&' in box and r'\1a&H00&' in box
    assert box.endswith(r'm 256 540 l 1024 540 1024 684 256 684{\p0}')
    assert r'\pos(640,612)' in text and r'\1c&HFFFFFF&' in text and r'\clip(256,540,1024,684)' in text
    assert text.endswith('}안녕')
    assert top_box.endswith(r'm 160 0 l 640 0 640 72 160 72{\p0}') and top_text.endswith('}Hi')


def test_overlay_redraws_only_when_window_size_changes(player):
    player.show_onscreen_translation((OnScreenBand(BOTTOM, '안녕'),))
    assert overlays() == []  # 아직 영상 자리를 모르면 기다린다
    engine().observe('osd-dimensions', PILLARBOX)
    engine().observe('osd-dimensions', dict(PILLARBOX))
    assert len(overlays()) == 1
    engine().observe('osd-dimensions', FULLSCREEN)  # 전체 화면: 영상 x 240~1680
    assert len(overlays()) == 2
    assert overlays()[1][4:6] == (1920, 1080)
    assert events(overlays()[1])[0].endswith(r'm 384 810 l 1536 810 1536 1026 384 1026{\p0}')


def test_clear_removes_overlay_and_resize_after_clear_draws_nothing(player):
    engine().observe('osd-dimensions', PILLARBOX)
    player.show_onscreen_translation((OnScreenBand(BOTTOM, '안녕'),))
    player.clear_onscreen_translation()
    assert overlays()[-1][1:4] == (1, 'none', '')
    engine().observe('osd-dimensions', FULLSCREEN)
    assert len(overlays()) == 2


def font_size(event):
    return float(event.split(r'\fs')[1].split('\\')[0])


def test_text_size_follows_region_height_and_shrinks_to_fit_width(player):
    engine().observe('osd-dimensions', PILLARBOX)
    short, long, lines = (OnScreenBand(BOTTOM, '안녕'), OnScreenBand(BOTTOM, '아주 긴 화면 번역 자막 줄' * 4),
                          OnScreenBand(BOTTOM, '첫 줄\n둘째 줄'))
    for band in (short, long, lines):
        player.show_onscreen_translation((band,))
    sizes = [font_size(events(command)[1]) for command in overlays()]
    # 짧은 줄은 영역 높이(144px)에 맞추고, 긴 줄은 영역 폭(768px)에 들게 줄이며, 두 줄은 줄마다 높이를 나눈다.
    assert 80 <= sizes[0] <= 144
    assert sizes[1] * len('아주 긴 화면 번역 자막 줄' * 4) * 0.6 <= 768 and sizes[1] < sizes[0] / 3
    assert sizes[2] <= sizes[0] / 2 + 1
    assert events(overlays()[2])[1].endswith(r'}첫 줄\N둘째 줄')


def test_text_is_escaped_so_braces_and_backslashes_show_as_written(player):
    engine().observe('osd-dimensions', PILLARBOX)
    player.show_onscreen_translation((OnScreenBand(BOTTOM, r'{\b1}굵게'),))
    text = events(overlays()[0])[1]
    # 여는·닫는 중괄호는 \{ \}로, 역빗금 뒤에는 단어 이음표(U+2060)를 넣어 태그가 되지 않는다.
    assert text.endswith('}' + r'\{' + '\\⁠b1' + r'\}' + '굵게')


def test_overlay_and_subtitle_position_after_close_are_skipped(player):
    engine().observe('osd-dimensions', PILLARBOX)
    player.prepare_close()
    player.show_onscreen_translation((OnScreenBand(BOTTOM, '안녕'),))
    player.clear_onscreen_translation()
    player.set_subtitles_raised(True)
    engine().observe('osd-dimensions', FULLSCREEN)
    assert overlays() == [] and not hasattr(engine(), 'sub_align_y')


def test_transcript_subtitles_move_to_top_and_back_to_bottom(player):
    player.set_subtitles_raised(True)
    assert engine().sub_align_y == 'top'
    player.set_subtitles_raised(False)
    assert engine().sub_align_y == 'bottom'
