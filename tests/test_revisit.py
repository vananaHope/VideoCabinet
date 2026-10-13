from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.revisit import RevisitSettings, ordered_revisit_entries


class Clock:
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Library(AppCore):
    """#3의 위치 소실 API가 들어오기 전, 공개 영상 목록 경계에서 파일 없음을 공급한다."""
    missing = ()

    def videos(self):
        return tuple(replace(v, locations=()) if v.id in self.missing else v
                     for v in super().videos())


@pytest.fixture
def library(tmp_path):
    clock = Clock()
    core = Library(media=Media(), clock=clock, database=tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    for title in ("B 영상", "A 영상", "C 영상"):
        (folder / f"{title}.mkv").write_bytes(title.encode())
    core.add_watched_folder(folder)
    core.scan()
    return core, clock


def press(core, key):
    return core.execute_highlight_command(core.command_for_key(key))


def mark(core, video, start, end=None):
    core.playback.start(video.id, start, record_viewing=False)
    press(core, "Insert")
    highlight = next(h for h in core.highlights(video.id) if h.start == start)
    if end is not None:
        highlight = core.update_highlight(highlight.id, start=start, end=end, note="구간 메모")
    core.playback.end()
    return highlight


def current_id(core):
    return core.revisit_playback.entry.highlight.id if core.revisit_playback else None


def test_list_order_tag_filter_and_missing(library):
    core, _ = library
    a, b, c = core.videos()
    last = mark(core, b, 40)
    second = mark(core, a, 20, 25)
    first = mark(core, a, 10)
    tag = core.add_highlight_tag(last.id, "복습")
    core.add_highlight_tag(first.id, "복습")
    core.add_video_tag(c.id, "복습")
    core.missing = (a.id,)
    assert [e.highlight for e in core.revisit_entries()] == [first, second, last]
    assert [e.playable for e in core.revisit_entries()] == [False, False, True]
    assert [e.highlight for e in core.revisit_entries(tag.id)] == [first, last]
    assert core.revisit_entries(tag.id)[0].last_revisited_at is None


def test_sort_ties_are_stable(library):
    core, _ = library
    a, b, _ = core.videos()
    ha, hb = mark(core, a, 30), mark(core, b, 10)
    entries = ordered_revisit_entries([replace(b, title=a.title), a], [hb, ha], {})
    assert [e.highlight.video_id for e in entries] == sorted([a.id, b.id])


def test_point_range_cross_video_auto_advance_and_end(library):
    core, clock = library
    a, b, _ = core.videos()
    first, second, last = mark(core, a, 10), mark(core, a, 30, 32), mark(core, b, 98)
    core.start_revisit()
    assert (core.revisit_playback.start, core.revisit_playback.end) == (10, 20)
    assert not core.playback.session.record_viewing
    core.playback.report(20)
    assert current_id(core) == second.id
    assert core.last_highlight_revisited_at(first.id) == clock.now
    core.playback.report(32)
    assert current_id(core) == last.id
    assert core.last_highlight_revisited_at(second.id) == clock.now
    assert core.playback.session.video_id == b.id
    assert core.revisit_playback.end == 100
    core.playback.report(100)
    assert core.playback.session is None and core.revisit_playback is None
    assert core.last_highlight_revisited_at(last.id) == clock.now


def test_home_end_use_list_in_revisit_and_timestamps_in_normal_playback(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 30)
    core.start_revisit()
    original = core.revisit_playback
    press(core, "Home")
    assert core.revisit_playback == original
    press(core, "End")
    assert current_id(core) == second.id
    press(core, "Home")
    assert current_id(core) == first.id
    core.switch_to(a.id)
    assert core.revisit_playback is None
    assert press(core, "End") == 10


@pytest.mark.parametrize("end", [None, 12])
def test_repeat_point_and_range_updates_timestamp_once_each_pass(library, end):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 10, end)
    core.start_revisit()
    assert core.command_for_key("\\") == Command(CommandType.TOGGLE_REVISIT_REPEAT)
    press(core, "\\")
    serial = core.revisit_playback.serial
    core.playback.report(core.revisit_playback.end)
    assert current_id(core) == h.id and core.revisit_playback.serial > serial
    assert core.revisit_repeat
    assert core.last_highlight_revisited_at(h.id) == clock.now
    clock.now += timedelta(days=31)
    core.playback.report(core.revisit_playback.end)
    assert core.last_highlight_revisited_at(h.id) == clock.now
    press(core, "\\")
    core.playback.report(core.revisit_playback.end)
    assert core.revisit_playback is None


