"""앱 수명과 설정 화면에 연결한 업데이트 확인의 공개 동작."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from my_video_manager import update_manifest
from my_video_manager.core import AppCore
from my_video_manager.update_check import LAST_CHECK_KEY, InstalledUpdateInfo
from my_video_manager.web_update_data import FAILURE_MESSAGES, failure_message
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_library_return_ui import Player
from test_startup_scan import Media, settle

SOURCE = Path(__file__).resolve().parents[1] / 'src/my_video_manager'
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


class GatedCheck:
    """작업자에서 부르는 check_for_update. gate가 열릴 때까지 네트워크 대기를 흉내 낸다."""

    def __init__(self, core):
        self.core = core
        self.gate = threading.Event()
        self.gate.set()
        self.threads = []
        self.failure = None

    def __call__(self):
        self.threads.append(threading.get_ident())
        assert self.gate.wait(20), '업데이트 확인 대기가 풀리지 않았습니다.'
        if self.failure is not None:
            raise self.failure
        return self.core.check_for_update()


@pytest.fixture
def app(tmp_path, monkeypatch, qapp):
    core = AppCore(database=tmp_path / 'data/library.sqlite3', media=Media(),
                   clock=lambda: datetime.now(timezone.utc),
                   update_installation=lambda: InstalledUpdateInfo('1.0.0', None))
    check = GatedCheck(core)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []

    def create(*, delay=0, show=True):
        window = MainWindow(core, player_factory=Player,
                            update_check_options=dict(startup_delay_ms=delay, check=check))
        windows.append(window)
        window.subtitles.timer.stop()
        window.translations.timer.stop()
        if show:
            window.show()
        return window

    yield core, check, create
    check.gate.set()
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def settings(window):
    return window.web_host.controllers['settings']


def update_payload(window):
    return settings(window).payload()['update']


def save(core, **values):
    core.settings.set(LAST_CHECK_KEY, {'checked_at': NOW.isoformat(), 'current_version': '1.0.0',
                                       'latest_version': '1.0.0', 'download_size': None,
                                       'failure_reason': None, 'kind': 'none', **values})


def test_startup_check_runs_on_worker_after_startup_scan_and_is_saved(app):
    core, check, create = app
    window = create(delay=60_000)
    wait_for(lambda: window._startup_scan_scheduled and not window._startup_scan_timer.isActive())
    # 시작 검사를 띄운 뒤에야 업데이트 확인을 예약하고, 첫 화면을 막지 않게 미룬다.
    assert window.updates._startup.isActive() and check.threads == []
    window.updates._startup.timeout.emit()
    wait_for(lambda: not window.updates.checking)
    assert len(check.threads) == 1 and check.threads[0] != threading.get_ident()
    # 실제 서명 키가 없는 기본 빌드는 요청 없이 조용한 실패로 남는다.
    last = update_payload(window)['last']
    assert last['kind'] == 'failed' and last['failureReason'] == 'invalid_public_key'
    assert last['failureQuiet'] and '서명 키' in last['failureMessage']
    assert not last['stale']


@pytest.mark.parametrize('state', ['recent', 'disabled'])
def test_startup_skips_check_when_not_due(app, state):
    core, check, create = app
    if state == 'recent':
        core.settings.set(LAST_CHECK_KEY, {'checked_at': datetime.now(timezone.utc).isoformat(),
                                           'kind': 'failed', 'current_version': '1.0.0',
                                           'latest_version': None, 'download_size': None,
                                           'failure_reason': 'invalid_public_key'})
    else:
        core.set_automatic_update_check_enabled(False)
    window = create()
    wait_for(lambda: window._startup_scan_scheduled and not window._startup_scan_timer.isActive())
    settle(200)
    assert check.threads == [] and not window.updates.checking


def test_manual_check_does_not_overlap_running_check(app):
    core, check, create = app
    window = create(delay=60_000)
    bridge = settings(window).bridge
    check.gate.clear()
    window.navigate_web_tab('settings')
    assert settings(window).is_active()
    snapshot = json.loads(bridge.checkUpdate())
    assert snapshot['update']['checking']
    wait_for(lambda: len(check.threads) == 1)
    # 진행 중 두 번째 요청(시작 확인 포함)은 새 작업자를 만들지 않고 같은 결과를 기다린다.
    assert json.loads(bridge.checkUpdate())['update']['checking']
    assert not window.updates.start()
    window.updates.check_on_startup()
    settle(100)
    assert len(check.threads) == 1
    changes = []
    bridge.settingsChanged.connect(lambda value: changes.append(json.loads(value)))
    check.gate.set()
    wait_for(lambda: not window.updates.checking)
    assert changes and not changes[-1]['update']['checking']
    assert changes[-1]['update']['last']['failureReason'] == 'invalid_public_key'
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    assert len(check.threads) == 2


def test_quit_does_not_wait_for_pending_check(app):
    core, check, create = app
    window = create(show=False)
    check.gate.clear()
    assert window.updates.start()
    wait_for(lambda: len(check.threads) == 1)
    started = time.monotonic()
    window.tray.quit()
    assert time.monotonic() - started < 2
    assert window.updates.closed and window.updates.checking
    # 종료 뒤 늦게 끝난 확인은 화면 상태를 바꾸지 않고, 시작 확인도 다시 하지 않는다.
    check.gate.set()
    settle(200)
    assert window.updates.checking
    assert not window.updates.start()
    window.updates.check_on_startup()
    assert len(check.threads) == 1


def test_settings_write_failure_is_reported_and_next_check_allowed(app):
    core, check, create = app
    window = create(show=False)
    check.failure = sqlite3.OperationalError('database is locked')
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    status = update_payload(window)
    assert status['error'] == '업데이트 확인 결과를 저장하지 못했습니다: database is locked'
    assert status['last'] is None
    check.failure = None
    assert window.updates.start()
    assert update_payload(window)['error'] == ''
    wait_for(lambda: not window.updates.checking)
    assert update_payload(window)['last']['kind'] == 'failed'


def test_startup_decision_failure_does_not_start_or_raise(app, monkeypatch):
    core, check, create = app
    window = create(show=False)
    monkeypatch.setattr(core, 'should_check_for_update', lambda: (_ for _ in ()).throw(sqlite3.OperationalError('locked')))
    window.updates.check_on_startup()
    assert check.threads == [] and not window.updates.checking


def test_payload_passes_stale_explicitly_and_hides_nothing_else(app):
    core, check, create = app
    window = create(show=False)
    assert update_payload(window) == dict(installedVersion='1.0.0', automatic=True, checking=False,
                                          error='', last=None)
    save(core, kind='patch', current_version='0.9.0', latest_version='1.2.3', download_size=12)
    last = update_payload(window)['last']
    assert last == dict(checkedAt=NOW.isoformat(), kind='patch', currentVersion='0.9.0',
                        latestVersion='1.2.3', downloadSize=12, failureReason=None,
                        failureMessage='', failureQuiet=False, stale=True)
    core.update_installation = lambda: InstalledUpdateInfo('0.9.0', None)
    assert update_payload(window)['last']['stale'] is False
    assert update_payload(window)['installedVersion'] == '0.9.0'


def test_check_slot_reports_storage_error_like_other_slots(app, monkeypatch):
    core, check, create = app
    window = create(show=False)
    monkeypatch.setattr(core, 'last_update_check', lambda: (_ for _ in ()).throw(sqlite3.OperationalError('disk I/O error')))
    assert json.loads(settings(window).bridge.checkUpdate()) == {'error': 'disk I/O error'}
    wait_for(lambda: not window.updates.checking)


def test_automatic_toggle_persists_and_rejects_bad_value(app):
    core, check, create = app
    window = create(show=False)
    bridge = settings(window).bridge
    window.navigate_web_tab('settings')
    assert json.loads(bridge.setAutomaticUpdateCheck(False))['update']['automatic'] is False
    assert not AppCore(database=core.database, media=Media(), clock=lambda: NOW).automatic_update_check_enabled()
    assert json.loads(bridge.setAutomaticUpdateCheck(True))['update']['automatic'] is True


def test_every_failure_code_has_its_own_message():
    codes = set()
    for name in ('update_http.py', 'update_check.py', 'update_manifest.py'):
        text = (SOURCE / name).read_text(encoding='utf-8')
        codes |= set(re.findall(r"(?:UpdateCheckError\(|ManifestError\(|failure_reason=)'([a-z0-9_]+)'", text))
    assert {'network', 'timeout', 'invalid_public_key', 'check_failed', 'unsafe_redirect'} <= codes
    assert codes - set(FAILURE_MESSAGES) == set()


@pytest.mark.parametrize('reason,expected', [
    ('http_503', 'GitHub 서버에 일시적인 문제가 있습니다(HTTP 503). 잠시 뒤 다시 확인하세요.'),
    ('http_418', 'GitHub가 오류를 돌려주었습니다(HTTP 418).'),
    ('future_reason', '확인하지 못했습니다(future_reason).'),
])
def test_unlisted_failure_codes_still_read_as_sentences(reason, expected):
    assert failure_message(reason) == expected


def test_real_public_key_path_is_offline_in_tests(app, monkeypatch):
    core, check, create = app
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'k' * 32)
    window = create(show=False)
    assert window.updates.start()
    wait_for(lambda: not window.updates.checking)
    assert update_payload(window)['last']['failureReason'] == 'network'
    assert update_payload(window)['last']['failureMessage'] == FAILURE_MESSAGES['network']
