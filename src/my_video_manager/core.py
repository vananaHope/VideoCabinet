"""UI/재생 엔진과 독립된 앱 코어의 공개 경계."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
from typing import Callable, Mapping, Protocol

from .highlights import Highlight, Highlights
from .playback import PlaybackHub
from .viewing import Viewing, ViewingRecorder, ViewingSettings, ViewingStatus, ViewingStore, viewing_status
from .subtitles import Subtitles, Transcriber, Transcript, SubtitleQueueEntry, transcript_srt


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
    POINT_HIGHLIGHT = "point_highlight"
    RANGE_HIGHLIGHT = "range_highlight"
    PREVIOUS_HIGHLIGHT = "previous_highlight"
    NEXT_HIGHLIGHT = "next_highlight"
    TOGGLE_SUBTITLES = "toggle_subtitles"


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
    "Insert": Command(CommandType.POINT_HIGHLIGHT),
    "Delete": Command(CommandType.RANGE_HIGHLIGHT),
    "Home": Command(CommandType.PREVIOUS_HIGHLIGHT),
    "End": Command(CommandType.NEXT_HIGHLIGHT),
    "/": Command(CommandType.TOGGLE_SUBTITLES),
}

MIN_PLAYBACK_SPEED = 0.25
MAX_PLAYBACK_SPEED = 100


def playback_speed(current: float, change: float) -> float:
    return max(MIN_PLAYBACK_SPEED, min(MAX_PLAYBACK_SPEED, current + change))


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
        viewing_settings: ViewingSettings | None = None,
        transcriber: Transcriber | None = None,
    ):
        self.database = (Path(database) if database is not None else default_data_directory() / "library.sqlite3").resolve()
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
        self.playback = PlaybackHub()
        self._highlights = Highlights(self._connect)
        self.playback.subscribe(self._highlights)
        self._highlight_commands = {
            CommandType.POINT_HIGHLIGHT: self._highlights.add_point,
            CommandType.RANGE_HIGHLIGHT: self._highlights.toggle_range,
            CommandType.PREVIOUS_HIGHLIGHT: lambda: self._highlights.adjacent(forward=False),
            CommandType.NEXT_HIGHLIGHT: lambda: self._highlights.adjacent(forward=True),
        }
        self._viewings = ViewingStore(self._connect, clock, viewing_settings or ViewingSettings())
        self.playback.subscribe(ViewingRecorder(self._start_viewing, self._viewings.report, self._viewings.end))
        self._subtitles = Subtitles(self._connect, clock, transcriber, self.playback_location)

    def request_subtitles(self, video_id: int, spoken_language: str | None = None) -> SubtitleQueueEntry:
        return self._subtitles.request(video_id, spoken_language)

    def subtitle_queue(self) -> tuple[SubtitleQueueEntry, ...]:
        return self._subtitles.queue()

    def process_next_subtitle(self) -> SubtitleQueueEntry | None:
        return self._subtitles.process_next()

    def stop_subtitle_processing(self) -> None:
        self._subtitles.stop_processing()

    def transcript(self, video_id: int) -> Transcript | None:
        return self._subtitles.transcript(video_id)

    def playback_subtitle(self, video_id: int) -> Path | None:
        transcript = self.transcript(video_id)
        if transcript is None or not transcript.lines:
            return None
        directory = self.database.parent / "playback-subtitles"
        directory.mkdir(exist_ok=True)
        path = directory / f"{video_id}.srt"
        path.write_text(transcript_srt(transcript), encoding="utf-8")
        return path

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

    def highlights(self, video_id: int) -> tuple[Highlight, ...]:
        return self._highlights.list(video_id)

    def update_highlight(self, highlight_id: int, *, start: float, end: float | None,
                         note: str) -> Highlight:
        return self._highlights.update(highlight_id, start=start, end=end, note=note)

    def delete_highlight(self, highlight_id: int) -> None:
        self._highlights.delete(highlight_id)

    @property
    def open_highlight_start(self) -> float | None:
        return self._highlights.open_start

    def is_highlight_command(self, command: Command) -> bool:
        return command.kind in self._highlight_commands

    def execute_highlight_command(self, command: Command) -> float | None:
        """하이라이트 명령을 적용하고, 탐색할 때만 목표 시각을 반환한다."""
        handler = self._highlight_commands.get(command.kind)
        if handler is None:
            raise ValueError("하이라이트 명령이 아닙니다.")
        result = handler()
        return None if isinstance(result, Highlight) else result

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
        pending = [folder.path for folder in reversed(self.watched_folders())]
        visited: set[Path] = set()
        while pending:
            directory = pending.pop()
            try:
                real_path = directory.resolve()
                if real_path in visited:
                    continue
                visited.add(real_path)
                with os.scandir(directory) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if (stat.S_ISLNK(info.st_mode)
                                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                                continue  # 정션·심볼릭 링크 등은 따라가지 않는다.
                            if stat.S_ISDIR(info.st_mode):
                                pending.append(path)
                            elif stat.S_ISREG(info.st_mode):
                                added += self._register(path.resolve())
                        except (OSError, ValueError, RuntimeError) as error:
                            issues.append(ScanIssue(path, str(error)))
            except (OSError, RuntimeError) as error:
                # 한 디렉터리의 열거 실패로 나머지 감시 폴더/하위 폴더를 막지 않는다.
                issues.append(ScanIssue(directory, str(error)))
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
                (fingerprint, path.stem, info.duration, info.format,
                 str(Path("thumbnails") / thumbnail.name), self._clock().isoformat()),
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
                      # 최초 골격의 절대 경로 레코드도 파일 이름으로 읽어 호환한다.
                      self._thumbnails / Path(row["thumbnail"]).name, datetime.fromisoformat(row["registered_at"]),
                      tuple(locations.get(row["id"], [])))
                for row in db.execute("SELECT * FROM videos ORDER BY title, id")
            )

    def playback_location(self, video_id: int) -> Location:
        with self._connect() as db:
            row = db.execute("SELECT path FROM locations WHERE video_id = ? ORDER BY path LIMIT 1", (video_id,)).fetchone()
        if row is None:
            raise ValueError("재생할 영상의 위치가 없습니다.")
        return Location(Path(row[0]))

    def _start_viewing(self, video_id: int, position: float) -> Viewing:
        with self._connect() as db:
            row = db.execute("SELECT duration FROM videos WHERE id=?", (video_id,)).fetchone()
        if row is None:
            raise ValueError("영상이 없습니다.")
        return self._viewings.start(video_id, row[0], position)

    def save_viewings(self) -> None:
        self._viewings.save_due()

    def viewings(self, video_id: int) -> tuple[Viewing, ...]:
        return self._viewings.list(video_id)

    def viewing_status(self, video_id: int) -> ViewingStatus:
        return viewing_status(self.viewings(video_id), self._viewings.settings)

    def resume_start(self, video_id: int) -> float:
        point = self.viewing_status(video_id).resume_point
        return max(0, point - self._viewings.settings.resume_rewind) if point is not None else 0


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
