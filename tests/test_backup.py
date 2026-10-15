from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
import zipfile

import pytest
from PySide6.QtCore import QLockFile

from my_video_manager.backup import (
    AUTO_BACKUP_KEEP, BackupError, BackupBusyError, BackupStorageError, MAX_BACKUP_RESTARTS,
    apply_pending_backup_restore, backup_before_migration,
    create_automatic_backup, create_backup, inspect_backup, request_backup_restore,
)
from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.library import migrate_library
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine


NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Transcriber:
    def transcribe(self, path, language, **kwargs):
        return TranscriberResult("en", (TranscriptSegment(0, 3, "hello"),))


class Translator:
    def translate(self, lines, language, **kwargs):
        return tuple(TranslatedLine(line.id, "안녕하세요") for line in lines)


def open_core(database):
    return AppCore(database=database, media=Media(), clock=lambda: NOW,
                   transcriber=Transcriber(), translator=Translator())


@contextmanager
def ownership(database):
    """시작 경로와 동일한 실제 QLockFile 소유권, 창/IPC는 필요 없다."""
    lock_path = database.parent / "instance.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    try:
        yield SimpleNamespace(lock=lock, lock_path=lock_path)
    finally:
        lock.unlock()


def apply(database):
    with ownership(database) as instance:
        return apply_pending_backup_restore(database, instance=instance)


@pytest.fixture
def core(tmp_path):
    core = open_core(tmp_path / "data" / "library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    for number in range(3):
        (folder / f"video-{number}.mkv").write_bytes(f"video-{number}".encode())
    core.add_watched_folder(folder)
    core.scan()
    return core


def populate(core):
    first, second, third = core.videos()
    core.rename_video(first.id, "보존할 제목")
    core.update_series(core.series()[0].id, name="보존할 시리즈", video_ids=(second.id, first.id))
    core.add_video_tag(first.id, "공부")
    core.switch_to(first.id, start=0)
    core.playback.report(20)
    core.execute_highlight_command(core.command_for_key("Insert"))
    highlight, = core.highlights(first.id)
    core.update_highlight(highlight.id, start=20, end=25, note="보존할 메모")
    core.add_highlight_tag(highlight.id, "장면")
    core.playback.end()
    core.start_reel()
    core.playback.report(25)
    core.advance_reel_if_due()
    core.playback.end()
    core.request_subtitles(first.id)
    core.process_next_subtitle()
    core.process_next_translation()
    line, = core.transcript(first.id).lines
    core.edit_transcript_line(first.id, line.id, "reviewed hello")
    core.process_next_translation()
    core.edit_translation_line(first.id, line.id, "검수 번역")
    core.request_subtitles(second.id)
    core.set_auto_subtitle_rule(folder=first.locations[0].path.parent, spoken_language="en")
    core.set_minimum_duration(7)
    keys = {row.command: row.keys for row in core.key_bindings()}
    keys[Command(CommandType.TOGGLE_PAUSE)] = ("Space",)
    core.save_key_bindings(keys)
    core.settings.set("backup.test", {"한글": [1, True]})
    core.dismiss_video(second.id)
    core.exclude_video(third.id)
    return first.id


def public_records(core):
    videos = core.videos() + core.excluded_videos()
    return dict(
        videos=videos, folders=core.watched_folders(), series=core.series(), tags=core.tags(),
        viewings={v.id: core.viewings(v.id) for v in videos},
        highlights=core.all_highlights(), video_tags=core.video_tags_map(),
        highlight_tags={h.id: core.highlight_tags(h.id) for h in core.all_highlights()},
        transcript={v.id: core.transcript(v.id) for v in videos},
        translation={v.id: core.translation(v.id) for v in videos},
        review={v.id: core.review_lines(v.id) for v in videos},
        subtitles=core.subtitle_queue(), translations=core.translation_queue(),
        queue=tuple(item for item in core.subtitle_queue_items() if item.state != "completed"),
        rules=core.auto_subtitle_rules(),
        dismissed=core.dismissed_videos(), keys=core.key_bindings(),
        minimum_duration=core.minimum_duration, setting=core.settings.get("backup.test"),
        revisits={h.id: core.last_highlight_revisited_at(h.id) for h in core.all_highlights()},
    )


@pytest.mark.parametrize("thumbnails", [False, True])
@pytest.mark.parametrize("playing", [False, True])
def test_round_trip_all_public_user_data_and_unsaved_viewing(core, tmp_path, thumbnails, playing):
    video_id = populate(core)
    if playing:
        core.switch_to(video_id, start=30)
        core.playback.report(45)  # 저장 주기가 지나지 않은 메모리 진행분
    expected = public_records(core)
    if playing:
        expected["viewings"][video_id] = tuple(
            replace(v, ended_at=v.updated_at) if v.ended_at is None else v
            for v in expected["viewings"][video_id])
    archive = tmp_path / "backup.zip"
    result = core.create_backup(archive, include_thumbnails=thumbnails)
    assert result.metadata.video_count == 3
    assert result.metadata.db_version == 2
    assert result.metadata.includes_thumbnails == thumbnails
    assert result.snapshot_seconds >= result.max_step_seconds >= 0
    assert core.inspect_backup(archive) == result.metadata
    if playing:
        assert core.playback.session is not None
        core.playback.report(60)
        core.playback.end()
    core.rename_video(video_id, "백업 뒤 바뀐 제목")
    request = core.request_backup_restore(archive)
    assert request.restart_required
    assert "내용 지문" in request.guidance
    assert core.video(video_id).title == "백업 뒤 바뀐 제목"
    assert core.pending_backup_restore() == result.metadata
    archive.unlink()  # 예약은 원본 파일에 의존하지 않는다.
    restored = apply(core.database)
    assert not restored.restart_required
    assert restored.safety_backup in core.automatic_backups()
    assert core.pending_backup_restore() is None
    assert apply(core.database) is None
    reopened = open_core(core.database)
    assert public_records(reopened) == expected


def test_bundle_contains_only_requested_data_and_matching_hashes(core, tmp_path):
    for directory in ("models", "translation-temp", "playback-subtitles"):
        (core.database.parent / directory).mkdir()
        (core.database.parent / directory / "private").write_bytes(b"excluded")
    (core.database.parent / "instance.lock").write_bytes(b"not a real lock")
    for include in (False, True):
        archive = tmp_path / f"backup-{include}.zip"
        core.create_backup(archive, include_thumbnails=include)
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            assert set(bundle.namelist()) == {*manifest["files"], "manifest.json"}
            assert len(manifest["files"]) == (4 if include else 1)
            for member, digest in manifest["files"].items():
                assert hashlib.sha256(bundle.read(member)).hexdigest() == digest
            assert manifest["application"] == "my-video-manager"
            assert manifest["app_version"]


def rewrite_archive(archive, *, change_manifest=None, change_files=None):
    with zipfile.ZipFile(archive) as bundle:
        files = {name: bundle.read(name) for name in bundle.namelist()}
    manifest = json.loads(files["manifest.json"])
    if change_manifest:
        change_manifest(manifest)
    if change_files:
        change_files(files, manifest)
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)


