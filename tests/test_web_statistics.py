"""통계 페이지 공개 채널, 작업자 경합과 실제 Qt 재생 왕복."""
from dataclasses import asdict
import json
from threading import Event, get_ident
from time import monotonic

from wait_helpers import CHILD_READY_TIMEOUT

import pytest
from PySide6.QtTest import QTest

from test_web_library_data import core
from test_web_library_page import window_factory


def wait_for(predicate, seconds=10):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(20)
    assert predicate()


def state(page):
    return json.loads(page.bridge.snapshot())


def test_statistics_channel_periods_and_playback_return(window_factory, core):
    from test_library_return_ui import Player
    window = window_factory()
    window.player_factory = Player
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    for days in (7, 30, 90, 365):
        assert json.loads(page.bridge.setPeriod(days)) == {'ok': True}
        wait_for(lambda: state(page)['result'] is not None and not state(page)['loading'])
        assert state(page)['result'] == json.loads(json.dumps(asdict(core.statistics_dashboard(days))))
    assert 'error' in json.loads(page.bridge.setPeriod(8))
    assert 'error' in json.loads(page.bridge.playVideo(99999))
    video = core.videos()[0]
    window.play_video(video.id)
    core.playback.report(40)
    window.back_to_list()
    wait_for(lambda: state(page)['result'] is not None and not state(page)['loading'])
    assert window.web_host.active_tab == 'statistics'
    assert state(page)['result']['period']['watched_seconds'] == 40
    assert json.loads(page.bridge.playVideo(video.id)) == {'ok': True}
    wait_for(lambda: core.playback.session is not None)
    window.back_to_list()
    wait_for(lambda: state(page)['result'] is not None and not state(page)['loading'])


def test_statistics_late_result_is_discarded_and_ui_can_keep_working(window_factory, core, monkeypatch):
    original = core.statistics_dashboard
    started, release = Event(), Event()
    main_thread, calls = get_ident(), []

    def slow(days):
        calls.append((days, get_ident()))
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
        return original(days)

    monkeypatch.setattr(core, 'statistics_dashboard', slow)
    window = window_factory()
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    wait_for(started.is_set)
    try:
        for days in (7, 90, 365):
            page.bridge.setPeriod(days)
        # DB 쓰기도 UI 스레드에서 계속 처리할 수 있다.
        video = core.videos()[0]
        core.playback.start(video.id, 0)
        core.playback.report(40)
        core.playback.end()
        assert state(page)['result'] is None
    finally:
        release.set()
    wait_for(lambda: state(page)['result'] is not None)
    assert [days for days, _ in calls] == [30, 365]
    assert all(thread != main_thread for _, thread in calls)
    assert state(page)['result']['period']['days'] == 365
    assert state(page)['result']['period']['viewing_count'] == 1


def test_transient_activation_cancels_before_query_and_errors_can_retry(window_factory, core, monkeypatch):
    calls = []
    original = core.statistics_dashboard

    def fail(days):
        calls.append(days)
        raise ValueError('통계 읽기 실패')

    monkeypatch.setattr(core, 'statistics_dashboard', fail)
    window = window_factory()
    window.navigate_web_tab('statistics')
    window.navigate_web_tab('library')
    QTest.qWait(150)
    assert calls == []
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    wait_for(lambda: bool(state(page)['message']))
    assert state(page)['message'] == '통계 읽기 실패'
    assert not state(page)['loading']
    monkeypatch.setattr(core, 'statistics_dashboard', original)
    page.bridge.setPeriod(7)
    wait_for(lambda: state(page)['result'] is not None)
    assert state(page)['result']['period']['days'] == 7


def test_viewing_end_refreshes_visible_statistics_without_tab_switch(window_factory, core):
    window = window_factory()
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    wait_for(lambda: state(page)['result'] is not None)
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(50)
    core.playback.end()
    wait_for(lambda: state(page)['result'] is not None and state(page)['result']['period']['viewing_count'] == 1)


def test_refresh_keeps_last_result_until_replacement_and_after_error(window_factory, core, monkeypatch):
    window = window_factory()
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    wait_for(lambda: state(page)['result'] is not None)
    previous = state(page)['result']
    started, release = Event(), Event()
    original = core.statistics_dashboard

    def slow(days):
        started.set()
        assert release.wait(10)
        return original(days)

    monkeypatch.setattr(core, 'statistics_dashboard', slow)
    page.bridge.setPeriod(365)
    wait_for(started.is_set)
    try:
        pending = state(page)
        assert pending['loading'] and pending['days'] == 365
        assert pending['result'] == previous
    finally:
        release.set()
    wait_for(lambda: not state(page)['loading'])
    assert state(page)['result']['period']['days'] == 365
    previous = state(page)['result']

    def fail(days):
        raise ValueError('일시적인 읽기 실패')

    monkeypatch.setattr(core, 'statistics_dashboard', fail)
    page.bridge.setPeriod(7)
    wait_for(lambda: not state(page)['loading'])
    assert state(page)['message'] == '일시적인 읽기 실패'
    assert state(page)['result'] == previous


@pytest.mark.parametrize('fail', [False, True])
def test_quitting_during_statistics_calculation_has_no_deleted_signal_error(tmp_path, fail):
    """실제 QApplication 종료가 QRunnable보다 먼저 끝나는 두 결과 경로."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = tmp_path / 'quit_statistics.py'
    script.write_text('''
from threading import Event
from time import sleep
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from my_video_manager.core import AppCore
from my_video_manager.web_thumbnail import register_thumbnail_scheme
from my_video_manager.ui import MainWindow
from pathlib import Path
from datetime import datetime, timezone
register_thumbnail_scheme()
started = Event()
core = AppCore(media=None, clock=lambda: datetime.now(timezone.utc), database=Path(__file__).with_suffix('.sqlite3'))
calculate = core.statistics_dashboard
def slow(days):
    started.set()
    sleep(0.3)
    if FAIL:
        raise ValueError('read failed')
    return calculate(days)
core.statistics_dashboard = slow
app = QApplication([])
window = MainWindow(core)
window.show()
window.navigate_web_tab('statistics')
timer = QTimer()
timer.timeout.connect(lambda: window.tray.quit() if started.is_set() else None)
timer.start(20)
QTimer.singleShot(CHILD_QUIT_MS, app.quit)
app.exec()
assert started.is_set()
# QApplication 파괴가 진행되는 동안 작업자가 정상/오류 결과를 마친다.
import shiboken6
shiboken6.delete(app)
'''.replace('FAIL', repr(fail)).replace('CHILD_QUIT_MS', str(int(CHILD_READY_TIMEOUT * 900))), encoding='utf-8')
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'QTWEBENGINE_CHROMIUM_FLAGS': '--disable-gpu'}, timeout=CHILD_READY_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert 'Traceback' not in result.stderr and 'Signal source has been deleted' not in result.stderr
