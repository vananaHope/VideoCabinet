"""시청 통계의 순수 계산과 일괄 조회 어댑터. 결과는 asdict 후 JSON으로 보낼 수 있다."""

from .translation_source import ONSCREEN, TRANSCRIPT

from dataclasses import dataclass
from bisect import bisect_right
from datetime import date, datetime, timedelta, tzinfo
from typing import Iterable

from .viewing import (VideoViewingStatistics, Viewing, ViewingKind, ViewingRecord, ViewingSettings,
                      _ViewingState, merge_intervals, summarize_viewings)


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


@dataclass(frozen=True)
class DistributionBucket:
    label: str
    video_count: int


@dataclass(frozen=True)
class LibraryInventory:
    video_count: int
    duration_seconds: float
    known_size_bytes: int
    unknown_size_count: int
    all_watched_seconds: float
    korean_subtitled_count: int
    never_played_count: int
    highlighted_video_count: int
    tagged_video_count: int
    duration_distribution: tuple[DistributionBucket, ...]
    format_distribution: tuple[DistributionBucket, ...]
    resolution_distribution: tuple[DistributionBucket, ...]
    resolution_pending_count: int
    resolution_pending_description: str


@dataclass(frozen=True)
class StatisticsDashboard:
    period: ViewingStatistics
    weekday_seconds: tuple[float, ...]
    hourly_seconds: tuple[float, ...]
    inventory: LibraryInventory


def _records(viewings: Iterable[Viewing]) -> Iterable[ViewingRecord]:
    """임의 구간도 받는 순수 API의 입력 어댑터. 저장소 조회 경로에서는 쓰지 않는다."""
    for viewing in viewings:
        seconds = sum(end - start for start, end in merge_intervals(viewing.intervals, viewing.duration))
        yield ViewingRecord(viewing.id, viewing.video_id, viewing.duration, seconds,
                            viewing.started_at, viewing.updated_at, viewing.last_position)


class _LocalDates:
    """기간의 로컬 자정을 한 번만 변환하고 시작 시각을 이진 검색한다."""

    def __init__(self, tz: tzinfo | None, *, system_local: bool = False):
        self.tz, self.system_local = tz, system_local

    def prepare(self, first: date, last: date):
        self.dates = [first + timedelta(days=i) for i in range((last - first).days + 2)]
        self.boundaries = [datetime.combine(day, datetime.min.time(), self.tz).timestamp()
                           for day in self.dates]
        # 유효한 UTC offset은 하루 미만이다. 두 offset의 날짜 차이까지 여유를 둔다.
        self.earliest = (first - timedelta(days=2)).isoformat()
        self.latest = (last + timedelta(days=2)).isoformat()

    def __call__(self, value: str | datetime) -> date:
        if isinstance(value, str) and len(value) >= 10 and value[4] == '-' and value[7] == '-':
            if value[:10] < self.earliest or value[:10] > self.latest:
                return self.dates[0] - timedelta(days=1)
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        # 같은 행의 요일·시간대 집계에서도 이미 파싱한 시작 시각을 사용한다.
        self.parsed = value
        if self.tz is None and not self.system_local:
            return value.date()
        if self.tz is not None and (value.tzinfo is None or value.tzinfo is self.tz):
            # 기존 순수 API는 이미 로컬인 시각(존재하지 않는 시각 포함)을 그대로 받는다.
            return value.date()
        index = bisect_right(self.boundaries, value.timestamp()) - 1
        return self.dates[index] if index >= 0 else self.dates[0] - timedelta(days=1)


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


def _period_statistics(records, videos, days, today, local_date, settings, activity=None) -> ViewingStatistics:
    if type(days) is not int or days not in (7, 30, 90, 365):
        raise ValueError("통계 기간은 7·30·90·365일 중 하나여야 합니다.")
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    local_date.prepare(previous_start, today)
    videos = {video.id: video for video in videos}
    daily_seconds = [0.0] * days
    daily_counts = [0] * days
    video_seconds: dict[int, float] = {}
    video_counts: dict[int, int] = {}
    states = {vid: _ViewingState() for vid in videos}
    previous_seconds, previous_count = 0.0, 0
    for viewing in records:
        if viewing.video_id not in videos:
            continue
        kind = states[viewing.video_id].add(viewing, settings)
        if activity is not None:
            activity.record(viewing, kind)
        if kind == ViewingKind.GLANCE:
            continue
        day = local_date(viewing.started_at)
        if start <= day <= today:
            if activity is not None:
                activity.in_period(viewing, day, local_date.parsed)
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
    statuses = [states[video.id].status(settings) for video in visible]
    finished_count = sum(status.finished for status in statuses)
    abandoned_count = sum(status.abandoned for status in statuses)
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


