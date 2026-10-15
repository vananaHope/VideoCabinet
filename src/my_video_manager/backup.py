"""라이브러리 스냅샷과 다음 시작 시 되돌리기. 화면이나 실행 중 코어를 소유하지 않는다."""

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4
import zipfile


APPLICATION = "my-video-manager"
FORMAT_VERSION = 1
AUTO_BACKUP_KEEP = 5
DATABASE_NAME = "library.sqlite3"
RESTORE_GUIDANCE = (
    "영상 파일은 백업에 포함되지 않습니다. 다른 PC에서 되돌린 뒤 파일 없음으로 보이면 "
    "새 영상 폴더를 감시 폴더로 추가하고 다시 검사하세요. 내용 지문이 같은 영상은 "
    "기존 태그·자막·하이라이트·시청 기록에 다시 연결됩니다."
)


class BackupError(ValueError):
    """검사에서 거부한 백업. 현재 라이브러리는 바꾸지 않는다."""


@dataclass(frozen=True)
class BackupMetadata:
    app_version: str
    db_version: int
    created_at: str
    video_count: int
    includes_thumbnails: bool


@dataclass(frozen=True)
class BackupResult:
    path: Path
    metadata: BackupMetadata
    snapshot_seconds: float
    # backup_step 호출 사이의 경과 시간: 실제 잠금 시간보다 큰 상한 추정치다.
    max_step_seconds: float


@dataclass(frozen=True)
class RestoreResult:
    metadata: BackupMetadata
    restart_required: bool
    guidance: str = RESTORE_GUIDANCE
    safety_backup: Path | None = None


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync(path):
    with Path(path).open("r+b") as stream:
        os.fsync(stream.fileno())


def _snapshot(database, destination):
    started = previous = time.monotonic()
    max_step = 0.0

    def progress(status, remaining, total):
        nonlocal previous, max_step
        now = time.monotonic()
        if status in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE):
            max_step = max(max_step, now - previous)
        if now - started > 30:
            raise TimeoutError("백업이 오래 지연되어 중단했습니다. 잠시 뒤 다시 시도하세요.")
        # SQLite가 progress 전에 원본의 읽기 잠금을 해제한다. Windows에서
        # 매 단계 sleep을 넣으면 타이머 해상도 때문에 복사가 길어져,
        # 주기적 시청 저장마다 스냅샷이 처음부터 반복될 수 있다.
        previous = time.monotonic()

    with closing(_readonly(database)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target, pages=128, progress=progress, sleep=0.01)
        target.execute("PRAGMA journal_mode=DELETE")
    return time.monotonic() - started, max_step


def _database_metadata(path):
    with closing(_readonly(path)) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BackupError("DB 무결성 검사에 실패했습니다.")
        # v0/v1 라이브러리에도 있던 공개 데이터의 최소 형태를 확인한다.
        db.execute("SELECT id, fingerprint, title, duration, format, thumbnail, registered_at FROM videos LIMIT 0")
        db.execute("SELECT path, video_id FROM locations LIMIT 0")
        db.execute("SELECT path FROM watched_folders LIMIT 0")
        return (db.execute("PRAGMA user_version").fetchone()[0],
                db.execute("SELECT count(*) FROM videos").fetchone()[0])


def create_backup(database: Path, destination: Path, *, include_thumbnails=False,
                  active_viewings=()) -> BackupResult:
    """독립 연결의 작은 backup_step으로 복사한다. UI에서는 작업자에서 호출한다."""
    database, destination = Path(database).resolve(), Path(destination).resolve()
    if destination.suffix.lower() != ".zip":
        raise BackupError("백업 파일의 확장자는 .zip이어야 합니다.")
    if destination == database or destination == pending_restore_path(database):
        raise BackupError("라이브러리 또는 되돌리기 요청을 백업 대상으로 쓸 수 없습니다.")
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        snapshot = stage / DATABASE_NAME
        elapsed, max_step = _snapshot(database, snapshot)
        # 저장 주기 전 진행분도 담되, 복사하는 동안 더 최신 저장/종료가
        # 들어왔다면 그 기록을 과거 진행분으로 덮어쓰지 않는다.
        if active_viewings:
            with closing(sqlite3.connect(snapshot)) as db, db:
                for viewing in active_viewings:
                    db.execute("UPDATE viewings SET updated_at=?, intervals=?, last_position=? "
                               "WHERE id=? AND ended_at IS NULL AND updated_at<=?",
                               (viewing.updated_at.isoformat(), json.dumps(viewing.intervals),
                                viewing.last_position, viewing.id, viewing.updated_at.isoformat()))
        db_version, count = _database_metadata(snapshot)
        metadata = BackupMetadata(version(APPLICATION), db_version,
                                  datetime.now(timezone.utc).isoformat(), count, include_thumbnails)
        files = {DATABASE_NAME: _sha256(snapshot)}
        archive = stage / "backup.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(snapshot, DATABASE_NAME)
            if include_thumbnails:
                with closing(_readonly(snapshot)) as db:
                    names = {Path(row[0]).name for row in db.execute("SELECT thumbnail FROM videos")}
                for name in sorted(names):
                    source = database.parent / "thumbnails" / name
                    if not source.is_file() or source.is_symlink():
                        continue
                    # 파일이 바뀌더라도 해시와 압축 내용은 같은 사본에서 만든다.
                    thumbnail = stage / "thumbnail"
                    shutil.copyfile(source, thumbnail)
                    member = "thumbnails/" + name
                    files[member] = _sha256(thumbnail)
                    bundle.write(thumbnail, member)
            manifest = dict(application=APPLICATION, format_version=FORMAT_VERSION,
                            **asdict(metadata), files=files)
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        _sync(archive)
        os.replace(archive, destination)
    return BackupResult(destination, metadata, elapsed, max_step)


