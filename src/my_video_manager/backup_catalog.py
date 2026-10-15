"""백업 화면용 가벼운 조회. 목록 읽기는 압축 해제·해시 검사를 하지 않는다."""
from dataclasses import dataclass
import json
from pathlib import Path
import zipfile

from .backup import AUTO_BACKUP_KEEP, BACKUP_RESTORE_GUIDANCE, automatic_backups, pending_backup_restore_path


@dataclass(frozen=True)
class AutomaticBackupEntry:
    path: str
    created_at: str
    size: int
    reason: str
    error: str = ""


@dataclass(frozen=True)
class BackupInventory:
    automatic: tuple[AutomaticBackupEntry, ...]
    folder: str
    pending_path: str
    pending: bool
    db_version: int
    keep: int = AUTO_BACKUP_KEEP
    guidance: str = BACKUP_RESTORE_GUIDANCE


def backup_inventory(database: Path, *, include_automatic=True) -> BackupInventory:
    from .library import LIBRARY_DB_VERSION
    rows = []
    reasons = {"before_restore": "백업 복원 전", "before_migration": "DB 형식 변경 전", "manual": "직접 만들기"}
    for path in automatic_backups(database) if include_automatic else ():
        size, created, reason, error = 0, "", "백업 복원 또는 DB 형식 변경 전(상세 이유 기록 없음)", ""
        try:
            size = path.stat().st_size
            with zipfile.ZipFile(path) as archive:
                if archive.getinfo("manifest.json").file_size > 1024 * 1024:
                    raise ValueError("백업 메타데이터가 너무 큽니다.")
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    raise ValueError('백업 메타데이터 형식이 올바르지 않습니다.')
                created = str(manifest["created_at"])
                reason = reasons.get(manifest.get("reason"), reason)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            error = "백업 정보를 읽을 수 없습니다. 복원 전에 파일 검사가 필요합니다."
        rows.append(AutomaticBackupEntry(str(path), created, size, reason, error))
    pending = pending_backup_restore_path(database)
    return BackupInventory(tuple(rows), str(Path(database).resolve().parent / "backups"), str(pending), pending.exists(),
                           LIBRARY_DB_VERSION)