@pytest.mark.parametrize("damage", [
    "not_zip", "foreign_app", "future_version", "bad_hash", "missing_db", "bad_db",
    "metadata_count", "bad_date", "path_traversal", "extra_file", "duplicate", "bad_json",
])
def test_rejects_invalid_backup_without_changing_data_or_pending_request(core, tmp_path, damage):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    core.request_backup_restore(archive)
    pending_before = core.pending_backup_restore()
    before = core.database.read_bytes()
    if damage == "not_zip":
        archive.write_bytes(b"broken")
    elif damage == "foreign_app":
        rewrite_archive(archive, change_manifest=lambda m: m.update(application="other"))
    elif damage == "future_version":
        rewrite_archive(archive, change_manifest=lambda m: m.update(db_version=999))
    elif damage == "bad_hash":
        rewrite_archive(archive, change_manifest=lambda m: m["files"].update({"library.sqlite3": "0" * 64}))
    elif damage == "missing_db":
        rewrite_archive(archive, change_files=lambda f, m: f.pop("library.sqlite3"))
    elif damage == "bad_db":
        def bad_db(files, manifest):
            files["library.sqlite3"] = b"not SQLite"
            manifest["files"]["library.sqlite3"] = hashlib.sha256(b"not SQLite").hexdigest()
        rewrite_archive(archive, change_files=bad_db)
    elif damage == "metadata_count":
        rewrite_archive(archive, change_manifest=lambda m: m.update(video_count=999))
    elif damage == "bad_date":
        rewrite_archive(archive, change_manifest=lambda m: m.update(created_at="bad"))
    elif damage == "path_traversal":
        def traversal(files, manifest):
            files["../outside"] = b"bad"
            manifest["files"]["../outside"] = hashlib.sha256(b"bad").hexdigest()
            manifest["includes_thumbnails"] = True
        rewrite_archive(archive, change_files=traversal)
    elif damage == "extra_file":
        rewrite_archive(archive, change_files=lambda f, m: f.update({"models/model": b"bad"}))
    elif damage == "duplicate":
        with pytest.warns(UserWarning), zipfile.ZipFile(archive, "a") as bundle:
            bundle.writestr("library.sqlite3", b"bad")
    else:
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("manifest.json", "[")
    for action in (core.inspect_backup, core.request_backup_restore):
        with pytest.raises(BackupError):
            action(archive)
    assert core.database.read_bytes() == before
    assert core.pending_backup_restore() == pending_before
    assert not (tmp_path / "outside").exists()


