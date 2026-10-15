"""라이브러리 스냅샷과 다음 시작 시 백업 복원. 화면이나 실행 중 코어를 소유하지 않는다."""

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import errno
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
MAX_BACKUP_RESTARTS = 3
MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024
STALE_RESTORE_SECONDS = 24 * 60 * 60
DATABASE_NAME = "library.sqlite3"
BACKUP_RESTORE_GUIDANCE = (
    "영상 파일은 백업에 포함되지 않습니다. 백업 복원 시 연결되지 않은 외장 드라이브 등 "
    "존재하지 않는 위치는 파일 없음으로 바뀝니다. 해당 드라이브를 연결하거나 "
    "새 영상 폴더를 감시 폴더로 추가하고 다시 검사하세요. 내용 지문이 같은 영상은 "
    "기존 태그·자막·하이라이트·시청 기록에 다시 연결됩니다."
)


class BackupError(ValueError):
    """검사에서 거부한 백업. 현재 라이브러리는 바꾸지 않는다."""

    def __init__(self, message, *, kind="invalid_backup"):
        self.kind = kind
        super().__init__(message)


class BackupBusyError(TimeoutError):
    """작업자에서 화면으로 전달할 수 있는 제한된 재시도 결과."""

    def __init__(self, restart_count, reason):
        self.restart_count, self.reason = restart_count, reason
        super().__init__("다른 작업의 DB 쓰기로 백업이 지연되었습니다. "
                         "재생과 자막 처리를 멈추고 다시 시도하세요.")


class BackupStorageError(OSError):
    """공간/파일 사용 문제. 예약을 거부하지 않고 다음 시작에서 재시도한다."""

    def __init__(self, code, message, kind):
        self.kind = kind
        super().__init__(code, message)


def _storage_error(error):
    if isinstance(error, BackupStorageError):
        return error
    if getattr(error, "errno", None) == errno.ENOSPC or getattr(error, "winerror", None) == 112:
        return BackupStorageError(errno.ENOSPC, "백업 공간이 부족합니다. 저장 공간을 확보한 뒤 다시 시도하세요.", "disk_full")
    if getattr(error, "winerror", None) in (32, 33) or getattr(error, "errno", None) == errno.EBUSY:
        return BackupStorageError(errno.EACCES, "백업 복원 파일 또는 DB가 사용 중이거나 접근할 수 없습니다. "
                                  "파일을 사용하는 프로그램을 닫고 접근 권한을 확인하세요.", "file_in_use")
    if isinstance(error, PermissionError) or getattr(error, "errno", None) in (errno.EACCES, errno.EPERM):
        return BackupStorageError(errno.EACCES, "백업 파일 또는 폴더에 접근할 권한이 없습니다. "
                                  "읽기 전용 설정과 접근 권한을 확인하세요.", "file_in_use")
    return BackupStorageError(getattr(error, "errno", None),
                              "백업 저장 장치에 접근할 수 없습니다. 연결과 쓰기 권한을 확인하세요.", "storage_error")


def backup_error_message(error):
    """백업 화면에서 내부 임시 경로와 OS 오류 접두사를 노출하지 않는다."""
    if isinstance(error, BackupBusyError):
        return str(error)
    if isinstance(error, OSError):
        return _storage_error(error).strerror
    return str(error)


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
    restart_count: int = 0


@dataclass(frozen=True)
class BackupRestoreResult:
    metadata: BackupMetadata | None
    restart_required: bool
    guidance: str = BACKUP_RESTORE_GUIDANCE
    safety_backup: Path | None = None
    status: str = "scheduled"
    error_kind: str | None = None
    error_message: str | None = None
    rejected_path: Path | None = None
    restart_count: int = 0


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
    started = previous = time.perf_counter()
    max_step = 0.0
    previous_remaining = None
    restarts = 0

    def progress(status, remaining, total):
        nonlocal previous, max_step, previous_remaining, restarts
        now = time.perf_counter()
        if status in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE):
            max_step = max(max_step, now - previous)
            if previous_remaining is not None and remaining > previous_remaining:
                restarts += 1
            previous_remaining = remaining
        if restarts >= MAX_BACKUP_RESTARTS:
            # 453 MiB에서 pages=-1 전환은 UI 시청 저장을 3초 넘게 막았다.
            raise BackupBusyError(restarts, "source_changed")
        if now - started > 30:
            raise BackupBusyError(restarts, "deadline_exceeded")
        # SQLite가 progress 전에 원본의 읽기 잠금을 해제한다. Windows에서
        # 매 단계 sleep을 넣으면 타이머 해상도 때문에 복사가 길어져,
        # 주기적 시청 저장마다 스냅샷이 처음부터 반복될 수 있다.
        previous = time.perf_counter()

    with closing(_readonly(database)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target, pages=128, progress=progress, sleep=0.01)
        target.execute("PRAGMA journal_mode=DELETE")
    return time.perf_counter() - started, max_step, restarts


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
                  active_viewings=(), reason="manual") -> BackupResult:
    """독립 연결의 작은 backup_step으로 복사한다. UI에서는 작업자에서 호출한다."""
    database, destination = Path(database).resolve(), Path(destination).resolve()
    if destination.suffix.lower() != ".zip":
        raise BackupError("백업 파일의 확장자는 .zip이어야 합니다.")
    if destination == database or destination == pending_backup_restore_path(database):
        raise BackupError("라이브러리 또는 백업 복원 요청을 백업 대상으로 쓸 수 없습니다.")
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        snapshot = stage / DATABASE_NAME
        elapsed, max_step, restarts = _snapshot(database, snapshot)
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
                            **asdict(metadata), files=files, reason=reason)
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        _sync(archive)
        os.replace(archive, destination)
    return BackupResult(destination, metadata, elapsed, max_step, restarts)


