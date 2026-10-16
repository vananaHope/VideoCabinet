"""내용 지문으로 영상을 식별하고 위치와 제외 상태를 보존한다."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
import os
from pathlib import Path
import stat
from threading import RLock
from typing import Protocol

from .external_subtitles import ExternalSubtitles


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    format: str
    width: int | None = None
    height: int | None = None


class MediaReader(Protocol):
    def read(self, path: Path) -> MediaInfo | None: ...
    def capture(self, path: Path, destination: Path, seconds: float) -> None: ...


@dataclass(frozen=True)
class Location:
    path: Path


@dataclass(frozen=True)
class WatchedFolder:
    path: Path


@dataclass(frozen=True)
class Video:
    id: int
    title: str
    fingerprint: str
    duration: float
    format: str
    thumbnail: Path
    registered_at: datetime
    locations: tuple[Location, ...]
    excluded: bool = False
    width: int | None = None
    height: int | None = None

    @property
    def missing(self) -> bool:
        return not self.locations


@dataclass(frozen=True)
class ScanIssue:
    path: Path
    message: str
    failed: bool = True


@dataclass(frozen=True)
class ScanResult:
    added: int
    issues: tuple[ScanIssue, ...]
    reconnected: bool = False


def _fingerprint(path: Path) -> str:
    # ADR-0002: 크기 + 앞/중앙/뒤 최대 64 KiB씩. 기존 v1 지문과 호환한다.
    sample_size = 64 * 1024
    with path.open("rb") as source:
        size = path.stat().st_size
        digest = hashlib.sha256(str(size).encode("ascii"))
        for offset in (0, max(0, (size - sample_size) // 2), max(0, size - sample_size)):
            source.seek(offset)
            digest.update(source.read(sample_size))
    return f"v1:{size}:{digest.hexdigest()}"


def _signature(path: Path) -> tuple[int, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise FileNotFoundError(f"파일이 아닙니다: {path}")
    return info.st_size, info.st_mtime_ns


LIBRARY_DB_VERSION = 4


def migrate_library(db, *, before_upgrade=None) -> None:
    """기존 기록을 보존하며 라이브러리를 현재 버전으로 이전한다."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > LIBRARY_DB_VERSION:
        raise ValueError("더 최신 버전에서 만든 라이브러리입니다. 프로그램을 업데이트하세요.")
    if version < LIBRARY_DB_VERSION:
        from .backup import backup_before_migration
        (before_upgrade or backup_before_migration)(db, LIBRARY_DB_VERSION)
    db.execute("BEGIN IMMEDIATE")
    if version == 0:
        db.execute("CREATE TABLE IF NOT EXISTS watched_folders (path TEXT PRIMARY KEY)")
        db.execute("""CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, duration REAL NOT NULL, format TEXT NOT NULL,
            thumbnail TEXT NOT NULL, registered_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS locations (
            path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id))""")
    if version < 2:
        db.execute("ALTER TABLE videos ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE locations ADD COLUMN size INTEGER")
        db.execute("ALTER TABLE locations ADD COLUMN mtime_ns INTEGER")
        db.execute("""CREATE TABLE library_file_checks (
            path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
            duration REAL, fingerprint TEXT)""")
        db.execute("UPDATE videos SET excluded=1 WHERE ',' || lower(format) || ',' LIKE '%,gif,%'")
        db.execute("PRAGMA user_version = 2")
    if version < 3:
        db.execute("ALTER TABLE videos ADD COLUMN width INTEGER")
        db.execute("ALTER TABLE videos ADD COLUMN height INTEGER")
        # 0=미처리, 1=확인, 2=파일 없음/실패(명시적 검사 때 재시도).
        db.execute("ALTER TABLE videos ADD COLUMN resolution_checked INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX videos_resolution_pending ON videos(id) WHERE resolution_checked=0")
        db.execute("PRAGMA user_version = 3")
    if version < 4:
        db.execute("""CREATE TABLE translation_glossary (
            queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
            source TEXT NOT NULL, target TEXT NOT NULL, ordinal INTEGER NOT NULL,
            PRIMARY KEY(queue_id, source))""")
        db.execute("PRAGMA user_version = 4")


