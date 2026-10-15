"""기존 영상의 해상도를 한 항목씩 채운다. 파일 I/O 중 DB 잠금을 잡지 않는다."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from threading import Lock
from time import perf_counter

from .library import _fingerprint, _signature


@dataclass(frozen=True)
class ResolutionResult:
    video_id: int | None
    state: str  # completed / unknown / cancelled / retry / exhausted
    message: str = ''
    elapsed_seconds: float = 0
    write_seconds: float = 0


class ResolutionBackfill:
    def __init__(self, connect, media):
        self._connect, self._media = connect, media
        self._lock = Lock()

    def step(self, cancellation):
        if cancellation.is_set():
            return ResolutionResult(None, 'cancelled')
        if not self._lock.acquire(blocking=False):
            return ResolutionResult(None, 'retry')
        try:
            return self._step(cancellation)
        finally:
            self._lock.release()

    def _step(self, cancellation):
        started = perf_counter()
        with self._connect() as db:
            row = db.execute('SELECT id, fingerprint FROM videos WHERE resolution_checked=0 ORDER BY id LIMIT 1').fetchone()
            if row is None:
                return ResolutionResult(None, 'exhausted')
            video_id, fingerprint = row
            paths = [Path(r[0]) for r in db.execute('SELECT path FROM locations WHERE video_id=? ORDER BY path', (video_id,))]
        info, message = None, ''
        for path in paths:
            if cancellation.is_set():
                return ResolutionResult(video_id, 'cancelled')
            try:
                signature = _signature(path)
                # 같은 경로가 다른 내용으로 교체됐다면 옛 영상에 해상도를 쓰지 않는다.
                if _fingerprint(path) != fingerprint:
                    continue
                reader = getattr(self._media, 'read_resolution', None)
                candidate = reader(path, cancellation=cancellation) if reader else self._media.read(path)
                if _signature(path) != signature:
                    continue
                if candidate and candidate.width and candidate.height:
                    info = candidate
                    break
            except (OSError, ValueError, RuntimeError) as error:
                message = str(error)
        if cancellation.is_set():
            return ResolutionResult(video_id, 'cancelled')
        write_started = perf_counter()
        try:
            with self._connect() as db:
                # 재생/받아쓰기 쓰기를 기다리며 오래 연결을 점유하지 않는다.
                db.execute('PRAGMA busy_timeout=50')
                db.execute('UPDATE videos SET width=?, height=?, resolution_checked=? WHERE id=? AND resolution_checked=0',
                           (info.width if info else None, info.height if info else None, 1 if info else 2, video_id))
        except sqlite3.OperationalError as error:
            if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():
                raise
            return ResolutionResult(video_id, 'retry', str(error), perf_counter() - started, perf_counter() - write_started)
        return ResolutionResult(video_id, 'completed' if info else 'unknown', message,
                                perf_counter() - started, perf_counter() - write_started)