def test_revalidates_pending_request_at_startup(core, tmp_path):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    core.request_backup_restore(archive)
    pending, = core.database.parent.glob("*.restore-pending.zip")
    pending.write_bytes(b"corrupted after request")
    before = core.database.read_bytes()
    assert apply(core.database).status == "rejected"
    assert core.database.read_bytes() == before
    assert core.automatic_backups() == ()


def test_cancel_backup_restore_and_require_correct_instance_ownership(core, tmp_path):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    core.request_backup_restore(archive)
    lock = QLockFile(str(core.database.parent / "instance.lock"))
    fake = SimpleNamespace(lock=lock, lock_path=core.database.parent / "instance.lock")
    with pytest.raises(RuntimeError, match="잠금"):
        apply_pending_backup_restore(core.database, instance=fake)
    other = tmp_path / "other"
    other.mkdir()
    with ownership(other / "library.sqlite3") as instance, pytest.raises(RuntimeError, match="잠금"):
        apply_pending_backup_restore(core.database, instance=instance)
    core.cancel_backup_restore()
    core.cancel_backup_restore()
    assert core.pending_backup_restore() is None
    assert apply(core.database) is None


@pytest.mark.parametrize("failure", ["replace", "disk_full_backup", "disk_full_prepare"])
def test_restore_failure_leaves_original_database_and_thumbnails(core, tmp_path, monkeypatch, failure):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive, include_thumbnails=True)
    video = core.videos()[0]
    core.rename_video(video.id, "원래 상태")
    video.thumbnail.write_bytes(b"current thumbnail")
    core.request_backup_restore(archive)
    before = public_records(core)
    thumbnails_before = {p.name: p.read_bytes() for p in video.thumbnail.parent.iterdir()}
    replace_file, copy_file = os.replace, __import__("shutil").copyfileobj

    def fail_replace(source, target):
        if ((failure == "replace" and Path(target) == core.database)
                or (failure == "disk_full_backup" and Path(target).parent.name == "backups")):
            raise OSError(errno.ENOSPC if failure == "disk_full_backup" else errno.EACCES, "injected")
        return replace_file(source, target)

    def fail_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "injected full disk")

    monkeypatch.setattr(os, "replace", fail_replace)
    if failure == "disk_full_prepare":
        monkeypatch.setattr("shutil.copyfileobj", fail_copy)
    result = apply(core.database)
    assert result.status == "deferred"
    assert result.error_kind in ("file_in_use", "disk_full")
    monkeypatch.setattr("shutil.copyfileobj", copy_file)
    assert public_records(core) == before
    assert {p.name: p.read_bytes() for p in video.thumbnail.parent.iterdir()} == thumbnails_before
    assert core.pending_backup_restore() is not None
    if failure == "replace":
        assert len(core.automatic_backups()) == 1
    monkeypatch.setattr(os, "replace", replace_file)
    apply(core.database)
    reopened = open_core(core.database)
    assert reopened.video(video.id).title == video.title
    assert reopened.video(video.id).thumbnail.read_bytes() == b"thumbnail"


def test_backup_failure_preserves_existing_destination(core, tmp_path, monkeypatch):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    original = archive.read_bytes()

    def full_disk(*args, **kwargs):
        raise OSError(errno.ENOSPC, "injected full disk")

    monkeypatch.setattr(zipfile.ZipFile, "write", full_disk)
    with pytest.raises(OSError):
        core.create_backup(archive)
    assert archive.read_bytes() == original
    assert not list(tmp_path.glob(".backup-*"))