class Library:
    def __init__(self, connect, media, clock, thumbnails, settings, *, on_registered=None):
        self._connect, self._media, self._clock = connect, media, clock
        self._thumbnails = thumbnails
        self._settings = settings
        self._on_registered = on_registered or (lambda video_id: None)
        # 검사와 화면에서 하는 위치/제외 변경의 순서를 보장한다.
        self._lock = RLock()
        with connect() as db:
            migrate_library(db)
            db.execute("CREATE INDEX IF NOT EXISTS locations_video_id ON locations(video_id)")
        self.external_subtitles = ExternalSubtitles(connect)

    def add_watched_folder(self, path: Path) -> WatchedFolder:
        path = Path(path).resolve()
        if not path.is_dir():
            raise ValueError(f"폴더가 아닙니다: {path}")
        with self._lock, self._connect() as db:
            db.execute("INSERT OR IGNORE INTO watched_folders VALUES (?)", (str(path),))
        return WatchedFolder(path)

    def watched_folders(self) -> tuple[WatchedFolder, ...]:
        with self._connect() as db:
            return tuple(WatchedFolder(Path(row[0])) for row in db.execute("SELECT path FROM watched_folders ORDER BY path"))

    def remove_watched_folder(self, path: Path) -> None:
        path = Path(path).resolve()
        with self._lock, self._connect() as db:
            if not db.execute("DELETE FROM watched_folders WHERE path=?", (str(path),)).rowcount:
                raise ValueError("감시 폴더를 찾을 수 없습니다.")
            # 해제한 폴더 아래의 위치를 모두 해제한다. 실제 파일과 영상 기록은 남긴다.
            paths = [row[0] for row in db.execute("SELECT path FROM locations")
                     if Path(row[0]).is_relative_to(path)]
            db.executemany("DELETE FROM locations WHERE path=?", ((p,) for p in paths))

    @property
    def minimum_duration(self) -> float:
        return self._settings.get("library.min_duration_seconds", 60.0)

    def set_minimum_duration(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("최소 길이는 0 이상의 유한한 초 단위 값이어야 합니다.")
        with self._lock:
            self._settings.set("library.min_duration_seconds", float(seconds))

    def rename_video(self, video_id: int, title: str) -> None:
        title = title.strip()
        if not title:
            raise ValueError("영상 제목을 입력하세요.")
        with self._lock, self._connect() as db:
            if not db.execute("UPDATE videos SET title=? WHERE id=?", (title, video_id)).rowcount:
                raise ValueError("영상을 찾을 수 없습니다.")

    def set_excluded(self, video_id: int, excluded: bool) -> None:
        with self._lock, self._connect() as db:
            if not db.execute("UPDATE videos SET excluded=? WHERE id=?", (excluded, video_id)).rowcount:
                raise ValueError("영상을 찾을 수 없습니다.")

    def videos(self, *, excluded: bool = False) -> tuple[Video, ...]:
        with self._connect() as db:
            db.execute("BEGIN")
            locations: dict[int, list[Location]] = {}
            for row in db.execute("SELECT video_id, path FROM locations ORDER BY path"):
                locations.setdefault(row["video_id"], []).append(Location(Path(row["path"])))
            return tuple(
                Video(row["id"], row["title"], row["fingerprint"], row["duration"], row["format"],
                      self._thumbnails / Path(row["thumbnail"]).name, datetime.fromisoformat(row["registered_at"]),
                      tuple(locations.get(row["id"], [])), bool(row["excluded"]), row["width"], row["height"])
                for row in db.execute("SELECT * FROM videos WHERE excluded=? ORDER BY title, id", (excluded,)))

    def _forget_location(self, path: Path) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM locations WHERE path=?", (str(path),))

    @staticmethod
    def _not_added(path: Path, message: str) -> ScanResult:
        return ScanResult(0, (ScanIssue(path, message, failed=False),))

    def _already_registered(self, path: Path, excluded: bool, *, reconnected=False) -> ScanResult:
        if excluded:
            return self._not_added(path, "제외 목록에 있는 영상입니다. 제외 목록에서 되돌려 주세요.")
        if reconnected:
            return ScanResult(0, (ScanIssue(path, "파일 없음이던 영상을 다시 찾았습니다.", failed=False),),
                              reconnected=True)
        return self._not_added(path, "이미 등록된 영상입니다.")

    def _register(self, path: Path, *, on_registered=None, missing_at_start=None,
                  signature=None, minimum=None) -> ScanResult:
        signature = _signature(path) if signature is None else signature
        minimum = self.minimum_duration if minimum is None else minimum
        with self._connect() as db:
            old = db.execute("""SELECT l.video_id, l.size, l.mtime_ns, v.excluded FROM locations l
                JOIN videos v ON v.id=l.video_id WHERE l.path=?""", (str(path),)).fetchone()
            if old and (old["size"], old["mtime_ns"]) == signature:
                return self._already_registered(path, old["excluded"])
            check = db.execute("SELECT * FROM library_file_checks WHERE path=?", (str(path),)).fetchone()
            if check and (check["size"], check["mtime_ns"]) == signature:
                if check["duration"] is None:
                    return self._not_added(path, "영상이 아닙니다(GIF 포함).")
                known = db.execute("SELECT id, excluded FROM videos WHERE fingerprint=?", (check["fingerprint"],)).fetchone()
                if known:
                    was_missing = not db.execute("SELECT 1 FROM locations WHERE video_id=?", (known[0],)).fetchone()
                    db.execute("INSERT OR REPLACE INTO locations(path, video_id, size, mtime_ns) VALUES (?, ?, ?, ?)",
                               (str(path), known[0], *signature))
                    db.execute("DELETE FROM library_file_checks WHERE path=?", (str(path),))
                    return self._already_registered(path, known["excluded"], reconnected=was_missing
                                                    and (missing_at_start is None or known[0] in missing_at_start))
                if check["duration"] < minimum:
                    return self._not_added(path, f"최소 길이({minimum:g}초) 미만입니다.")
            legacy_gifs = {row["fingerprint"]: row for row in db.execute(
                """SELECT id, fingerprint, excluded FROM videos
                   WHERE ',' || lower(format) || ',' LIKE '%,gif,%' AND fingerprint LIKE ?""",
                (f"v1:{signature[0]}:%",))}
        # 다른 내용으로 교체된 위치는 읽기/캡처 실패 시에도 옛 영상에 남기지 않는다.
        self._forget_location(path)
        # 새 GIF는 등록하지 않지만 이전 DB의 GIF와 사용자의 되돌리기 결정은 보존한다.
        legacy_gif = legacy_gifs.get(_fingerprint(path)) if legacy_gifs else None
        if legacy_gif:
            self._check_unchanged(path, signature)
            with self._connect() as db:
                was_missing = (not (old and old["video_id"] == legacy_gif["id"])
                               and not db.execute("SELECT 1 FROM locations WHERE video_id=?", (legacy_gif["id"],)).fetchone())
                db.execute("INSERT OR REPLACE INTO locations(path, video_id, size, mtime_ns) VALUES (?, ?, ?, ?)",
                           (str(path), legacy_gif["id"], *signature))
                db.execute("DELETE FROM library_file_checks WHERE path=?", (str(path),))
            return self._already_registered(path, legacy_gif["excluded"], reconnected=was_missing
                                            and (missing_at_start is None or legacy_gif["id"] in missing_at_start))
        info = self._media.read(path)
        if info is not None and "gif" in info.format.lower().split(","):
            info = None
        fingerprint = _fingerprint(path) if info is not None else None
        with self._connect() as db:
            existing = db.execute("SELECT id, excluded FROM videos WHERE fingerprint=?", (fingerprint,)).fetchone()
        if info is None or (not existing and info.duration < minimum):
            self._check_unchanged(path, signature)
            with self._connect() as db:
                db.execute("INSERT OR REPLACE INTO library_file_checks VALUES (?, ?, ?, ?, ?)",
                           (str(path), *signature, info.duration if info else None, fingerprint))
            return self._not_added(path, "영상이 아닙니다(GIF 포함)." if info is None
                                   else f"최소 길이({minimum:g}초) 미만입니다.")
        from .thumbnails import THUMBNAIL_SUFFIX
        thumbnail = self._thumbnails / (fingerprint.split(":")[-1] + THUMBNAIL_SUFFIX)
        if not existing:
            self._media.capture(path, thumbnail, min(10, info.duration / 10))
        self._check_unchanged(path, signature)
        with self._connect() as db:
            if existing:
                video_id = existing[0]
                was_missing = (not (old and old["video_id"] == video_id)
                               and not db.execute("SELECT 1 FROM locations WHERE video_id=?", (video_id,)).fetchone())
            else:
                video_id = db.execute(
                    "INSERT INTO videos (fingerprint, title, duration, format, thumbnail, registered_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (fingerprint, path.stem, info.duration, info.format,
                     str(Path("thumbnails") / thumbnail.name), self._clock().isoformat())).lastrowid
            db.execute("INSERT OR REPLACE INTO locations(path, video_id, size, mtime_ns) VALUES (?, ?, ?, ?)",
                       (str(path), video_id, *signature))
            db.execute("DELETE FROM library_file_checks WHERE path=?", (str(path),))
            db.execute("UPDATE videos SET width=?, height=?, resolution_checked=1 WHERE id=?",
                       (info.width, info.height, video_id))
        if not existing:
            (on_registered or self._on_registered)(video_id)
        return (self._already_registered(path, existing["excluded"], reconnected=was_missing
                                         and (missing_at_start is None or existing[0] in missing_at_start))
                if existing else ScanResult(1, ()))

    def video(self, video_id: int) -> Video:
        with self._connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            if row is None:
                raise ValueError("영상을 찾을 수 없습니다.")
            locations = tuple(Location(Path(r[0])) for r in db.execute(
                "SELECT path FROM locations WHERE video_id = ? ORDER BY path", (video_id,)))
            return Video(row["id"], row["title"], row["fingerprint"], row["duration"], row["format"],
                         self._thumbnails / Path(row["thumbnail"]).name, datetime.fromisoformat(row["registered_at"]),
                         locations, bool(row["excluded"]), row["width"], row["height"])

    @staticmethod
    def _check_unchanged(path, signature):
        if _signature(path) != signature:
            raise ValueError("검사 중 파일이 변경되었습니다. 다시 검사해 주세요.")

    def add_file(self, path: Path) -> ScanResult:
        with self._lock:
            path = Path(path).resolve()
            with self._connect() as db:
                affected = {row[0] for row in db.execute("SELECT video_id FROM locations WHERE path=?", (str(path),))}
            result = self._register(path)
            with self._connect() as db:
                affected.update(row[0] for row in db.execute("SELECT video_id FROM locations WHERE path=?", (str(path),)))
            warnings = self.external_subtitles.refresh(affected)
            return ScanResult(result.added, result.issues + tuple(ScanIssue(*warning) for warning in warnings),
                              reconnected=result.reconnected)

    def reconnect_video(self, video_id: int, path: Path) -> None:
        with self._lock:
            with self._connect() as db:
                video = db.execute("SELECT fingerprint FROM videos WHERE id=?", (video_id,)).fetchone()
            if video is None:
                raise ValueError("영상을 찾을 수 없습니다.")
            path = Path(path).resolve()
            signature = _signature(path)
            if _fingerprint(path) != video[0]:
                raise ValueError("다른 내용의 파일입니다. 원래 영상과 같은 파일을 선택하세요.")
            self._check_unchanged(path, signature)
            with self._connect() as db:
                db.execute("INSERT OR REPLACE INTO locations(path, video_id, size, mtime_ns) VALUES (?, ?, ?, ?)",
                           (str(path), video_id, *signature))
                db.execute("DELETE FROM library_file_checks WHERE path=?", (str(path),))
                db.execute("UPDATE videos SET resolution_checked=0 WHERE id=? AND width IS NULL", (video_id,))

    def playback_location(self, video_id: int) -> Location:
        with self._connect() as db:
            video = db.execute("SELECT excluded FROM videos WHERE id=?", (video_id,)).fetchone()
            paths = [Path(row[0]) for row in db.execute("SELECT path FROM locations WHERE video_id=? ORDER BY path", (video_id,))]
        if video and video[0]:
            raise ValueError("제외된 영상입니다. 제외 목록에서 되돌려 주세요.")
        for path in paths:
            if path.is_file():
                return Location(path)
            self._forget_location(path)
        raise ValueError("파일 없음: 영상의 위치가 없습니다. 다시 검사하거나 파일을 다시 연결해 주세요.")

    def scan(self, *, on_registered=None) -> ScanResult:
        with self._lock:
            result = self._scan(on_registered=on_registered)
            warnings = self.external_subtitles.refresh()
            return ScanResult(result.added, result.issues + tuple(ScanIssue(*warning) for warning in warnings),
                              reconnected=result.reconnected)

    def _scan(self, *, on_registered=None) -> ScanResult:
        added, issues = 0, []
        reconnected = False
        processed: set[Path] = set()
        seen: set[Path] = set()
        inaccessible: set[Path] = set()
        # 직접 추가한 파일도 변경/사라짐을 확인한다. 읽기 권한 오류는 위치 삭제로 해석하지 않는다.
        with self._connect() as db:
            # 실패한 해상도는 유지한다. 파일 변경은 _register에서 다시 읽고,
            # 명시적 위치 연결은 reconnect_video에서 미확인으로 되돌린다.
            locations = {Path(row["path"]): (row["size"], row["mtime_ns"])
                         for row in db.execute("SELECT path, size, mtime_ns FROM locations")}
            checks = {Path(row["path"]): row for row in db.execute("SELECT * FROM library_file_checks")}
            known_fingerprints = {row[0] for row in db.execute("SELECT fingerprint FROM videos")}
            missing_at_start = {row[0] for row in db.execute(
                "SELECT id FROM videos WHERE NOT EXISTS (SELECT 1 FROM locations WHERE video_id = videos.id)")}
        minimum = self.minimum_duration
        check_paths = set(checks)

        def registered(video_id):
            # 같은 검사에서 새로 등록된 영상의 짧은 복사본도 기존 영상에 연결한다.
            with self._connect() as db:
                known_fingerprints.add(db.execute("SELECT fingerprint FROM videos WHERE id=?", (video_id,)).fetchone()[0])
            (on_registered or self._on_registered)(video_id)

        def register(path, signature):
            nonlocal reconnected
            # scan은 이미 등록됨/제외됨/비영상/최소 길이 미만 안내를 결과에 싣지 않는다.
            if locations.get(path) == signature:
                return 0
            check = checks.get(path)
            if check and (check["size"], check["mtime_ns"]) == signature:
                if check["duration"] is None:
                    return 0
                if check["duration"] < minimum and check["fingerprint"] not in known_fingerprints:
                    return 0
            # 순회 뒤 파일이 바뀌었거나 DirEntry 값이 늦을 수 있어 등록 시 서명을 새로 읽는다.
            result = self._register(path, on_registered=registered, missing_at_start=missing_at_start,
                                    minimum=minimum)
            check_paths.add(path)
            if result.reconnected:
                reconnected = True
                issues.extend(result.issues)
            return result.added

        roots = [folder.path for folder in self.watched_folders()]
        pending = list(reversed(roots))
        visited: set[Path] = set()
        signatures: dict[Path, tuple[int, int]] = {}
        entries_in_order: list[Path | ScanIssue] = []
        # 먼저 순회 결과를 모아 기존 위치 확인에도 DirEntry의 stat을 재사용한다.
        # 등록/오류 보고는 기존처럼 저장된 위치 먼저, 이어서 순회 순서로 처리한다.
        while pending:
            directory = pending.pop()
            try:
                real_path = directory.resolve()
                if real_path in visited:
                    continue
                visited.add(real_path)
                with os.scandir(directory) as entries:
                    for entry in entries:
                        path = real_path / entry.name
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if (stat.S_ISLNK(info.st_mode)
                                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                                entries_in_order.append(ScanIssue(
                                    path, "건너뜀: 다른 폴더나 파일을 가리키는 연결(정션·심볼릭 링크)", failed=False))
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                pending.append(path)
                            elif stat.S_ISREG(info.st_mode):
                                seen.add(path)
                                signatures[path] = (info.st_size, info.st_mtime_ns)
                                entries_in_order.append(path)
                        except (OSError, ValueError, RuntimeError) as error:
                            inaccessible.add(path)
                            entries_in_order.append(ScanIssue(path, str(error)))
            except (OSError, RuntimeError) as error:
                if not isinstance(error, (FileNotFoundError, NotADirectoryError)):
                    inaccessible.add(directory)
                entries_in_order.append(ScanIssue(directory, str(error)))

        for path in locations:
            processed.add(path)
            try:
                signature = signatures.get(path)
                added += register(path, _signature(path) if signature is None else signature)
            except (FileNotFoundError, NotADirectoryError):
                self._forget_location(path)
            except (OSError, ValueError, RuntimeError) as error:
                issues.append(ScanIssue(path, str(error)))
        for entry in entries_in_order:
            if isinstance(entry, ScanIssue):
                issues.append(entry)
            elif entry not in processed:
                processed.add(entry)
                try:
                    added += register(entry, signatures[entry])
                except (OSError, ValueError, RuntimeError) as error:
                    inaccessible.add(entry)
                    issues.append(ScanIssue(entry, str(error)))
        with self._connect() as db:
            stale = [path for path in check_paths if path not in seen
                     and any(path.is_relative_to(root) for root in roots)
                     and not any(path.is_relative_to(blocked) for blocked in inaccessible)]
            db.executemany("DELETE FROM library_file_checks WHERE path=?", ((str(path),) for path in stale))
        return ScanResult(added, tuple(issues), reconnected=reconnected)
