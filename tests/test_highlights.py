from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.highlights import Highlight, Note, nearest_highlight
from my_video_manager.highlight_editing import initial_time_input, resolve_time_input, time_input_maximum


@pytest.mark.parametrize(('highlights', 'position', 'expected_id'), [
    ((Highlight(1, 1, 10, 30, None), Highlight(2, 1, 24, None, None)), 25, 1),
    ((Highlight(1, 1, 10, 30, None), Highlight(2, 1, 40, None, None)), 32, 1),
    ((Highlight(2, 1, 20, None, None), Highlight(1, 1, 10, None, None)), 15, 1),
    ((Highlight(2, 1, 10, None, None), Highlight(1, 1, 10, None, None)), 10, 1),
    ((), 10, None),
])
def test_nearest_highlight_uses_interval_distance_and_time_order(highlights, position, expected_id):
    nearest = nearest_highlight(highlights, position)
    assert (nearest.id if nearest else None) == expected_id


class FakeMedia:
    def __init__(self, duration=120):
        self.duration = duration

    def read(self, path):
        return MediaInfo(self.duration, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


@pytest.fixture
def core(tmp_path):
    core = AppCore(media=FakeMedia(), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "first.mkv").write_bytes(b"first video")
    (folder / "second.mkv").write_bytes(b"second video")
    core.add_watched_folder(folder)
    core.scan()
    return core


def press(core, key):
    return core.execute_highlight_command(core.command_for_key(key))


@pytest.mark.parametrize("key, kind", [
    ("Insert", CommandType.POINT_HIGHLIGHT), ("Delete", CommandType.RANGE_HIGHLIGHT),
    ("Home", CommandType.PREVIOUS_HIGHLIGHT), ("End", CommandType.NEXT_HIGHLIGHT),
])
def test_highlight_key_commands(core, key, kind):
    assert core.command_for_key(key) == Command(kind)
    assert core.is_highlight_command(core.command_for_key(key))


def test_keys_create_point_and_range_on_current_video(core):
    first, second = core.videos()
    core.playback.start(first.id, 2.125)
    press(core, "Insert")
    core.playback.report(10)
    press(core, "Delete")
    assert core.open_highlight_start == 10
    core.playback.report(25.5)
    press(core, "Delete")
    assert core.open_highlight_start is None
    assert [(h.start, h.end) for h in core.highlights(first.id)] == [(2.125, None), (10, 25.5)]
    assert core.highlights(second.id) == ()


@pytest.mark.parametrize("action", ["stop", "switch"])
@pytest.mark.parametrize("end, expected_end", [(30, 30), (20, None), (5, None)])
def test_open_range_closes_at_last_position_on_stop_or_switch(core, action, end, expected_end):
    first, second = core.videos()
    core.playback.start(first.id, 20)
    press(core, "Delete")
    core.playback.report(end, seeked=end < 20)
    if action == "stop":
        core.playback.end()
        core.playback.end()  # 중복 종료는 추가 저장하지 않는다.
    else:
        core.playback.start(second.id, 40)
        core.playback.end()
    highlight, = core.highlights(first.id)
    assert (highlight.start, highlight.end) == (20, expected_end)
    assert core.open_highlight_start is None
    assert core.highlights(second.id) == ()


@pytest.mark.parametrize("end", [10, 5])
def test_delete_after_rewind_or_no_progress_keeps_point(core, end):
    video = core.videos()[0]
    core.playback.start(video.id, 10)
    press(core, "Delete")
    core.playback.report(end, seeked=True)
    press(core, "Delete")
    highlight, = core.highlights(video.id)
    assert (highlight.start, highlight.end) == (10, None)


def test_insert_during_open_range_does_not_close_it(core):
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    press(core, "Delete")
    core.playback.report(4)
    press(core, "Insert")
    assert core.open_highlight_start == 0
    core.playback.report(8)
    core.playback.end()
    assert [(h.start, h.end) for h in core.highlights(video.id)] == [(0, 8), (4, None)]


@pytest.mark.parametrize("position, previous, following", [
    (0, None, 10), (10, 0, 30), (10.5, 0, 30), (11, 0, 30),
    (11.001, 10, 30), (29, 10, 30), (30, 10, None), (120, 30, None),
])
def test_home_skips_last_second_and_end_finds_next_start(core, position, previous, following):
    first, second = core.videos()
    core.playback.start(second.id, 15)
    press(core, "Insert")
    core.playback.start(first.id, 30)
    press(core, "Delete")
    core.playback.report(45)
    press(core, "Delete")
    for point in (10, 0, 10):  # 중복 시작과 생성 순서에 영향받지 않는다.
        core.playback.report(point, seeked=True)
        press(core, "Insert")
    core.playback.report(position, seeked=True)
    assert press(core, "Home") == previous
    assert press(core, "End") == following


def test_empty_highlight_navigation_does_nothing(core):
    core.playback.start(core.videos()[0].id, 50)
    assert press(core, "Home") is None
    assert press(core, "End") is None


def test_edit_note_times_delete_and_reopen(core):
    video = core.videos()[0]
    core.playback.start(video.id, 15)
    press(core, "Insert")
    highlight, = core.highlights(video.id)
    edited = core.update_highlight(highlight.id, start=20.25, end=35.5, note=" 첫 메모 ")
    assert edited.note == Note("첫 메모")
    edited = core.update_highlight(highlight.id, start=21, end=36, note="고친 메모\n둘째 줄")
    reopened = AppCore(media=FakeMedia(), clock=lambda: None, database=core.database)
    assert reopened.highlights(video.id) == (edited,)
    assert (edited.start, edited.end, edited.note.text) == (21, 36, "고친 메모\n둘째 줄")
    point = reopened.update_highlight(highlight.id, start=120, end=None, note="  ")
    assert point.end is None and point.note is None
    reopened.delete_highlight(highlight.id)
    assert core.highlights(video.id) == ()
    with pytest.raises(ValueError, match="하이라이트를 찾을 수 없습니다"):
        core.update_highlight(highlight.id, start=0, end=None, note="단독 메모 불가")


@pytest.mark.parametrize("start, end", [
    (-1, None), (121, None), (float("nan"), None), (float("inf"), None),
    (10, 10), (10, 9), (10, 121), (10, float("nan")), (10, float("inf")),
])
def test_invalid_edit_preserves_highlight_and_note(core, start, end):
    video = core.videos()[0]
    core.playback.start(video.id, 3)
    press(core, "Insert")
    original, = core.highlights(video.id)
    with pytest.raises(ValueError):
        core.update_highlight(original.id, start=start, end=end, note="저장되면 안 됨")
    assert core.highlights(video.id) == (original,)


def test_rebound_key_creates_highlight(core):
    core.set_key_bindings({"Space": Command(CommandType.POINT_HIGHLIGHT)})
    video = core.videos()[0]
    core.playback.start(video.id, 12)
    press(core, "Space")
    assert core.highlights(video.id)[0].start == 12
    assert core.is_highlight_command(core.command_for_key("Space"))
    assert core.command_for_key("Insert") is None


@pytest.mark.parametrize("key", ["Insert", "Delete", "Home", "End"])
def test_highlight_commands_require_playback(core, key):
    with pytest.raises(ValueError, match="재생 중인 영상"):
        press(core, key)


def test_reported_positions_are_clamped_to_video(core):
    video = core.videos()[0]
    core.playback.start(video.id, -0.01)
    press(core, "Insert")
    core.playback.report(120.001)
    press(core, "Insert")
    assert [h.start for h in core.highlights(video.id)] == [0, 120]


@pytest.mark.parametrize("duration, maximum", [
    (60.0416, 60.041), (12.3456, 12.345), (60.041, 60.041),
    (0.0004, 0), (120, 120), (0, 0),
])
def test_time_input_maximum_stays_within_video(duration, maximum):
    assert time_input_maximum(duration) == maximum
    assert maximum <= duration


@pytest.mark.parametrize("original_start, original_end, entered_start, entered_end, expected_start, expected_end", [
    (5.533333, 60.0416, 5.533, 60.041, 5.533333, 60.0416),
    (60.0416, None, 60.041, None, 60.0416, None),
    (60.0415, 60.0416, 60.041, 60.041, 60.0415, 60.0416),
    (5.533333, 60.0416, 6, 60.041, 6, 60.0416),
    (5.533333, 60.0416, 5.533, 60, 5.533333, 60),
    (5.533333, None, 5.533, 60.041, 5.533333, 60.041),
    (5.533333, 60.0416, 5.533, None, 5.533333, None),
])
def test_editing_preserves_untouched_precision_and_saves_changed_times(
        tmp_path, original_start, original_end, entered_start, entered_end, expected_start, expected_end):
    core = AppCore(media=FakeMedia(60.0416), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "precise.mkv").write_bytes(b"video with submillisecond duration")
    core.add_watched_folder(folder)
    core.scan()
    video, = core.videos()
    core.playback.start(video.id, original_start)
    if original_end is None:
        press(core, "Insert")
    else:
        press(core, "Delete")
        core.playback.report(original_end)
        press(core, "Delete")
    highlight, = core.highlights(video.id)
    initial_start = initial_time_input(highlight.start, video.duration)
    initial_end = initial_time_input(highlight.end if highlight.end is not None else highlight.start, video.duration)
    start = resolve_time_input(highlight.start, initial_start, entered_start)
    end = (resolve_time_input(highlight.end, initial_end, entered_end)
           if entered_end is not None else None)

    core.update_highlight(highlight.id, start=start, end=end, note="메모 수정")

    saved, = core.highlights(video.id)
    assert (saved.start, saved.end, saved.note.text) == (expected_start, expected_end, "메모 수정")


@pytest.mark.parametrize("key", ["Enter", "Left", "Up"])
def test_player_commands_are_not_highlight_commands(core, key):
    command = core.command_for_key(key)
    assert not core.is_highlight_command(command)
    with pytest.raises(ValueError, match="하이라이트 명령이 아닙니다"):
        core.execute_highlight_command(command)
