from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.reel import ReelSettings, ordered_reel_entries


class Clock:
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


def remove_files(core, *videos):
    for video in videos:
        for location in video.locations:
            location.path.unlink()
    core.scan()
    assert all(v.missing for v in core.videos() if v.id in {video.id for video in videos})


@pytest.fixture
def library(tmp_path):
    clock = Clock()
    core = AppCore(media=Media(), clock=clock, database=tmp_path / "data/library.sqlite3")
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
    return core.reel_playback.entry.highlight.id if core.reel_playback else None


@pytest.mark.parametrize("remapped", [False, True])
def test_shared_navigation_bindings_are_valid_in_normal_playback_and_reel(library, remapped):
    core, _ = library
    a, b, _ = core.videos()
    first, second, other = mark(core, a, 10, 15), mark(core, a, 30, 35), mark(core, b, 20, 25)
    previous, following, previous_video, next_video = ("F7", "F8", "F9", "F10") if remapped else ("Home", "End", "PgUp", "PgDn")
    bindings = {row.command: row.keys for row in core.key_bindings()}
    for kind, key in ((CommandType.PREVIOUS_HIGHLIGHT, previous), (CommandType.NEXT_HIGHLIGHT, following),
                      (CommandType.PREVIOUS_VIDEO, previous_video), (CommandType.NEXT_VIDEO, next_video)):
        bindings[Command(kind)] = (key,)
    core.switch_to(a.id)
    core.playback.report(25)
    core.save_key_bindings(bindings)
    assert press(core, previous) == 10
    assert press(core, following) == 30
    assert core.execute_video_command(core.command_for_key(next_video), (a.id, b.id)) == b.id
    core.switch_to(b.id)
    assert core.execute_video_command(core.command_for_key(previous_video), (a.id, b.id)) == a.id
    core.start_reel(highlight_id=first.id)
    # 같은 명령을 모아보기에서 해석하므로 동일 배치를 다시 저장해도 충돌하지 않는다.
    core.save_key_bindings(bindings)
    press(core, following)
    assert current_id(core) == second.id
    press(core, previous)
    assert current_id(core) == first.id
    core.execute_video_command(core.command_for_key(next_video), ())
    assert current_id(core) == other.id
    core.execute_video_command(core.command_for_key(previous_video), ())
    assert current_id(core) == first.id


def test_list_order_tag_filter_and_missing(library):
    core, _ = library
    a, b, c = core.videos()
    last = mark(core, b, 40)
    second = mark(core, a, 20, 25)
    first = mark(core, a, 10)
    tag = core.add_highlight_tag(last.id, "복습")
    core.add_highlight_tag(first.id, "복습")
    core.add_video_tag(c.id, "복습")
    remove_files(core, a)
    assert [e.highlight for e in core.reel_entries()] == [first, second, last]
    assert [e.playable for e in core.reel_entries()] == [False, False, True]
    assert [e.highlight for e in core.reel_entries(tag.id)] == [first, last]
    assert core.reel_entries(tag.id)[0].last_revisited_at is None


def test_sort_ties_are_stable(library):
    core, _ = library
    a, b, _ = core.videos()
    ha, hb = mark(core, a, 30), mark(core, b, 10)
    entries = ordered_reel_entries([replace(b, title=a.title), a], [hb, ha], {})
    assert [e.highlight.video_id for e in entries] == sorted([a.id, b.id])


def test_excluded_highlights_hidden_including_tag_filter_and_restored_with_records(library):
    core, clock = library
    a, b, _ = core.videos()
    first, hidden = mark(core, a, 10), mark(core, b, 20)
    tag = core.add_highlight_tag(hidden.id, "복습")
    core.start_reel(highlight_id=hidden.id)
    core.playback.report(23)
    core.playback.end()
    core.exclude_video(b.id)
    assert [e.highlight for e in core.reel_entries()] == [first]
    assert core.reel_entries(tag.id) == ()
    with pytest.raises(ValueError, match="목록에 없는"):
        core.start_reel(highlight_id=hidden.id)
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    assert [e.highlight for e in reopened.reel_entries()] == [first]
    reopened.restore_video(b.id)
    entry, = reopened.reel_entries(tag.id)
    assert entry.highlight == hidden and entry.playable
    assert entry.last_revisited_at == clock.now
    reopened.start_reel(tag.id)
    assert current_id(reopened) == hidden.id