def test_missing_locations_reconnect_by_fingerprint_on_other_pc(core, tmp_path):
    video_id = populate(core)
    video = core.video(video_id)
    archive = tmp_path / "backup.zip"
    core.create_backup(archive, include_thumbnails=True)
    new_folder = tmp_path / "new-pc-videos"
    video.locations[0].path.parent.rename(new_folder)
    target = open_core(tmp_path / "new-pc-data" / "library.sqlite3")
    target.request_backup_restore(archive)
    result = apply(target.database)
    target = open_core(target.database)
    assert all(v.missing for v in target.videos() + target.excluded_videos())
    assert target.video(video_id).thumbnail.read_bytes() == b"thumbnail"
    target.add_watched_folder(new_folder)
    assert target.scan().added == 0
    assert target.video(video_id).fingerprint == video.fingerprint
    assert not target.video(video_id).missing
    assert target.video_tags(video_id) == core.video_tags(video_id)
    assert target.highlights(video_id) == core.highlights(video_id)
    assert target.viewings(video_id) == core.viewings(video_id)
    assert target.transcript(video_id) == core.transcript(video_id)
    assert "감시 폴더" in result.guidance and "다시 검사" in result.guidance


@pytest.mark.parametrize("old_version", [0, 1])
def test_old_backup_is_migrated_before_replacement(core, tmp_path, old_version):
    from test_library import legacy_database
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    database, path = legacy_database(old_dir, old_version)
    archive = tmp_path / "legacy.zip"
    create_backup(database, archive)
    core.request_backup_restore(archive)
    apply(core.database)
    reopened = open_core(core.database)
    assert reopened.video(42).title == "옛 제목"
    assert reopened.highlights(42)[0].note.text == "옛 메모"
    assert reopened.video_tags(42)[0].name == "옛 태그"
    assert reopened.transcript(42).lines[0].text == "old words"
    assert reopened.viewing_status(42).finished
    assert reopened.inspect_backup(reopened.create_backup(tmp_path / "new.zip").path).db_version == 2


def test_automatic_retention_keeps_latest_five_and_never_removes_manual_zip(core):
    directory = core.database.parent / "backups"
    directory.mkdir()
    manual = core.create_backup(directory / "auto-manual.zip").path
    results = [create_automatic_backup(core.database) for _ in range(AUTO_BACKUP_KEEP + 2)]
    assert core.automatic_backups() == tuple(result.path for result in reversed(results[-AUTO_BACKUP_KEEP:]))
    assert manual.exists()
    assert all(core.inspect_backup(path).db_version == 2 for path in core.automatic_backups())


def test_fake_next_migration_backs_up_before_ddl_and_survives_rollback(core):
    # #64의 실제 v3 DDL 대신 실패하는 가짜 이전으로 공개 연결 지점을 검증한다.
    with closing(sqlite3.connect(core.database)) as db:
        saved = backup_before_migration(db, 3)
        assert saved.metadata.db_version == 2
        with pytest.raises(RuntimeError), db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE videos ADD COLUMN fake_migration TEXT")
            db.execute("PRAGMA user_version=3")
            raise RuntimeError("fake migration failure")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert core.inspect_backup(saved.path).db_version == 2
    assert open_core(core.database).videos() == core.videos()
    with closing(sqlite3.connect(core.database)) as db:
        assert backup_before_migration(db, 2) is None


def test_real_migration_calls_backup_before_transaction_and_aborts_if_backup_fails(tmp_path, monkeypatch):
    from test_library import legacy_database
    database, _ = legacy_database(tmp_path, 1)
    before = database.read_bytes()

    def fail_backup(*args, **kwargs):
        raise OSError(errno.ENOSPC, "injected full disk")

    monkeypatch.setattr("my_video_manager.backup.create_automatic_backup", fail_backup)
    with closing(sqlite3.connect(database)) as db, pytest.raises(OSError):
        migrate_library(db)
    assert database.read_bytes() == before


