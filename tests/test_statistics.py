"""순수 통계와 AppCore 공개 시나리오: 기간 경계, 분류, 복습, 일괄 조회."""

from dataclasses import asdict, replace
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone, tzinfo
import json
import sqlite3
from threading import Event, get_ident

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.statistics import StatisticsVideo, video_viewing_statistics, viewing_statistics
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.viewing import (Viewing, ViewingKind, ViewingRecord, ViewingSettings, ViewingStatus,
                                     summarize_viewings, viewing_status)


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


def test_library_snapshot_includes_statistics_with_one_viewing_query(library, monkeypatch):
    core, _, (a, b, _) = library
    watch(core, a.id, 90)
    watch(core, a.id, 90)
    watch(core, b.id, 20)
    expected_statuses = {v.id: core.viewing_status(v.id) for v in core.videos()}
    expected_statistics = core.video_viewing_statistics()
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    snapshot = core.library_snapshot()
    assert snapshot.video_statistics == expected_statistics
    assert snapshot.statuses == expected_statuses
    assert sum("FROM viewings" in sql for sql in statements) == 1


@pytest.mark.parametrize("settings", [ViewingSettings(), ViewingSettings(
    finished_ratio=0.8, abandoned_ratio=0.1, favorite_count=3)])
def test_combined_summary_matches_original_status_and_statistics_for_every_video(settings):
    # 분류 경계·같은 시작 시각·ID와 역순인 updated_at·마지막 위치 없는 시청을 섞는다.
    # 통합 전 상태 계산을 독립 기준으로 남겨 두 경로가 같은 결함을 공유해도 잡는다.
    grouped = {vid: [] for vid in range(1, 51)}
    seconds = [0, 4.999, 5, 9.999, 10, 79.999, 80, 89.999, 90, 100]
    records = []
    for vid in grouped:
        for i in range(vid % 13):
            row = replace(viewing(vid, seconds=seconds[(vid + i) % len(seconds)], ident=vid * 20 + i),
                          updated_at=NOW - timedelta(seconds=i),
                          last_position=None if i % 4 == 0 else float(i * 3))
            grouped[vid].append(row)
            records.append(ViewingRecord(row.id, vid, row.duration, row.played_seconds,
                                         row.started_at, row.updated_at, row.last_position))
    # 순서를 바꿔도 마지막 정지 위치는 가장 큰 ID에서 가져와야 한다.
    summary = summarize_viewings(reversed(records), grouped, settings)
    for vid, rows in grouped.items():
        finished_count = sum(row.classify(settings) == ViewingKind.FINISHED for row in rows)
        finished = finished_count > 0
        abandoned = not finished and any(row.classify(settings) == ViewingKind.ABANDONED for row in rows)
        last = max((row for row in rows if row.last_position is not None), key=lambda row: row.id, default=None)
        point = last.last_position if abandoned and last is not None else None
        expected = ViewingStatus(
            finished, abandoned, finished_count >= settings.favorite_count, finished_count,
            point, point / last.duration * 100 if point is not None else None,
            max((row.updated_at for row in rows), default=None))
        assert viewing_status(tuple(rows), settings) == expected
        assert summary.statuses[vid] == expected
        counted = [row for row in rows if row.classify(settings) != ViewingKind.GLANCE]
        stats = summary.statistics[vid]
        assert stats.viewing_count == len(counted)
        assert stats.watched_seconds == pytest.approx(sum(row.played_seconds for row in counted))
        assert stats.last_viewed_at == (expected.last_viewed_at.isoformat() if expected.last_viewed_at else None)


def test_resume_percent_uses_duration_of_last_position_even_when_latest_viewing_has_none():
    rows = (
        replace(viewing(seconds=50, ident=1), last_position=50),
        replace(viewing(seconds=1, ident=2), duration=200, last_position=60),
        replace(viewing(seconds=0, ident=3), duration=1000, last_position=None),
    )
    records = [ViewingRecord(v.id, v.video_id, v.duration, v.played_seconds,
                             v.started_at, v.updated_at, v.last_position) for v in rows]
    expected = ViewingStatus(abandoned=True, resume_point=60, stopped_percent=30,
                             last_viewed_at=rows[0].updated_at)
    assert viewing_status(rows, ViewingSettings()) == expected
    assert summarize_viewings(reversed(records), [1], ViewingSettings()).statuses[1] == expected
    assert calculate(rows).library.abandoned_count == 1
    assert calculate(rows).library.finished_count == 0


@pytest.mark.parametrize('settings', [ViewingSettings(), ViewingSettings(finished_ratio=0.8, abandoned_ratio=0.1)])
def test_period_inventory_matches_all_time_status_with_glances_and_exclusions(settings):
    rows = [viewing(1, seconds=85), viewing(1, seconds=1, ident=2),
            viewing(2, seconds=6), viewing(3, seconds=1), viewing(4, seconds=100)]
    rows = [replace(v, started_at=NOW - timedelta(days=90)) for v in rows]
    result = calculate(rows, [video(vid, excluded=vid == 4) for vid in range(1, 6)], settings=settings)
    statuses = [viewing_status(tuple(v for v in rows if v.video_id == vid), settings) for vid in range(1, 4)]
    assert result.viewing_count == 0
    assert result.library.finished_count == sum(s.finished for s in statuses)
    assert result.library.abandoned_count == sum(s.abandoned for s in statuses)
    assert result.library.unwatched_count == 4 - sum(s.finished or s.abandoned for s in statuses)


