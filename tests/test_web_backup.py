"""공개 설정 브리지와 AppCore로 백업 화면의 작업·예약·실패 수명을 확인한다."""
import errno
import json
from pathlib import Path
import sqlite3
import threading
import time
import zipfile

import pytest
from PySide6.QtCore import QEventLoop, QStandardPaths, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from test_web_library_data import core
from test_web_library_page import window_factory
from my_video_manager.backup import BackupBusyError, BackupRestoreResult, create_automatic_backup, inspect_backup
from my_video_manager.library import LIBRARY_DB_VERSION


def bridge_for(window):
    return window.web_host.controllers['settings'].bridge


def state(bridge):
    return json.loads(bridge.backupSnapshot())


def tick():
    loop = QEventLoop()
    QTimer.singleShot(20, loop.quit)
    loop.exec()


def wait(bridge):
    deadline = time.monotonic() + 20
    while state(bridge)['busy']:
        assert time.monotonic() < deadline
        tick()


def action(bridge, name, target='', thumbnails=False):
    reply = json.loads(bridge.backupAction(name, target, thumbnails))
    assert reply == {'ok': True}, reply
    wait(bridge)
    return state(bridge)


def test_native_pickers_preview_schedule_cancel_keep_current_records(window_factory, core, tmp_path, monkeypatch):
    window = window_factory()
    bridge = bridge_for(window)
    archive = tmp_path / '한글 백업.zip'
    saved, opened = [], []
    def save(*args):
        saved.append(args)
        return str(archive), ''
    def choose(*args):
        opened.append(args)
        return str(archive), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', save)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose)
    before = core.videos()
    result = action(bridge, 'create', thumbnails=True)
    assert archive.exists() and '백업을 만들었습니다' in result['message']
    assert inspect_backup(archive).includes_thumbnails
    result = action(bridge, 'choose')
    assert result['preview']['video_count'] == len(before)
    assert result['preview']['db_version'] == LIBRARY_DB_VERSION
    assert result['preview']['version_message'] == f'현재 DB 버전 {LIBRARY_DB_VERSION}과 같은 버전의 백업입니다.'
    assert result['preview']['created_at'] and result['preview']['app_version']
    assert saved[0][1] == '백업 만들기' and opened[0][1] == '백업 복원 파일 선택'
    assert Path(saved[0][2]).parent == Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    assert not core.pending_backup_restore()
    result = action(bridge, 'schedule')
    assert result['pending'] and result['preview'] is None
    assert '다시 시작하면 적용' in result['message']
    assert core.videos() == before
    result = action(bridge, 'cancel')
    assert not result['pending'] and core.pending_backup_restore() is None
    assert core.videos() == before


@pytest.mark.parametrize('name', ['create', 'choose'])
def test_picker_cancel_releases_busy_without_files(window_factory, core, monkeypatch, name):
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: ('', ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: ('', ''))
    result = action(bridge, name)
    assert not result['busy'] and not result['failure'] and not result['preview']
    assert not core.backup_inventory().pending


def test_v2_migration_backup_is_listed_previewed_and_scheduled_in_v3(window_factory, core):
    from test_backup import open_core
    from test_resolution import downgrade_v2

    downgrade_v2(core.database)
    upgraded = open_core(core.database)
    saved, = upgraded.automatic_backups()
    with zipfile.ZipFile(saved) as archive:
        assert json.loads(archive.read('manifest.json'))['reason'] == 'before_migration'
    bridge = bridge_for(window_factory())
    result = action(bridge, 'refresh')
    assert result['dbVersion'] == 3
    assert result['automatic'][0]['reason'] == 'DB 버전 올리기 전'
    result = action(bridge, 'preview', str(saved))
    assert result['preview']['db_version'] == 2
    assert result['preview']['version_message'] == (
        '이 백업은 DB 버전 2입니다. 다시 시작하면 현재 버전 3에 맞춰 바꾼 뒤 복원합니다. '
        '복원 전 지금 라이브러리는 자동 백업으로 남습니다.')
    assert result['preview']['video_count'] == len(upgraded.videos())
    before = upgraded.videos()
    assert action(bridge, 'schedule')['pending']
    assert upgraded.pending_backup_restore().db_version == 2
    assert upgraded.videos() == before


