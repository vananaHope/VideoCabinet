"""실제 Qt 작업자 수명: 전경 작업에 양보하고 종료 시 진행 중 probe를 취소한다."""
from threading import Event, get_ident

from PySide6.QtTest import QTest

from my_video_manager.resolution import ResolutionResult
from test_web_library_data import core
from test_web_library_page import window_factory
from test_web_statistics import wait_for


def test_resolution_worker_pauses_for_playback_transcription_and_scan(window_factory, core, monkeypatch):
    entered, completed = Event(), Event()
    calls = []
    def fill(*, cancellation):
        calls.append(get_ident())
        entered.set()
        cancellation.wait(5)
        completed.set()
        return ResolutionResult(None, 'cancelled')
    monkeypatch.setattr(core, 'fill_next_resolution', fill)
    window = window_factory()
    controls = window.resolutions
    controls.timer.stop()
    controls.tick()
    wait_for(entered.is_set)
    core.playback.start(core.videos()[0].id, 0)
    assert controls.cancellation.is_set()  # 작업자의 자연 종료가 취소 성공으로 보이지 않게 한다.
    wait_for(completed.is_set)
    wait_for(lambda: controls.future.done())
    controls.tick()
    assert controls.future is None and len(calls) == 1
    assert calls[0] != get_ident()
    core.playback.end()
    # 정상 subtitle 작업자의 실제 제어 경계와 동일한 busy 상태.
    marker = object()
    window.subtitles.worker = marker
    try:
        controls.tick()
        assert controls.future is None
    finally:
        window.subtitles.worker = None
    window.library_page.worker = marker
    try:
        controls.tick()
        assert controls.future is None
    finally:
        window.library_page.worker = None
    entered.clear()
    controls.tick()
    wait_for(entered.is_set)
    controls.shutdown()
    assert controls.future.done() and controls.cancellation.is_set()


def test_resolution_worker_stops_when_exhausted_and_restarts_after_scan(window_factory, core, monkeypatch):
    calls = []
    def fill(*, cancellation):
        calls.append(1)
        return ResolutionResult(None, 'exhausted')
    monkeypatch.setattr(core, 'fill_next_resolution', fill)
    window = window_factory()
    controls = window.resolutions
    refreshes = []
    monkeypatch.setattr(window.web_host.controllers['statistics'], 'refresh', lambda: refreshes.append(True))
    controls.tick()
    wait_for(lambda: controls.future.done())
    controls.tick()
    assert not controls.timer.isActive()
    assert refreshes == []  # 처리할 항목이 없으면 이미 계산한 통계를 다시 읽지 않는다.
    QTest.qWait(1100)
    assert len(calls) == 1
    window.refresh()
    assert controls.timer.isActive()


def test_resolution_failure_stops_without_leaking_worker(window_factory, core, monkeypatch):
    def fill(*, cancellation):
        raise OSError('disk error')
    monkeypatch.setattr(core, 'fill_next_resolution', fill)
    window = window_factory()
    controls = window.resolutions
    controls.tick()
    wait_for(lambda: controls.future.done())
    controls.tick()
    assert controls.future is None and not controls.timer.isActive()
    assert 'disk error' in window.statusBar().currentMessage()