def test_pause_seek_rewind_and_threshold(library):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 10, 50)
    core.start_revisit()
    clock.now += timedelta(seconds=50)
    core.playback.report(10)  # 벽시계와 일시정지는 복습이 아니다.
    core.playback.report(40, seeked=True)
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(42)
    core.playback.report(40, seeked=True)
    core.playback.report(42)  # 중복 구간은 두 번 세지 않는다.
    core.playback.report(42.999)
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(43)
    assert core.last_highlight_revisited_at(h.id) == clock.now
    clock.now += timedelta(seconds=5)
    core.playback.report(44)
    assert core.last_highlight_revisited_at(h.id) == clock.now - timedelta(seconds=5)


def test_seek_to_end_does_not_record_and_short_partial_does_not_count(library):
    core, _ = library
    a = core.videos()[0]
    first, second = mark(core, a, 10, 12), mark(core, a, 20, 22)
    core.start_revisit()
    core.playback.report(12, seeked=True)
    assert current_id(core) == second.id
    assert core.last_highlight_revisited_at(first.id) is None
    core.playback.report(21)
    core.playback.end()
    assert core.last_highlight_revisited_at(second.id) is None


@pytest.mark.parametrize("watched_end", [0, 20, 95])
def test_viewing_classification_and_resume_are_unchanged_and_records_survive_restart(library, watched_end):
    core, clock = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 20)
    core.playback.start(a.id, 0)
    core.playback.report(watched_end)
    core.playback.end()
    before = [(core.viewings(v.id), core.viewing_status(v.id), core.resume_start(v.id)) for v in (a, b)]
    core.start_revisit()
    core.playback.report(13)
    press(core, "End")
    clock.now += timedelta(days=1)
    core.playback.report(30)
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    after = [(reopened.viewings(v.id), reopened.viewing_status(v.id), reopened.resume_start(v.id)) for v in (a, b)]
    assert before == after
    assert reopened.last_highlight_revisited_at(first.id) == clock.now - timedelta(days=1)
    assert reopened.last_video_revisited_at(b.id) == clock.now
    assert reopened.revisit_entries()[1].last_revisited_at == clock.now


def test_video_last_revisit_aggregates_and_delete_cleans_up(library):
    core, clock = library
    a = core.videos()[0]
    first, second = mark(core, a, 10), mark(core, a, 20)
    assert core.last_video_revisited_at(a.id) is None
    core.start_revisit()
    core.playback.report(13)
    earlier = clock.now
    clock.now += timedelta(days=2)
    press(core, "End")
    core.playback.report(23)
    assert core.last_video_revisited_at(a.id) == clock.now
    core.delete_highlight(second.id)
    assert core.last_highlight_revisited_at(second.id) is None
    assert core.last_video_revisited_at(a.id) == earlier
    core.delete_highlight(first.id)
    assert core.last_video_revisited_at(a.id) is None


def test_missing_skipped_both_directions_and_selected_missing_refused(library):
    core, _ = library
    a, b, c = core.videos()
    first, missing, last = mark(core, a, 10), mark(core, b, 20), mark(core, c, 30)
    core.missing = (b.id,)
    core.start_revisit()
    press(core, "End")
    assert current_id(core) == last.id
    press(core, "Home")
    assert current_id(core) == first.id
    with pytest.raises(ValueError, match="파일 없음"):
        core.start_revisit(highlight_id=missing.id)
    assert current_id(core) == first.id
    core.missing = (a.id, b.id, c.id)
    assert core.start_revisit() is None
    assert core.playback.session is None


def test_selected_filter_snapshot_creation_and_open_range_close(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 20)
    tag = core.add_highlight_tag(first.id, "선택")
    core.start_revisit(tag.id)
    core.playback.report(11)
    press(core, "Insert")
    press(core, "Delete")
    core.playback.report(12)
    press(core, "End")
    assert core.playback.session is None
    assert [(h.start, h.end) for h in core.highlights(a.id)] == [(10, None), (11, None), (11, 12)]
    assert len(core.revisit_entries()) == 4
    core.start_revisit(highlight_id=second.id)
    assert current_id(core) == second.id


