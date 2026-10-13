from datetime import datetime, timedelta, timezone

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.viewing import (
    Viewing, ViewingKind, ViewingSettings, merge_intervals, report_position,
)


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "video.mkv").write_bytes(b"video")
    clock = Clock()
    core = AppCore(media=Media(), clock=clock, database=tmp_path / "data/library.sqlite3")
    core.add_watched_folder(folder)
    core.scan()
    return core, core.videos()[0].id, clock


def watch(core, video_id, start, end):
    viewing = core.start_viewing(video_id)
    core.report_playback_position(viewing.id, start)
    core.report_playback_position(viewing.id, end)
    return core.end_viewing(viewing.id)


@pytest.mark.parametrize("intervals, expected", [
    ([], ()),
    ([(10, 20), (0, 5)], ((0, 5), (10, 20))),
    ([(0, 10), (5, 20), (0, 10)], ((0, 20),)),
    ([(20, 30), (0, 10), (10, 20)], ((0, 30),)),
    ([(0, 100), (10, 20)], ((0, 100),)),
    ([(-10, 4), (90, 120)], ((0, 4), (90, 100))),
    ([(3, 3), (20, 10), (-9, -1), (110, 120)], ()),
    ([(0.1, 0.2), (0.15, 0.3)], ((0.1, 0.3),)),
])
def test_interval_union(intervals, expected):
    assert merge_intervals(intervals, 100) == expected


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_invalid_duration(duration):
    with pytest.raises(ValueError):
        merge_intervals([], duration)


@pytest.mark.parametrize("position", [float("nan"), float("inf"), -float("inf")])
def test_invalid_position(position):
    with pytest.raises(ValueError):
        report_position(Viewing(1, 1, 100, NOW, NOW), position)
    with pytest.raises(ValueError):
        merge_intervals([(0, position)], 100)


@pytest.mark.parametrize("end, kind", [
    (0, ViewingKind.PREVIEW), (4.999, ViewingKind.PREVIEW),
    (5, ViewingKind.ABANDONED), (89.999, ViewingKind.ABANDONED),
    (90, ViewingKind.FINISHED), (100, ViewingKind.FINISHED),
])
def test_classification_boundaries(library, end, kind):
    core, video_id, _ = library
    viewing = watch(core, video_id, 0, end)
    assert viewing.classify(ViewingSettings()) == kind
    status = core.viewing_status(video_id)
    assert status.finished == (kind == ViewingKind.FINISHED)
    assert status.abandoned == (kind == ViewingKind.ABANDONED)
    assert not status.favorite


def test_seek_overlap_pause_and_position_based_speed(library):
    core, video_id, clock = library
    viewing = core.start_viewing(video_id)
    core.report_playback_position(viewing.id, 0)
    clock.advance(5)  # 2배속으로 영상 시간 10초를 본다.
    core.report_playback_position(viewing.id, 10)
    core.report_playback_position(viewing.id, 80, discontinuity=True)
    clock.advance(5)
    core.report_playback_position(viewing.id, 90)
    core.report_playback_position(viewing.id, 5, discontinuity=True)
    core.report_playback_position(viewing.id, 15)
    clock.advance(60)  # 일시정지: 시계만 흘러도 누적하지 않는다.
    core.report_playback_position(viewing.id, 15)
    result = core.end_viewing(viewing.id)
    assert result.intervals == ((0, 15), (80, 90))
    assert result.played_seconds == 25
    assert result.last_position == 15
    assert core.viewing_status(video_id).stopped_percent == 15


def test_tiny_forward_seek_is_not_played(library):
    core, video_id, _ = library
    viewing = core.start_viewing(video_id)
    for position, discontinuity in [(0, False), (4.9, False), (5.1, True), (5.15, False)]:
        core.report_playback_position(viewing.id, position, discontinuity=discontinuity)
    result = core.end_viewing(viewing.id)
    assert result.played_seconds == pytest.approx(4.95)
    assert result.classify(ViewingSettings()) == ViewingKind.PREVIEW


