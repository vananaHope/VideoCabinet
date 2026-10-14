"""시청 통계의 순수 계산과 일괄 조회 어댑터. 결과는 asdict 후 JSON으로 보낼 수 있다."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Iterable

from .viewing import (VideoViewingStatistics, Viewing, ViewingKind, ViewingRecord, ViewingSettings,
                      classify_viewing, merge_intervals, summarize_viewings)


@dataclass(frozen=True)
class StatisticsVideo:
    """통계에 필요한 영상 정보만 담는 입력. 자막 유무는 기존 has_transcript와 같다."""
    id: int
    title: str
    registered_at: datetime
    excluded: bool = False
    missing: bool = False
    has_subtitles: bool = False
    highlight_count: int = 0


@dataclass(frozen=True)
class DailyViewingStatistics:
    date: str
    watched_seconds: float
    viewing_count: int


@dataclass(frozen=True)
class TopViewedVideo:
    video_id: int
    title: str
    watched_seconds: float
    viewing_count: int
    excluded: bool
    missing: bool


@dataclass(frozen=True)
class LibraryStatistics:
    finished_count: int
    abandoned_count: int
    unwatched_count: int
    subtitled_video_count: int
    highlight_count: int


@dataclass(frozen=True)
class ViewingStatistics:
    days: int
    start_date: str
    end_date: str
    watched_seconds: float
    viewing_count: int
    previous_watched_seconds: float
    previous_viewing_count: int
    # None은 화면의 "이전 기록 없음"에 해당한다. 0%와 구별한다.
    watched_seconds_change_percent: float | None
    viewing_count_change_percent: float | None
    watched_video_count: int
    watched_day_count: int
    longest_streak_days: int
    added_video_count: int
    average_seconds: float
    daily: tuple[DailyViewingStatistics, ...]
    top_videos: tuple[TopViewedVideo, ...]
    library: LibraryStatistics


def _records(viewings: Iterable[Viewing]) -> Iterable[ViewingRecord]:
    """임의 구간도 받는 순수 API의 입력 어댑터. 저장소 조회 경로에서는 쓰지 않는다."""
    for viewing in viewings:
        seconds = sum(end - start for start, end in merge_intervals(viewing.intervals, viewing.duration))
        yield ViewingRecord(viewing.id, viewing.video_id, viewing.duration, seconds,
                            viewing.started_at, viewing.updated_at, viewing.last_position)


class _LocalDates:
    """한 집계 안에서만 분 단위 변환을 공유한다. offset과 fold를 구분한다."""

    def __init__(self, tz: tzinfo | None, *, system_local: bool = False):
        self.tz, self.system_local = tz, system_local
        self._minutes: dict[tuple, date] = {}

    def __call__(self, value: str | datetime) -> date:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if self.tz is None and not self.system_local:
            return value.date()
        if value.tzinfo is None and self.tz is not None:
            value = value.replace(tzinfo=self.tz)
        key = (value.year, value.month, value.day, value.hour, value.minute, value.utcoffset(), value.fold)
        day = self._minutes.get(key)
        if day is None:
            converted = value.astimezone(self.tz)
            day = converted.date()
            # 초 단위 offset은 한 입력 분 안에서 로컬 자정이 바뀔 수 있다.
            if converted.second == value.second and converted.microsecond == value.microsecond:
                self._minutes[key] = day
        return day


def video_viewing_statistics(
    viewings: Iterable[Viewing], video_ids: Iterable[int],
    settings: ViewingSettings = ViewingSettings(),
) -> dict[int, VideoViewingStatistics]:
    """기간 제한 없는 수치. 시청 없는 영상도 0/None으로 반환한다."""
    return summarize_viewings(_records(viewings), video_ids, settings).statistics


def viewing_statistics(
    viewings: Iterable[Viewing], videos: Iterable[StatisticsVideo],
    days: int, today: date, tz: tzinfo | None,
    settings: ViewingSettings = ViewingSettings(),
) -> ViewingStatistics:
    """오늘 포함 최근 days일과 바로 앞의 같은 일수 기간을 비교한다.

    tz를 지정하면 시작/등록 시각을 그 시간대로 변환한다. naive 시각은 해당
    시간대의 로컬 시각으로 해석한다. tz=None이면 입력이 이미 로컬 시각이어야
    한다. 출력 날짜/시각은 ISO 문자열이고 시간은 영상 기준 초다.
    라이브러리 현황은 전체 기간이며 제외 영상만 뺀다.
    """
    return _period_statistics(_records(viewings), videos, days, today, _LocalDates(tz), settings)


def _period_statistics(records, videos, days, today, local_date, settings) -> ViewingStatistics:
    if type(days) is not int or days not in (7, 30, 90, 365):
        raise ValueError("통계 기간은 7·30·90·365일 중 하나여야 합니다.")
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    videos = {video.id: video for video in videos}
    daily_seconds = [0.0] * days
    daily_counts = [0] * days
    video_seconds: dict[int, float] = {}
    video_counts: dict[int, int] = {}
    finished, abandoned = set(), set()
    previous_seconds, previous_count = 0.0, 0
    for viewing in records:
        if viewing.video_id not in videos:
            continue
        kind = classify_viewing(viewing.played_seconds, viewing.duration, settings)
        if kind == ViewingKind.GLANCE:
            continue
        (finished if kind == ViewingKind.FINISHED else abandoned).add(viewing.video_id)
        day = local_date(viewing.started_at)
        if start <= day <= today:
            offset = (day - start).days
            seconds = viewing.played_seconds
            daily_seconds[offset] += seconds
            daily_counts[offset] += 1
            vid = viewing.video_id
            video_seconds[vid] = video_seconds.get(vid, 0.0) + seconds
            video_counts[vid] = video_counts.get(vid, 0) + 1
        elif previous_start <= day < start:
            previous_seconds += viewing.played_seconds
            previous_count += 1

    watched_seconds, count = sum(daily_seconds), sum(daily_counts)
    longest = streak = 0
    for daily_count in daily_counts:
        streak = streak + 1 if daily_count else 0
        longest = max(longest, streak)
    visible = [video for video in videos.values() if not video.excluded]
    finished_count = sum(video.id in finished for video in visible)
    abandoned_count = sum(video.id in abandoned and video.id not in finished for video in visible)
    ranked = sorted(video_counts, key=lambda vid: (
        -video_seconds[vid], -video_counts[vid], videos[vid].title, vid))[:5]
    return ViewingStatistics(
        days, start.isoformat(), today.isoformat(), watched_seconds, count,
        previous_seconds, previous_count,
        (watched_seconds - previous_seconds) / previous_seconds * 100 if previous_seconds else None,
        (count - previous_count) / previous_count * 100 if previous_count else None,
        len(video_counts), sum(value > 0 for value in daily_counts), longest,
        sum(start <= local_date(video.registered_at) <= today for video in visible),
        watched_seconds / count if count else 0.0,
        tuple(DailyViewingStatistics((start + timedelta(days=i)).isoformat(), seconds, daily_counts[i])
              for i, seconds in enumerate(daily_seconds)),
        tuple(TopViewedVideo(vid, videos[vid].title, video_seconds[vid], video_counts[vid],
                             videos[vid].excluded, videos[vid].missing) for vid in ranked),
        LibraryStatistics(finished_count, abandoned_count, len(visible) - finished_count - abandoned_count,
                          sum(video.has_subtitles for video in visible),
                          sum(video.highlight_count for video in visible)),
    )


class StatisticsReader:
    """접속·시계·시청 저장소를 주입하는 얇은 일괄 조회 어댑터. DB는 변경하지 않는다."""

    def __init__(self, connect, clock, viewings):
        self._connect, self._clock, self._viewings = connect, clock, viewings

    def video_map(self) -> dict[int, VideoViewingStatistics]:
        return self._viewings.summary().statistics

    def period(self, days: int, *, tz: tzinfo | None = None) -> ViewingStatistics:
        now = self._clock()
        if now.tzinfo is None and tz is not None:
            now = now.replace(tzinfo=tz)
        now = now.astimezone(tz)
        with self._connect() as db:
            db.execute("BEGIN")
            locations = db.execute("SELECT DISTINCT video_id FROM locations").fetchall()
            transcripts = db.execute("SELECT video_id FROM transcripts").fetchall()
            highlight_rows = db.execute("SELECT video_id, COUNT(*) FROM highlights GROUP BY video_id").fetchall()
            video_rows = db.execute("SELECT id, title, registered_at, excluded FROM videos").fetchall()
            snapshot = self._viewings.read_rows(connection=db)
        located = {row[0] for row in locations}
        subtitled = {row[0] for row in transcripts}
        highlights = dict(highlight_rows)
        videos = tuple(StatisticsVideo(
            row["id"], row["title"], datetime.fromisoformat(row["registered_at"]),
            bool(row["excluded"]), row["id"] not in located, row["id"] in subtitled,
            highlights.get(row["id"], 0),
        ) for row in video_rows)
        return _period_statistics(snapshot.records(), videos, days, now.date(),
                                  _LocalDates(tz, system_local=tz is None), self._viewings.settings)
