"""추천 선정과 관심 없음의 영구 저장. 시간과 입력 상태는 코어가 공급한다."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

from .library import Video
from .series import next_episode
from .tags import Tag

ROW_LIMIT = 20


@dataclass(frozen=True)
class RecommendationRowDefinition:
    kind: str
    title: str
    dedicated: bool = False


# 표시 순서가 원본이다. 전용 줄부터 배정하며, 각 그룹 안의 배정 순서는 표시 순서다.
# 새 줄은 정의와 select_recommendations의 후보를 더한다. 일반 줄은 dedicated=False다.
ROW_DEFINITIONS = (
    RecommendationRowDefinition("similar_tags", "태그가 비슷함"),  # #203의 취향 맞춤이 대체한다.
    RecommendationRowDefinition("forgotten", "잊고 있던 영상"),
    RecommendationRowDefinition("continue_watching", "이어 보기", dedicated=True),
    RecommendationRowDefinition("next_episode", "다음 화", dedicated=True),
    RecommendationRowDefinition("highlight_review", "하이라이트 복습", dedicated=True),
)
ROW_TITLES = {row.kind: row.title for row in ROW_DEFINITIONS}


@dataclass(frozen=True)
class Recommendation:
    video: Video
    reason: str
    shared_tags: tuple[Tag, ...] = ()


@dataclass(frozen=True)
class RecommendationRow:
    """같은 이유로 추천한 영상의 묶음. kind는 줄 종류, items는 줄 안 순서다."""
    kind: str
    title: str
    items: tuple[Recommendation, ...]


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


def select_recommendations(videos, statuses, tags, series, dismissed, revisit_times, *,
                           now, unwatched_days=30, revisit_days=30,
                           continue_watching_days=30) -> tuple[RecommendationRow, ...]:
    """기준마다 후보 줄을 만들고 줄 배정 규칙을 적용한다. 틀어보기만 있으면 시청 없음이다."""
    playable = {v.id: v for v in videos if not v.missing and not v.excluded}
    allowed = set(playable)
    continue_period = timedelta(days=continue_watching_days)
    stopped_at = {vid: statuses[vid].last_viewed_at or video.registered_at
                  for vid, video in playable.items() if statuses[vid].abandoned}
    continue_allowed = {vid for vid, stopped in stopped_at.items()
                        if vid not in dismissed and now - stopped <= continue_period}
    next_episode_times = {}
    revisit_allowed = {vid for vid in playable if vid not in dismissed and vid in revisit_times
                       and now - revisit_times[vid] >= timedelta(days=revisit_days)}
    for group in series:
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
    visible = {v.id for v in videos if not v.excluded}
    favorite_tags = {tag.id for vid, status in statuses.items() if vid in visible and status.favorite
                     for tag in tags.get(vid, ())}
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
        shared = tuple(tag for tag in tags.get(vid, ()) if tag.id in favorite_tags)
        if vid in allowed and unwatched and shared:
            ranked["similar_tags"].append(((-len(shared), video.registered_at.timestamp(), vid), Recommendation(
                video, "겹친 태그 · " + ", ".join(t.name for t in shared), shared)))
        if vid in allowed and unwatched and now - video.registered_at > timedelta(days=unwatched_days):
            ranked["forgotten"].append(((video.registered_at.timestamp(), vid), Recommendation(
                video, f"등록하고 {_elapsed_days(now, video.registered_at)}일 동안 시청하지 않았어요")))
        # 기한이 지난 시리즈의 보다 만 화에는 예외를 적용하지 않는다.
        if vid in allowed and status.abandoned and now - stopped_at[vid] > continue_period:
            ranked["forgotten"].append(((stopped_at[vid].timestamp(), vid), Recommendation(
                video, f"{status.stopped_percent:.0f}%에서 멈춘 뒤 {_elapsed_days(now, stopped_at[vid])}일 지났어요")))
    allocation_order = sorted(ROW_DEFINITIONS, key=lambda row: not row.dedicated)
    assigned = assign_rows(RecommendationRow(row.kind, row.title,
                           tuple(item for _, item in sorted(ranked[row.kind], key=lambda pair: pair[0])))
                           for row in allocation_order)
    by_kind = {row.kind: row for row in assigned}
    return tuple(by_kind[row.kind] for row in ROW_DEFINITIONS if row.kind in by_kind)


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
        days = self._settings.get(f"recommend.{criterion}_days", 30)
        if isinstance(days, bool) or not isinstance(days, (int, float)) or not isfinite(days) or not 0 <= days <= 365000:
            raise ValueError("추천 기간은 0 이상 365000 이하의 유한한 일수여야 합니다.")
        return days
