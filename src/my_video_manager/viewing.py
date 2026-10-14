"""시청 구간의 순수 계산과 저장. 재생 엔진/화면에 의존하지 않는다."""

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import json
from math import isfinite
from typing import Iterable, Iterator, NamedTuple


@dataclass(frozen=True)
class ViewingSettings:
    finished_ratio: float = 0.9
    abandoned_ratio: float = 0.05
    favorite_count: int = 2
    resume_rewind: float = 3
    save_interval: float = 5

    def __post_init__(self):
        if not 0 < self.abandoned_ratio < self.finished_ratio <= 1:
            raise ValueError("시청 분류 비율은 0 < 보다 만 < 다 봄 <= 1이어야 합니다.")
        if not isinstance(self.favorite_count, int) or self.favorite_count < 1:
            raise ValueError("즐겨 보는 영상의 횟수는 양의 정수여야 합니다.")
        if not isfinite(self.resume_rewind) or self.resume_rewind < 0:
            raise ValueError("이어보기 되감기는 유한한 음이 아닌 값이어야 합니다.")
        if not isfinite(self.save_interval) or self.save_interval <= 0:
            raise ValueError("저장 간격은 유한한 양수여야 합니다.")


class ViewingKind(str, Enum):
    FINISHED = "finished"
    ABANDONED = "abandoned"
    GLANCE = "glance"


def classify_viewing(played_seconds: float, duration: float, settings: ViewingSettings) -> ViewingKind:
    """구간을 이미 센 호출자는 비율과 분류를 한 번만 계산한다."""
    ratio = played_seconds / duration
    if ratio >= settings.finished_ratio:
        return ViewingKind.FINISHED
    if ratio >= settings.abandoned_ratio:
        return ViewingKind.ABANDONED
    return ViewingKind.GLANCE


def merge_intervals(intervals, duration: float) -> tuple[tuple[float, float], ...]:
    """영상 범위로 자른 구간의 합집합. 역방향/빈 구간은 재생으로 세지 않는다."""
    if not isfinite(duration) or duration <= 0:
        raise ValueError("영상 길이는 유한한 양수여야 합니다.")
    bounded = []
    for start, end in intervals:
        if not isfinite(start) or not isfinite(end):
            raise ValueError("재생 위치는 유한한 값이어야 합니다.")
        start, end = max(0, start), min(duration, end)
        if start < end:
            bounded.append((start, end))
    result = []
    for start, end in sorted(bounded):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return tuple(result)


@dataclass(frozen=True)
class Viewing:
    id: int
    video_id: int
    duration: float
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    intervals: tuple[tuple[float, float], ...] = ()
    last_position: float | None = None

    @property
    def played_seconds(self) -> float:
        return sum(end - start for start, end in self.intervals)

    @property
    def played_ratio(self) -> float:
        return self.played_seconds / self.duration

    def classify(self, settings: ViewingSettings) -> ViewingKind:
        return classify_viewing(self.played_seconds, self.duration, settings)


def report_position(viewing: Viewing, position: float, *, seeked: bool = False) -> Viewing:
    """연속된 엔진 보고 사이만 누적한다. 탐색/재개 첫 보고는 새 기준점이다.

    호출자는 탐색을 위치 차이나 벽시계로 추측하지 않고 엔진의 불연속 이벤트로
    전달한다. 따라서 작은 탐색도 제외하며 배속은 계산에 개입하지 않는다.
    """
    if viewing.ended_at is not None:
        raise ValueError("이미 닫힌 시청입니다.")
    if not isfinite(position):
        raise ValueError("재생 위치는 유한한 값이어야 합니다.")
    position = max(0, min(viewing.duration, position))
    intervals = viewing.intervals
    if not seeked and viewing.last_position is not None:
        intervals = merge_intervals((*intervals, (viewing.last_position, position)), viewing.duration)
    return replace(viewing, intervals=intervals, last_position=position)


@dataclass(frozen=True)
class ViewingStatus:
    finished: bool = False
    abandoned: bool = False
    favorite: bool = False
    finished_count: int = 0
    resume_point: float | None = None
    stopped_percent: float | None = None
    last_viewed_at: datetime | None = None


def viewing_status(viewings: tuple[Viewing, ...], settings: ViewingSettings) -> ViewingStatus:
    finished_count = sum(v.classify(settings) == ViewingKind.FINISHED for v in viewings)
    finished = finished_count > 0
    abandoned = not finished and any(v.classify(settings) == ViewingKind.ABANDONED for v in viewings)
    # 시작 시각이 같은 가짜 시계/빠른 재실행에도 ID가 최종 순서를 보장한다.
    last = max((v for v in viewings if v.last_position is not None), key=lambda v: v.id, default=None)
    point = last.last_position if abandoned and last is not None else None
    return ViewingStatus(finished, abandoned, finished_count >= settings.favorite_count,
                         finished_count, point,
                         point / last.duration * 100 if point is not None else None,
                         max((v.updated_at for v in viewings), default=None))


