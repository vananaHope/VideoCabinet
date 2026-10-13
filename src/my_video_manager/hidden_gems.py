"""숨겨진 보석 선정과 관심 없음의 영구 저장. 시간과 입력 상태는 코어가 공급한다."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from .library import Video
from .tags import Tag


@dataclass(frozen=True)
class HiddenGem:
    video: Video
    criterion: str
    reason: str
    shared_tags: tuple[Tag, ...] = ()


def select_hidden_gems(videos, statuses, tags, series, dismissed, revisit_times, *,
                       now, unwatched_days=30, revisit_days=30) -> tuple[HiddenGem, ...]:
    """기준 순서와 기준별 정렬을 적용한다. 틀어보기만 있으면 시청 없음이다."""
    playable = {v.id: v for v in videos if not v.missing and not v.excluded}
    allowed = set(playable)
    for group in series:
        allowed.difference_update(group.video_ids)
        first = next((vid for vid in group.video_ids
                      if vid in playable and not statuses[vid].finished), None)
        if first is not None:
            allowed.add(first)
    # 관심 없음은 첫 미완료 화를 고른 뒤 적용한다. 뒤 화로 넘어가지 않는다.
    allowed.difference_update(dismissed)
    favorite_tags = {tag.id for vid, status in statuses.items() if status.favorite
                     for tag in tags.get(vid, ())}
    ranked = []
    for vid in allowed:
        video, status = playable[vid], statuses[vid]
        unwatched = not status.finished and not status.abandoned
        shared = tuple(tag for tag in tags.get(vid, ()) if tag.id in favorite_tags)
        revisit = revisit_times.get(vid)
        if status.abandoned:
            gem = HiddenGem(video, "abandoned", f"보다 만 · {status.stopped_percent:.0f}%에서 멈췄어요")
            order = (0, -(status.last_viewed_at or video.registered_at).timestamp(), vid)
        elif revisit is not None and now - revisit >= timedelta(days=revisit_days):
            gem = HiddenGem(video, "revisit", "복습할 때가 됨 · 하이라이트를 다시 볼 시간이에요")
            order = (1, revisit.timestamp(), vid)
        elif unwatched and shared:
            gem = HiddenGem(video, "similar_tags", "태그가 비슷함 · " + ", ".join(t.name for t in shared), shared)
            order = (2, -len(shared), video.registered_at.timestamp(), vid)
        elif unwatched and now - video.registered_at >= timedelta(days=unwatched_days):
            gem = HiddenGem(video, "unwatched", "오래 시청 없음 · 등록한 뒤 아직 시청하지 않았어요")
            order = (3, video.registered_at.timestamp(), vid)
        else:
            continue
        ranked.append((order, gem))
    return tuple(gem for _, gem in sorted(ranked, key=lambda pair: pair[0])[:10])


class HiddenGems:
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
