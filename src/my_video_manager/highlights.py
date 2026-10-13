"""하이라이트의 저장, 편집, 재생 중 열린 구간 규칙."""

from dataclasses import dataclass
import math

from .playback import PlaybackSession


@dataclass(frozen=True)
class Note:
    text: str


@dataclass(frozen=True)
class Highlight:
    id: int
    video_id: int
    start: float
    end: float | None
    note: Note | None


class Highlights:
    def __init__(self, connect):
        self._connect = connect
        self._video_id = None
        self._duration = 0.0
        self._position = 0.0
        self._open_start = None
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS highlights (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    start REAL NOT NULL CHECK(start >= 0),
                    end REAL CHECK(end > start),
                    note TEXT
                );
                CREATE INDEX IF NOT EXISTS highlights_video_start
                    ON highlights(video_id, start, id);
            """)

    def list(self, video_id: int) -> tuple[Highlight, ...]:
        with self._connect() as db:
            return tuple(self._highlight(row) for row in db.execute(
                "SELECT * FROM highlights WHERE video_id = ? ORDER BY start, id", (video_id,)))

    def list_by_ids(self, highlight_ids: set[int]) -> tuple[Highlight, ...]:
        ids = tuple(highlight_ids)
        highlights = []
        with self._connect() as db:
            # SQLite의 바인딩 개수 제한 안에서 조회하고 공개 정렬 순서를 유지한다.
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                highlights.extend(self._highlight(row) for row in db.execute(
                    f"SELECT * FROM highlights WHERE id IN ({placeholders})", batch))
        return tuple(sorted(highlights, key=lambda h: (h.video_id, h.start, h.id)))

    def list_all(self) -> tuple[Highlight, ...]:
        with self._connect() as db:
            return tuple(self._highlight(row) for row in db.execute(
                "SELECT * FROM highlights ORDER BY video_id, start, id"))

    @staticmethod
    def _highlight(row) -> Highlight:
        return Highlight(row["id"], row["video_id"], row["start"], row["end"],
                         Note(row["note"]) if row["note"] else None)

    @staticmethod
    def _validate_time(value: float, duration: float) -> None:
        if not math.isfinite(value) or not 0 <= value <= duration:
            raise ValueError("시각은 0초 이상 영상 길이 이하여야 합니다.")

    def _duration_for(self, video_id: int) -> float:
        with self._connect() as db:
            row = db.execute("SELECT duration FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            raise ValueError("영상을 찾을 수 없습니다.")
        return row[0]

    def update(self, highlight_id: int, *, start: float, end: float | None,
               note: str) -> Highlight:
        with self._connect() as db:
            row = db.execute("SELECT * FROM highlights WHERE id = ?", (highlight_id,)).fetchone()
            if row is None:
                raise ValueError("하이라이트를 찾을 수 없습니다.")
            duration = self._duration_for(row["video_id"])
            self._validate_time(start, duration)
            if end is not None:
                self._validate_time(end, duration)
                if end <= start:
                    raise ValueError("구간의 끝은 시작보다 뒤여야 합니다.")
            text = note.strip() or None
            db.execute("UPDATE highlights SET start = ?, end = ?, note = ? WHERE id = ?",
                       (start, end, text, highlight_id))
            return Highlight(highlight_id, row["video_id"], start, end,
                             Note(text) if text else None)

    def delete(self, highlight_id: int) -> None:
        # 메모는 하이라이트 행의 일부이므로 단독으로 남을 수 없다.
        with self._connect() as db:
            if not db.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,)).rowcount:
                raise ValueError("하이라이트를 찾을 수 없습니다.")

    def playback_started(self, session: PlaybackSession, position: float) -> None:
        duration = self._duration_for(session.video_id)
        self._video_id = session.video_id
        self._duration = duration
        self._open_start = None
        self.playback_position(session, position, False)

    def playback_position(self, session: PlaybackSession, position: float, seeked: bool) -> None:
        if self._video_id is None:
            raise ValueError("재생 중인 영상이 없습니다.")
        if not math.isfinite(position):
            raise ValueError("재생 위치가 올바르지 않습니다.")
        # 디코더가 길이보다 약간 바깥의 위치를 보고해도 영상 안에 표시한다.
        self._position = max(0.0, min(self._duration, position))

    @property
    def open_start(self) -> float | None:
        return self._open_start

    def add_point(self) -> Highlight:
        return self._save(self._position, None)

    def toggle_range(self) -> Highlight | None:
        if self._video_id is None:
            raise ValueError("재생 중인 영상이 없습니다.")
        if self._open_start is None:
            self._open_start = self._position
            return None
        start = self._open_start
        highlight = self._save(start, self._position if self._position > start else None)
        self._open_start = None
        return highlight

    def playback_ended(self, session: PlaybackSession, position: float) -> None:
        self.playback_position(session, position, False)
        if self._open_start is not None:
            self.toggle_range()
        self._video_id = None

    def adjacent(self, *, forward: bool) -> float | None:
        if self._video_id is None:
            raise ValueError("재생 중인 영상이 없습니다.")
        starts = [h.start for h in self.list(self._video_id)]
        if forward:
            return next((start for start in starts if start > self._position), None)
        return next((start for start in reversed(starts) if start < self._position - 1), None)

    def _save(self, start: float, end: float | None) -> Highlight:
        if self._video_id is None:
            raise ValueError("재생 중인 영상이 없습니다.")
        with self._connect() as db:
            cursor = db.execute("INSERT INTO highlights (video_id, start, end) VALUES (?, ?, ?)",
                                (self._video_id, start, end))
            return Highlight(cursor.lastrowid, self._video_id, start, end, None)
