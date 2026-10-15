import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QEventLoop, QTimer

from test_web_library_data import core
from test_web_library_page import window_factory
from my_video_manager.cuda_runtime import PreparationError, PreparationProgress
from my_video_manager.cuda_runtime import SubtitlePreparation
from my_video_manager.subtitle_controls import SubtitleControls
from my_video_manager.core import AppCore


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
    core.request_subtitles(core.videos()[0].id)

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


@pytest.mark.parametrize('kind', ['cancelled', 'network'])
def test_restart_waits_for_explicit_retry(window_factory, core, monkeypatch, kind):
    from my_video_manager import subtitle_controls
    window = window_factory()
    window.subtitles.timer.stop()
    video = core.videos()[0]
    core.request_subtitles(video.id)
    def fail():
        raise PreparationError(kind, 'model.bin: HTTP Error 503')
    service = SubtitlePreparation(core.database.parent, gpu_available=fail)
    with pytest.raises(PreparationError):
        core.prepare_subtitle_support(preparation=service)
    restarted = AppCore(database=core.database, media=None, clock=datetime.now)
    window.core = restarted
    monkeypatch.setattr(subtitle_controls, 'sys', SimpleNamespace(frozen=True))
    controls = SubtitleControls(window)
    controls.timer.stop()
    calls = []
    monkeypatch.setattr(restarted, 'prepare_subtitle_support', lambda **kwargs: calls.append('prepare'))
    monkeypatch.setattr(restarted, 'process_next_subtitle', lambda: None)
    for _ in range(3):
        controls.process_queue()
    assert calls == []
    assert controls.preparation['state'] == 'failed'
    assert controls.preparation['kind'] == kind
    assert '503' in controls.preparation['message']
    assert restarted.subtitle_queue()[0].state == 'queued'
    controls.prepare()
    wait_until(lambda: controls.preparation_worker is None and controls.worker is None)
    assert calls == ['prepare'] and controls.support_ready
    controls.shutdown()


def test_empty_queue_hides_failure_and_retry_cannot_download(window_factory, core, monkeypatch):
    window = window_factory()
    controls = window.subtitles
    controls.timer.stop()
    controls.support_ready = False
    video = core.videos()[0]
    core.request_subtitles(video.id)
    controls.preparation_result('network', 'HTTP 503')
    core.remove_from_subtitle_queue(video.id)
    calls = []
    monkeypatch.setattr(core, 'prepare_subtitle_support', lambda **kwargs: calls.append('prepare'))
    bridge = window.web_host.controllers['queue'].bridge
    # 타이머보다 먼저 온 오래된 다시 시도 클릭도 차단한다.
    bridge.preparationAction('retry')
    controls.process_queue()
    assert json.loads(bridge.preparationSnapshot())['state'] == 'idle'
    assert calls == [] and controls.preparation_worker is None
    core.request_subtitles(video.id)
    controls.process_queue()
    assert controls.preparation['state'] == 'failed' and calls == []


def test_request_notice_uses_manifest_and_disappears_when_ready(window_factory, core, monkeypatch):
    import sys
    from my_video_manager.runtime_assets import preparation_download_label
    from my_video_manager.web_dialogs_models import DialogModel
    window = window_factory()
    window.subtitles.timer.stop()
    model = DialogModel(window.web_host.dialogs, 'subtitles', video_id=core.videos()[0].id)
    assert model.snapshot()['information'] == ''  # 소스 실행
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert preparation_download_label() in model.snapshot()['information']
    monkeypatch.setattr(core, 'subtitle_support_status', lambda: dict(kind='ready'))
    assert model.snapshot()['information'] == ''