@dataclass(frozen=True)
class VideoViewingStatistics:
    video_id: int
    viewing_count: int = 0
    watched_seconds: float = 0.0
    # ViewingStatus.last_viewed_at과 같은 updated_at 최댓값. 틀어보기도 포함한다.
    last_viewed_at: str | None = None


class ViewingRecord(NamedTuple):
    """구간 합을 한 번 구한 시청 입력. 날짜 파싱은 필요한 집계에서만 한다."""
    id: int
    video_id: int
    duration: float
    played_seconds: float
    started_at: str | datetime
    updated_at: str | datetime
    last_position: float | None


@dataclass(frozen=True)
class ViewingSummary:
    statuses: dict[int, ViewingStatus]
    statistics: dict[int, VideoViewingStatistics]


@dataclass
class _ViewingTotals:
    finished_count: int = 0
    viewing_count: int = 0
    seconds: float = 0.0
    last_viewed_at: datetime | None = None
    last_position_id: int = -1
    last_position: float | None = None
    last_duration: float = 1.0


def summarize_viewings(records: Iterable[ViewingRecord], video_ids: Iterable[int],
                       settings: ViewingSettings) -> ViewingSummary:
    """전체 기간의 상태와 수치를 같은 순회에서 계산한다. DB·Qt와 무관하다."""
    totals = {vid: _ViewingTotals() for vid in video_ids}
    for record in records:
        total = totals.get(record.video_id)
        if total is None:
            continue
        kind = classify_viewing(record.played_seconds, record.duration, settings)
        if kind != ViewingKind.GLANCE:
            total.viewing_count += 1
            total.seconds += record.played_seconds
            total.finished_count += kind == ViewingKind.FINISHED
        updated = (datetime.fromisoformat(record.updated_at)
                   if isinstance(record.updated_at, str) else record.updated_at)
        if total.last_viewed_at is None or updated > total.last_viewed_at:
            total.last_viewed_at = updated
        if record.last_position is not None and record.id > total.last_position_id:
            total.last_position_id = record.id
            total.last_position = record.last_position
            total.last_duration = record.duration
    statuses, statistics = {}, {}
    for vid, total in totals.items():
        finished = total.finished_count > 0
        abandoned = not finished and total.viewing_count > 0
        point = total.last_position if abandoned else None
        statuses[vid] = ViewingStatus(
            finished, abandoned, total.finished_count >= settings.favorite_count, total.finished_count,
            point, point / total.last_duration * 100 if point is not None else None, total.last_viewed_at)
        statistics[vid] = VideoViewingStatistics(
            vid, total.viewing_count, total.seconds,
            total.last_viewed_at.isoformat() if total.last_viewed_at is not None else None)
    return ViewingSummary(statuses, statistics)


@dataclass(frozen=True)
class ViewingRows:
    """읽기 트랜잭션 안에서 확보한 DB 행과 불변 진행분의 스냅샷."""
    rows: list
    active: dict[int, Viewing]

    def records(self) -> Iterator[ViewingRecord]:
        """잠금을 해제한 뒤 파싱한다. 저장 구간은 report_position에서 이미 병합했다."""
        for row in self.rows:
            active = self.active.get(row["id"])
            if active is not None:
                yield ViewingRecord(active.id, active.video_id, active.duration, active.played_seconds,
                                    active.started_at, active.updated_at, active.last_position)
            else:
                seconds = sum(end - start for start, end in json.loads(row["intervals"]))
                yield ViewingRecord(row["id"], row["video_id"], row["duration"], seconds,
                                    row["started_at"], row["updated_at"], row["last_position"])


class ViewingRecorder:
    """공용 재생 수명주기와 시청 저장을 연결한다."""

    def __init__(self, start, report, end):
        self._start, self._report, self._end = start, report, end
        self._viewing_id = None

    def playback_started(self, session, position):
        if session.record_viewing:
            self._viewing_id = self._start(session.video_id, position).id

    def playback_position(self, session, position, seeked):
        if self._viewing_id is not None:
            self._report(self._viewing_id, position, seeked=seeked)

    def playback_ended(self, session, position):
        if self._viewing_id is not None:
            self._end(self._viewing_id)
            self._viewing_id = None


