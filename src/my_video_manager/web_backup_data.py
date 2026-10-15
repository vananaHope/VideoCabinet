"""설정 백업 구역의 생성 계약."""
from typing import TypedDict


class BackupMetadataData(TypedDict):
    app_version: str
    db_version: int
    created_at: str
    video_count: int
    includes_thumbnails: bool


class AutomaticBackupData(TypedDict):
    path: str
    created_at: str
    size: int
    reason: str
    error: str


class BackupStartupData(TypedDict):
    status: str
    error: str
    guidance: str
    safety_backup: str
    rejected_path: str


class BackupData(TypedDict):
    busy: bool
    operation: str
    message: str
    failure: str
    preview: BackupMetadataData | None
    previewPath: str
    pending: bool
    pendingDeferred: bool
    pendingPath: str
    startup: BackupStartupData | None
    automatic: list[AutomaticBackupData]
    folder: str
    dbVersion: int
    keep: int
    guidance: str