@pytest.mark.parametrize("change_after_start", [False, True])
def test_pgup_pgdn_skip_both_missing_and_excluded_videos(library, change_after_start):
    core, _ = library
    a, b, c = core.videos()
    path = a.locations[0].path.parent / "D 영상.mkv"
    path.write_bytes(b"fourth video")
    core.add_file(path)
    d = core.videos()[-1]
    first, _, _, last = [mark(core, video, 10) for video in (a, b, c, d)]
    if change_after_start:
        core.start_reel()
    remove_files(core, b)
    core.exclude_video(c.id)
    if not change_after_start:
        core.start_reel()
    core.execute_video_command(core.command_for_key("PgDn"), ())
    assert current_id(core) == last.id
    core.execute_video_command(core.command_for_key("PgUp"), ())
    assert current_id(core) == first.id
    assert not core.playback.session.record_viewing


@pytest.mark.parametrize("state", ["missing", "excluded"])
def test_auto_advance_skips_newly_unavailable_video(library, state):
    core, _ = library
    a, b, c = core.videos()
    first, _, last = [mark(core, video, 10) for video in (a, b, c)]
    core.start_reel()
    if state == "missing":
        remove_files(core, b)
    else:
        core.exclude_video(b.id)
    core.playback.report(20)
    core.advance_reel_if_due()
    assert current_id(core) == last.id
    press(core, "Home")
    assert current_id(core) == first.id


@pytest.mark.parametrize("state", ["missing", "excluded"])
@pytest.mark.parametrize("key", ["PgUp", "PgDn"])
def test_video_navigation_keeps_anchor_when_current_video_becomes_unavailable(library, state, key):
    core, _ = library
    a, b, c = core.videos()
    first, _, second, last = (mark(core, a, 10), mark(core, b, 10),
                              mark(core, b, 30), mark(core, c, 10))
    core.start_reel(highlight_id=second.id)
    if state == "missing":
        remove_files(core, b)
    else:
        core.exclude_video(b.id)
    core.execute_video_command(core.command_for_key(key), ())
    assert current_id(core) == (first.id if key == "PgUp" else last.id)


def test_point_range_cross_video_auto_advance_and_end(library):
    core, clock = library
    a, b, _ = core.videos()
    first, second, last = mark(core, a, 10), mark(core, a, 30, 32), mark(core, b, 98)
    core.start_reel()
    assert (core.reel_playback.start, core.reel_playback.end) == (10, 20)
    assert not core.playback.session.record_viewing
    core.playback.report(20)
    core.advance_reel_if_due()
    assert current_id(core) == second.id
    assert core.last_highlight_revisited_at(first.id) == clock.now
    core.playback.report(32)
    core.advance_reel_if_due()
    assert current_id(core) == last.id
    assert core.last_highlight_revisited_at(second.id) == clock.now
    assert core.playback.session.video_id == b.id
    assert core.reel_playback.end == 100
    core.playback.report(100)
    core.advance_reel_if_due()
    assert core.playback.session is None and core.reel_playback is None
    assert core.last_highlight_revisited_at(last.id) == clock.now


def test_home_end_use_list_in_reel_and_timestamps_in_normal_playback(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 30)
    core.start_reel()
    original = core.reel_playback
    press(core, "Home")
    assert core.reel_playback == original
    press(core, "End")
    assert current_id(core) == second.id
    press(core, "Home")
    assert current_id(core) == first.id
    core.switch_to(a.id)
    assert core.reel_playback is None
    assert press(core, "End") == 10


@pytest.mark.parametrize("end", [None, 12])
def test_repeat_point_and_range_updates_timestamp_once_each_pass(library, end):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 10, end)
    core.start_reel()
    assert core.command_for_key("\\") == Command(CommandType.TOGGLE_REEL_REPEAT)
    press(core, "\\")
    serial = core.reel_playback.serial
    core.playback.report(core.reel_playback.end)
    core.advance_reel_if_due()
    assert current_id(core) == h.id and core.reel_playback.serial > serial
    assert core.reel_repeat
    assert core.last_highlight_revisited_at(h.id) == clock.now
    clock.now += timedelta(days=31)
    core.playback.report(core.reel_playback.end)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) == clock.now
    press(core, "\\")
    core.playback.report(core.reel_playback.end)
    core.advance_reel_if_due()
    assert core.reel_playback is None


