"""하이라이트 모아보기 순서와 복습 기록. 화면·재생 엔진과 독립된 정책."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .highlights import Highlight
from .viewing import merge_intervals


@dataclass(frozen=True)
class RevisitSettings:
    point_duration: float = 10
    minimum_played: float = 3

    def __post_init__(self):
        if any(not isfinite(value) or value <= 0
               for value in (self.point_duration, self.minimum_played)):
            raise ValueError("복습의 지점 길이와 최소 재생 시간은 유한한 양수여야 합니다.")


@dataclass(frozen=True)
class RevisitEntry:
    highlight: Highlight
    video_title: str
    duration: float
    playable: bool
    last_revisited_at: datetime | None


def ordered_revisit_entries(videos, highlights, last_revisited) -> tuple[RevisitEntry, ...]:
    """제목(대소문자 구분) → 영상 ID → 영상 안 시각 → 하이라이트 ID."""
    by_id = {video.id: video for video in videos}
    entries = [RevisitEntry(h, by_id[h.video_id].title, by_id[h.video_id].duration,
                            bool(by_id[h.video_id].locations), last_revisited.get(h.id))
               for h in highlights if h.video_id in by_id]
    return tuple(sorted(entries, key=lambda e: (e.video_title, e.highlight.video_id,
                                                e.highlight.start, e.highlight.id)))


@dataclass(frozen=True)
class RevisitPlayback:
    """엔진이 재생할 한 항목. serial은 반복 때도 바뀌어 이전 엔진 보고를 구별한다."""
    entry: RevisitEntry
    end: float
    serial: int

    @property
    def start(self) -> float:
        return self.entry.highlight.start

    @property
    def video_id(self) -> int:
        return self.entry.highlight.video_id


class Revisits:
    def __init__(self, connect, clock, playback, videos, highlights, highlights_for_tag, settings):
        self._connect, self._clock, self._playback = connect, clock, playback
        self._videos, self._highlights, self._for_tag = videos, highlights, highlights_for_tag
        self.settings = settings
        self.current: RevisitPlayback | None = None
        self.repeat = False
        self._entries = ()
        self._index = 0
        self._serial = 0
        self._changing = False
        self._intervals = ()
        self._position = 0.0
        self._recorded = False
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

    def list(self, tag_id: int | None = None) -> tuple[RevisitEntry, ...]:
        videos = self._videos()
        highlights = (self._for_tag(tag_id) if tag_id is not None else
                      tuple(h for v in videos for h in self._highlights(v.id)))
        with self._connect() as db:
            last = {row[0]: datetime.fromisoformat(row[1]) for row in db.execute(
                "SELECT highlight_id, last_revisited_at FROM revisits")}
        return ordered_revisit_entries(videos, highlights, last)

    def start(self, tag_id: int | None = None, highlight_id: int | None = None):
        entries = self.list(tag_id)
        index = next((i for i, e in enumerate(entries) if e.highlight.id == highlight_id), None)
        if highlight_id is not None and index is None:
            raise ValueError("모아보기 목록에 없는 하이라이트입니다.")
        if index is not None and not entries[index].playable:
            raise ValueError("파일 없음: 재생할 영상의 위치가 없습니다.")
        self._playback.end()
        self._entries = entries
        self.repeat = False
        self._move(index if index is not None else 0, 1)
        return self.current

    def _available(self, entry):
        # 재생 중 편집·삭제나 위치 변경도 다음 항목을 열 때 확인한다.
        video = next((v for v in self._videos() if v.id == entry.highlight.video_id), None)
        return (video is not None and bool(video.locations)
                and any(h.id == entry.highlight.id for h in self._highlights(video.id)))

    def _move(self, index, direction):
        while 0 <= index < len(self._entries):
            entry = self._entries[index]
            end = min(entry.duration, entry.highlight.end if entry.highlight.end is not None
                      else entry.highlight.start + self.settings.point_duration)
            if self._available(entry) and end > entry.highlight.start:
                self._changing = True
                try:
                    self._playback.end()
                    self._index = index
                    self._serial += 1
                    self.current = RevisitPlayback(entry, end, self._serial)
                    self._intervals, self._recorded = (), False
                    self._position = entry.highlight.start
                    self._playback.start(entry.highlight.video_id, entry.highlight.start,
                                         record_viewing=False)
                finally:
                    self._changing = False
                return
            index += direction
        if direction > 0:
            self._playback.end()
            self.current = None

    def adjacent(self, *, forward: bool):
        if self.current is not None:
            self._move(self._index + (1 if forward else -1), 1 if forward else -1)

    def toggle_repeat(self):
        if self.current is not None:
            self.repeat = not self.repeat

    def adjacent_video(self, *, forward: bool):
        if self.current is None:
            return
        groups = []
        for index, entry in enumerate(self._entries):
            if self._available(entry) and entry.highlight.start < entry.duration:
                if not groups or groups[-1][0] != entry.highlight.video_id:
                    groups.append((entry.highlight.video_id, index))
        group = next((i for i, (video_id, _) in enumerate(groups)
                      if video_id == self.current.video_id), None)
        if group is None:
            return
        target = group + 1 if forward else group if self._index > groups[group][1] else group - 1
        if 0 <= target < len(groups):
            self._move(groups[target][1], 1)

    def playback_started(self, session, position):
        if not self._changing:
            self.current = None
            self.repeat = False

    def playback_position(self, session, position, seeked):
        current = self.current
        if current is None or self._changing:
            return
        if not isfinite(position):
            raise ValueError("재생 위치는 유한한 값이어야 합니다.")
        if not seeked:
            self._intervals = merge_intervals(
                (*self._intervals, (self._position - current.start, position - current.start)),
                current.end - current.start)
        self._position = position
        played = sum(end - start for start, end in self._intervals)
        required = min(self.settings.minimum_played, current.end - current.start)
        if not self._recorded and played + 1e-9 >= required:
            with self._connect() as db:
                # 목록을 연 뒤 삭제된 하이라이트는 복습 기록을 되살리지 않는다.
                db.execute("""INSERT INTO revisits (highlight_id, last_revisited_at)
                    SELECT id, ? FROM highlights WHERE id = ?
                    ON CONFLICT(highlight_id) DO UPDATE SET last_revisited_at = excluded.last_revisited_at""",
                           (self._clock().isoformat(), current.entry.highlight.id))
            self._recorded = True
        if position >= current.end:
            self._move(self._index if self.repeat else self._index + 1, 1)

    def playback_ended(self, session, position):
        if not self._changing:
            self.current = None
            self.repeat = False
            self._entries = ()
