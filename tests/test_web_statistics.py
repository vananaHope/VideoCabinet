"""통계 페이지 공개 채널, 작업자 경합과 실제 Qt 재생 왕복."""
from dataclasses import asdict
import json
from threading import Event, get_ident
from time import monotonic

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
    window = window_factory('1')
    window.player_factory = Player
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    for days in (7, 30, 90, 365):
        assert json.loads(page.bridge.setPeriod(days)) == {'ok': True}
        wait_for(lambda: state(page)['result'] is not None)
        assert state(page)['result'] == json.loads(json.dumps(asdict(core.statistics_dashboard(days))))
    assert 'error' in json.loads(page.bridge.setPeriod(8))
    assert 'error' in json.loads(page.bridge.playVideo(99999))
    video = core.videos()[0]
    window.play_video(video.id)
    core.playback.report(40)
    window.back_to_list()
    wait_for(lambda: state(page)['result'] is not None)
    assert window.web_host.active_tab == 'statistics'
    assert state(page)['result']['period']['watched_seconds'] == 40
    assert json.loads(page.bridge.playVideo(video.id)) == {'ok': True}
    wait_for(lambda: core.playback.session is not None)
    window.back_to_list()
    wait_for(lambda: state(page)['result'] is not None)


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
    window = window_factory('1')
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
    window = window_factory('1')
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
    window = window_factory('1')
    window.navigate_web_tab('statistics')
    page = window.web_host.controllers['statistics']
    wait_for(lambda: state(page)['result'] is not None)
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(50)
    core.playback.end()
    wait_for(lambda: state(page)['result'] is not None and state(page)['result']['period']['viewing_count'] == 1)
