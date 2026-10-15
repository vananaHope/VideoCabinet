import errno
import logging
from pathlib import Path
import zipfile

import pytest

from my_video_manager.app_logging import configure_app_logging, LOG_MAX_BYTES
from my_video_manager.backup import backup_error_message
from my_video_manager.subtitle_preparation_state import log_failure
from test_backup import open_core, apply


@pytest.fixture
def app_log(tmp_path):
    logger = logging.getLogger('my_video_manager')
    previous_level = logger.level
    handler = configure_app_logging(tmp_path)
    assert handler is not None
    try:
        yield tmp_path / 'logs/app.log', handler
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)


def test_backup_oserror_is_written_with_redacted_exception_chain(app_log):
    path, _ = app_log
    home = str(Path.home())
    try:
        raise PermissionError(errno.EACCES, 'denied', str(Path.home() / 'private.zip'))
    except OSError as error:
        backup_error_message(error)
    logging.getLogger('my_video_manager.backup').error(
        'wrapped: %s Authorization: Bearer very-secret-token token=private-token '
        'https://alice:pass@host/path?query-secret hf_PrivateToken',
        str(PermissionError(errno.EACCES, 'denied', str(Path.home() / 'nested.zip'))))
    content = path.read_text(encoding='utf-8')
    assert 'my_video_manager.backup WARNING' in content and 'PermissionError' in content
    assert 'private.zip' in content and 'nested.zip' in content and '~' in content
    for value in (home, home.replace('\\', '\\\\'), 'very-secret-token', 'private-token',
                  'alice', 'query-secret', 'hf_PrivateToken'):
        assert value not in content


def test_app_and_preparation_logs_keep_separate_paths_and_rotation_budget(app_log, tmp_path):
    path, handler = app_log
    assert configure_app_logging(tmp_path) is not handler
    # 반복 초기화가 중복 핸들러를 남기지 않는다. fixture가 새 핸들러도 정리한다.
    logger = logging.getLogger('my_video_manager')
    current, = logger.handlers
    try:
        for _ in range(10):
            logger.warning('회전 진단 ' * 10000)
        logger.warning('단일 대형 진단 ' * LOG_MAX_BYTES)
        log_failure(tmp_path, 'interrupted', '중단되었습니다.', '')
        app_files = list(path.parent.glob('app.log*'))
        assert len(app_files) == 3
        assert all(p.stat().st_size <= LOG_MAX_BYTES for p in app_files)
        preparation = (path.parent / 'subtitle-preparation.log').read_text(encoding='utf-8')
        assert 'my_video_manager.preparation INFO interrupted' in preparation
        assert 'interrupted' not in path.read_text(encoding='utf-8')
        core = open_core(tmp_path / 'library.sqlite3')
        archive = core.create_backup(tmp_path / 'backup.zip', include_thumbnails=True).path
        with zipfile.ZipFile(archive) as bundle:
            assert not any('logs/' in name or '.log' in name for name in bundle.namelist())
    finally:
        logger.removeHandler(current)
        current.close()


def test_log_directory_creation_failure_is_ignored(tmp_path):
    (tmp_path / 'logs').write_text('not a directory')
    assert configure_app_logging(tmp_path) is None


@pytest.mark.parametrize('failure', ['write', 'rotate'])
def test_log_write_and_rotation_failures_do_not_escape_or_echo_secrets(app_log, monkeypatch, capsys, failure):
    _, handler = app_log
    def denied(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'secret=private-value')
    if failure == 'write':
        monkeypatch.setattr(handler.stream, 'write', denied)
    else:
        monkeypatch.setattr(handler, 'shouldRollover', lambda record: True)
        monkeypatch.setattr(handler, 'doRollover', denied)
    logging.getLogger('my_video_manager.backup').warning('token=private-value')
    assert capsys.readouterr().err == ''


def test_unexpected_restore_failure_is_logged_and_pending_restore_survives(app_log, tmp_path, monkeypatch):
    import my_video_manager.backup as backup
    path, _ = app_log
    core = open_core(tmp_path / 'data/library.sqlite3')
    archive = core.create_backup(tmp_path / 'backup.zip').path
    core.request_backup_restore(archive)
    def broken(database):
        raise RuntimeError('token=private-value restore-detail')
    monkeypatch.setattr(backup, '_apply_backup_restore', broken)
    assert apply(core.database).status == 'deferred'
    assert backup.pending_backup_restore_path(core.database).exists()
    content = path.read_text(encoding='utf-8')
    assert 'restore-detail' in content and 'RuntimeError' in content
    assert 'private-value' not in content
