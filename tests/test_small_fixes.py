"""#95: 시작 복원과 준비 진단의 공개 실패 경로."""
import errno
from pathlib import Path
from threading import Thread, Event

import pytest

from my_video_manager.backup import backup_error_message
from my_video_manager.subtitle_preparation_state import safe_detail
from test_backup import open_core, apply


def test_stringified_nested_oserror_home_is_redacted():
    path = str(Path.home() / 'private' / 'file.zip')
    detail = f'wrapped: {PermissionError(errno.EACCES, "denied", path)}'
    result = safe_detail(detail)
    assert str(Path.home()) not in result
    assert str(Path.home()).replace('\\', '\\\\') not in result
    assert '~' in result and 'file.zip' in result


def test_missing_drive_is_not_reported_as_deleted_file(monkeypatch):
    root = Path('Z:/')
    original = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda path: False if path == root else original(path))
    message = backup_error_message(FileNotFoundError(errno.ENOENT, 'missing', 'Z:/backup.zip'))
    assert '드라이브' in message and '연결' in message
    assert '지워졌거나' not in message


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows 파일 공유 잠금')
def test_restore_waits_for_previous_process_database_handle(tmp_path, monkeypatch):
    import my_video_manager.backup as backup
    core = open_core(tmp_path / 'data/library.sqlite3')
    archive = core.create_backup(tmp_path / 'backup.zip').path
    core.request_backup_restore(archive)
    opened = Event()
    release = Event()

    def old_process_handle():
        with core.database.open('rb'):
            opened.set()
            assert release.wait(5)

    check = backup._check_replace_available
    conflicts = []
    def check_then_release(database):
        try:
            return check(database)
        except OSError as error:
            conflicts.append(error.winerror)
            release.set()
            raise
    monkeypatch.setattr(backup, '_check_replace_available', check_then_release)

    thread = Thread(target=old_process_handle)
    thread.start()
    try:
        assert opened.wait(5)
        assert apply(core.database).status == 'applied'
        assert conflicts and conflicts[0] == 32
    finally:
        release.set()
        thread.join(5)


@pytest.mark.parametrize('code,expected_attempts', [(errno.EBUSY, 9), (errno.EACCES, 1)])
def test_restore_retry_is_bounded_and_only_for_sharing_conflicts(tmp_path, monkeypatch, code, expected_attempts):
    import my_video_manager.backup as backup
    core = open_core(tmp_path / 'data/library.sqlite3')
    archive = core.create_backup(tmp_path / 'backup.zip').path
    core.request_backup_restore(archive)
    before = core.database.read_bytes()
    attempts, delays = [], []
    def unavailable(database):
        attempts.append(database)
        raise OSError(code, 'busy')
    monkeypatch.setattr(backup, '_check_replace_available', unavailable)
    monkeypatch.setattr(backup.time, 'sleep', delays.append)
    result = apply(core.database)
    assert result.status == 'deferred' and result.error_kind == 'file_in_use'
    assert len(attempts) == expected_attempts
    assert sum(delays) == (2 if code == errno.EBUSY else 0)
    assert core.database.read_bytes() == before
    assert backup.pending_backup_restore_path(core.database).exists()
    assert core.automatic_backups() == ()