class _Activity:
    """기간 집계와 같은 순회에서 전체 이력과 선택 기간의 시작 시각을 모은다."""
    def __init__(self, tz):
        self.tz = tz
        self.weekdays, self.hours = [0.0] * 7, [0.0] * 24
        self.played = set()
        self.watched_seconds = 0.0

    def record(self, viewing, kind):
        self.played.add(viewing.video_id)
        if kind != ViewingKind.GLANCE:
            self.watched_seconds += viewing.played_seconds

    def in_period(self, viewing, day, started):
        if started.tzinfo is None and self.tz is not None:
            started = started.replace(tzinfo=self.tz)
        local = started.astimezone(self.tz)
        self.weekdays[(day.weekday() + 1) % 7] += viewing.played_seconds
        self.hours[local.hour] += viewing.played_seconds


def _inventory(video_rows, sizes, korean, highlighted, tagged, revisited, activity):
    visible = [row for row in video_rows if not row['excluded']]
    bands = [0] * 5
    resolutions = [0] * 6
    pending = sum(row['resolution_checked'] == 0 for row in visible)
    formats = {}
    format_names = {'matroska,webm': 'Matroska / WebM', 'matroska': 'Matroska',
                    'webm': 'WebM', 'mov,mp4,m4a,3gp,3g2,mj2': 'MP4 / QuickTime',
                    'mp4': 'MP4', 'mov': 'QuickTime', 'avi': 'AVI', 'mpegts': 'MPEG-TS',
                    'mpeg': 'MPEG', 'flv': 'Flash Video', 'asf': 'ASF / WMV', 'ogg': 'Ogg'}
    for row in visible:
        # 구간의 최소값 이상으로 묶는다. PAL 576p도 SD, 1600p는 1440p다.
        short_side = min(row['width'] or 0, row['height'] or 0)
        resolutions[bisect_right((720, 1080, 1440, 2160), short_side) if short_side > 0 else 5] += 1
        bands[bisect_right((600, 1800, 3600, 7200), row['duration'])] += 1
        name = format_names.get(row['format'], row['format'].upper() or '알 수 없음')
        formats[name] = formats.get(name, 0) + 1
    return LibraryInventory(
        len(visible), sum(row['duration'] for row in visible),
        sum(sizes[row['id']] for row in visible if sizes.get(row['id']) is not None),
        sum(sizes.get(row['id']) is None for row in visible), activity.watched_seconds,
        sum(row['id'] in korean for row in visible),
        sum(row['id'] not in activity.played and row['id'] not in revisited for row in visible),
        sum(row['id'] in highlighted for row in visible), sum(row['id'] in tagged for row in visible),
        tuple(DistributionBucket(label, count) for label, count in zip(
            ('10분 미만', '10~30분', '30~60분', '1~2시간', '2시간 이상'), bands)),
        tuple(DistributionBucket(label, count) for label, count in sorted(formats.items(), key=lambda x: (-x[1], x[0]))),
        tuple(DistributionBucket(label, count) for label, count in zip(
            ('SD', '720p', '1080p', '1440p', '4K 이상', '알 수 없음'), resolutions)),
        pending, f'확인 중 {pending:,}개 포함' if pending else '',
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

    def dashboard(self, days: int, *, tz: tzinfo | None = None) -> StatisticsDashboard:
        now = self._clock()
        if now.tzinfo is None and tz is not None:
            now = now.replace(tzinfo=tz)
        now = now.astimezone(tz)
        with self._connect() as db:
            db.execute('BEGIN')
            video_rows = db.execute('SELECT id, title, registered_at, excluded, duration, format, width, height, resolution_checked FROM videos').fetchall()
            snapshot = self._viewings.read_rows(connection=db)
        # 현황은 시청 스냅샷과 별개다. 명시적 BEGIN 없이 각 fetch 직후 읽기 잠금을
        # 풀어 시청·자막 작업자의 커밋이 여러 현황 쿼리 전체를 기다리지 않게 한다.
        with self._connect() as db:
            locations = db.execute('SELECT video_id, MAX(CASE WHEN size >= 0 THEN size END) FROM locations GROUP BY video_id').fetchall()
            transcripts = db.execute('SELECT video_id FROM transcripts').fetchall()
            highlights = db.execute('SELECT video_id, COUNT(*) FROM highlights GROUP BY video_id').fetchall()
            korean = self._korean_subtitled(db)
            tagged_rows = db.execute('SELECT DISTINCT video_id FROM video_tags').fetchall()
            revisited_rows = db.execute('SELECT DISTINCT h.video_id FROM revisits r JOIN highlights h ON h.id = r.highlight_id').fetchall()
        # 모든 fetch와 진행분 복사를 마친 뒤 읽기 트랜잭션을 닫고 파싱한다.
        sizes, highlight_counts = dict(locations), dict(highlights)
        subtitled = {row[0] for row in transcripts}
        videos = tuple(StatisticsVideo(
            row['id'], row['title'], datetime.fromisoformat(row['registered_at']),
            bool(row['excluded']), row['id'] not in sizes, row['id'] in subtitled,
            highlight_counts.get(row['id'], 0),
        ) for row in video_rows)
        activity = _Activity(tz)
        period = _period_statistics(snapshot.records(), videos, days, now.date(),
                                    _LocalDates(tz, system_local=tz is None), self._viewings.settings, activity)
        inventory = _inventory(video_rows, sizes, korean, highlight_counts,
                               {r[0] for r in tagged_rows}, {r[0] for r in revisited_rows}, activity)
        return StatisticsDashboard(period, tuple(activity.weekdays), tuple(activity.hours), inventory)

    @staticmethod
    def _korean_subtitled(db):
        # LibraryDetails의 TranslationSummary와 같은 확정/현재 요청의 부분 번역 규칙.
        # 번역 행에서 출발하되 큰 번역 테이블도 한 번에 잠그지 않는다. 각 fetch 후
        # autocommit 읽기가 끝나므로 기다리는 시청·자막 쓰기가 다음 묶음 전에 진행된다.
        korean = {row[0] for row in db.execute(
            "SELECT video_id FROM transcripts WHERE spoken_language = 'ko'").fetchall()}
        # 완료 시 targets → lines로 이동한 행도 뒤쪽 스캔에 들어오도록 대상을 먼저 읽는다.
        # 화면 번역 자막도 한국어 번역 줄이다. 원어 자막이 없는 영상도 현재 화면 자막 줄의 번역이면 센다.
        # 표마다 범위는 한 번만 잡고, 두 출처는 같은 묶음 조회 안에서 합친다.
        onscreen_lines = """JOIN onscreen_subtitle_lines l ON l.id = g.line_id
                JOIN onscreen_subtitles s ON s.id = l.generation_id
                JOIN onscreen_subtitle_regions r ON r.id = s.region_id"""
        queries = (
            ('translation_targets', f"""SELECT q.video_id FROM translation_targets g
                JOIN translation_queue q ON q.id = g.queue_id
                JOIN transcripts t ON t.video_id = q.video_id
                JOIN transcript_lines l ON l.id = g.line_id AND l.transcript_id = t.id
                WHERE g.rowid > :lower AND g.rowid <= :upper AND g.text IS NOT NULL AND q.source = :transcript
                UNION SELECT q.video_id FROM translation_targets g
                JOIN translation_queue q ON q.id = g.queue_id
                {onscreen_lines} AND r.video_id = q.video_id
                WHERE g.rowid > :lower AND g.rowid <= :upper AND g.text IS NOT NULL AND q.source = :onscreen"""),
            ('translation_lines', f"""SELECT t.video_id FROM translation_lines g
                JOIN transcript_lines l ON l.id = g.line_id
                JOIN transcripts t ON t.id = l.transcript_id
                WHERE g.rowid > :lower AND g.rowid <= :upper AND g.source = :transcript
                UNION SELECT r.video_id FROM translation_lines g
                {onscreen_lines}
                WHERE g.rowid > :lower AND g.rowid <= :upper AND g.source = :onscreen"""),
        )
        for table, query in queries:
            last_rowid = db.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM {table}').fetchone()[0]
            for lower in range(0, last_rowid, 10000):
                rows = db.execute(query, dict(lower=lower, upper=lower + 10000,
                                              transcript=TRANSCRIPT, onscreen=ONSCREEN)).fetchall()
                korean.update(row[0] for row in rows)
        return korean