def _valid_member(name):
    return name == DATABASE_NAME or bool(re.fullmatch(r"thumbnails/[A-Za-z0-9_-]+\.jpg", name))


def _extract_checked(archive, stage):
    from .library import LIBRARY_DB_VERSION

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            names = [member.filename for member in members]
            if len(names) != len({name.casefold() for name in names}) or "manifest.json" not in names:
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
            # 파일을 쓰기 전에 경로와 선언된 크기를 모두 확인한다.
            for name, digest in files.items():
                if not _valid_member(name) or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                    raise BackupError("백업 파일 경로나 해시가 올바르지 않습니다.")
                if name.startswith("thumbnails/") and bundle.getinfo(name).file_size > MAX_THUMBNAIL_BYTES:
                    raise BackupError("썸네일 파일이 허용 크기 8 MiB를 넘습니다.")
            if sum(member.file_size for member in members) > shutil.disk_usage(stage).free:
                raise BackupStorageError(errno.ENOSPC,
                                         "백업을 검사할 임시 저장 공간이 부족합니다. 공간을 확보한 뒤 다시 시도하세요.",
                                         "disk_full")
            for name, digest in files.items():
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


def pending_backup_restore_path(database: Path) -> Path:
    database = Path(database).resolve()
    return database.with_name(database.name + ".restore-pending.zip")


def request_backup_restore(database: Path, archive: Path) -> BackupRestoreResult:
    """원본 ZIP이 이동되어도 유지되는 검증된 사본 하나를 원자적으로 예약한다."""
    database = Path(database).resolve()
    with tempfile.TemporaryDirectory(prefix=".restore-request-", dir=database.parent) as temporary:
        candidate = Path(temporary) / "pending.zip"
        shutil.copyfile(archive, candidate)
        metadata = inspect_backup(candidate)
        _sync(candidate)
        os.replace(candidate, pending_backup_restore_path(database))
    return BackupRestoreResult(metadata, restart_required=True)


def cancel_backup_restore(database: Path) -> None:
    pending_backup_restore_path(database).unlink(missing_ok=True)


def automatic_backups(database: Path) -> tuple[Path, ...]:
    directory = Path(database).resolve().parent / "backups"
    paths = (path for path in directory.glob("auto-*.zip")
             if re.fullmatch(r"auto-\d{8}T\d{12}Z-[0-9a-f]{32}\.zip", path.name)
             and path.is_file() and not path.is_symlink())
    return tuple(sorted(paths, key=lambda path: path.name, reverse=True))


def create_automatic_backup(database: Path, *, include_thumbnails=False, reason="before_restore") -> BackupResult:
    directory = Path(database).resolve().parent / "backups"
    try:
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result = create_backup(database, directory / f"auto-{stamp}-{uuid4().hex}.zip",
                               include_thumbnails=include_thumbnails, reason=reason)
    except BackupBusyError:
        raise
    except OSError as error:
        raise _storage_error(error) from error
    except sqlite3.OperationalError as error:
        if "full" in str(error).lower():
            raise _storage_error(OSError(errno.ENOSPC, str(error))) from error
        raise
    for path in automatic_backups(database)[AUTO_BACKUP_KEEP:]:
        try:
            path.unlink()
        except OSError:
            pass  # 새 백업은 완성됐다. 잠긴 오래된 ZIP은 다음 생성 때 다시 정리한다.
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
    return create_automatic_backup(Path(filename), reason="before_migration") if filename else None