@pytest.mark.parametrize("days", [7, 365])
@pytest.mark.parametrize("tz", [None, UTC, KST, timezone(timedelta(hours=-5)),
                                timezone(timedelta(seconds=30))])
def test_period_reader_matches_pure_api_with_local_dates_and_active_viewing(library, days, tz):
    core, clock, videos = library
    a, b, c = videos
    for offset, seconds in ((-730, 95), (-365, 90), (-14, 25), (-7, 10), (-6, 5), (0, 1)):
        clock.now = NOW + timedelta(days=offset)
        watch(core, a.id, seconds)
    # 같은 입력 분이 로컬 자정을 가르는 초 단위 offset도 확인한다.
    for second in (20, 40):
        clock.now = datetime(2026, 10, 13, 23, 59, second, tzinfo=UTC)
        watch(core, b.id, 20)
    clock.now = NOW
    core.exclude_video(a.id)
    c.locations[0].path.unlink()
    core.scan()
    core.playback.start(b.id, 0)
    core.playback.report(30)
    inputs = [StatisticsVideo(v.id, v.title,
                              v.registered_at.astimezone() if tz is None else v.registered_at,
                              v.excluded, v.missing) for v in (*core.videos(), *core.excluded_videos())]
    rows = [row for v in videos for row in core.viewings(v.id)]
    if tz is None:
        rows = [replace(row, started_at=row.started_at.astimezone()) for row in rows]
    expected = viewing_statistics(rows, inputs, days, clock.now.astimezone(tz).date(), tz)
    assert core.viewing_statistics(days, tz=tz) == expected


def test_minute_memo_preserves_offset_and_second_boundaries():
    rows = [viewing(when=datetime(2026, 10, 13, 23, 59, second, tzinfo=UTC)) for second in (20, 40)]
    result = calculate(rows, tz=timezone(timedelta(seconds=30)))
    assert result.daily[-2].viewing_count == result.daily[-1].viewing_count == 1
    rows = [viewing(when=datetime(2026, 10, 14, 0, 30, tzinfo=KST)),
            viewing(when=datetime(2026, 10, 14, 0, 30, tzinfo=UTC))]
    result = calculate(rows, tz=UTC)
    assert result.daily[-2].viewing_count == result.daily[-1].viewing_count == 1


def test_minute_memo_distinguishes_repeated_local_minute_fold():
    class RepeatedMidnight(tzinfo):
        def utcoffset(self, dt):
            return timedelta(hours=1 - dt.fold)

        def dst(self, dt):
            return timedelta(0)

    repeated = RepeatedMidnight()
    rows = [viewing(when=datetime(2026, 10, 14, 0, 30, tzinfo=repeated, fold=fold)) for fold in (0, 1)]
    result = calculate(rows, tz=UTC)
    assert result.daily[-2].viewing_count == result.daily[-1].viewing_count == 1


@pytest.mark.parametrize("operation", ["snapshot", "video", "period", "dashboard"])
def test_background_parsing_releases_lock_and_keeps_active_snapshot(library, monkeypatch, operation):
    core, clock, (a, b, _) = library
    watch(core, a.id, 90)
    core.playback.start(b.id, 0)
    core.playback.report(20)  # 아직 저장되지 않은 진행분
    query = {"snapshot": core.library_snapshot, "video": core.video_viewing_statistics,
             "period": lambda: core.viewing_statistics(7, tz=KST),
             "dashboard": lambda: core.statistics_dashboard(7, tz=KST)}[operation]
    expected = query()
    parsing, resume = Event(), Event()
    main_thread = get_ident()
    original_loads, original_connect = json.loads, sqlite3.connect

    def parked_loads(*args, **kwargs):
        if get_ident() != main_thread and not parsing.is_set():
            parsing.set()
            assert resume.wait(10)
        return original_loads(*args, **kwargs)

    def short_timeout_connect(*args, **kwargs):
        kwargs["timeout"] = 0.05
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(json, "loads", parked_loads)
    monkeypatch.setattr(sqlite3, "connect", short_timeout_connect)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(query)
        try:
            assert parsing.wait(10)
            clock.now += timedelta(seconds=1)
            core.playback.report(40)
            core.playback.end()  # 파싱을 멈춰 둔 동안에도 쓰기 커밋이 완료되어야 한다.
        finally:
            resume.set()
        assert result.result(timeout=10) == expected
    # 읽던 순간의 진행분은 20초, 종료 후 새 조회는 40초다.
    assert core.video_viewing_statistics()[b.id].watched_seconds == 40
