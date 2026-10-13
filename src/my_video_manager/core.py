"""UI/재생 엔진과 독립된 앱 코어의 공개 경계."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
from pathlib import Path
import sqlite3
from typing import Callable, Mapping, Protocol


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    format: str


class MediaReader(Protocol):
    def read(self, path: Path) -> MediaInfo | None:
        """영상이 아니면 None, 읽기 실패 시 예외를 반환한다."""
        ...

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


class CommandType(str, Enum):
    TOGGLE_PAUSE = "toggle_pause"
    SEEK = "seek"
    CHANGE_SPEED = "change_speed"


@dataclass(frozen=True)
class Command:
    kind: CommandType
    amount: float = 0


DEFAULT_KEY_BINDINGS = {
    "Enter": Command(CommandType.TOGGLE_PAUSE),
    "Left": Command(CommandType.SEEK, -5),
    "Right": Command(CommandType.SEEK, 5),
    ",": Command(CommandType.SEEK, -3),
    "Up": Command(CommandType.CHANGE_SPEED, 0.25),
    "Down": Command(CommandType.CHANGE_SPEED, -0.25),
}


@dataclass(frozen=True)
class ScanIssue:
    path: Path
    message: str


@dataclass(frozen=True)
class ScanResult:
    added: int
    issues: tuple[ScanIssue, ...]


def default_data_directory() -> Path:
    return Path.home() / ".my-video-manager"


def _fingerprint(path: Path) -> str:
    # v1: 크기 + 최대 64 KiB씩 앞/중앙/뒤. 전체 해시가 아니므로
    # 샘플 밖만 달라지는 같은 크기의 파일은 구별하지 못할 수 있다.
    sample_size = 64 * 1024
    with path.open("rb") as source:
        size = path.stat().st_size
        digest = hashlib.sha256(str(size).encode("ascii"))
        for offset in (0, max(0, (size - sample_size) // 2), max(0, size - sample_size)):
            source.seek(offset)
            digest.update(source.read(sample_size))
    return f"v1:{size}:{digest.hexdigest()}"


class AppCore:
    def __init__(
        self,
        *,
        media: MediaReader,
        clock: Callable[[], datetime],
        database: Path | None = None,
        key_bindings: Mapping[str, Command] | None = None,
    ):
        self.database = Path(database) if database is not None else default_data_directory() / "library.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._thumbnails = self.database.parent / "thumbnails"
        self._thumbnails.mkdir(exist_ok=True)
        self._media = media
        self._clock = clock
        self.set_key_bindings(DEFAULT_KEY_BINDINGS if key_bindings is None else key_bindings)
        # 접속은 호출 단위로 열어 UI 작업자 스레드에서도 코어를 사용할 수 있다.
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS watched_folders (path TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    duration REAL NOT NULL,
                    format TEXT NOT NULL,
                    thumbnail TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS locations (
                    path TEXT PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id)
                );
                PRAGMA user_version = 1;
            """)

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # sqlite3의 context manager는 commit/rollback만 하므로 명시적으로 닫는다.
        return _Connection(connection)

    def set_key_bindings(self, bindings: Mapping[str, Command]) -> None:
        self._key_bindings = dict(bindings)

    def command_for_key(self, key: str) -> Command | None:
        return self._key_bindings.get(key)

    def add_watched_folder(self, path: Path) -> WatchedFolder:
        path = Path(path).resolve()
        if not path.is_dir():
            raise ValueError(f"폴더가 아닙니다: {path}")
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO watched_folders VALUES (?)", (str(path),))
        return WatchedFolder(path)

    def watched_folders(self) -> tuple[WatchedFolder, ...]:
        with self._connect() as db:
            return tuple(WatchedFolder(Path(row[0])) for row in db.execute("SELECT path FROM watched_folders ORDER BY path"))

    def scan(self) -> ScanResult:
        added = 0
        issues = []
        for folder in self.watched_folders():
            if not folder.path.is_dir():
                issues.append(ScanIssue(folder.path, "감시 폴더를 읽을 수 없습니다."))
                continue
            # 확장자 대신 어댑터가 영상 스트림 여부를 판별한다.
            for path in sorted(folder.path.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    added += self._register(path.resolve())
                except (OSError, ValueError, RuntimeError) as error:
                    issues.append(ScanIssue(path, str(error)))
        return ScanResult(added, tuple(issues))

    def _register(self, path: Path) -> int:
        with self._connect() as db:
            if db.execute("SELECT 1 FROM locations WHERE path = ?", (str(path),)).fetchone():
                return 0  # 기존 위치의 변경/이동 처리는 이슈 #3 범위
        info = self._media.read(path)
        if info is None:
            return 0
        fingerprint = _fingerprint(path)
        with self._connect() as db:
            existing = db.execute("SELECT id FROM videos WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if existing:
            with self._connect() as db:
                db.execute("INSERT OR IGNORE INTO locations VALUES (?, ?)", (str(path), existing[0]))
            return 0
        thumbnail = self._thumbnails / (fingerprint.split(":")[-1] + ".jpg")
        self._media.capture(path, thumbnail, min(10, info.duration / 10))
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO videos (fingerprint, title, duration, format, thumbnail, registered_at) VALUES (?, ?, ?, ?, ?, ?)",
                (fingerprint, path.stem, info.duration, info.format, str(thumbnail), self._clock().isoformat()),
            )
            db.execute("INSERT INTO locations VALUES (?, ?)", (str(path), cursor.lastrowid))
        return 1

    def videos(self) -> tuple[Video, ...]:
        with self._connect() as db:
            locations: dict[int, list[Location]] = {}
            for row in db.execute("SELECT video_id, path FROM locations ORDER BY path"):
                locations.setdefault(row["video_id"], []).append(Location(Path(row["path"])))
            return tuple(
                Video(row["id"], row["title"], row["fingerprint"], row["duration"], row["format"],
                      Path(row["thumbnail"]), datetime.fromisoformat(row["registered_at"]),
                      tuple(locations.get(row["id"], [])))
                for row in db.execute("SELECT * FROM videos ORDER BY title, id")
            )

    def playback_location(self, video_id: int) -> Location:
        with self._connect() as db:
            row = db.execute("SELECT path FROM locations WHERE video_id = ? ORDER BY path LIMIT 1", (video_id,)).fetchone()
        if row is None:
            raise ValueError("재생할 영상의 위치가 없습니다.")
        return Location(Path(row[0]))


class _Connection:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection.__enter__()

    def __exit__(self, *args):
        try:
            return self.connection.__exit__(*args)
        finally:
            self.connection.close()