@pytest.mark.parametrize('error', [BackupBusyError(3, 'source_changed')])
def test_failed_worker_releases_busy_preserves_error_on_reentry_and_allows_retry(window_factory, core, tmp_path, monkeypatch, error):
    window = window_factory()
    bridge = bridge_for(window)
    archive = tmp_path / 'retry.zip'
    real_create = core.create_backup
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(core, 'create_backup', fail)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(archive), ''))
    result = action(bridge, 'create')
    assert result['failure'] == str(error) and not result['busy']
    assert not archive.exists()
    assert action(bridge, 'refresh')['failure'] == str(error)
    monkeypatch.setattr(core, 'create_backup', real_create)
    assert not action(bridge, 'create')['failure'] and archive.exists()


def test_busy_worker_keeps_ui_responsive_blocks_other_actions_and_quit(window_factory, core, tmp_path, monkeypatch):
    window = window_factory()
    bridge = bridge_for(window)
    entered, release = threading.Event(), threading.Event()
    real_create = core.create_backup
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real_create(*args, **kwargs)
    monkeypatch.setattr(core, 'create_backup', slow)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'slow.zip'), ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    try:
        bridge.backupAction('create', '', False)
        while not entered.is_set():
            tick()
        assert state(bridge)['operation'] == 'create'
        assert 'error' in json.loads(bridge.backupAction('cancel', '', False))
        assert json.loads(bridge.backupAction('refresh', '', False)) == {'ok': True}
        window.tray.quit()
        assert not window.tray.quitting and window.isVisible()
        assert '백업 작업' in warnings[-1][2]
        window.navigate_web_tab('queue')
        assert window.web_host.active_tab == 'queue'
    finally:
        release.set()
        wait(bridge)
    assert not state(bridge)['failure']


@pytest.mark.parametrize('startup_status', ['applied', 'rejected', 'deferred'])
def test_startup_result_survives_schedule_and_cancel(window_factory, core, tmp_path, monkeypatch, startup_status):
    archive = core.create_backup(tmp_path / 'source.zip').path
    if startup_status == 'deferred':
        core.request_backup_restore(archive)
    core.set_backup_restore_startup_result(BackupRestoreResult(None, False, status=startup_status,
                                           error_message='지난 시작의 이유', error_kind='disk_full'))
    bridge = bridge_for(window_factory())
    assert state(bridge)['startup']['status'] == startup_status
    assert state(bridge)['pendingDeferred'] == (startup_status == 'deferred')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(archive), ''))
    action(bridge, 'choose')
    assert not action(bridge, 'schedule')['pendingDeferred']
    result = action(bridge, 'cancel')
    assert not result['pending']
    assert result['startup']['status'] == startup_status
    assert result['startup']['error'] == '지난 시작의 이유'


def test_changed_preview_and_invalid_zip_cannot_schedule(window_factory, core, tmp_path, monkeypatch):
    archive = core.create_backup(tmp_path / 'source.zip').path
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(archive), ''))
    action(bridge, 'choose')
    archive.write_bytes(b'broken')
    assert '바뀌었습니다' in action(bridge, 'schedule')['failure']
    assert not state(bridge)['preview'] and not core.backup_inventory().pending
    result = action(bridge, 'choose')
    assert result['failure'] and result['preview'] is None and not result['busy']
    assert action(bridge, 'schedule')['failure'] and not core.backup_inventory().pending


def test_newer_backup_clears_preview_and_blocks_schedule_with_update_guidance(window_factory, core, tmp_path, monkeypatch):
    from contextlib import closing
    from my_video_manager.backup import create_backup

    current = core.create_backup(tmp_path / 'current.zip').path
    future_db = tmp_path / 'future.sqlite3'
    with closing(sqlite3.connect(core.database)) as source, closing(sqlite3.connect(future_db)) as target:
        source.backup(target)
        target.execute(f'PRAGMA user_version={LIBRARY_DB_VERSION + 1}')
    future = create_backup(future_db, tmp_path / 'future.zip').path
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(current), ''))
    assert action(bridge, 'choose')['preview']
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(future), ''))
    result = action(bridge, 'choose')
    assert '더 최신 DB 버전' in result['failure'] and '업데이트' in result['failure']
    assert result['preview'] is None and not result['previewPath']
    assert action(bridge, 'schedule')['failure']
    assert core.pending_backup_restore() is None


