"""순수 통계와 AppCore 공개 시나리오: 기간 경계, 분류, 복습, 일괄 조회."""

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
import json
import sqlite3

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.statistics import StatisticsVideo, video_viewing_statistics, viewing_statistics
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.viewing import Viewing, ViewingSettings


UTC = timezone.utc
KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 12, tzinfo=KST)


def viewing(vid=1, when=NOW, seconds=50, *, ident=1):
    return Viewing(ident, vid, 100, when, when + timedelta(seconds=1),
                   intervals=((0, seconds),))


def video(vid=1, title="영상", **kwargs):
    return StatisticsVideo(vid, title, NOW, **kwargs)


def calculate(viewings=(), videos=None, days=7, tz=KST, settings=ViewingSettings()):
    return viewing_statistics(viewings, [video()] if videos is None else videos, days, TODAY, tz, settings)


@pytest.mark.parametrize("days", [7, 30, 90, 365])
def test_pure_period_boundaries_include_today_and_local_midnights(days):
    start = datetime.combine(TODAY - timedelta(days=days - 1), datetime.min.time(), KST)
    previous_start = start - timedelta(days=days)
    tomorrow = datetime.combine(TODAY + timedelta(days=1), datetime.min.time(), KST)
    times = [previous_start - timedelta(microseconds=1), previous_start,
             start - timedelta(microseconds=1), start,
             tomorrow - timedelta(microseconds=1), tomorrow]
    # 저장 시각은 UTC여도 시작한 로컬 날짜로 집계한다.
    rows = [viewing(when=t.astimezone(UTC)) for t in times]
    result = calculate(rows, days=days)
    assert result.viewing_count == result.previous_viewing_count == 2
    assert result.watched_seconds == result.previous_watched_seconds == 100
    assert result.watched_seconds_change_percent == result.viewing_count_change_percent == 0
    assert result.start_date == start.date().isoformat()
    assert result.end_date == TODAY.isoformat()
    assert len(result.daily) == days
    assert result.daily[0].viewing_count == result.daily[-1].viewing_count == 1


def test_timezone_is_injected_and_localized_inputs_keep_their_own_offsets():
    before_korean_midnight = datetime(2026, 10, 13, 14, 59, 59, tzinfo=UTC)
    after_korean_midnight = before_korean_midnight + timedelta(seconds=1)
    rows = [viewing(when=before_korean_midnight), viewing(when=after_korean_midnight)]
    assert calculate(rows).daily[-1].viewing_count == 1
    assert calculate(rows, tz=UTC).daily[-1].viewing_count == 0
    localized = [replace(v, started_at=v.started_at.astimezone(KST)) for v in rows]
    assert calculate(localized, tz=None) == calculate(rows)


def test_overlap_clipping_and_configured_classification_are_reused():
    rows = [replace(viewing(), intervals=((-10, 10), (5, 20), (90, 110))),
            viewing(seconds=4.999), viewing(seconds=5)]
    result = calculate(rows)
    assert (result.watched_seconds, result.viewing_count, result.average_seconds) == (35, 2, 17.5)
    custom = calculate(rows, settings=ViewingSettings(abandoned_ratio=0.3))
    assert (custom.watched_seconds, custom.viewing_count) == (30, 1)
    assert video_viewing_statistics(rows, [1], ViewingSettings(abandoned_ratio=0.3))[1].watched_seconds == 30


@pytest.mark.parametrize("previous,current,expected", [(0, 0, None), (0, 1, None), (2, 0, -100),
                                                        (1, 2, 100), (2, 1, -50)])
def test_percentage_change_has_explicit_no_previous_record(previous, current, expected):
    rows = [viewing(when=NOW - timedelta(days=7)) for _ in range(previous)]
    rows += [viewing() for _ in range(current)]
    result = calculate(rows)
    assert result.watched_seconds_change_percent == result.viewing_count_change_percent == expected


@pytest.mark.parametrize("offsets,longest,watched_days", [([], 0, 0), ([0], 1, 1),
    ([0, 1, 2, 4, 5, 6], 3, 6), ([0, 0, 1, 2, 3, 4, 5, 6, 7], 7, 7), ([2, 3, 4, 6], 3, 4)])