def test_pause_seek_rewind_and_threshold(library):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 10, 50)
    core.start_reel()
    clock.now += timedelta(seconds=50)
    core.playback.report(10)  # 벽시계와 일시정지는 복습이 아니다.
    core.advance_reel_if_due()
    core.playback.report(40, seeked=True)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(42)
    core.advance_reel_if_due()
    core.playback.report(40, seeked=True)
    core.advance_reel_if_due()
    core.playback.report(42)  # 중복 구간은 두 번 세지 않는다.
    core.advance_reel_if_due()
    core.playback.report(42.999)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(43)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) == clock.now
    clock.now += timedelta(seconds=5)
    core.playback.report(44)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) == clock.now - timedelta(seconds=5)


def test_seek_to_end_does_not_record_and_short_partial_does_not_count(library):
    core, _ = library
    a = core.videos()[0]
    first, second = mark(core, a, 10, 12), mark(core, a, 20, 22)
    core.start_reel()
    core.playback.report(12, seeked=True)
    core.advance_reel_if_due()
    assert current_id(core) == second.id
    assert core.last_highlight_revisited_at(first.id) is None
    core.playback.report(21)
    core.advance_reel_if_due()
    core.playback.end()
    assert core.last_highlight_revisited_at(second.id) is None


@pytest.mark.parametrize("watched_end", [0, 20, 95])
def test_viewing_classification_and_resume_are_unchanged_and_records_survive_restart(library, watched_end):
    core, clock = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 20)
    core.playback.start(a.id, 0)
    core.playback.report(watched_end)
    core.advance_reel_if_due()
    core.playback.end()
    before = [(core.viewings(v.id), core.viewing_status(v.id), core.resume_start(v.id)) for v in (a, b)]
    core.start_reel()
    core.playback.report(13)
    core.advance_reel_if_due()
    press(core, "End")
    clock.now += timedelta(days=1)
    core.playback.report(30)
    core.advance_reel_if_due()
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    after = [(reopened.viewings(v.id), reopened.viewing_status(v.id), reopened.resume_start(v.id)) for v in (a, b)]
    assert before == after
    assert reopened.last_highlight_revisited_at(first.id) == clock.now - timedelta(days=1)
    assert reopened.last_video_revisited_at(b.id) == clock.now
    assert reopened.reel_entries()[1].last_revisited_at == clock.now


def test_video_last_revisit_aggregates_and_delete_cleans_up(library):
    core, clock = library
    a = core.videos()[0]
    first, second = mark(core, a, 10), mark(core, a, 20)
    assert core.last_video_revisited_at(a.id) is None
    core.start_reel()
    core.playback.report(13)
    core.advance_reel_if_due()
    earlier = clock.now
    clock.now += timedelta(days=2)
    press(core, "End")
    core.playback.report(23)
    core.advance_reel_if_due()
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
    remove_files(core, b)
    core.start_reel()
    press(core, "End")
    assert current_id(core) == last.id
    press(core, "Home")
    assert current_id(core) == first.id
    with pytest.raises(ValueError, match="파일 없음"):
        core.start_reel(highlight_id=missing.id)
    assert current_id(core) == first.id
    remove_files(core, a, c)
    assert core.start_reel() is None
    assert core.playback.session is None


def test_selected_filter_snapshot_creation_and_open_range_close(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10), mark(core, b, 20)
    tag = core.add_highlight_tag(first.id, "선택")
    core.start_reel(tag.id)
    core.playback.report(11)
    core.advance_reel_if_due()
    press(core, "Insert")
    press(core, "Delete")
    core.playback.report(12)
    core.advance_reel_if_due()
    press(core, "End")
    assert core.playback.session is None
    assert [(h.start, h.end) for h in core.highlights(a.id)] == [(10, None), (11, None), (11, 12)]
    assert len(core.reel_entries()) == 4
    core.start_reel(highlight_id=second.id)
    assert current_id(core) == second.id


def test_empty_and_point_at_video_end_are_skipped(library):
    core, _ = library
    assert core.start_reel() is None
    mark(core, core.videos()[0], 100)
    assert len(core.reel_entries()) == 1
    assert core.start_reel() is None