def test_preview_discard_and_auto_backup_picker(window_factory, core):
    backup = create_automatic_backup(core.database)
    bridge = bridge_for(window_factory())
    action(bridge, 'refresh')
    assert action(bridge, 'preview', str(backup.path))['preview']
    assert action(bridge, 'discard')['preview'] is None
    assert not core.backup_inventory().pending
    assert action(bridge, 'preview', 'not-in-list.zip')['failure']


def test_automatic_catalog_reason_old_compatibility_and_no_extraction(core, tmp_path, monkeypatch):
    from my_video_manager import backup
    first = create_automatic_backup(core.database, reason='before_migration')
    second = create_automatic_backup(core.database)
    legacy = create_automatic_backup(core.database)
    with zipfile.ZipFile(legacy.path) as bundle:
        contents = {name: bundle.read(name) for name in bundle.namelist()}
    manifest = json.loads(contents['manifest.json'])
    manifest.pop('reason')
    contents['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(legacy.path, 'w') as bundle:
        for name, value in contents.items():
            bundle.writestr(name, value)
    assert core.inspect_backup(legacy.path) == legacy.metadata
    core.request_backup_restore(legacy.path)
    assert core.pending_backup_restore() == legacy.metadata
    def no_extract(*args):
        raise AssertionError('목록 조회는 백업을 풀지 않아야 한다')
    monkeypatch.setattr(backup, 'inspect_backup', no_extract)
    rows = {row.path: row for row in core.backup_inventory().automatic}
    assert rows[str(first.path)].reason == 'DB 버전 올리기 전'
    assert rows[str(second.path)].reason == '백업 복원 전'
    assert '상세 이유 기록 없음' in rows[str(legacy.path)].reason
    assert all(row.size > 0 and row.created_at for row in rows.values())


def test_cancel_failure_keeps_pending_and_next_try_succeeds(window_factory, core, tmp_path, monkeypatch):
    core.request_backup_restore(core.create_backup(tmp_path / 'source.zip').path)
    bridge = bridge_for(window_factory())
    real_cancel = core.cancel_backup_restore
    def fail():
        raise PermissionError('파일을 사용하는 프로그램을 닫으세요')
    monkeypatch.setattr(core, 'cancel_backup_restore', fail)
    assert action(bridge, 'cancel')['pending']
    assert state(bridge)['failure']
    monkeypatch.setattr(core, 'cancel_backup_restore', real_cancel)
    assert not action(bridge, 'cancel')['pending']


def test_completed_schedule_and_cancel_stay_accurate_when_catalog_refresh_fails(window_factory, core, tmp_path, monkeypatch):
    archive = core.create_backup(tmp_path / 'source.zip').path
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(archive), ''))
    action(bridge, 'choose')
    def fail():
        raise PermissionError('자동 백업 폴더 접근 불가')
    monkeypatch.setattr(core, 'backup_inventory', fail)
    scheduled = action(bridge, 'schedule')
    assert scheduled['pending'] and core.pending_backup_restore() is not None
    assert '예약했습니다' in scheduled['message'] and '작업은 완료했지만' in scheduled['failure']
    cancelled = action(bridge, 'cancel')
    assert not cancelled['pending'] and core.pending_backup_restore() is None
    assert '취소했습니다' in cancelled['message'] and '작업은 완료했지만' in cancelled['failure']


@pytest.mark.parametrize('version', [3, 4])
def test_preview_supported_db_v3_and_future_version_rejection(window_factory, core, tmp_path, monkeypatch, version):
    from my_video_manager import library
    monkeypatch.setattr(library, 'LIBRARY_DB_VERSION', 3)
    # 메타데이터 비교의 버전 경계만 구성한다. 실제 v3 DDL은 #64가 소유한다.
    with sqlite3.connect(core.database) as db:
        db.execute(f'PRAGMA user_version = {version}')
    archive = core.create_backup(tmp_path / 'version.zip').path
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(archive), ''))
    result = action(bridge, 'choose')
    assert result['dbVersion'] == 3
    if version == 3:
        assert result['preview']['db_version'] == 3 and not result['failure']
    else:
        assert result['preview'] is None and '최신 DB 버전' in result['failure']
    assert not core.backup_inventory().pending