def test_longest_streak_is_within_period_and_does_not_require_today(offsets, longest, watched_days):
    result = calculate([viewing(when=NOW - timedelta(days=d)) for d in offsets])
    assert result.longest_streak_days == longest
    assert result.watched_day_count == watched_days


def test_empty_period_has_zero_daily_series_and_all_time_library_status():
    result = calculate([viewing(when=NOW - timedelta(days=60), seconds=90)])
    assert result.viewing_count == result.watched_seconds == result.average_seconds == 0
    assert result.watched_video_count == result.watched_day_count == result.longest_streak_days == 0
    assert result.top_videos == ()
    assert len(result.daily) == 7
    assert all(day.watched_seconds == day.viewing_count == 0 for day in result.daily)
    assert result.library.finished_count == 1
    assert result.library.unwatched_count == 0
    assert calculate(videos=[]).library.unwatched_count == 0
    json.dumps(asdict(result), ensure_ascii=False, allow_nan=False)


def test_top_five_sort_time_then_count_then_title_and_keep_excluded_missing():
    videos = [video(i, title, excluded=i == 2, missing=i == 3)
              for i, title in enumerate(["최다", "횟수", "가", "나", "다", "라"], 1)]
    rows = [viewing(1, seconds=80), viewing(2, seconds=25), viewing(2, seconds=25)]
    rows += [viewing(i, seconds=50) for i in range(3, 7)]
    rows += [viewing(6, when=NOW - timedelta(days=8), seconds=100)]
    result = calculate(rows, videos)
    assert [v.video_id for v in result.top_videos] == [1, 2, 3, 4, 5]
    assert result.top_videos[1].excluded
    assert result.top_videos[2].missing
    assert result.watched_video_count == 6
    assert result.watched_seconds == 330


def test_registered_dates_and_library_exclude_only_excluded_videos():
    start = datetime(2026, 10, 8, tzinfo=KST)
    videos = [replace(video(1, has_subtitles=True, highlight_count=2), registered_at=start.astimezone(UTC)),
              video(2, excluded=True, has_subtitles=True, highlight_count=9),
              video(3, missing=True, has_subtitles=True, highlight_count=3),
              replace(video(4), registered_at=start - timedelta(microseconds=1)),
              replace(video(5), registered_at=NOW + timedelta(days=1))]
    result = calculate([viewing(1, seconds=90), viewing(1, seconds=50), viewing(2, seconds=90),
                        viewing(3, seconds=10), viewing(4, seconds=1)], videos)
    assert result.added_video_count == 2
    assert asdict(result.library) == dict(finished_count=1, abandoned_count=1, unwatched_count=2,
                                        subtitled_video_count=2, highlight_count=5)


@pytest.mark.parametrize("days", [0, -7, 1, 8, 7.0, True, "7", None])
def test_unsupported_periods_are_rejected(days):
    with pytest.raises(ValueError, match="7·30·90·365"):
        calculate(days=days)


class Clock:
    now = NOW

    def __call__(self):
        return self.now


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Transcriber:
    def transcribe(self, path, spoken_language, *, cancellation, progress=None):
        return TranscriberResult("ko", (TranscriptSegment(0, 2, "자막"),))


@pytest.fixture
def library(tmp_path):
    clock = Clock()
    core = AppCore(media=Media(), clock=clock, database=tmp_path / "data/library.sqlite3",
                   transcriber=Transcriber(), viewing_settings=ViewingSettings(save_interval=3600))
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.mkv"
        path.write_bytes(name.encode())
        core.add_file(path)
    return core, clock, core.videos()


def watch(core, vid, seconds):
    core.playback.start(vid, 0)
    core.playback.report(seconds)
    core.playback.end()