def test_custom_point_length_and_record_threshold(library):
    core, clock = library
    h = mark(core, core.videos()[0], 10)
    custom = AppCore(media=Media(), clock=clock, database=core.database,
                     reel_settings=ReelSettings(point_duration=5, minimum_played=1))
    custom.start_reel()
    assert custom.reel_playback.end == 15
    custom.playback.report(11)
    assert custom.last_highlight_revisited_at(h.id) == clock.now


def test_first_engine_report_and_eof_complete_a_short_fractional_range(library):
    core, clock = library
    a = core.videos()[0]
    h = mark(core, a, 98.7654, 100)
    core.start_reel()
    core.playback.report(98.7654, seeked=True)  # 엔진의 최초 재생 시작 기준
    core.advance_reel_if_due()
    core.playback.report(98.8)  # 첫 화면 보고까지 재생된 시간
    core.advance_reel_if_due()
    core.playback.report(99.98)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) is None
    core.playback.report(100)  # 실제 EOF 보고로 마지막 프레임의 남은 길이 반영
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(h.id) == clock.now


def test_deleting_current_or_queued_highlight_does_not_resurrect_it(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second, last = mark(core, a, 10), mark(core, a, 20), mark(core, b, 10)
    core.start_reel()
    core.delete_highlight(first.id)
    core.delete_highlight(second.id)
    core.playback.report(20)
    core.advance_reel_if_due()
    assert core.last_highlight_revisited_at(first.id) is None
    assert current_id(core) == last.id


def test_start_reel_closes_normal_viewing_and_open_highlight(library):
    core, _ = library
    a = core.videos()[0]
    mark(core, a, 10)
    core.switch_to(a.id)
    core.playback.report(10)
    core.advance_reel_if_due()
    press(core, "Delete")
    core.playback.report(15)
    core.advance_reel_if_due()
    core.start_reel()
    viewing, = core.viewings(a.id)
    assert viewing.ended_at is not None
    assert viewing.played_seconds == 15
    assert core.highlights(a.id)[-1].end == 15
    core.playback.report(20)
    core.advance_reel_if_due()
    assert core.viewings(a.id) == (viewing,)


def test_repeat_rebinding_and_normal_playback_noop(library):
    core, _ = library
    press(core, "\\")
    assert not core.reel_repeat
    core.set_key_bindings({"Space": Command(CommandType.TOGGLE_REEL_REPEAT)})
    assert core.command_for_key("\\") is None
    core.playback.start(core.videos()[0].id, 10, record_viewing=False)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    core.start_reel()
    press(core, "Space")
    assert core.reel_repeat


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
@pytest.mark.parametrize("field", ["point_duration", "minimum_played"])
def test_invalid_settings(value, field):
    with pytest.raises(ValueError):
        ReelSettings(**{field: value})


def test_pgup_pgdn_stay_in_reel_and_use_video_groups(library):
    core, _ = library
    a, b, c = core.videos()
    a1, a2, b1, b2, c1 = (mark(core, a, 10), mark(core, a, 20), mark(core, b, 10),
                           mark(core, b, 20), mark(core, c, 10))
    def video_key(key):
        return core.execute_video_command(core.command_for_key(key), ())
    core.start_reel()
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
    remove_files(core, b)
    video_key("PgDn")
    assert current_id(core) == c1.id
    video_key("PgDn")
    assert current_id(core) == c1.id
    assert not core.playback.session.record_viewing
    core.switch_to(a.id)
    assert core.execute_video_command(core.command_for_key("PgDn"), (a.id, c.id)) == c.id


@pytest.mark.parametrize("key", ["Enter", "Left", "Right", ",", "Up", "Down", "/"])
def test_regular_player_keys_unchanged_in_reel(library, key):
    core, _ = library
    before = core.command_for_key(key)
    mark(core, core.videos()[0], 10)
    core.start_reel()
    assert core.command_for_key(key) == before
    assert not core.is_highlight_command(before)


def test_reel_instructs_seek_within_video_and_open_across_videos(library):
    core, _ = library
    a, b, _ = core.videos()
    mark(core, a, 10)
    mark(core, a, 30)
    mark(core, b, 10)
    core.start_reel()
    assert core.reel_playback.action == "open"
    press(core, "End")
    assert core.reel_playback.action == "seek"
    core.playback.report(30, seeked=True)
    assert core.last_highlight_revisited_at(current_id(core)) is None
    press(core, "\\")
    core.playback.report(40)
    core.advance_reel_if_due()
    assert core.reel_playback.action == "seek"
    press(core, "End")
    assert core.reel_playback.action == "open"
    core.execute_video_command(core.command_for_key("PgUp"), ())
    assert core.reel_playback.action == "open"
    press(core, "End")
    core.execute_video_command(core.command_for_key("PgUp"), ())
    assert core.reel_playback.action == "seek"


def test_all_listeners_receive_position_before_reel_transition(library):
    core, _ = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 10, 12), mark(core, b, 20)
    events = []

    class Listener:
        session = None

        def playback_started(self, session, position):
            assert self.session is None
            self.session = session
            events.append(("start", session.video_id, position))

        def playback_position(self, session, position, seeked):
            assert self.session is session
            events.append(("position", session.video_id, position))

        def playback_ended(self, session, position):
            assert self.session is session
            self.session = None
            events.append(("end", session.video_id, position))

    # 기존 시청·하이라이트·모아보기 뒤에 새 리스너가 추가되어도 계약을 지킨다.
    core.playback.subscribe(Listener())
    core.start_reel()
    press(core, "Delete")
    events.clear()
    core.playback.report(12)
    assert events == [("position", a.id, 12)]
    assert current_id(core) == first.id and core.open_highlight_start == 10
    core.advance_reel_if_due()
    assert events == [("position", a.id, 12), ("end", a.id, 12), ("start", b.id, 20)]
    assert current_id(core) == second.id and core.open_highlight_start is None
    assert core.highlights(a.id)[-1].end == 12
    assert core.viewings(a.id) == core.viewings(b.id) == ()
    core.advance_reel_if_due()  # 같은 완료 보고를 두 번 처리하지 않는다.
    assert current_id(core) == second.id