def test_empty_and_point_at_video_end_are_skipped(library):
    core, _ = library
    assert core.start_revisit() is None
    mark(core, core.videos()[0], 100)
    assert len(core.revisit_entries()) == 1
    assert core.start_revisit() is None


def test_custom_point_length_and_record_threshold(library):
    core, clock = library
    h = mark(core, core.videos()[0], 10)
    custom = AppCore(media=Media(), clock=clock, database=core.database,
                     revisit_settings=RevisitSettings(point_duration=5, minimum_played=1))
    custom.start_revisit()
    assert custom.revisit_playback.end == 15
    custom.playback.report(11)
    assert custom.last_highlight_revisited_at(h.id) == clock.now


def test_first_engine_report_and_eof_complete_a_short_fractional_range(library):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 98.7654, 100)
    core.start_revisit()
    core.playback.report(98.7654, seeked=True)  # 엔진의 최초 재생 시작 기준
    core.playback.report(98.8)  # 첫 화면 보고까지 재생된 시간
    core.playback.report(99.98)
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(100)  # 실제 EOF 보고로 마지막 프레임의 남은 길이 반영
    assert core.last_highlight_revisited_at(h.id) == clock.now


def test_deleting_current_or_queued_highlight_does_not_resurrect_it(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second, last = mark(core, a, 10), mark(core, a, 20), mark(core, b, 10)
    core.start_revisit()
    core.delete_highlight(first.id)
    core.delete_highlight(second.id)
    core.playback.report(20)
    assert core.last_highlight_revisited_at(first.id) is None
    assert current_id(core) == last.id


def test_start_revisit_closes_normal_viewing_and_open_highlight(library):
    core, _ = library
    a = core.videos()[0]
    mark(core, a, 10)
    core.switch_to(a.id)
    core.playback.report(10)
    press(core, "Delete")
    core.playback.report(15)
    core.start_revisit()
    viewing, = core.viewings(a.id)
    assert viewing.ended_at is not None
    assert viewing.played_seconds == 15
    assert core.highlights(a.id)[-1].end == 15
    core.playback.report(20)
    assert core.viewings(a.id) == (viewing,)


def test_repeat_rebinding_and_normal_playback_noop(library):
    core, _ = library
    press(core, "\\")
    assert not core.revisit_repeat
    core.set_key_bindings({"Space": Command(CommandType.TOGGLE_REVISIT_REPEAT)})
    assert core.command_for_key("\\") is None
    core.playback.start(core.videos()[0].id, 10, record_viewing=False)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    core.start_revisit()
    press(core, "Space")
    assert core.revisit_repeat


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
@pytest.mark.parametrize("field", ["point_duration", "minimum_played"])
def test_invalid_settings(value, field):
    with pytest.raises(ValueError):
        RevisitSettings(**{field: value})


def test_pgup_pgdn_stay_in_revisit_and_use_video_groups(library):
    core, _ = library
    a, b, c = core.videos()
    a1, a2, b1, b2, c1 = (mark(core, a, 10), mark(core, a, 20), mark(core, b, 10),
                           mark(core, b, 20), mark(core, c, 10))
    def video_key(key):
        return core.execute_video_command(core.command_for_key(key), ())
    core.start_revisit()
    video_key("PgUp")
    assert current_id(core) == a1.id
    press(core, "End")
    video_key("PgUp")
    assert current_id(core) == a1.id
    video_key("PgDn")
    assert current_id(core) == b1.id
    press(core, "End")
    video_key("PgUp")
    assert current_id(core) == b1.id
    video_key("PgUp")
    assert current_id(core) == a1.id
    core.missing = (b.id,)
    video_key("PgDn")
    assert current_id(core) == c1.id
    video_key("PgDn")
    assert current_id(core) == c1.id
    assert not core.playback.session.record_viewing
    core.switch_to(a.id)
    assert core.execute_video_command(core.command_for_key("PgDn"), (a.id, c.id)) == c.id


@pytest.mark.parametrize("key", ["Enter", "Left", "Right", ",", "Up", "Down", "/"])
def test_regular_player_keys_unchanged_in_revisit(library, key):
    core, _ = library
    before = core.command_for_key(key)
    mark(core, core.videos()[0], 10)
    core.start_revisit()
    assert core.command_for_key(key) == before
    assert not core.is_highlight_command(before)