def test_wal_snapshot_and_restore_include_committed_wal(core, tmp_path):
    archive = tmp_path / "wal.zip"
    with closing(sqlite3.connect(core.database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("SELECT count(*) FROM videos").fetchone()
        core.rename_video(core.videos()[0].id, "WAL에 저장한 제목")
        assert Path(str(core.database) + "-wal").exists()
        core.create_backup(archive)
    core.rename_video(core.videos()[0].id, "백업 뒤 제목")
    core.request_backup_restore(archive)
    apply(core.database)
    assert "WAL에 저장한 제목" in {v.title for v in open_core(core.database).videos()}


def test_backup_allows_viewing_and_subtitle_writes_while_copying(core, tmp_path):
    core.settings.set("large-fixture", "x" * (4 * 1024 * 1024))
    video_id = core.videos()[0].id
    core.switch_to(video_id, start=0)
    core.request_subtitles(video_id)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(core.create_backup, tmp_path / "concurrent.zip")
        core.process_next_subtitle()
        for position in range(1, 11):
            core.playback.report(position)
            core.settings.set("concurrent-write", position)
            time.sleep(0.002)
        try:
            result = future.result(timeout=10)
        except BackupBusyError as error:
            # 쓰기 빈도가 복사보다 높으면 이제 명확히 중단한다. 쓰기가
            # 멎은 뒤 재시도는 성공하며, 시청/자막 작업은 계속 보존된다.
            assert error.reason == "source_changed"
            assert error.restart_count == MAX_BACKUP_RESTARTS
            result = core.create_backup(tmp_path / "concurrent.zip")
    assert core.transcript(video_id).lines[0].text == "hello"
    assert core.viewings(video_id)[-1].last_position == 10
    assert core.settings.get("concurrent-write") == 10
    assert core.inspect_backup(result.path).video_count == 3


def test_failed_staged_migration_does_not_touch_current_library(core, tmp_path, monkeypatch):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    core.request_backup_restore(archive)
    before = core.database.read_bytes()

    def fail_migration(db, **kwargs):
        raise RuntimeError("migration failed")

    monkeypatch.setattr("my_video_manager.library.migrate_library", fail_migration)
    result = apply(core.database)
    assert result.status == "rejected"
    assert "이전" in result.error_message
    assert core.database.read_bytes() == before
    assert core.pending_backup_restore() is None


def test_post_commit_cleanup_failure_never_reapplies_restore(core, tmp_path, monkeypatch):
    archive = tmp_path / "backup.zip"
    core.create_backup(archive)
    core.request_backup_restore(archive)
    original_unlink = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.name.endswith(".applying"):
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    assert apply(core.database).restart_required is False
    reopened = open_core(core.database)
    video_id = reopened.videos()[0].id
    reopened.rename_video(video_id, "되돌리기 이후 새 기록")
    assert apply(core.database) is None
    assert open_core(core.database).video(video_id).title == "되돌리기 이후 새 기록"


def test_review_corrupt_request_does_not_block_startup(core, tmp_path):
    core.create_backup(tmp_path / "backup.zip")
    core.request_backup_restore(tmp_path / "backup.zip")
    pending, = core.database.parent.glob("*.restore-pending.zip")
    pending.write_bytes(b"corrupt")
    before = public_records(core)
    result = apply(core.database)
    assert result.status == "rejected"
    assert not pending.exists()
    assert list(core.database.parent.glob("*.rejected"))
    assert public_records(open_core(core.database)) == before
    assert apply(core.database) is None


def test_review_locked_old_backup_does_not_block_new_backup(core, monkeypatch):
    for _ in range(AUTO_BACKUP_KEEP):
        create_automatic_backup(core.database)
    oldest = core.automatic_backups()[-1]
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == oldest:
            raise PermissionError("archive in use")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    latest = create_automatic_backup(core.database)
    assert latest.path.is_file()
    assert oldest.exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    create_automatic_backup(core.database)
    assert not oldest.exists()
    assert len(core.automatic_backups()) == AUTO_BACKUP_KEEP


@pytest.mark.parametrize("failure", ["corrupt", "migration", "disk_full", "damaged_and_full"])
def test_main_opens_current_library_after_failed_backup_restore(core, tmp_path, monkeypatch, failure):
    """실제 main → 복원 → AppCore 시작 순서. 화면/엔진 대신 관찰용 경계만 주입한다."""
    import sys
    from PySide6 import QtWidgets
    from my_video_manager import __main__, adapters, single_instance, theme, transcription, translation_cli, ui

    archive = core.create_backup(tmp_path / "backup.zip").path
    core.request_backup_restore(archive)
    video_id = core.videos()[0].id
    core.rename_video(video_id, "지금 라이브러리")
    expected = public_records(core)
    if failure == "corrupt":
        pending, = core.database.parent.glob("*.restore-pending.zip")
        pending.write_bytes(b"bad")
    elif failure == "migration":
        real_migration = migrate_library
        def fail_staging(db, **kwargs):
            if kwargs.get("before_upgrade"):
                raise RuntimeError("invalid migration")
            return real_migration(db, **kwargs)
        monkeypatch.setattr("my_video_manager.library.migrate_library", fail_staging)
    elif failure == "disk_full":
        def full_disk(*args, **kwargs):
            raise OSError(errno.ENOSPC, "disk full")
        monkeypatch.setattr("shutil.copyfileobj", full_disk)
    else:
        # 정상 예약의 추출은 되지만 현재 손상 DB의 안전용 원시 복사는 공간 부족이다.
        import shutil
        real_copy = shutil.copyfile
        def full_raw_copy(source, target, *args, **kwargs):
            if Path(source) == core.database:
                raise OSError(errno.ENOSPC, "disk full")
            return real_copy(source, target, *args, **kwargs)
        monkeypatch.setattr(shutil, "copyfile", full_raw_copy)
        core.database.write_bytes(b"damaged header")

    class Signal:
        def __init__(self):
            self.callbacks = []
        def connect(self, callback):
            self.callbacks.append(callback)

    class Application:
        def __init__(self, *args):
            self.aboutToQuit = Signal()
        def setQuitOnLastWindowClosed(self, value):
            pass
        def exec(self):
            for callback in self.aboutToQuit.callbacks:
                callback()
            return 0

    class Instance:
        def __init__(self, directory, parent):
            self.lock_path = directory / "instance.lock"
            self.lock = QLockFile(str(self.lock_path))
            self.activated = Signal()
        def start(self):
            return self.lock.tryLock(0)
        def close(self):
            self.lock.unlock()

    started = []
    class Window:
        def __init__(self, opened):
            started.append(opened)
            self.tray = SimpleNamespace(open=lambda: None)
        def show(self):
            pass

    monkeypatch.setattr(sys, "argv", ["my-video-manager", "--data-dir", str(core.database.parent)])
    monkeypatch.delenv("MVM_WEB_UI", raising=False)
    monkeypatch.setattr(QtWidgets, "QApplication", Application)
    monkeypatch.setattr(theme, "apply_theme", lambda app: None)
    monkeypatch.setattr(single_instance, "SingleInstance", Instance)
    monkeypatch.setattr(ui, "MainWindow", Window)
    monkeypatch.setattr(adapters, "FFmpegMediaReader", Media)
    monkeypatch.setattr(transcription, "FasterWhisperTranscriber", lambda path: Transcriber())
    monkeypatch.setattr(translation_cli, "SubscriptionCLITranslator", lambda path: Translator())
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args: errors.append(args))
    for attempt in range(2):
        if failure == "damaged_and_full":
            assert __main__.main() == 1
            assert started == []
            assert core.database.read_bytes() == b"damaged header"
            assert core.pending_backup_restore() is not None
            message = errors[-1][2]
            assert "디스크 공간을 확보한 뒤 다시 시작하면 예약된 백업 복원이 적용" in message
            assert str(core.database.with_name(core.database.name + ".restore-pending.zip")) in message
            assert "[Errno" not in message
            continue
        assert __main__.main() == 0
        assert public_records(started[-1]) == expected
        state = started[-1].backup_restore_status()
        if failure == "disk_full":
            assert state.status == "deferred" and state.error_kind == "disk_full"
        elif attempt == 0:
            assert state.status == "rejected"
        else:
            assert state is None
    if failure == "damaged_and_full":
        assert len(errors) == 2
        monkeypatch.setattr(shutil, "copyfile", real_copy)
        assert __main__.main() == 0
        assert started[-1].backup_restore_status().status == "applied"
        assert len(errors) == 2
        return
    assert errors == []
    if failure == "disk_full":
        started[-1].cancel_backup_restore()
        assert started[-1].backup_restore_status() is None
        assert started[-1].pending_backup_restore() is None


@pytest.mark.parametrize("operation", ["restore", "migration"])
def test_retention_failure_does_not_block_restore_or_migration(core, tmp_path, monkeypatch, operation):
    for _ in range(AUTO_BACKUP_KEEP):
        create_automatic_backup(core.database)
    oldest = core.automatic_backups()[-1]
    unlink = Path.unlink
    def locked(path, *args, **kwargs):
        if path == oldest:
            raise PermissionError("old backup open")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    if operation == "restore":
        core.request_backup_restore(core.create_backup(tmp_path / "restore.zip").path)
        assert apply(core.database).status == "applied"
    else:
        from test_library import legacy_database
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        database, _ = legacy_database(legacy, 1)
        # 이전 대상과 같은 데이터 폴더의 보존 목록을 사용한다.
        os.replace(database, core.database)
        reopened = open_core(core.database)
        assert reopened.video(42).title == "옛 제목"
        assert inspect_backup(reopened.automatic_backups()[0]).db_version == 1
    assert oldest.exists()


def test_successful_legacy_migration_has_one_pre_upgrade_backup(tmp_path):
    from test_library import legacy_database
    database, _ = legacy_database(tmp_path, 1)
    core = open_core(database)
    saved, = core.automatic_backups()
    assert core.inspect_backup(saved).db_version == 1
    assert core.video(42).title == "옛 제목"
    assert open_core(database).automatic_backups() == (saved,)


def test_automatic_backup_disk_full_is_actionable_and_still_blocks_migration(tmp_path, monkeypatch):
    from test_library import legacy_database
    database, _ = legacy_database(tmp_path, 1)
    def full_disk(*args, **kwargs):
        raise OSError(errno.ENOSPC, "disk full")
    monkeypatch.setattr(zipfile.ZipFile, "write", full_disk)
    with pytest.raises(BackupStorageError) as caught:
        open_core(database)
    assert caught.value.kind == "disk_full"
    assert "공간" in str(caught.value)
    # AppCore가 settings 테이블을 준비하는 기존 시작 동작 외 이전은 실행되지 않는다.
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT title FROM videos WHERE id=42").fetchone()[0] == "옛 제목"


def test_repeated_source_writes_fail_with_count_and_guidance(core, tmp_path, monkeypatch):
    core.settings.set("large-fixture", "x" * (4 * 1024 * 1024))
    archive = core.create_backup(tmp_path / "backup.zip").path
    original = archive.read_bytes()
    connect = sqlite3.connect
    class UpdatingSource(sqlite3.Connection):
        def backup(self, target, *, progress, **kwargs):
            steps = 0
            def progress_and_write(status, remaining, total):
                nonlocal steps
                progress(status, remaining, total)
                steps += 1
                if status == sqlite3.SQLITE_OK and steps % 2 == 0:
                    core.settings.set("force-restart", steps)
            return super().backup(target, progress=progress_and_write, **kwargs)
    def instrument(database, *args, **kwargs):
        if str(database).startswith(core.database.as_uri()) and kwargs.get("uri"):
            kwargs["factory"] = UpdatingSource
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", instrument)
    with pytest.raises(BackupBusyError) as caught:
        core.create_backup(archive)
    assert caught.value.restart_count == MAX_BACKUP_RESTARTS
    assert caught.value.reason == "source_changed"
    assert "재생" in str(caught.value) and "다시 시도" in str(caught.value)
    assert archive.read_bytes() == original


@pytest.mark.parametrize("invalid", ["case_collision", "thumbnail_too_large", "insufficient_space"])
def test_extract_preflight_rejects_before_writing_members(core, tmp_path, monkeypatch, invalid):
    archive = core.create_backup(tmp_path / "backup.zip").path
    if invalid == "case_collision":
        def add_twins(files, manifest):
            manifest["includes_thumbnails"] = True
            for name in ("thumbnails/x.jpg", "thumbnails/X.jpg"):
                files[name] = name.encode()
                manifest["files"][name] = hashlib.sha256(files[name]).hexdigest()
        rewrite_archive(archive, change_files=add_twins)
    elif invalid == "thumbnail_too_large":
        def oversized(files, manifest):
            manifest["includes_thumbnails"] = True
            files["thumbnails/large.jpg"] = b"x" * (8 * 1024 * 1024 + 1)
            manifest["files"]["thumbnails/large.jpg"] = hashlib.sha256(files["thumbnails/large.jpg"]).hexdigest()
        rewrite_archive(archive, change_files=oversized)
    else:
        monkeypatch.setattr("shutil.disk_usage", lambda path: SimpleNamespace(free=1))
    def must_not_extract(*args, **kwargs):
        pytest.fail("preflight must reject before extracting")
    monkeypatch.setattr("shutil.copyfileobj", must_not_extract)
    with pytest.raises(BackupStorageError if invalid == "insufficient_space" else BackupError):
        core.inspect_backup(archive)


def test_offline_drive_location_is_missing_and_guidance_explains_exception(core, tmp_path):
    video = core.videos()[0]
    archive = core.create_backup(tmp_path / "backup.zip").path
    video.locations[0].path.unlink()
    core.request_backup_restore(archive)
    result = apply(core.database)
    assert open_core(core.database).video(video.id).missing
    assert "외장 드라이브" in result.guidance
    assert "다시 검사" in result.guidance


def test_startup_cleans_only_old_internal_restore_artifacts(core):
    directory = core.database.parent
    stale = directory / ".restore-old"
    stale.mkdir()
    (stale / "partial.sqlite3").write_bytes(b"temporary")
    applying = directory / "library.sqlite3.restore-pending.zip.applying"
    applying.write_bytes(b"consumed request")
    fresh = directory / ".restore-fresh"
    fresh.mkdir()
    rejected = directory / "library.sqlite3.restore-pending.zip.saved.rejected"
    rejected.write_bytes(b"keep rejected backup")
    for path in (stale, applying, rejected):
        os.utime(path, (0, 0))
    assert apply(core.database) is None
    assert not stale.exists() and not applying.exists()
    assert fresh.exists() and rejected.exists()


def test_open_delete_journal_database_defers_restore_with_actionable_error(core, tmp_path):
    archive = core.create_backup(tmp_path / "backup.zip").path
    core.request_backup_restore(archive)
    expected = public_records(core)
    with closing(sqlite3.connect(core.database)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        result = apply(core.database)
        assert result.status == "deferred"
        assert result.error_kind == "file_in_use"
        assert "사용" in result.error_message
        assert not result.error_message.startswith("[Errno")
        assert apply(core.database).status == "deferred"
        assert core.automatic_backups() == ()
        writer.rollback()
    assert public_records(open_core(core.database)) == expected
    assert core.pending_backup_restore() is not None
    assert apply(core.database).status == "applied"


@pytest.mark.parametrize("damage", ["index", "header"])
def test_valid_backup_restores_damaged_current_database(core, tmp_path, damage):
    expected = public_records(core)
    core.request_backup_restore(core.create_backup(tmp_path / "healthy.zip").path)
    with closing(sqlite3.connect(core.database)) as db:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        root = db.execute("SELECT rootpage FROM sqlite_master WHERE name='locations_video_id'").fetchone()[0]
    with core.database.open("r+b") as stream:
        stream.seek((root - 1) * page_size if damage == "index" else 0)
        stream.write(b"broken database!")
    original = core.database.read_bytes()
    sidecars = {}
    if damage == "header":
        # 원시 보존은 SQLite가 열 수 없는 DB의 동반 파일도 빠뜨리지 않는다.
        for suffix in ("-wal", "-journal"):
            path = Path(str(core.database) + suffix)
            sidecars[suffix] = ("damaged" + suffix).encode()
            path.write_bytes(sidecars[suffix])
    result = apply(core.database)
    assert result.status == "applied"
    assert public_records(open_core(core.database)) == expected
    assert result.safety_backup.name.startswith("damaged-")
    assert result.safety_backup.read_bytes() == original
    for suffix, contents in sidecars.items():
        assert Path(str(result.safety_backup) + suffix).read_bytes() == contents
        assert not Path(str(core.database) + suffix).exists()
    assert core.pending_backup_restore() is None
    assert apply(core.database) is None
    for _ in range(AUTO_BACKUP_KEEP + 1):
        create_automatic_backup(core.database)
    assert len(core.automatic_backups()) == AUTO_BACKUP_KEEP
    assert result.safety_backup.read_bytes() == original


@pytest.mark.parametrize("failure", ["raw_copy", "sidecar_move", "database_replace"])
def test_damaged_database_restore_failure_keeps_original_and_pending(core, tmp_path, monkeypatch, failure):
    expected = public_records(core)
    core.request_backup_restore(core.create_backup(tmp_path / "healthy.zip").path)
    core.database.write_bytes(b"damaged original database")
    originals = {core.database: core.database.read_bytes()}
    for suffix in ("-wal", "-journal"):
        path = Path(str(core.database) + suffix)
        originals[path] = ("original" + suffix).encode()
        path.write_bytes(originals[path])
    import shutil
    copyfile, replace_file = shutil.copyfile, os.replace
    def copy(source, target, *args, **kwargs):
        if failure == "raw_copy" and Path(source) == core.database:
            raise OSError(errno.ENOSPC, "disk full")
        return copyfile(source, target, *args, **kwargs)
    def move(source, target):
        if ((failure == "database_replace" and Path(target) == core.database)
                or (failure == "sidecar_move" and Path(source) == Path(str(core.database) + "-journal"))):
            raise PermissionError(errno.EACCES, "in use")
        return replace_file(source, target)
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copyfile", copy)
        patch.setattr(os, "replace", move)
        result = apply(core.database)
    assert result.status == "deferred"
    assert result.error_kind == ("disk_full" if failure == "raw_copy" else "file_in_use")
    assert not result.error_message.startswith("[Errno")
    for path, contents in originals.items():
        assert path.read_bytes() == contents
    assert core.pending_backup_restore() is not None
    assert apply(core.database).status == "applied"
    assert public_records(open_core(core.database)) == expected
