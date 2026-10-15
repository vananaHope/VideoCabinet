"""크기 버전이 없는 썸네일을 유휴 시간에 원자 교체한다. 진행은 파일명에 남는다."""
from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

from .library import _fingerprint, _signature
from .resolution import ResolutionResult

THUMBNAIL_SUFFIX = '.640.jpg'


class ThumbnailBackfill:
    def __init__(self, connect, media, directory, settings):
        self.connect, self.media, self.directory, self.settings = connect, media, directory, settings
        self.lock = Lock()
        # 인덱스만 추가한다. 저장 형식/열 변화가 없어 DB 버전과 자동 백업은 그대로다.
        with connect() as db:
            db.execute("CREATE INDEX IF NOT EXISTS videos_thumbnail_pending ON videos(id) WHERE substr(thumbnail,-8)!='.640.jpg' AND excluded=0")

    def retry_unavailable(self):
        self.settings.reset('thumbnail.cursor')

    def step(self, cancellation):
        if cancellation.is_set():
            return ResolutionResult(None, 'cancelled')
        if not self.lock.acquire(blocking=False):
            return ResolutionResult(None, 'retry')
        try:
            return self._step(cancellation)
        except sqlite3.OperationalError as error:
            if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():
                raise
            return ResolutionResult(None, 'retry', str(error))
        finally:
            self.lock.release()

    def _step(self, cancellation):
        with self.connect() as db:
            db.execute('PRAGMA busy_timeout=50')
            row = db.execute("""SELECT id, fingerprint, thumbnail, duration FROM videos
                WHERE substr(thumbnail,-8)!='.640.jpg' AND excluded=0
                AND id > COALESCE((SELECT CAST(value AS INTEGER) FROM settings WHERE key='thumbnail.cursor'),0)
                ORDER BY id LIMIT 1""").fetchone()
            if row is None:
                return ResolutionResult(None, 'exhausted')
            vid, fingerprint, old_name, duration = row
            paths = [Path(r[0]) for r in db.execute('SELECT path FROM locations WHERE video_id=?', (vid,))]
        target = self.directory / (fingerprint.split(':')[-1] + THUMBNAIL_SUFFIX)
        temporary = target.with_name(uuid4().hex + '.tmp.jpg')
        message = ''
        try:
            for path in paths:
                if cancellation.is_set():
                    return ResolutionResult(vid, 'cancelled')
                try:
                    signature = _signature(path)
                    if _fingerprint(path) != fingerprint:
                        continue
                    capture = getattr(self.media, 'capture_background', None)
                    if capture:
                        capture(path, temporary, min(10, duration / 10), cancellation=cancellation)
                    else:
                        self.media.capture(path, temporary, min(10, duration / 10))
                    if cancellation.is_set():
                        return ResolutionResult(vid, 'cancelled')
                    if _signature(path) != signature or not temporary.is_file():
                        continue
                    temporary.replace(target)
                    with self.connect() as db:
                        db.execute('PRAGMA busy_timeout=50')
                        updated = db.execute('UPDATE videos SET thumbnail=? WHERE id=? AND thumbnail=? AND excluded=0',
                                             (str(Path('thumbnails') / target.name), vid, old_name)).rowcount
                    if updated:
                        # DB가 새 파일을 가리킨 다음 이전 캐시를 정리한다.
                        try:
                            (self.directory / Path(old_name).name).unlink(missing_ok=True)
                        except OSError:
                            pass  # 열린 캐시는 그대로 두되 성공한 교체를 다시 시도하지 않는다.
                    return ResolutionResult(vid, 'completed' if updated else 'retry')
                except (OSError, ValueError, RuntimeError) as error:
                    message = str(error)
            if cancellation.is_set():
                return ResolutionResult(vid, 'cancelled')
            # 실패한 항목도 커서를 전진시켜 매번 앞의 실패 목록을 다시 훑지 않는다.
            self.settings.set('thumbnail.cursor', vid)
            return ResolutionResult(vid, 'unknown', message)
        finally:
            temporary.unlink(missing_ok=True)