@pytest.mark.parametrize("days", [7, 30, 90, 365])
def test_core_fake_clock_and_local_period_boundaries(library, days):
    core, clock, (a, _, _) = library
    start = datetime.combine(TODAY - timedelta(days=days - 1), datetime.min.time(), KST)
    for at in (start - timedelta(seconds=1), start, NOW):
        clock.now = at.astimezone(UTC)
        watch(core, a.id, 10)
    result = core.viewing_statistics(days, tz=KST)
    assert result.viewing_count == 2
    assert result.previous_viewing_count == 1
    assert result.viewing_count_change_percent == 100
    assert result.daily[0].viewing_count == result.daily[-1].viewing_count == 1


def test_core_active_viewing_speed_overlap_glance_and_last_timestamp(library):
    core, clock, (a, b, _) = library
    core.playback.start(a.id, 0)
    clock.now += timedelta(seconds=5)  # 2배속: 벽시계 5초에 영상 10초
    core.playback.report(10)
    core.playback.report(5, seeked=True)
    core.playback.report(20)
    assert core.viewing_statistics(7, tz=KST).watched_seconds == 20
    assert core.video_viewing_statistics()[a.id].watched_seconds == 20
    core.playback.end()
    clock.now += timedelta(days=1)
    watch(core, a.id, 1)
    watch(core, b.id, 1)
    stats = core.video_viewing_statistics()
    assert stats[a.id].viewing_count == 1
    assert stats[a.id].watched_seconds == 20
    assert stats[b.id].viewing_count == stats[b.id].watched_seconds == 0
    assert stats[a.id].last_viewed_at == core.viewing_status(a.id).last_viewed_at.isoformat()
    assert stats[b.id].last_viewed_at == clock.now.isoformat()
    assert stats[core.videos()[2].id].last_viewed_at is None
    assert core.viewing_statistics(7, tz=KST).viewing_count == 1
    json.dumps({vid: asdict(value) for vid, value in stats.items()}, allow_nan=False)


def test_core_reel_revisit_never_enters_viewing_statistics(library):
    core, clock, (a, _, _) = library
    core.playback.start(a.id, 10, record_viewing=False)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    highlight = core.highlights(a.id)[0]
    core.update_highlight(highlight.id, start=10, end=20, note="복습")
    before = core.video_viewing_statistics()
    core.start_reel(highlight_id=highlight.id)
    clock.now += timedelta(seconds=4)
    core.playback.report(14)
    core.playback.end()
    assert core.last_highlight_revisited_at(highlight.id) is not None
    assert core.viewings(a.id) == ()
    assert core.video_viewing_statistics() == before
    result = core.viewing_statistics(7, tz=KST)
    assert result.viewing_count == result.watched_seconds == 0
    assert result.library.highlight_count == 1


def test_core_library_counts_excluded_missing_subtitles_and_restart(library):
    core, clock, (a, b, c) = library
    for v in (a, b):
        core.request_subtitles(v.id)
        assert core.process_next_subtitle().state == "completed"
        core.playback.start(v.id, 0)
        core.execute_highlight_command(core.command_for_key("Insert"))
        core.playback.report(90 if v == a else 20)
        core.playback.end()
    core.exclude_video(a.id)
    b.locations[0].path.unlink()
    core.scan()
    result = core.viewing_statistics(7, tz=KST)
    assert asdict(result.library) == dict(finished_count=0, abandoned_count=1, unwatched_count=1,
                                        subtitled_video_count=1, highlight_count=1)
    assert result.added_video_count == 2
    assert result.viewing_count == 2
    assert result.top_videos[0].excluded and result.top_videos[1].missing
    assert set(core.video_viewing_statistics()) == {a.id, b.id, c.id}
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    assert reopened.viewing_statistics(7, tz=KST) == result
    assert reopened.video_viewing_statistics() == core.video_viewing_statistics()


def test_query_count_is_constant_as_videos_increase(library, tmp_path, monkeypatch):
    core, _, _ = library
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)

    def counts():
        result = []
        for query in (core.video_viewing_statistics, lambda: core.viewing_statistics(7, tz=KST)):
            statements.clear()
            query()
            result.append(sum(sql.startswith("SELECT") for sql in statements))
        return result

    small = counts()
    for i in range(20):
        path = tmp_path / f"extra{i}.mkv"
        path.write_bytes(str(i).encode())
        core.add_file(path)
    assert counts() == small == [2, 5]