def test_first_report_is_baseline_and_reverse_report_does_not_count(library):
    core, video_id, _ = library
    viewing = core.start_viewing(video_id)
    for position in (80, 85, 20, 25):
        core.report_playback_position(viewing.id, position)
    assert core.end_viewing(viewing.id).played_seconds == 10


def test_empty_and_clamped_reports(library):
    core, video_id, _ = library
    empty = core.end_viewing(core.start_viewing(video_id).id)
    assert empty.played_seconds == 0
    assert core.resume_start(video_id) == 0
    result = watch(core, video_id, -5, 105)
    assert result.played_seconds == 100
    assert result.last_position == 100


def test_abandoned_display_uses_last_position_including_preview(library):
    core, video_id, _ = library
    watch(core, video_id, 0, 42)
    assert core.resume_start(video_id) == 39
    watch(core, video_id, 42, 60)
    assert core.viewing_status(video_id).stopped_percent == 60
    assert core.resume_start(video_id) == 57
    watch(core, video_id, 70, 72)  # 틀어보기도 마지막 정지 위치는 갱신한다.
    assert core.viewing_status(video_id).abandoned
    assert core.viewing_status(video_id).stopped_percent == 72
    assert core.resume_start(video_id) == 69
    watch(core, video_id, 1, 2)
    assert core.resume_start(video_id) == 0


def test_distinct_viewings_do_not_combine_and_finished_never_regresses(library):
    core, video_id, _ = library
    watch(core, video_id, 0, 50)
    watch(core, video_id, 50, 100)
    assert not core.viewing_status(video_id).finished
    watch(core, video_id, 0, 90)
    watch(core, video_id, 20, 22)
    status = core.viewing_status(video_id)
    assert status.finished and not status.abandoned
    assert status.resume_point is None and core.resume_start(video_id) == 0
    assert not status.favorite
    watch(core, video_id, 5, 100)
    assert core.viewing_status(video_id).favorite
    assert core.viewing_status(video_id).finished_count == 2


def test_settings_are_injected_and_history_reclassified(library):
    core, video_id, clock = library
    watch(core, video_id, 0, 75)
    settings = ViewingSettings(finished_ratio=0.8, abandoned_ratio=0.1, favorite_count=3, resume_rewind=7)
    reopened = AppCore(media=Media(), clock=clock, database=core.database, viewing_settings=settings)
    assert reopened.resume_start(video_id) == 68
    watch(reopened, video_id, 0, 80)
    watch(reopened, video_id, 0, 80)
    assert not reopened.viewing_status(video_id).favorite
    watch(reopened, video_id, 0, 80)
    assert reopened.viewing_status(video_id).favorite


@pytest.mark.parametrize("changes", [
    {"finished_ratio": 1.1}, {"abandoned_ratio": 0}, {"abandoned_ratio": 0.9},
    {"finished_ratio": float("nan")}, {"favorite_count": 0}, {"favorite_count": 1.5},
    {"resume_rewind": -1}, {"resume_rewind": float("inf")},
    {"save_interval": 0}, {"save_interval": float("nan")},
])
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        ViewingSettings(**changes)


def test_periodic_checkpoint_and_crash_recovery(library):
    core, video_id, clock = library
    viewing = core.start_viewing(video_id)
    core.report_playback_position(viewing.id, 0)
    clock.advance(5)
    core.report_playback_position(viewing.id, 40)
    checkpoint_time = clock()
    clock.advance(1)
    core.report_playback_position(viewing.id, 45)
    # end_viewing 없이 새 앱을 열어 강제 종료 후 복구를 재현한다.
    clock.advance(100)
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    recovered, = reopened.viewings(video_id)
    assert recovered.played_seconds == 40
    assert recovered.ended_at == checkpoint_time
    assert reopened.resume_start(video_id) == 37
    watch(reopened, video_id, 37, 50)
    again = AppCore(media=Media(), clock=clock, database=core.database)
    assert len(again.viewings(video_id)) == 2
    assert all(v.ended_at is not None for v in again.viewings(video_id))
    assert again.resume_start(video_id) == 47


