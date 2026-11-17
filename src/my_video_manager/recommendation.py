"""추천 선정과 관심 없음의 영구 저장. 시간과 입력 상태는 코어가 공급한다."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

from .library import Video
from .series import next_episode
from .tags import Tag
from .viewing import ViewingKind, ViewingSettings, classify_viewing

ROW_LIMIT = 20
RECENT_VIEWING_DAYS = 14
TASTE_HALF_LIFE_DAYS = 30
PERIOD_MINIMUM_DAYS = 0
PERIOD_MAXIMUM_DAYS = 365000


@dataclass(frozen=True)
class RecommendationRowDefinition:
    kind: str
    title: str
    dedicated: bool = False


@dataclass(frozen=True)
class RecommendationPeriodDefinition:
    """설정 화면이 그릴 수 있는 기간 하나의 이름·설명·기본값·허용 범위."""
    criterion: str
    label: str
    default_days: float
    description: str
    minimum_days: float = PERIOD_MINIMUM_DAYS
    maximum_days: float = PERIOD_MAXIMUM_DAYS


# 설정 화면에 표시하는 순서다. 설정 키는 recommend.<criterion>_days다.
RECOMMENDATION_PERIODS = (
    RecommendationPeriodDefinition(
        "continue_watching", "이어 보기", 30,
        "보다 만 영상을 이어 보기에 두는 기간입니다. 넘기면 잊고 있던 영상으로 옮깁니다."),
    RecommendationPeriodDefinition(
        "revisit", "하이라이트 복습", 30,
        "하이라이트를 만들거나 마지막으로 복습한 뒤 이 기간이 지나면 복습을 권합니다."),
    RecommendationPeriodDefinition(
        "new_arrivals", "새로 추가됨", 14,
        "추가한 뒤 아직 안 본 영상을 새로 추가됨에 두는 기간입니다."),
    RecommendationPeriodDefinition(
        "rewatch", "다시 보기", 60,
        "즐겨 보는 영상을 마지막으로 본 뒤 이 기간을 넘기면 다시 보기를 권합니다."),
    RecommendationPeriodDefinition(
        "unwatched", "잊고 있던 영상", 30,
        "추가한 뒤 이 기간을 넘기도록 안 본 영상을 잊고 있던 영상으로 꺼냅니다."),
)
RECOMMENDATION_PERIODS_BY_CRITERION = {period.criterion: period for period in RECOMMENDATION_PERIODS}

# 표시 순서가 원본이다. 전용 줄부터 배정하며, 각 그룹 안의 배정 순서는 표시 순서다.
# 새 줄은 정의와 select_recommendations의 후보를 더한다. 일반 줄은 dedicated=False다.
ROW_DEFINITIONS = (
    RecommendationRowDefinition("because_watched", "『제목』을 봤다면"),
    RecommendationRowDefinition("taste", "취향 맞춤"),
    RecommendationRowDefinition("new_arrivals", "새로 추가됨"),
    RecommendationRowDefinition("rewatch", "다시 보기"),
    RecommendationRowDefinition("forgotten", "잊고 있던 영상"),
    RecommendationRowDefinition("continue_watching", "이어 보기", dedicated=True),
    RecommendationRowDefinition("next_episode", "다음 화", dedicated=True),
    RecommendationRowDefinition("highlight_review", "하이라이트 복습", dedicated=True),
)
ROW_TITLES = {row.kind: row.title for row in ROW_DEFINITIONS}


def recommendation_period_definition(criterion: str) -> RecommendationPeriodDefinition:
    try:
        return RECOMMENDATION_PERIODS_BY_CRITERION[criterion]
    except KeyError:
        raise ValueError("알 수 없는 추천 기간입니다.") from None


def validate_period_days(definition: RecommendationPeriodDefinition, days) -> float:
    """유한한 수이며 정의된 범위 안인지 확인한다. 불리언과 문자열은 수가 아니다.

    범위를 먼저 본다. float로 바꿀 수 없을 만큼 큰 정수에 isfinite를 부르면 OverflowError가 난다.
    """
    if (isinstance(days, bool) or not isinstance(days, (int, float))
            or not definition.minimum_days <= days <= definition.maximum_days or not isfinite(days)):
        raise ValueError("추천 기간은 0 이상 365000 이하의 유한한 일수여야 합니다.")
    return days


@dataclass(frozen=True)
class Recommendation:
    video: Video
    reason: str
    shared_tags: tuple[Tag, ...] = ()


@dataclass(frozen=True)
class RecommendationRow:
    """kind는 줄 종류, key는 기준 영상까지 구별하는 안정적인 줄 식별자다."""
    kind: str
    title: str
    items: tuple[Recommendation, ...]
    source_video_id: int | None = None

    @property
    def key(self) -> str:
        return self.kind if self.source_video_id is None else f"{self.kind}:{self.source_video_id}"


def assign_rows(candidates, limit=ROW_LIMIT) -> tuple[RecommendationRow, ...]:
    """배정 순서대로 후보 줄을 받아 영상마다 상위 limit 안에 드는 첫 줄 하나에 배정한다.

    앞서 배정한 영상을 뒤 줄 후보에서 먼저 뺀 뒤 자르므로, 앞 줄에서 밀려난 영상은
    뒤 줄 조건에 맞으면 그 줄에 나올 수 있다. 표시 순서와는 별개이며 빈 줄은 뺀다.
    """
    placed, rows = set(), []
    for row in candidates:
        items = tuple(item for item in row.items if item.video.id not in placed)[:limit]
        placed.update(item.video.id for item in items)
        if items:
            rows.append(replace(row, items=items))
    return tuple(rows)


def _elapsed_days(now, then):
    return max(0, (now - then).days)


def _added_reason(days):
    return "오늘 추가했어요" if days == 0 else f"{days}일 전에 추가했어요"


def because_watched_title(title):
    """『제목』 뒤의 목적격 조사를 마지막 글자의 받침에 맞춘다.

    마지막 글자가 한글이 아니면 숫자 읽기를 추정하지 않고 '을(를)'을 쓴다.
    """
    last = title[-1:] if title else ""
    if "가" <= last <= "힣":
        particle = "을" if (ord(last) - ord("가")) % 28 else "를"
    else:
        particle = "을(를)"
    return f"『{title}』{particle} 봤다면"


def select_recommendations(videos, statuses, tags, series, dismissed, revisit_times, *,
                           now, viewing_records=(), viewing_settings=ViewingSettings(),
                           unwatched_days=30, revisit_days=30, continue_watching_days=30,
                           new_arrivals_days=14, rewatch_days=60) -> tuple[RecommendationRow, ...]:
    """기준마다 후보 줄을 만들고 줄 배정 규칙을 적용한다. 틀어보기만 있으면 시청 없음이다."""
    playable = {v.id: v for v in videos if not v.missing and not v.excluded}
    allowed = set(playable)
    continue_period = timedelta(days=continue_watching_days)
    new_arrivals_period = timedelta(days=new_arrivals_days)
    rewatch_period = timedelta(days=rewatch_days)
    stopped_at = {vid: statuses[vid].last_viewed_at or video.registered_at
                  for vid, video in playable.items() if statuses[vid].abandoned}
    continue_allowed = {vid for vid, stopped in stopped_at.items()
                        if vid not in dismissed and now - stopped <= continue_period}
    next_episode_times = {}
    revisit_allowed = {vid for vid in playable if vid not in dismissed and vid in revisit_times
                       and now - revisit_times[vid] >= timedelta(days=revisit_days)}
    series_ids = {}
    for group in series:
        series_ids.update((vid, group.id) for vid in group.video_ids)
        allowed.difference_update(group.video_ids)
        candidate = next_episode(group.video_ids, statuses)
        if candidate in playable and candidate not in dismissed:
            allowed.add(candidate)
            # 틀어보기만 한 시리즈에는 '다음 화' 줄을 만들지 않는다.
            # 시청이 있는 영상의 마지막 시각에는 이후 틀어보기도 포함한다.
            viewed_at = [statuses[vid].last_viewed_at for vid in group.video_ids
                         if (statuses[vid].finished or statuses[vid].abandoned)
                         and statuses[vid].last_viewed_at is not None]
            if viewed_at:
                next_episode_times[candidate] = max(viewed_at)
        # 기한 안의 보다 만 화는 다음 볼 화가 아니어도 '이어 보기'에만 남을 수 있다.
        # 시리즈마다 가장 최근에 멈춘 한 편만 남기고, 같으면 앞 화가 먼저다.
        abandoned = [vid for vid in group.video_ids if vid in continue_allowed]
        if abandoned:
            continue_allowed.difference_update(abandoned)
            continue_allowed.add(max(abandoned, key=lambda vid: stopped_at[vid]))
        overdue = revisit_allowed.intersection(group.video_ids)
        if overdue:
            # 복습은 다음 볼 화 규칙의 예외지만 시리즈마다 가장 오래 밀린 한 편만 남긴다.
            revisit_allowed.difference_update(overdue)
            revisit_allowed.add(min(overdue, key=lambda vid: (revisit_times[vid], vid)))
    # 관심 없음은 다음 볼 화를 고른 뒤 적용한다. 뒤 화로 넘어가지 않는다.
    allowed.difference_update(dismissed)
    visible = {v.id: v for v in videos if not v.excluded}
    latest_viewings, tag_scores = {}, {}
    for record in viewing_records:
        if record.video_id not in visible or classify_viewing(
                record.played_seconds, record.duration, viewing_settings) == ViewingKind.GLANCE:
            continue
        started = (datetime.fromisoformat(record.started_at)
                   if isinstance(record.started_at, str) else record.started_at)
        if now - timedelta(days=RECENT_VIEWING_DAYS) <= started <= now:
            latest_viewings[record.video_id] = max(started, latest_viewings.get(record.video_id, started))
        elapsed = max(0, (now - started).total_seconds() / 86400)
        score = record.played_seconds * 0.5 ** (elapsed / TASTE_HALF_LIFE_DAYS)
        for tag in tags.get(record.video_id, ()):
            tag_scores[tag.id] = tag_scores.get(tag.id, 0) + score
    # 먼저 최근 영상 세 개를 고른 뒤 태그 없는 영상은 건너뛴다. 다음 영상으로 채우지 않는다.
    source_ids = sorted(latest_viewings, key=lambda vid: (-latest_viewings[vid].timestamp(), vid))[:3]
    source_tags = {vid: {tag.id for tag in tags.get(vid, ())} for vid in source_ids if tags.get(vid)}
    because_ranked = {vid: [] for vid in source_tags}
    ranked = {kind: [] for kind in ROW_TITLES}
    # 한 영상이 여러 기준에 맞으면 모든 후보 줄에 넣는다. 어느 줄에 나올지는 assign_rows가 정한다.
    for vid in allowed | revisit_allowed | continue_allowed:
        video, status = playable[vid], statuses[vid]
        unwatched = not status.finished and not status.abandoned
        if vid in continue_allowed:
            ranked["continue_watching"].append(((-stopped_at[vid].timestamp(), vid),
                                               Recommendation(video, f"{status.stopped_percent:.0f}%에서 멈췄어요")))
        if vid in next_episode_times:
            ranked["next_episode"].append(((-next_episode_times[vid].timestamp(), vid),
                                          Recommendation(video, "시청 중인 시리즈의 다음 볼 화예요")))
        if vid in revisit_allowed:
            revisit = revisit_times[vid]
            ranked["highlight_review"].append(((revisit.timestamp(), vid), Recommendation(
                video, f"하이라이트를 {_elapsed_days(now, revisit)}일 동안 복습하지 않았어요")))
        if vid in allowed and unwatched:
            video_tags = tags.get(vid, ())
            for source_id, tag_ids in source_tags.items():
                if source_id in series_ids and series_ids[source_id] == series_ids.get(vid):
                    continue
                shared = tuple(tag for tag in video_tags if tag.id in tag_ids)
                if shared:
                    because_ranked[source_id].append(((-len(shared), video.registered_at.timestamp(), vid),
                        Recommendation(video, "겹친 태그 · " + ", ".join(t.name for t in shared), shared)))
            scored_tags = sorted((tag for tag in video_tags if tag_scores.get(tag.id, 0) > 0),
                                 key=lambda tag: (-tag_scores[tag.id], tag.id))
            score = sum(tag_scores[tag.id] for tag in scored_tags)
            if score > 0:
                top_tags = tuple(scored_tags[:2])
                ranked["taste"].append(((-score, video.registered_at.timestamp(), vid), Recommendation(
                    video, "자주 본 태그 · " + ", ".join(tag.name for tag in top_tags), top_tags)))
        if vid in allowed and unwatched and now - video.registered_at <= new_arrivals_period:
            ranked["new_arrivals"].append(((-video.registered_at.timestamp(), vid), Recommendation(
                video, _added_reason(_elapsed_days(now, video.registered_at)))))
        if (vid in allowed and status.favorite and status.last_viewed_at is not None
                and now - status.last_viewed_at > rewatch_period):
            ranked["rewatch"].append(((status.last_viewed_at.timestamp(), vid), Recommendation(
                video, f"{_elapsed_days(now, status.last_viewed_at)}일 동안 다시 보지 않았어요")))
        if vid in allowed and unwatched and now - video.registered_at > timedelta(days=unwatched_days):
            ranked["forgotten"].append(((video.registered_at.timestamp(), vid), Recommendation(
                video, f"등록하고 {_elapsed_days(now, video.registered_at)}일 동안 시청하지 않았어요")))
        # 기한이 지난 시리즈의 보다 만 화에는 예외를 적용하지 않는다.
        if vid in allowed and status.abandoned and now - stopped_at[vid] > continue_period:
            ranked["forgotten"].append(((stopped_at[vid].timestamp(), vid), Recommendation(
                video, f"{status.stopped_percent:.0f}%에서 멈춘 뒤 {_elapsed_days(now, stopped_at[vid])}일 지났어요")))
    candidates = []
    for definition in ROW_DEFINITIONS:
        if definition.kind == "because_watched":
            for source_id, entries in because_ranked.items():
                candidates.append(RecommendationRow(definition.kind, because_watched_title(visible[source_id].title),
                    tuple(item for _, item in sorted(entries, key=lambda pair: pair[0])), source_id))
        else:
            candidates.append(RecommendationRow(definition.kind, definition.title,
                tuple(item for _, item in sorted(ranked[definition.kind], key=lambda pair: pair[0]))))
    dedicated = {row.kind for row in ROW_DEFINITIONS if row.dedicated}
    assigned = assign_rows(sorted(candidates, key=lambda row: row.kind not in dedicated))
    by_key = {row.key: row for row in assigned}
    return tuple(by_key[row.key] for row in candidates if row.key in by_key)


class RecommendationStore:
    def __init__(self, connect, clock, settings):
        self._connect, self._clock, self._settings = connect, clock, settings
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dismissed_videos (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS highlight_created_at (
                    highlight_id INTEGER PRIMARY KEY REFERENCES highlights(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );
            """)
            # 과거 생성 시각은 복원할 수 없으므로 최초 업그레이드 시각을 보존한다.
            missing = db.execute("""SELECT h.id FROM highlights h
                LEFT JOIN highlight_created_at c ON c.highlight_id = h.id
                WHERE c.highlight_id IS NULL""").fetchall()
            if missing:
                now = clock().isoformat()
                db.executemany("INSERT OR IGNORE INTO highlight_created_at VALUES (?, ?)",
                               ((row[0], now) for row in missing))

    def record_highlight_created(self, db, highlight_id):
        # 하이라이트 생성과 같은 트랜잭션으로 저장한다.
        db.execute("INSERT INTO highlight_created_at VALUES (?, ?)",
                   (highlight_id, self._clock().isoformat()))

    def dismissed_ids(self) -> set[int]:
        with self._connect() as db:
            return {row[0] for row in db.execute("SELECT video_id FROM dismissed_videos")}

    def set_dismissed(self, video_id: int, dismissed: bool) -> None:
        with self._connect() as db:
            if db.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone() is None:
                raise ValueError("영상을 찾을 수 없습니다.")
            if dismissed:
                db.execute("INSERT OR IGNORE INTO dismissed_videos VALUES (?)", (video_id,))
            else:
                db.execute("DELETE FROM dismissed_videos WHERE video_id=?", (video_id,))

    def revisit_times(self) -> dict[int, datetime]:
        times = {}
        with self._connect() as db:
            for row in db.execute("""SELECT h.video_id, c.created_at, r.last_revisited_at
                    FROM highlights h JOIN highlight_created_at c ON c.highlight_id = h.id
                    LEFT JOIN revisits r ON r.highlight_id = h.id"""):
                values = [datetime.fromisoformat(row["created_at"])]
                if row["last_revisited_at"]:
                    values.append(datetime.fromisoformat(row["last_revisited_at"]))
                if row["video_id"] in times:
                    values.append(times[row["video_id"]])
                times[row["video_id"]] = max(values)
        return times

    def days(self, criterion: str) -> float:
        definition = recommendation_period_definition(criterion)
        value = self._settings.get(f"recommend.{criterion}_days", definition.default_days)
        return validate_period_days(definition, value)

    def set_days(self, criterion: str, days: float) -> None:
        """검증한 기간만 저장한다. 잘못된 값은 저장하지 않고 예외로 거부한다."""
        definition = recommendation_period_definition(criterion)
        self._settings.set(f"recommend.{criterion}_days", validate_period_days(definition, days))

    def reset_days(self, criterion: str) -> None:
        """저장값을 지워 다음 읽기부터 정의된 기본값을 쓴다."""
        recommendation_period_definition(criterion)
        self._settings.reset(f"recommend.{criterion}_days")
