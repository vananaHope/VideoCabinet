"""기존 캐시 업그레이드의 취소·재개·실패·식별자 보존과 작업자 수명."""
from pathlib import Path
import sqlite3
from threading import Event

import pytest

from my_video_manager.core import AppCore
from my_video_manager.resolution import ResolutionResult
from test_library import NOW, Media
from test_web_library_data import core
from test_web_library_page import window_factory
from test_web_statistics import wait_for


def legacy(core):
    paths = []
    with sqlite3.connect(core.database) as db:
        for video in core.videos():
            old = video.thumbnail.with_name(video.thumbnail.name.replace('.640.jpg', '.jpg'))
            video.thumbnail.rename(old)
            db.execute('UPDATE videos SET thumbnail=? WHERE id=?', (str(Path('thumbnails') / old.name), video.id))
            paths.append(old)
    return paths


def test_new_thumbnail_is_versioned_and_old_ones_resume_after_restart(core):
    assert all(v.thumbnail.name.endswith('.640.jpg') for v in core.videos())
    assert core.fill_next_thumbnail(cancellation=Event()).state == 'exhausted'
    old = legacy(core)
    assert core.fill_next_thumbnail(cancellation=Event()).state == 'completed'
    reopened = AppCore(media=Media(), clock=lambda: NOW, database=core.database)
    assert reopened.fill_next_thumbnail(cancellation=Event()).state == 'completed'
    assert reopened.fill_next_thumbnail(cancellation=Event()).state == 'completed'
    assert reopened.fill_next_thumbnail(cancellation=Event()).state == 'exhausted'
    assert all(not p.exists() for p in old)
    assert all(v.thumbnail.is_file() for v in reopened.videos())


def test_cancel_capture_keeps_old_file_and_does_not_mark_done(core, monkeypatch):
    old = legacy(core)
    cancellation = Event()
    def capture(path, destination, seconds):
        destination.write_bytes(b'partial')
        cancellation.set()
    monkeypatch.setattr(core._media, 'capture', capture)
    assert core.fill_next_thumbnail(cancellation=cancellation).state == 'cancelled'
    assert all(p.exists() for p in old)
    assert not list(old[0].parent.glob('*.tmp.jpg'))
    monkeypatch.setattr(core._media, 'capture', Media().capture)
    cancellation.clear()
    assert core.fill_next_thumbnail(cancellation=cancellation).state == 'completed'


def test_missing_and_failed_files_are_not_retried_until_explicit_scan(core, monkeypatch):
    legacy(core)
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError('capture failed')
    monkeypatch.setattr(core._media, 'capture', fail)
    for _ in range(3):
        assert core.fill_next_thumbnail(cancellation=Event()).state == 'unknown'
    assert core.fill_next_thumbnail(cancellation=Event()).state == 'exhausted'
    assert len(calls) == 3
    reopened = AppCore(media=core._media, clock=lambda: NOW, database=core.database)
    assert reopened.fill_next_thumbnail(cancellation=Event()).state == 'exhausted'
    reopened.scan()
    assert reopened.fill_next_thumbnail(cancellation=Event()).state == 'unknown'
    assert len(calls) == 4


def test_replaced_file_does_not_upgrade_previous_video(core):
    legacy(core)
    video = min(core.videos(), key=lambda v: v.id)
    video.locations[0].path.write_bytes(b'different content')
    result = core.fill_next_thumbnail(cancellation=Event())
    assert result.video_id == video.id and result.state == 'unknown'
    assert not core.video(video.id).thumbnail.name.endswith('.640.jpg')


def test_thumbnail_worker_yields_to_playback_subtitles_scan_and_shutdown(window_factory, core, monkeypatch):
    entered = Event()
    calls = []
    def step(*, cancellation):
        calls.append(True)
        entered.set()
        cancellation.wait(5)
        return ResolutionResult(None, 'cancelled')
    monkeypatch.setattr(core, 'fill_next_thumbnail', step)
    window = window_factory()
    controls = window.thumbnails
    controls.timer.stop()
    controls.tick()
    wait_for(entered.is_set)
    core.playback.start(core.videos()[0].id, 0)
    assert controls.cancellation.is_set()
    wait_for(lambda: controls.future.done())
    controls.tick()
    assert controls.future is None
    core.playback.end()
    for owner in (window.subtitles, window.library_page):
        owner.worker = object()
        try:
            controls.tick()
            assert controls.future is None
        finally:
            owner.worker = None
    entered.clear()
    controls.tick()
    wait_for(entered.is_set)
    controls.shutdown()
    assert controls.future.done() and controls.cancellation.is_set() and len(calls) == 2


def test_thumbnail_worker_failure_stops_cleanly(window_factory, core, monkeypatch):
    def fail(**kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(core, 'fill_next_thumbnail', fail)
    window = window_factory()
    controls = window.thumbnails
    controls.tick()
    wait_for(lambda: controls.future.done())
    controls.tick()
    assert controls.future is None and not controls.timer.isActive()
    assert 'disk full' in window.statusBar().currentMessage()


@pytest.mark.parametrize('cancel', [True, False])
def test_background_ffmpeg_is_low_priority_and_killed_on_cancel_or_timeout(tmp_path, monkeypatch, cancel):
    from my_video_manager import adapters
    import subprocess
    cancellation = Event()
    commands = []
    class Process:
        killed = False
        def communicate(self, timeout=None):
            if timeout is not None:
                cancellation.set()
                raise subprocess.TimeoutExpired('ffmpeg', timeout)
            return '', ''
        def poll(self):
            return 1 if self.killed else None
        def kill(self):
            self.killed = True
    process = Process()
    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return process
    monkeypatch.setattr(adapters, 'executable', lambda name: name)
    monkeypatch.setattr(adapters.subprocess, 'Popen', popen)
    if not cancel:
        times = iter([0, 121])
        monkeypatch.setattr(adapters.time, 'monotonic', lambda: next(times))
    reader = adapters.FFmpegMediaReader()
    if cancel:
        reader.capture_background(tmp_path / 'input.mp4', tmp_path / 'out.jpg', 10, cancellation=cancellation)
    else:
        with pytest.raises(RuntimeError, match='120'):
            reader.capture_background(tmp_path / 'input.mp4', tmp_path / 'out.jpg', 10, cancellation=cancellation)
    assert process.killed
    assert 'scale=640:-2' in commands[0][0] and '-threads' in commands[0][0]
    if adapters.sys.platform == 'win32':
        assert commands[0][1]['creationflags'] & subprocess.BELOW_NORMAL_PRIORITY_CLASS