@pytest.mark.parametrize("duration", [99.96, 100.04])
def test_eof_advances_despite_engine_database_duration_difference(library, duration):
    core, clock = library
    a, b, _ = core.videos()
    first, second = mark(core, a, 98, 100), mark(core, b, 10)
    core.start_reel()
    core.playback.report(duration)
    core.advance_reel_if_due(eof=True)
    assert current_id(core) == second.id
    assert core.last_highlight_revisited_at(first.id) == clock.now


def test_seek_to_shorter_engine_eof_does_not_count_as_revisit(library):
    core, _ = library
    h = mark(core, core.videos()[0], 98, 100)
    core.start_reel()
    core.playback.report(99.98, seeked=True)
    core.advance_reel_if_due(eof=True)
    assert core.reel_playback is None
    assert core.last_highlight_revisited_at(h.id) is None


def test_natural_video_title_sort_preserves_time_order(library):
    core, _ = library
    a, b, c = core.videos()
    marks = [mark(core, a, 20), mark(core, a, 5), mark(core, b, 10), mark(core, c, 30)]
    videos = [replace(a, title="강의 2강"), replace(b, title="강의 10강"), replace(c, title="강의 1강")]
    entries = ordered_reel_entries(videos, marks, {})
    assert [(e.video_title, e.highlight.start) for e in entries] == [
        ("강의 1강", 30), ("강의 2강", 5), ("강의 2강", 20), ("강의 10강", 10)]


@pytest.mark.parametrize("key", ["End", "Home", "PgUp", "PgDn"])
def test_repeat_survives_manual_movement_and_ends_only_on_toggle_or_exit(library, key):
    core, _ = library
    a, b, _ = core.videos()
    mark(core, a, 10)
    middle = mark(core, a, 30)
    mark(core, b, 10)
    core.start_reel(highlight_id=middle.id)
    press(core, "\\")
    if key.startswith("Pg"):
        core.execute_video_command(core.command_for_key(key), ())
    else:
        press(core, key)
    target = current_id(core)
    assert core.reel_repeat
    core.playback.report(core.reel_playback.end)
    core.advance_reel_if_due()
    assert current_id(core) == target
    press(core, "\\")
    assert not core.reel_repeat
    press(core, "\\")
    core.playback.end()
    assert not core.reel_repeat


def test_selecting_zero_length_item_is_rejected_without_changing_current_playback(library):
    core, _ = library
    a, b, _ = core.videos()
    first, zero = mark(core, a, 10), mark(core, a, 100)
    mark(core, b, 20)
    core.start_reel()
    with pytest.raises(ValueError, match="재생할 길이"):
        core.start_reel(highlight_id=zero.id)
    assert current_id(core) == first.id


