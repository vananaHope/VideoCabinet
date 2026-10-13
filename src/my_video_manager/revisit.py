"""하이라이트의 마지막 복습 기록과 영상별 조회."""

from datetime import datetime


class Revisits:
    def __init__(self, connect, clock):
        self._connect, self._clock = connect, clock
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS revisits (
                    highlight_id INTEGER PRIMARY KEY REFERENCES highlights(id) ON DELETE CASCADE,
                    last_revisited_at TEXT NOT NULL
                );
            """)

    def last_for_highlight(self, highlight_id: int) -> datetime | None:
        with self._connect() as db:
            row = db.execute("SELECT last_revisited_at FROM revisits WHERE highlight_id = ?",
                             (highlight_id,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def last_for_video(self, video_id: int) -> datetime | None:
        with self._connect() as db:
            rows = db.execute("""SELECT r.last_revisited_at FROM revisits r
                JOIN highlights h ON h.id = r.highlight_id WHERE h.video_id = ?""", (video_id,))
            return max((datetime.fromisoformat(row[0]) for row in rows), default=None)

    def last_by_highlight(self) -> dict[int, datetime]:
        with self._connect() as db:
            return {row[0]: datetime.fromisoformat(row[1]) for row in db.execute(
                "SELECT highlight_id, last_revisited_at FROM revisits")}

    def record(self, highlight_id: int) -> None:
        with self._connect() as db:
            # 재생 중 삭제된 항목의 기록을 되살리지 않는다.
            db.execute("""INSERT INTO revisits (highlight_id, last_revisited_at)
                SELECT id, ? FROM highlights WHERE id = ?
                ON CONFLICT(highlight_id) DO UPDATE SET last_revisited_at = excluded.last_revisited_at""",
                       (self._clock().isoformat(), highlight_id))