class ViewingStore:
    """AppCore가 소유하는 시청 저장소. connect/clock은 코어에서 주입한다."""

    def __init__(self, connect, clock, settings: ViewingSettings):
        self._connect, self._clock, self.settings = connect, clock, settings
        self._active: dict[int, Viewing] = {}
        self._saved_at: dict[int, datetime] = {}
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS viewings (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    duration REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    intervals TEXT NOT NULL,
                    last_position REAL
                );
                CREATE INDEX IF NOT EXISTS viewings_video ON viewings(video_id);
                UPDATE viewings SET ended_at = updated_at WHERE ended_at IS NULL;
            """)

    def start(self, video_id: int, duration: float, position: float) -> Viewing:
        merge_intervals((), duration)
        now = self._clock()
        viewing = report_position(Viewing(0, video_id, duration, now, now), position, seeked=True)
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO viewings (video_id, duration, started_at, updated_at, intervals, last_position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (video_id, duration, now.isoformat(), now.isoformat(), "[]", viewing.last_position),
            )
        viewing = replace(viewing, id=cursor.lastrowid)
        self._active[viewing.id] = viewing
        self._saved_at[viewing.id] = now
        return viewing

    def report(self, viewing_id: int, position: float, *, seeked: bool = False) -> None:
        viewing = report_position(self._require_active(viewing_id), position, seeked=seeked)
        self._active[viewing_id] = replace(viewing, updated_at=self._clock())
        self.save_due()

    def _require_active(self, viewing_id):
        if viewing_id not in self._active:
            raise ValueError("진행 중인 시청이 아닙니다.")
        return self._active[viewing_id]

    def save_due(self) -> None:
        now = self._clock()
        for viewing in self._active.values():
            if (now - self._saved_at[viewing.id]).total_seconds() >= self.settings.save_interval:
                self._save(viewing)
                self._saved_at[viewing.id] = now

    def end(self, viewing_id: int) -> Viewing:
        now = self._clock()
        viewing = replace(self._require_active(viewing_id), updated_at=now, ended_at=now)
        self._save(viewing)
        del self._active[viewing_id]
        del self._saved_at[viewing_id]
        return viewing

    def _save(self, viewing):
        with self._connect() as db:
            db.execute("UPDATE viewings SET updated_at=?, ended_at=?, intervals=?, last_position=? WHERE id=?",
                       (viewing.updated_at.isoformat(), viewing.ended_at.isoformat() if viewing.ended_at else None,
                        json.dumps(viewing.intervals), viewing.last_position, viewing.id))

    def list(self, video_id: int) -> tuple[Viewing, ...]:
        with self._connect() as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT * FROM viewings WHERE video_id=? ORDER BY id", (video_id,)).fetchall()
            active = dict(self._active)
        return tuple(self._from_row(row, active) for row in rows)

    def list_all(self, *, connection=None) -> tuple[Viewing, ...]:
        """전체 시청을 한 번에 읽으며 저장 전 진행분도 기존 조회와 같이 반영한다."""
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute("BEGIN")
            rows = db.execute("SELECT * FROM viewings ORDER BY id").fetchall()
            active = dict(self._active)
        return tuple(self._from_row(row, active) for row in rows)

    def read_rows(self, *, connection=None) -> ViewingRows:
        """외부 접속을 넘긴 호출자도 records() 파싱 전에 읽기 트랜잭션을 닫는다."""
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute("BEGIN")
            rows = db.execute(
                "SELECT id, video_id, duration, intervals, started_at, updated_at, last_position "
                "FROM viewings ORDER BY id").fetchall()
            active = dict(self._active)
        return ViewingRows(rows, active)

    def summary(self) -> ViewingSummary:
        """시청 없는 영상과 저장 전 진행분을 포함한 상태·수치 일괄 조회."""
        with self._connect() as db:
            db.execute("BEGIN")
            ids = [row[0] for row in db.execute("SELECT id FROM videos").fetchall()]
            snapshot = self.read_rows(connection=db)
        return summarize_viewings(snapshot.records(), ids, self.settings)

    def status_map(self) -> dict[int, ViewingStatus]:
        """시청 없는 영상도 포함하며 저장 전의 진행 중 시청을 즉시 반영한다."""
        return self.summary().statuses

    @staticmethod
    def _from_row(row, active) -> Viewing:
        viewing = active.get(row["id"])
        if viewing is not None:
            return viewing
        return Viewing(
            row["id"], row["video_id"], row["duration"], datetime.fromisoformat(row["started_at"]),
            datetime.fromisoformat(row["updated_at"]),
            datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            tuple(tuple(pair) for pair in json.loads(row["intervals"])), row["last_position"],
        )