def test_list_and_pgdn_read_each_public_snapshot_once(library):
    original, clock = library
    for video in original.videos():
        for time in (10, 20, 30):
            mark(original, video, time)

    class CountingCore(AppCore):
        video_reads = highlight_reads = 0

        def videos(self):
            self.video_reads += 1
            return super().videos()

        def all_highlights(self, tag_id=None):
            self.highlight_reads += 1
            return super().all_highlights(tag_id)

    core = CountingCore(media=Media(), clock=clock, database=original.database)
    core.reel_entries()
    assert (core.video_reads, core.highlight_reads) == (1, 1)
    core.start_reel()
    core.video_reads = core.highlight_reads = 0
    core.execute_video_command(core.command_for_key("PgDn"), ())
    assert (core.video_reads, core.highlight_reads) == (1, 1)


def test_subtitle_language_survives_same_video_reel_moves_but_resets_on_new_video(library):
    from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
    from my_video_manager.translation import TranslatedLine

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            return TranscriberResult("en", (TranscriptSegment(0, 100, "source"),), model="large-v3")

    class Translator:
        def translate(self, lines, language, **kwargs):
            return tuple(TranslatedLine(line.id, "번역") for line in lines)

    original, clock = library
    a, b, _ = original.videos()
    first = mark(original, a, 10)
    mark(original, a, 30)
    mark(original, b, 10)
    core = AppCore(media=Media(), clock=clock, database=original.database,
                   transcriber=Transcriber(), translator=Translator())
    for video in (a, b):
        core.request_subtitles(video.id)
        core.process_next_subtitle()
        core.process_next_translation()
    core.start_reel()
    assert "source" in core.playback_subtitle(a.id).read_text(encoding="utf-8")
    assert core.toggle_subtitle_language() == (True, "번역 자막")
    translated = core.playback_subtitle(a.id)
    assert "번역" in translated.read_text(encoding="utf-8")
    press(core, "End")
    assert core.reel_playback.action == "seek" and core.playback_subtitle(a.id) == translated
    press(core, "\\")
    core.playback.report(core.reel_playback.end)
    core.advance_reel_if_due()
    assert core.playback_subtitle(a.id) == translated
    core.execute_video_command(core.command_for_key("PgUp"), ())
    assert current_id(core) == first.id and core.playback_subtitle(a.id) == translated
    core.execute_video_command(core.command_for_key("PgDn"), ())
    assert core.reel_playback.video_id == b.id
    assert "source" in core.playback_subtitle(b.id).read_text(encoding="utf-8")
    core.toggle_subtitle_language()
    core.switch_to(b.id)  # 일반 재생의 재시작은 #8 정책대로 원어다.
    assert "source" in core.playback_subtitle(b.id).read_text(encoding="utf-8")
    core.start_reel()
    core.toggle_subtitle_language()
    core.start_reel()  # 새 모아보기 역시 원어로 시작한다.
    assert "source" in core.playback_subtitle(a.id).read_text(encoding="utf-8")


def test_playback_exposes_filtered_snapshot_position_and_total(library):
    core, _ = library
    a, b, _ = core.videos()
    first, ignored, last = mark(core, a, 10), mark(core, a, 20), mark(core, b, 30)
    tag = core.add_highlight_tag(first.id, "복습")
    core.add_highlight_tag(last.id, "복습")
    core.start_reel(tag.id, first.id)
    assert (core.reel_playback.index, core.reel_playback.total) == (1, 2)
    press(core, "End")
    assert current_id(core) == last.id
    assert (core.reel_playback.index, core.reel_playback.total) == (2, 2)
    press(core, "Home")
    assert (core.reel_playback.index, core.reel_playback.total) == (1, 2)


def test_seeking_back_before_a_deferred_advance_keeps_the_current_item(library):
    core, _ = library
    video = core.videos()[0]
    first = mark(core, video, 10, 20)
    mark(core, video, 40, 50)
    core.start_reel(None, first.id)
    core.playback.report(20)
    # 전환을 미룬 사이 사용자가 구간 안으로 되돌아가면 끝 도달은 취소된다.
    core.playback.report(15, seeked=True)
    core.advance_reel_if_due()
    assert current_id(core) == first.id
    core.playback.report(20)
    core.advance_reel_if_due()
    assert core.reel_playback.start == 40
