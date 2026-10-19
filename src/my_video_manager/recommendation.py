"""추천 선정과 관심 없음의 영구 저장. 시간과 입력 상태는 코어가 공급한다."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

from .library import Video
from .series import next_episode
from .tags import Tag

ROW_LIMIT = 20
# 줄 우선순위 순서. 새 줄은 여기와 select_recommendations의 후보에 함께 더한다.
ROW_TITLES = {"abandoned": "보다 만", "revisit": "복습할 때가 됨",
              "similar_tags": "태그가 비슷함", "unwatched": "오래 시청 없음"}


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
    """우선순위 순 후보 줄에서 영상마다 자신이 상위 limit 안에 드는 가장 위 줄 하나에만 배정한다.

    위 줄에 배정한 영상을 아래 줄 후보에서 먼저 뺀 뒤 자르므로, 위 줄에서 밀려난 영상은
    아래 줄 조건에 맞으면 그 줄에 나올 수 있다. 빈 줄은 결과에서 뺀다.
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
                           now, unwatched_days=30, revisit_days=30) -> tuple[RecommendationRow, ...]:
    """기준마다 후보 줄을 만들고 줄 배정 규칙을 적용한다. 틀어보기만 있으면 시청 없음이다."""
    playable = {v.id: v for v in videos if not v.missing and not v.excluded}
    allowed = set(playable)
    abandoned_allowed = set()
    revisit_allowed = {vid for vid in playable if vid not in dismissed and vid in revisit_times
                       and now - revisit_times[vid] >= timedelta(days=revisit_days)}
    for group in series:
        allowed.difference_update(group.video_ids)
        candidate = next_episode(group.video_ids, statuses)
        if candidate in playable and candidate not in dismissed:
            allowed.add(candidate)
        # 보다 만 화는 다음 볼 화가 아니어도 '보다 만' 줄에만 후보로 남을 수 있다.
        abandoned_allowed.update(vid for vid in group.video_ids
                                 if vid in playable and vid not in dismissed and statuses[vid].abandoned)
        overdue = revisit_allowed.intersection(group.video_ids)
        if overdue:
            # 복습은 다음 볼 화 규칙의 예외지만 시리즈마다 가장 오래 밀린 한 편만 남긴다.
            revisit_allowed.difference_update(overdue)
            revisit_allowed.add(min(overdue, key=lambda vid: (revisit_times[vid], vid)))
    # 관심 없음은 다음 볼 화를 고른 뒤 적용한다. 뒤 화로 넘어가지 않는다.
    allowed.difference_update(dismissed)
    abandoned_allowed.update(allowed)
    visible = {v.id for v in videos if not v.excluded}
    favorite_tags = {tag.id for vid, status in statuses.items() if vid in visible and status.favorite
                     for tag in tags.get(vid, ())}
    ranked = {kind: [] for kind in ROW_TITLES}
    # 한 영상이 여러 기준에 맞으면 모든 후보 줄에 넣는다. 어느 줄에 나올지는 assign_rows가 정한다.
    for vid in allowed | revisit_allowed | abandoned_allowed:
        video, status = playable[vid], statuses[vid]
        unwatched = not status.finished and not status.abandoned
        if vid in abandoned_allowed and status.abandoned:
            ranked["abandoned"].append(((-(status.last_viewed_at or video.registered_at).timestamp(), vid),
                                        Recommendation(video, f"{status.stopped_percent:.0f}%에서 멈췄어요")))
        if vid in revisit_allowed:
            revisit = revisit_times[vid]
            ranked["revisit"].append(((revisit.timestamp(), vid), Recommendation(
                video, f"하이라이트를 {_elapsed_days(now, revisit)}일 동안 복습하지 않았어요")))
        shared = tuple(tag for tag in tags.get(vid, ()) if tag.id in favorite_tags)
        if vid in allowed and unwatched and shared:
            ranked["similar_tags"].append(((-len(shared), video.registered_at.timestamp(), vid), Recommendation(
                video, "겹친 태그 · " + ", ".join(t.name for t in shared), shared)))
        if vid in allowed and unwatched and now - video.registered_at >= timedelta(days=unwatched_days):
            ranked["unwatched"].append(((video.registered_at.timestamp(), vid), Recommendation(
                video, f"등록하고 {_elapsed_days(now, video.registered_at)}일 동안 시청하지 않았어요")))
    return assign_rows(RecommendationRow(kind, ROW_TITLES[kind],
                                         tuple(item for _, item in sorted(items, key=lambda pair: pair[0])))
                       for kind, items in ranked.items())


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
