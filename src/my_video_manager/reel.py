"""하이라이트 모아보기의 순서, 재생 지시와 복습 판정."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import re
from typing import Literal

from .highlights import Highlight
from .viewing import merge_intervals


@dataclass(frozen=True)
class ReelSettings:
    point_duration: float = 10
    minimum_played: float = 3

    def __post_init__(self):
        if any(not isfinite(value) or value <= 0
               for value in (self.point_duration, self.minimum_played)):
            raise ValueError("모아보기의 지점 길이와 최소 복습 시간은 유한한 양수여야 합니다.")


@dataclass(frozen=True)
class ReelEntry:
    highlight: Highlight
    video_title: str
    duration: float
    playable: bool
    last_revisited_at: datetime | None


def natural_title_key(title: str):
    return tuple((1, int(part)) if part.isdecimal() else (0, part)
                 for part in re.split(r"(\d+)", title))


def ordered_reel_entries(videos, highlights, last_revisited) -> tuple[ReelEntry, ...]:
    """영상 제목 자연 정렬 → 영상 ID → 영상 안 시각 → 하이라이트 ID."""
    by_id = {video.id: video for video in videos}
    entries = [ReelEntry(h, by_id[h.video_id].title, by_id[h.video_id].duration,
                         bool(by_id[h.video_id].locations), last_revisited.get(h.id))
               for h in highlights if h.video_id in by_id]
    return tuple(sorted(entries, key=lambda e: (natural_title_key(e.video_title),
                                                e.highlight.video_id, e.highlight.start, e.highlight.id)))


@dataclass(frozen=True)
class ReelPlayback:
    """항목별 엔진 지시. 같은 영상은 seek, 다른 영상과 첫 시작은 open."""
    entry: ReelEntry
    end: float
    serial: int
    action: Literal["open", "seek"]

    @property
    def start(self) -> float:
        return self.entry.highlight.start

    @property
    def video_id(self) -> int:
        return self.entry.highlight.video_id


class HighlightReel:
    def __init__(self, playback, videos, highlights, revisits, settings):
        self._playback, self._videos, self._highlights = playback, videos, highlights
        self._revisits, self.settings = revisits, settings
        self.current: ReelPlayback | None = None
        self.repeat = False
        self._entries = ()
        self._index = self._serial = 0
        self._changing = self._due = False
        self._intervals = ()
        self._position = 0.0
        self._recorded = self._last_seeked = False

    def list(self, tag_id: int | None = None) -> tuple[ReelEntry, ...]:
        return ordered_reel_entries(self._videos(), self._highlights(tag_id),
                                    self._revisits.last_by_highlight())

    def start(self, tag_id: int | None = None, highlight_id: int | None = None):
        entries = self.list(tag_id)
        index = next((i for i, e in enumerate(entries) if e.highlight.id == highlight_id), None)
        if highlight_id is not None and index is None:
            raise ValueError("모아보기 목록에 없는 하이라이트입니다.")
        if index is not None:
            if not entries[index].playable:
                raise ValueError("파일 없음: 재생할 영상의 위치가 없습니다.")
            if self._end(entries[index]) <= entries[index].highlight.start:
                raise ValueError("재생할 길이가 없는 하이라이트입니다.")
        self._playback.end()
        self._entries = entries
        self.repeat = False
        self._move(index if index is not None else 0, 1,
                   {e.highlight.id for e in entries if e.playable})
        return self.current

    def _available_ids(self):
        # 한 명령에서 각각 한 번 읽는다. 항목별 전체 조회를 하지 않는다.
        videos = {v.id for v in self._videos() if v.locations}
        return {h.id for h in self._highlights() if h.video_id in videos}

    def _end(self, entry):
        return min(entry.duration, entry.highlight.end if entry.highlight.end is not None
                   else entry.highlight.start + self.settings.point_duration)

    def _move(self, index, direction, available=None):
        if available is None:
            available = self._available_ids()
        while 0 <= index < len(self._entries):
            entry = self._entries[index]
            end = self._end(entry)
            if entry.highlight.id in available and end > entry.highlight.start:
                action = "seek" if self.current and self.current.video_id == entry.highlight.video_id else "open"
                self._changing = True
                try:
                    self._playback.end()
                    self._index = index
                    self._serial += 1
                    self.current = ReelPlayback(entry, end, self._serial, action)
                    self._intervals, self._recorded = (), False
                    self._due = self._last_seeked = False
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
        available = self._available_ids()
        groups = []
        for index, entry in enumerate(self._entries):
            if entry.highlight.id in available and self._end(entry) > entry.highlight.start:
                if not groups or groups[-1][0] != entry.highlight.video_id:
                    groups.append((entry.highlight.video_id, index))
        group = next((i for i, (video_id, _) in enumerate(groups)
                      if video_id == self.current.video_id), None)
        if group is None:
            return
        target = group + 1 if forward else group if self._index > groups[group][1] else group - 1
        if 0 <= target < len(groups):
            self._move(groups[target][1], 1, available)

    def advance_if_due(self, *, eof=False):
        """모든 리스너가 보고를 받은 뒤 호출한다. EOF는 길이 메타데이터와 독립된 끝 신호다."""
        current = self.current
        if current is None:
            return
        if eof:
            if not self._due and current.end == current.entry.duration:
                # 마지막 프레임/길이 메타데이터 차이를 끝 도달로 보정한다.
                self._playback.report(current.end, seeked=self._last_seeked)
            self._due = True
        if self._due:
            self._move(self._index if self.repeat else self._index + 1, 1)

    def playback_started(self, session, position):
        if not self._changing:
            self.current = None
            self.repeat = self._due = False

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
        self._position, self._last_seeked = position, seeked
        played = sum(end - start for start, end in self._intervals)
        required = min(self.settings.minimum_played, current.end - current.start)
        if not self._recorded and played + 1e-9 >= required:
            self._revisits.record(current.entry.highlight.id)
            self._recorded = True
        if position >= current.end:
            self._due = True

    def playback_ended(self, session, position):
        if not self._changing:
            self.current = None
            self.repeat = self._due = False
            self._entries = ()