def _check_replace_available(database):
    """Windows 열린 파일을 백업 생성 전에 검사한다. 최종 replace도 다시 보호한다."""
    if os.name != "nt":
        return  # POSIX에서는 열린 파일도 rename 가능하다. SQLite 잠금은 아래에서 확인한다.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    for path in (database, *(Path(str(database) + suffix) for suffix in ("-wal", "-journal", "-shm"))):
        if not path.exists():
            continue
        if path.stat().st_file_attributes & 0x1:  # FILE_ATTRIBUTE_READONLY
            raise BackupStorageError(errno.EACCES, "읽기 전용 파일의 속성을 해제한 뒤 다시 시도하세요.", "file_in_use")
        # DELETE | GENERIC_READ, 공유 없음, OPEN_EXISTING. 내용을 읽거나 바꾸지 않는다.
        handle = create(str(path), 0x00010000 | 0x80000000, 0, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        close(handle)


def _preserve_damaged_database(database):
    """손상 사본은 자동 ZIP 5개 정리에서 제외하고 사용자가 정리할 때까지 보존한다."""
    directory = database.parent / "backups"
    directory.mkdir(exist_ok=True)
    suffixes = ("", "-wal", "-journal")
    sources = {suffix: Path(str(database) + suffix) for suffix in suffixes}
    fingerprints = {suffix: (source.stat().st_size, _sha256(source))
                    for suffix, source in sources.items() if source.exists()}
    # 늦은 교체 실패 뒤에는 완성 사본을 재사용한다. 동반 파일도 모두 같아야 한다.
    for candidate in directory.glob("damaged-*.sqlite3"):
        matches = True
        for suffix in suffixes:
            saved = Path(str(candidate) + suffix)
            if saved.is_symlink() or saved.exists() != (suffix in fingerprints):
                matches = False
                break
            if suffix in fingerprints and (saved.stat().st_size, _sha256(saved)) != fingerprints[suffix]:
                matches = False
                break
        if matches:
            return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"damaged-{stamp}-{uuid4().hex}.sqlite3"
    try:
        for suffix in fingerprints:
            copy = Path(str(target) + suffix)
            shutil.copyfile(sources[suffix], copy)
            _sync(copy)
    except BaseException:
        for suffix in suffixes:
            try:
                Path(str(target) + suffix).unlink(missing_ok=True)
            except OSError:
                pass  # 다른 동반 파일도 정리하고 원래 복사 오류를 유지한다.
        raise
    return target


def _safety_backup(database):
    if not database.exists():
        return None
    _check_replace_available(database)
    try:
        # 깨진 헤더와 저널이 함께 있으면 readonly SQLite가 손상 대신
        # 저널 복구를 위한 쓰기 권한 오류를 먼저 낼 수 있다.
        with database.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise BackupError("현재 DB 헤더가 손상되었습니다.")
        _database_metadata(database)
        with closing(sqlite3.connect(database, timeout=1)) as db:
            if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise BackupStorageError(errno.EBUSY, "사용 중인 DB 연결을 닫은 뒤 백업 복원을 다시 시도하세요.",
                                         "file_in_use")
            db.execute("PRAGMA journal_mode=DELETE")
        return create_automatic_backup(database, include_thumbnails=True).path
    except (BackupError, sqlite3.DatabaseError) as error:
        # 현재 DB의 손상은 검증을 마친 예약 ZIP의 결함이 아니다.
        if isinstance(error, sqlite3.OperationalError):
            message = str(error).lower()
            if any(word in message for word in ("locked", "busy", "full", "readonly", "disk i/o", "unable to open")):
                code = errno.ENOSPC if "full" in message else errno.EBUSY
                raise _storage_error(OSError(code, str(error))) from error
        return _preserve_damaged_database(database)


def _apply_backup_restore(database: Path) -> BackupRestoreResult:
    """SingleInstance 잠금 확보 뒤, AppCore/작업자/DB 연결을 만들기 전에만 호출한다.

    썸네일은 기존 파일을 덮어쓰지 않는다. 준비와 이전을 마친 DB의 replace가
    유일한 커밋 지점이며, 그 뒤의 청소 실패는 백업 복원 실패로 취급하지 않는다.
    """
    pending = pending_backup_restore_path(database)
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
                try:
                    migrate_library(db, before_upgrade=lambda db, target: None)
                except OSError:
                    raise
                except Exception as error:
                    if isinstance(error, sqlite3.OperationalError) and "full" in str(error).lower():
                        raise _storage_error(OSError(errno.ENOSPC, str(error))) from error
                    raise BackupError("백업 DB 이전에 실패했습니다. 앱을 업데이트하거나 다른 백업을 선택하세요.",
                                      kind="migration_failed") from error
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
            safety = _safety_backup(database)
            # 손상 DB의 WAL/저널이 새 DB에 재생되지 않도록 격리한다.
            # 교체가 실패하면 같은 위치로 돌려 원본과 동반 파일을 함께 보존한다.
            moved_sidecars = []
            os.replace(pending, consumed)
            try:
                for suffix in ("-wal", "-journal", "-shm"):
                    source = Path(str(database) + suffix)
                    if source.exists():
                        saved = stage / ("original" + suffix)
                        os.replace(source, saved)
                        moved_sidecars.append((saved, source))
                os.replace(snapshot, database)
            except BaseException:
                for saved, source in reversed(moved_sidecars):
                    os.replace(saved, source)
                os.replace(consumed, pending)
                raise
            committed = True
            result = BackupRestoreResult(metadata, restart_required=False, safety_backup=safety, status="applied")
    finally:
        if not committed:
            for path in added_thumbnails:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            # 이미 교체된 DB가 다음 시작 때 다시 과거로 덮이지 않도록 요청은
            # 커밋 전에 소비했다. 비정상 종료의 .applying도 재적용하지 않는다.
            try:
                consumed.unlink(missing_ok=True)
            except OSError:
                pass
    return result


def _cleanup_stale_restore_files(database):
    """해당 폴더 잠금 아래 오래된 내부 임시 파일만 최선 노력으로 청소한다."""
    directory = database.parent.resolve()
    pending = pending_backup_restore_path(database)
    candidates = [*directory.glob(".restore-*"), pending.with_name(pending.name + ".applying")]
    for path in candidates:
        try:
            # 정션/심볼릭 링크로 데이터 폴더 밖을 청소하지 않는다.
            if path.is_symlink() or path.resolve() != path.absolute() or path.resolve().parent != directory:
                continue
            if time.time() - path.stat().st_mtime < STALE_RESTORE_SECONDS:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            pass


def _deferred_restore_result(database, kind, message, *, restart_count=0):
    action = ("디스크 공간을 확보한 뒤 다시 시작하면 예약된 백업 복원이 적용됩니다."
              if kind == "disk_full" else
              "오류 원인을 해결한 뒤 다시 시작하면 예약된 백업 복원을 다시 시도합니다.")
    return BackupRestoreResult(None, False, status="deferred", error_kind=kind,
                               error_message=message, restart_count=restart_count,
                               guidance=action + "\n예약 파일: " + str(pending_backup_restore_path(database)))


def apply_pending_backup_restore(database: Path, *, instance) -> BackupRestoreResult | None:
    """시작 결과를 반환한다. 복원 실패는 현재 라이브러리의 정상 시작을 막지 않는다."""
    database = Path(database).resolve()
    if not instance.lock.isLocked() or instance.lock_path.parent.resolve() != database.parent:
        raise RuntimeError("백업 복원에는 이 데이터 폴더의 단일 인스턴스 잠금이 필요합니다.")
    _cleanup_stale_restore_files(database)
    pending = pending_backup_restore_path(database)
    if not pending.exists():
        return None
    try:
        return _apply_backup_restore(database)
    except BackupError as error:
        rejected = pending.with_name(pending.name + f".{uuid4().hex}.rejected")
        try:
            os.replace(pending, rejected)
        except OSError as quarantine_error:
            failure = _storage_error(quarantine_error)
            return _deferred_restore_result(database, failure.kind, failure.strerror)
        return BackupRestoreResult(None, False, status="rejected", error_kind=error.kind,
                                   error_message=str(error), rejected_path=rejected)
    except BackupBusyError as error:
        return _deferred_restore_result(database, error.reason, str(error), restart_count=error.restart_count)
    except (OSError, sqlite3.DatabaseError) as error:
        if isinstance(error, sqlite3.DatabaseError):
            code = errno.ENOSPC if "full" in str(error).lower() else errno.EBUSY
            error = OSError(code, str(error))
        failure = _storage_error(error)
        return _deferred_restore_result(database, failure.kind, failure.strerror)
    except Exception:
        # 예상하지 못한 준비 오류도 예약을 보존하고 현재 DB로 시작하게 한다.
        return _deferred_restore_result(database, "restore_failed",
                                        "백업 복원을 완료하지 못했습니다. 예약을 취소하거나 다른 백업으로 다시 시도하세요.")