def test_snapshot_does_not_reread_catalog_or_extract_zip(window_factory, core, monkeypatch):
    calls = []
    real_inventory = core.backup_inventory
    def inventory(**kwargs):
        calls.append(kwargs)
        return real_inventory(**kwargs)
    monkeypatch.setattr(core, 'backup_inventory', inventory)
    bridge = bridge_for(window_factory())
    assert calls == [{'include_automatic': False}]
    action(bridge, 'refresh')
    for _ in range(100):
        assert state(bridge)['automatic'] == []
        bridge.snapshot()
    assert calls == [{'include_automatic': False}, {}]


def test_recovery_dialog_cancel_failure_retry_focus_and_folder(core, tmp_path, monkeypatch):
    from my_video_manager.backup_recovery import BackupRecoveryDialog, QDesktopServices
    core.request_backup_restore(core.create_backup(tmp_path / 'source.zip').path)
    app = QApplication.instance() or QApplication([])
    result = BackupRestoreResult(None, False, status='deferred', error_message='공간 부족', guidance='공간을 확보하세요')
    dialog = BackupRecoveryDialog(core.database, result, 'file is not a database')
    dialog.show()
    app.processEvents()
    assert dialog.focusWidget() is dialog.retry
    QTest.keyClick(dialog.retry, Qt.Key.Key_Tab)
    assert dialog.focusWidget() is dialog.cancel
    urls = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: urls.append(url) or True)
    dialog.open_folder.click()
    assert Path(urls[0].toLocalFile()) == core.database.parent
    dialog.cancel.click()
    assert not core.backup_inventory().pending and not dialog.cancel.isEnabled()
    assert core.database.exists() and '취소했습니다' in dialog.message.text()
    QTest.keyClick(dialog.retry, Qt.Key.Key_Escape)
    assert dialog.result() == 0
    dialog.deleteLater()


def test_restart_command_preserves_data_directory(tmp_path, monkeypatch):
    from my_video_manager.backup_recovery import restart_command
    import sys
    program, args = restart_command(tmp_path)
    assert program == sys.executable and args == ['-m', 'my_video_manager', '--data-dir', str(tmp_path)]
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert restart_command(tmp_path)[1] == ['--data-dir', str(tmp_path)]


def test_recovery_cancel_failure_preserves_reservation_and_retry_uses_same_lock(core, tmp_path, monkeypatch):
    from my_video_manager import backup_recovery
    from my_video_manager.backup_recovery import BackupRecoveryDialog, open_with_backup_recovery
    from test_backup import ownership
    core.request_backup_restore(core.create_backup(tmp_path / 'source.zip').path)
    app = QApplication.instance() or QApplication([])
    failure = BackupRestoreResult(None, False, status='deferred', error_message='공간 부족', guidance='공간을 확보하세요')
    dialog = BackupRecoveryDialog(core.database, failure, '손상 DB')
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args))
    real_cancel = backup_recovery.cancel_backup_restore
    def cannot_cancel(database):
        raise PermissionError('읽기 전용')
    monkeypatch.setattr(backup_recovery, 'cancel_backup_restore', cannot_cancel)
    dialog.cancel.click()
    assert core.backup_inventory().pending and dialog.cancel.isEnabled()
    assert messages and '읽기 전용' in messages[-1][2]
    monkeypatch.setattr(backup_recovery, 'cancel_backup_restore', real_cancel)
    dialog.close()
    dialog.deleteLater()
    attempts = []
    with ownership(core.database) as instance:
        real_apply = backup_recovery.apply_pending_backup_restore
        def apply(database, *, instance):
            assert instance.lock.isLocked()
            attempts.append('apply')
            return failure if len(attempts) == 1 else real_apply(database, instance=instance)
        def create():
            attempts.append('open')
            if len(attempts) == 2:
                raise RuntimeError('현재 데이터로 열 수 없음')
            return core
        def retry(self):
            assert self.retry.isDefault() and instance.lock.isLocked()
            return 1
        monkeypatch.setattr(backup_recovery, 'apply_pending_backup_restore', apply)
        monkeypatch.setattr(BackupRecoveryDialog, 'exec', retry)
        assert open_with_backup_recovery(core.database, instance, create) is core
        assert attempts == ['apply', 'open', 'apply', 'open']
        assert core.backup_restore_status().status == 'applied'
        assert not core.backup_inventory().pending