def test_timer_saves_even_without_more_position_reports(library):
    core, video_id, clock = library
    viewing = core.start_viewing(video_id)
    core.report_playback_position(viewing.id, 0)
    core.report_playback_position(viewing.id, 30)
    clock.advance(5)
    core.save_viewings()
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    assert reopened.viewings(video_id)[0].played_seconds == 30


def test_close_forces_save_and_rejects_late_reports(library):
    core, video_id, clock = library
    result = watch(core, video_id, 0, 40)
    reopened = AppCore(media=Media(), clock=clock, database=core.database)
    assert reopened.viewings(video_id) == (result,)
    with pytest.raises(ValueError):
        core.report_playback_position(result.id, 45)
    with pytest.raises(ValueError):
        core.end_viewing(result.id)
    with pytest.raises(ValueError):
        core.start_viewing(999)
    with pytest.raises(ValueError):
        report_position(result, 45)


def test_playback_lifecycle_records_seeks_and_closes_on_switch(library):
    core, video_id, _ = library
    core.playback.start(video_id, 0)
    core.playback.report(10)
    core.playback.report(90, seeked=True)
    core.playback.report(95)
    core.playback.start(video_id, core.resume_start(video_id))
    first, second = core.viewings(video_id)
    assert first.ended_at is not None
    assert first.played_seconds == 15
    assert second.last_position == 92
    core.playback.report(98)
    core.playback.end()
    assert core.viewings(video_id)[1].played_seconds == 6
    core.playback.end()  # 화면 종료가 중복되어도 새 시청이 생기지 않는다.
    core.playback.report(100)
    assert len(core.viewings(video_id)) == 2


def test_non_viewing_playback_does_not_create_or_change_history(library):
    core, video_id, _ = library
    watch(core, video_id, 0, 40)
    before = core.viewings(video_id)
    core.playback.start(video_id, 10, record_viewing=False)
    core.playback.report(100)
    core.playback.end()
    assert core.viewings(video_id) == before
    assert core.resume_start(video_id) == 37
    core.playback.start(video_id, 37)
    core.playback.report(50)
    core.playback.start(video_id, 80, record_viewing=False)
    core.playback.report(100)
    core.playback.end()
    assert len(core.viewings(video_id)) == 2
    assert core.viewings(video_id)[1].played_seconds == 13


def test_preview_viewings_never_accumulate_into_abandoned(library):
    core, video_id, _ = library
    for start in range(0, 100, 4):
        watch(core, video_id, start, start + 4)
    status = core.viewing_status(video_id)
    assert not status.finished and not status.abandoned and not status.favorite
    assert status.stopped_percent is None and core.resume_start(video_id) == 0


def test_configurable_save_interval(library):
    core, video_id, clock = library
    core = AppCore(media=Media(), clock=clock, database=core.database,
                   viewing_settings=ViewingSettings(save_interval=2))
    core.playback.start(video_id, 0)
    clock.advance(2)
    core.playback.report(10)
    clock.advance(1)
    core.playback.report(15)
    recovered = AppCore(media=Media(), clock=clock, database=core.database)
    assert recovered.viewings(video_id)[0].played_seconds == 10


def test_configurable_abandoned_threshold(library):
    core, video_id, clock = library
    watch(core, video_id, 0, 5)
    core = AppCore(media=Media(), clock=clock, database=core.database,
                   viewing_settings=ViewingSettings(abandoned_ratio=0.1))
    assert not core.viewing_status(video_id).abandoned
    watch(core, video_id, 0, 10)
    assert core.viewing_status(video_id).abandoned