def _valid_member(name):
    return name == DATABASE_NAME or bool(re.fullmatch(r"thumbnails/[A-Za-z0-9_-]+\.jpg", name))


def _extract_checked(archive, stage):
    from .library import LIBRARY_DB_VERSION

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise BackupError("중복 파일이 있거나 manifest.json이 없습니다.")
            if bundle.getinfo("manifest.json").file_size > 1024 * 1024:
                raise BackupError("백업 메타데이터가 너무 큽니다.")
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest["application"] != APPLICATION or manifest["format_version"] != FORMAT_VERSION:
                raise BackupError("이 앱에서 지원하는 백업이 아닙니다.")
            metadata = BackupMetadata(**{key: manifest[key] for key in BackupMetadata.__dataclass_fields__})
            if (type(metadata.db_version) is not int or metadata.db_version < 0
                    or type(metadata.video_count) is not int or metadata.video_count < 0
                    or type(metadata.includes_thumbnails) is not bool
                    or not isinstance(metadata.app_version, str) or not metadata.app_version
                    or datetime.fromisoformat(metadata.created_at).tzinfo is None):
                raise BackupError("백업 메타데이터 형식이 올바르지 않습니다.")
            if metadata.db_version > LIBRARY_DB_VERSION:
                raise BackupError("더 최신 DB 버전의 백업입니다. 프로그램을 업데이트하세요.")
            files = manifest["files"]
            if not isinstance(files, dict) or DATABASE_NAME not in files or set(names) != {*files, "manifest.json"}:
                raise BackupError("백업 파일 목록이 일치하지 않습니다.")
            if not metadata.includes_thumbnails and len(files) != 1:
                raise BackupError("썸네일 포함 정보가 일치하지 않습니다.")
            for name, digest in files.items():
                if not _valid_member(name) or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                    raise BackupError("백업 파일 경로나 해시가 올바르지 않습니다.")
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if _sha256(target) != digest:
                    raise BackupError("백업 파일의 SHA-256이 일치하지 않습니다.")
            if _database_metadata(stage / DATABASE_NAME) != (metadata.db_version, metadata.video_count):
                raise BackupError("DB와 백업 메타데이터가 일치하지 않습니다.")
            return metadata
    except (KeyError, TypeError, ValueError, sqlite3.DatabaseError, zipfile.BadZipFile,
            RuntimeError, NotImplementedError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError("손상되었거나 형식이 올바르지 않은 백업입니다.") from error


def inspect_backup(archive: Path) -> BackupMetadata:
    """모든 파일의 해시와 DB를 검사한 뒤 미리보기 메타데이터를 돌려준다."""
    with tempfile.TemporaryDirectory(prefix="mvm-backup-check-") as temporary:
        return _extract_checked(archive, Path(temporary))


def pending_restore_path(database: Path) -> Path:
    database = Path(database).resolve()
    return database.with_name(database.name + ".restore-pending.zip")


def request_restore(database: Path, archive: Path) -> RestoreResult:
    """원본 ZIP이 이동되어도 유지되는 검증된 사본 하나를 원자적으로 예약한다."""
    database = Path(database).resolve()
    with tempfile.TemporaryDirectory(prefix=".restore-request-", dir=database.parent) as temporary:
        candidate = Path(temporary) / "pending.zip"
        shutil.copyfile(archive, candidate)
        metadata = inspect_backup(candidate)
        _sync(candidate)
        os.replace(candidate, pending_restore_path(database))
    return RestoreResult(metadata, restart_required=True)


def cancel_restore(database: Path) -> None:
    pending_restore_path(database).unlink(missing_ok=True)


def automatic_backups(database: Path) -> tuple[Path, ...]:
    directory = Path(database).resolve().parent / "backups"
    paths = (path for path in directory.glob("auto-*.zip")
             if re.fullmatch(r"auto-\d{8}T\d{12}Z-[0-9a-f]{32}\.zip", path.name)
             and path.is_file() and not path.is_symlink())
    return tuple(sorted(paths, key=lambda path: path.name, reverse=True))


def create_automatic_backup(database: Path, *, include_thumbnails=False) -> BackupResult:
    directory = Path(database).resolve().parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    result = create_backup(database, directory / f"auto-{stamp}-{uuid4().hex}.zip",
                           include_thumbnails=include_thumbnails)
    for path in automatic_backups(database)[AUTO_BACKUP_KEEP:]:
        path.unlink()
    return result


def backup_before_migration(db, target_version: int) -> BackupResult | None:
    """BEGIN/DDL보다 먼저 호출한다. 새 빈 DB와 메모리 DB에는 백업을 만들지 않는다."""
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current >= target_version or not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='videos'").fetchone():
        return None
    if db.in_transaction:
        raise BackupError("DB 이전 전 백업은 트랜잭션 시작 전에 만들어야 합니다.")
    filename = next(row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main")
    return create_automatic_backup(Path(filename)) if filename else None


def apply_pending_restore(database: Path, *, instance) -> RestoreResult | None:
    """SingleInstance 잠금 확보 뒤, AppCore/작업자/DB 연결을 만들기 전에만 호출한다.

    썸네일은 기존 파일을 덮어쓰지 않는다. 준비와 이전을 마친 DB의 replace가
    유일한 커밋 지점이며, 그 뒤의 청소 실패는 되돌리기 실패로 취급하지 않는다.
    """
    database = Path(database).resolve()
    if not instance.lock.isLocked() or instance.lock_path.parent.resolve() != database.parent:
        raise RuntimeError("되돌리기에는 이 데이터 폴더의 단일 인스턴스 잠금이 필요합니다.")
    pending = pending_restore_path(database)
    if not pending.exists():
        return None
    from .library import migrate_library

    added_thumbnails = []
    consumed = pending.with_name(pending.name + ".applying")
    committed = False
    try:
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=database.parent,
                                         ignore_cleanup_errors=True) as temporary:
            stage = Path(temporary)
            metadata = _extract_checked(pending, stage)
            snapshot = stage / DATABASE_NAME
            # 실제 라이브러리를 건드리기 전에 이전까지 성공하는지 확인한다.
            with closing(sqlite3.connect(snapshot)) as db, db:
                migrate_library(db, before_upgrade=lambda db, target: None)
                for (path,) in db.execute("SELECT path FROM locations").fetchall():
                    try:
                        Path(path).stat()
                    except (FileNotFoundError, NotADirectoryError):
                        db.execute("DELETE FROM locations WHERE path=?", (path,))
                thumbnails = database.parent / "thumbnails"
                thumbnails.mkdir(exist_ok=True)
                for source in (stage / "thumbnails").glob("*.jpg"):
                    target = thumbnails / source.name
                    if target.exists() and _sha256(target) == _sha256(source):
                        continue
                    if target.exists():
                        target = thumbnails / f"restored-{uuid4().hex}.jpg"
                        for video_id, thumbnail in db.execute("SELECT id, thumbnail FROM videos").fetchall():
                            if Path(thumbnail).name == source.name:
                                db.execute("UPDATE videos SET thumbnail=? WHERE id=?",
                                           ("thumbnails/" + target.name, video_id))
                    os.replace(source, target)
                    added_thumbnails.append(target)
                    _sync(target)
            _sync(snapshot)
            safety = create_automatic_backup(database, include_thumbnails=True).path if database.exists() else None
            if database.exists():
                # 중단된 WAL도 SQLite로 회수한다. 외부 연결이 남으면 교체하지 않는다.
                with closing(sqlite3.connect(database, timeout=1)) as db:
                    if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                        raise BackupError("사용 중인 DB 연결이 있어 되돌릴 수 없습니다.")
                    db.execute("PRAGMA journal_mode=DELETE")
            os.replace(pending, consumed)
            try:
                os.replace(snapshot, database)
            except BaseException:
                os.replace(consumed, pending)
                raise
            committed = True
            result = RestoreResult(metadata, restart_required=False, safety_backup=safety)
    finally:
        if not committed:
            for path in added_thumbnails:
                path.unlink(missing_ok=True)
        else:
            # 이미 교체된 DB가 다음 시작 때 다시 과거로 덮이지 않도록 요청은
            # 커밋 전에 소비했다. 비정상 종료의 .applying도 재적용하지 않는다.
            try:
                consumed.unlink(missing_ok=True)
            except OSError:
                pass
    return result
