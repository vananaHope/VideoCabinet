import json
import time

from PySide6.QtCore import QEventLoop, QTimer

from test_web_library_data import core
from test_web_library_page import window_factory
from my_video_manager.cuda_runtime import PreparationError, PreparationProgress


def wait_until(condition):
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()


def test_first_queue_preparation_cancel_retry_preserves_queue(window_factory, core, monkeypatch):
    window = window_factory()
    controls = window.subtitles
    controls.timer.stop()
    controls.support_ready = False
    video = core.videos()[0]
    core.request_subtitles(video.id)
    events = []
    calls = []
    bridge = window.web_host.controllers['queue'].bridge
    bridge.preparationChanged.connect(lambda text: events.append(json.loads(text)))

    def prepare(*, cancellation, progress):
        calls.append('prepare')
        progress(PreparationProgress('download', 'model.bin', 1, 100))
        if len(calls) == 1:
            assert cancellation.wait(5)
            raise PreparationError('cancelled')

    monkeypatch.setattr(core, 'prepare_subtitle_support', prepare)
    processed = []
    monkeypatch.setattr(core, 'process_next_subtitle', lambda: processed.append(True))
    controls.process_queue()
    wait_until(lambda: any(value['phase'] == 'download' for value in events))
    assert not processed
    assert json.loads(bridge.preparationAction('cancel')) == {'ok': True}
    wait_until(lambda: controls.preparation_worker is None)
    assert json.loads(bridge.preparationSnapshot())['kind'] == 'cancelled'
    assert core.subtitle_queue()[0].state == 'queued'
    controls.process_queue()
    assert calls == ['prepare']  # 취소 후 타이머가 자동 재시도하지 않는다.
    assert json.loads(bridge.preparationAction('retry')) == {'ok': True}
    wait_until(lambda: bool(processed) and controls.worker is None)
    assert controls.support_ready
    assert calls == ['prepare', 'prepare']


def test_shutdown_cancels_preparation_and_joins_worker(window_factory, core, monkeypatch):
    window = window_factory()
    controls = window.subtitles
    controls.support_ready = False

    def prepare(*, cancellation, progress):
        assert cancellation.wait(5)
        raise PreparationError('cancelled')

    monkeypatch.setattr(core, 'prepare_subtitle_support', prepare)
    controls.prepare()
    worker = controls.preparation_worker
    assert controls.shutdown()
    assert not worker.isRunning()


def test_general_version_and_fixed_release_browser_link(window_factory, monkeypatch):
    from my_video_manager import web_settings_page
    from my_video_manager.app_version import current_version, RELEASES_URL
    window = window_factory()
    bridge = window.web_host.controllers['settings'].bridge
    data = json.loads(bridge.snapshot())
    assert data['version'] == current_version()
    assert data['releasesUrl'] == RELEASES_URL
    opened = []
    monkeypatch.setattr(web_settings_page.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()) or True)
    bridge.action('releases')
    wait_until(lambda: bool(opened))
    assert opened == [RELEASES_URL]