def test_restart_uses_existing_safe_shutdown_and_aborted_shutdown_does_not_restart(window_factory, core, tmp_path, monkeypatch):
    core.request_backup_restore(core.create_backup(tmp_path / 'source.zip').path)
    window = window_factory()
    app = QApplication.instance()
    app.setProperty('backupRestartRequested', False)
    monkeypatch.setattr(window.subtitles, 'shutdown', lambda: False)
    action(bridge_for(window), 'restart')
    assert not app.property('backupRestartRequested') and not window.tray.quitting
    calls = []
    monkeypatch.setattr(window.subtitles, 'shutdown', lambda: calls.append('subtitles') or True)
    monkeypatch.setattr(window.translations, 'shutdown', lambda: calls.append('translations'))
    monkeypatch.setattr(window, 'end_playback', lambda: calls.append('playback'))
    action(bridge_for(window), 'restart')
    assert calls == ['subtitles', 'translations', 'playback']
    assert window.tray.quitting and app.property('backupRestartRequested')
    assert core.backup_inventory().pending
    app.setProperty('backupRestartRequested', False)


@pytest.mark.parametrize('operation', ['create', 'schedule', 'cancel', 'refresh', 'choose'])
@pytest.mark.parametrize('code, phrase', [(errno.EACCES, '권한'), (errno.ENOSPC, '공간'),
                                         (errno.EBUSY, '사용 중'), (errno.ENOENT, '찾을 수 없습니다'),
                                         (5, '사용 중'), (32, '사용 중'), (33, '사용 중'), (112, '공간')])
def test_os_errors_have_actionable_messages_without_internal_paths(window_factory, core, tmp_path, monkeypatch, operation, code, phrase):
    archive = core.create_backup(tmp_path / 'source.zip').path
    bridge = bridge_for(window_factory())
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(archive), ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(archive), ''))
    if operation == 'schedule':
        action(bridge, 'choose')
    def fail(*args, **kwargs):
        error = OSError(code, 'raw OS failure', str(tmp_path / '.backup-private' / 'backup.zip'))
        if code in (5, 32, 33, 112):
            error.winerror = code
        raise error
    if operation == 'choose':
        from my_video_manager.web_backup import BackupControls
        monkeypatch.setattr(BackupControls, 'stamp', fail)
    else:
        method = {'create': 'create_backup', 'schedule': 'request_backup_restore',
                  'cancel': 'cancel_backup_restore', 'refresh': 'backup_inventory'}[operation]
        monkeypatch.setattr(core, method, fail)
    result = action(bridge, operation)
    assert phrase in result['failure']
    assert not result['busy']
    assert f'오류 코드 {code}' in result['failure']
    assert all(raw not in result['failure'] for raw in ('[Errno', '[WinError', '.backup-', 'raw OS'))


def test_recovery_startup_error_is_not_a_backup_error(core, tmp_path):
    from my_video_manager.backup_recovery import BackupRecoveryDialog
    error = PermissionError(errno.EACCES, 'Access is denied', str(tmp_path / 'private'))
    dialog = BackupRecoveryDialog(core.database, None, error)
    try:
        startup = dialog.message.text().split('시작 오류: ')[1]
        assert startup == '라이브러리를 열지 못했습니다. Access is denied'
        assert str(tmp_path) not in startup
        assert '백업' not in startup
    finally:
        dialog.close()


@pytest.mark.parametrize('next_status', [None, 'applied', 'rejected'])
def test_recovery_retry_shows_current_result_after_initial_failure(core, monkeypatch, next_status):
    from my_video_manager import backup_recovery as recovery
    failure = BackupRestoreResult(None, False, status='deferred', error_message='지난 실패', guidance='지난 예약 안내')
    current = (BackupRestoreResult(None, False, status=next_status, error_message='이번 결과', guidance='이번 안내')
               if next_status else None)
    results = iter([failure, current])
    monkeypatch.setattr(recovery, 'apply_pending_backup_restore', lambda *args, **kwargs: next(results))
    texts = []
    def execute(dialog):
        texts.append(dialog.message.text())
        return 1 if len(texts) == 1 else 0
    monkeypatch.setattr(recovery.BackupRecoveryDialog, 'exec', execute)
    def create():
        raise RuntimeError('현재 시작 실패')
    assert recovery.open_with_backup_recovery(core.database, object(), create) is None
    assert '지난 실패' in texts[0] and '지난 예약 안내' in texts[0]
    assert '지난 실패' not in texts[1] and '지난 예약 안내' not in texts[1]
    assert ('이번 결과' if next_status else '예약된 백업 복원이 없습니다') in texts[1]
