"""시청 통계의 순수 계산과 일괄 조회 어댑터. 결과는 asdict 후 JSON으로 보낼 수 있다."""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from typing import Iterable

from .viewing import Viewing, ViewingKind, ViewingSettings, merge_intervals


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
class VideoViewingStatistics:
    video_id: int
    viewing_count: int = 0
    watched_seconds: float = 0.0
    # ViewingStatus.last_viewed_at과 같은 updated_at 최댓값. 틀어보기도 포함한다.
    last_viewed_at: str | None = None


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


def _normalized(viewing: Viewing) -> Viewing:
    return replace(viewing, intervals=merge_intervals(viewing.intervals, viewing.duration))


def _local_date(value: datetime, tz: tzinfo | None) -> date:
    # None은 이미 각 시각의 로컬 시간대로 변환한 입력이라는 뜻이다.
    # OS 시간대나 실제 시계를 읽지 않아 순수 함수에서 DST까지 재현할 수 있다.
    if tz is None:
        return value.date()
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(tz).date()


def video_viewing_statistics(
    viewings: Iterable[Viewing], video_ids: Iterable[int],
    settings: ViewingSettings = ViewingSettings(),
) -> dict[int, VideoViewingStatistics]:
    """기간 제한 없는 수치. 시청 없는 영상도 0/None으로 반환한다."""
    counts = dict.fromkeys(video_ids, 0)
    seconds = dict.fromkeys(counts, 0.0)
    last: dict[int, datetime] = {}
    for viewing in viewings:
        vid = viewing.video_id
        if vid not in counts:
            continue
        if vid not in last or viewing.updated_at > last[vid]:
            last[vid] = viewing.updated_at
        viewing = _normalized(viewing)
        if viewing.classify(settings) != ViewingKind.GLANCE:
            counts[vid] += 1
            seconds[vid] += viewing.played_seconds
    return {vid: VideoViewingStatistics(vid, count, seconds[vid],
                                       last[vid].isoformat() if vid in last else None)
            for vid, count in counts.items()}


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
    for viewing in viewings:
        if viewing.video_id not in videos:
            continue
        viewing = _normalized(viewing)
        kind = viewing.classify(settings)
        if kind == ViewingKind.GLANCE:
            continue
        (finished if kind == ViewingKind.FINISHED else abandoned).add(viewing.video_id)
        day = _local_date(viewing.started_at, tz)
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
        sum(start <= _local_date(video.registered_at, tz) <= today for video in visible),
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
        with self._connect() as db:
            db.execute("BEGIN")
            ids = [row[0] for row in db.execute("SELECT id FROM videos")]
            viewings = self._viewings.list_all(connection=db)
        return video_viewing_statistics(viewings, ids, self._viewings.settings)

    def period(self, days: int, *, tz: tzinfo | None = None) -> ViewingStatistics:
        now = self._clock()
        if now.tzinfo is None and tz is not None:
            now = now.replace(tzinfo=tz)
        now = now.astimezone(tz)
        with self._connect() as db:
            db.execute("BEGIN")
            located = {row[0] for row in db.execute("SELECT DISTINCT video_id FROM locations")}
            subtitled = {row[0] for row in db.execute("SELECT video_id FROM transcripts")}
            highlights = dict(db.execute("SELECT video_id, COUNT(*) FROM highlights GROUP BY video_id"))
            videos = tuple(StatisticsVideo(
                row["id"], row["title"], datetime.fromisoformat(row["registered_at"]),
                bool(row["excluded"]), row["id"] not in located, row["id"] in subtitled,
                highlights.get(row["id"], 0),
            ) for row in db.execute("SELECT id, title, registered_at, excluded FROM videos"))
            viewings = self._viewings.list_all(connection=db)
        if tz is None:
            # astimezone()를 각 날짜에 적용한다. 현재 UTC offset을 과거 날짜에도
            # 적용하면 시스템 시간대의 DST 경계에서 잘못된 날로 셀 수 있다.
            videos = tuple(replace(v, registered_at=v.registered_at.astimezone()) for v in videos)
            viewings = tuple(replace(v, started_at=v.started_at.astimezone()) for v in viewings)
        return viewing_statistics(viewings, videos, days, now.date(), tz, self._viewings.settings)
