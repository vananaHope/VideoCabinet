"""감시 루트·드라이브가 사라지거나 다시 연결될 때의 감지와 기록 보존(#133)."""

import logging
from pathlib import Path
from queue import Empty, Queue
import shutil
import sys
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from my_video_manager.folder_watch import RECONNECT_SECONDS
from my_video_manager.folder_watch_adapter import WatchdogFolderWatcher
from test_external_subtitles import srt
from test_folder_watch import FakeTime, FakeWatcher, wait_until_watching
from test_library import core, video_file


class ReconnectingWatcher(FakeWatcher):
    """어댑터처럼 멈춘 루트를 실패로 옮기고, 다시 나타나면 재설치한다."""

    def __init__(self):
        super().__init__()
        self.failed_folders = ()
        self.lost = set()
        self.reconnects = 0
        self.error = None

    def start(self, folders, on_change):
        self.failed_folders = tuple(folder for folder in folders if not folder.is_dir())
        super().start(folders, on_change)

    def emit(self, *folders):
        if not set(folders) & (self.lost | set(self.failed_folders)):
            super().emit(*folders)

    def reconnect(self):
        self.reconnects += 1
        if self.error:
            raise self.error
        failed = set(self.failed_folders) | self.lost
        self.lost = set()
        recovered = tuple(folder for folder in sorted(failed) if folder.is_dir())
        self.failed_folders = tuple(sorted(failed - set(recovered)))
        return recovered


def unplug(folder):
    away = folder.with_name(folder.name + "-unplugged")
    folder.rename(away)
    return away


def test_lost_root_keeps_other_roots_and_rescans_once_after_reconnect(core, tmp_path):
    lost = video_file(tmp_path / "drive", "kept.mkv", b"kept").parent
    deleted = video_file(lost, "deleted.mkv", b"deleted")
    healthy = video_file(tmp_path / "healthy", content=b"healthy").parent
    for root in (lost, healthy):
        core.add_watched_folder(root)
    core.scan()
    before = {video.title: video for video in core.videos()}
    watcher, time, batches = ReconnectingWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    service.start()

    # 드라이브 분리: emitter가 이벤트 없이 멈춘다.
    away = unplug(lost)
    watcher.lost.add(lost)
    time.advance(RECONNECT_SECONDS)
    assert service.failed_folders == (lost,)
    result = core.scan()
    assert [issue.path for issue in result.issues if issue.failed] == [lost]
    assert all(core.video(video.id) == video for video in before.values())

    # 다른 루트의 감지는 계속된다.
    added = video_file(healthy, "added.mkv", b"added")
    watcher.emit(healthy)
    time.advance(6)
    assert batches == [(healthy,)]
    assert core.scan(folders=batches.pop()).added == 1

    # 끊긴 동안의 변경은 다시 연결된 뒤 루트 한 번의 지정 검사로 반영된다.
    video_file(away, "new.mkv", b"new")
    (away / deleted.name).unlink()
    time.advance(RECONNECT_SECONDS * 3)
    assert batches == [] and service.failed_folders == (lost,)
    away.rename(lost)
    reconnected = time.now + RECONNECT_SECONDS
    while service.failed_folders:
        assert time.now < reconnected
        time.advance(0.5)
    assert batches == []  # 다시 연결한 루트도 디바운스·안정화를 거친다.
    time.advance(6)
    assert batches == [(lost,)]
    assert core.scan(folders=batches.pop()).added == 1
    titles = {video.title: video for video in core.videos()}
    assert titles["deleted"].missing and not titles["kept"].missing
    assert {"new", "added"} <= set(titles)
    assert added.is_file()

    # 다시 연결한 루트의 이후 변경도 감지한다.
    video_file(lost, "later.mkv", b"later")
    watcher.emit(lost)
    time.advance(6)
    assert batches == [(lost,)]
    reconnects = watcher.reconnects
    service.stop()
    time.advance(RECONNECT_SECONDS * 3)
    assert watcher.reconnects == reconnects


def test_root_missing_at_start_is_retried_and_rescanned(core, tmp_path):
    root = tmp_path / "later"
    root.mkdir()
    core.add_watched_folder(root)
    root.rmdir()
    watcher, time, batches = ReconnectingWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    service.start()
    assert service.failed_folders == (root,)
    time.advance(RECONNECT_SECONDS * 2)
    assert batches == []
    video_file(root)
    time.advance(RECONNECT_SECONDS + 6)
    assert batches == [(root,)]
    assert core.scan(folders=batches.pop()).added == 1
    service.stop()


def test_reconnect_errors_are_logged_once_and_retried_without_blocking(core, tmp_path, caplog):
    root = video_file(tmp_path / "watched").parent
    core.add_watched_folder(root)
    watcher, time, batches = ReconnectingWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    service.start()
    watcher.error = OSError("device not ready")
    with caplog.at_level(logging.WARNING):
        time.advance(RECONNECT_SECONDS * 5)
        assert watcher.reconnects == 5
        assert sum("재연결 확인 실패" in record.message for record in caplog.records) == 1
        # 껐다 켠 뒤 새 확인 체인의 첫 실패도 다시 남긴다.
        service.stop()
        service.start()
        time.advance(RECONNECT_SECONDS * 2)
    assert sum("재연결 확인 실패" in record.message for record in caplog.records) == 2
    watcher.error = None
    watcher.emit(root)
    time.advance(6)
    assert batches == [(root,)]
    service.stop()


@pytest.mark.parametrize("scope", ["root", "child", "full"])
def test_missing_root_preserves_locations_and_subtitles_until_it_returns(core, tmp_path, scope):
    root = tmp_path / "drive"
    path = video_file(root / "child")
    path.with_suffix(".srt").write_text(srt(), encoding="utf-8")
    core.add_watched_folder(root)
    core.scan()
    video, = core.videos()
    subtitles = core.external_subtitles(video.id)
    assert subtitles
    away = unplug(root)
    folders = {"root": [root], "child": [path.parent], "full": None}[scope]
    result = core.scan(folders=folders)
    assert result.added == 0
    assert result.issues and all(issue.failed for issue in result.issues)
    assert core.video(video.id) == video
    assert core.external_subtitles(video.id) == subtitles
    away.rename(root)
    result = core.scan(folders=folders)
    assert result.added == 0 and not result.issues and not result.reconnected
    assert core.video(video.id) == video
    assert core.external_subtitles(video.id) == subtitles


def test_deleted_inner_root_under_existing_outer_root_is_still_missing(core, tmp_path):
    path = video_file(tmp_path / "outer/inner")
    core.add_watched_folder(path.parent.parent)
    core.add_watched_folder(path.parent)
    core.scan()
    video, = core.videos()
    shutil.rmtree(path.parent)
    result = core.scan(folders=[path.parent])
    assert result.issues and all(issue.failed for issue in result.issues)
    assert core.video(video.id).missing


def test_reconnect_check_keeps_running_after_delivery_error(core, tmp_path):
    root = video_file(tmp_path / "watched").parent
    core.add_watched_folder(root)

    class Unresolvable:
        def __fspath__(self):
            raise TypeError("경로로 바꿀 수 없음")

    class Watcher(ReconnectingWatcher):
        def reconnect(self):
            super().reconnect()
            return (Unresolvable(),) if self.reconnects == 1 else ()

    watcher, time, batches = Watcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    service.start()
    with pytest.raises(TypeError):
        time.advance(RECONNECT_SECONDS)
    time.advance(RECONNECT_SECONDS * 2)
    assert watcher.reconnects == 3
    service.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ReadDirectoryChangesW 버퍼 넘침")
def test_buffer_overflow_rescans_whole_root_once_and_logs_once(core, tmp_path, monkeypatch, caplog):
    from watchdog.observers.api import EventQueue, ObservedWatch
    from my_video_manager import folder_watch_adapter

    root = video_file(tmp_path / "watched/nested").parent.parent
    core.add_watched_folder(root)
    queue = EventQueue()
    emitter = folder_watch_adapter._Emitter(queue, ObservedWatch(str(root), recursive=True))
    emitter._whandle = object()
    adapter, time, batches = WatchdogFolderWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=adapter, clock=time, scheduler=time)
    service.start()
    handler = adapter._handler
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            # 실제 어댑터의 emitter는 진짜 읽기에서 기다리므로 이 emitter의 읽기만 바꾼다.
            with monkeypatch.context() as patch:
                patch.setattr(folder_watch_adapter, "read_events", lambda *args, **kwargs: [])
                emitter.queue_events(0)
            while not queue.empty():
                handler.dispatch(queue.get()[0])
            time.advance(0.2)
        emitter._whandle = None
        assert handler.overflows == 3
        assert sum("버퍼가 넘쳐" in record.message for record in caplog.records) == 1
        time.advance(6)
        assert batches == [(root,)]
        service.stop()
    summary, = [record.message for record in caplog.records if "버퍼 넘침이" in record.message]
    assert "3번" in summary


def test_real_root_deleted_and_recreated_resumes_detection(core, tmp_path):
    healthy = tmp_path / "healthy"
    lost = tmp_path / "lost"
    for root in (healthy, lost):
        root.mkdir()
        core.add_watched_folder(root)
    events = Queue()
    adapter = WatchdogFolderWatcher()
    service = core.create_folder_watch(events.put, watcher=adapter, debounce_seconds=0.05,
                                       stable_seconds=0.2, poll_seconds=0.05, reconnect_seconds=0.1)

    def wait_for(predicate):
        deadline = monotonic() + 10
        while not predicate():
            assert monotonic() < deadline
            try:
                events.get(timeout=0.05)
            except Empty:
                pass

    def drained():
        try:
            events.get(timeout=0.5)
        except Empty:
            return True
        return False

    def wait_for_batch(folder):
        deadline = monotonic() + 10
        while True:
            batch = events.get(timeout=max(0.01, deadline - monotonic()))
            if folder in batch:
                return batch

    try:
        service.start()
        wait_until_watching(events, healthy)
        wait_until_watching(events, lost)
        shutil.rmtree(lost)
        wait_for(lambda: service.failed_folders == (lost,))
        wait_for(lambda: events.empty() and drained())  # 삭제 이벤트의 늦은 묶음을 비운다.
        video_file(healthy)
        assert core.scan(folders=wait_for_batch(healthy)).added == 1
        video_file(lost, "while-away.mkv", b"while away")
        batch = wait_for_batch(lost)
        assert not service.failed_folders
        assert core.scan(folders=batch).added == 1
        wait_until_watching(events, lost)
        video_file(lost, "after.mkv", b"after")
        assert core.scan(folders=wait_for_batch(lost)).added == 1
    finally:
        service.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ReadDirectoryChangesW 읽기 오류")
def test_real_emitter_read_error_without_event_is_reconnected(tmp_path, monkeypatch, caplog):
    from my_video_manager import folder_watch_adapter

    root = tmp_path / "share"
    root.mkdir()
    changes = Queue()
    adapter = WatchdogFolderWatcher()

    def touch_until_change(name):
        deadline = monotonic() + 10
        attempt = 0
        while True:
            assert monotonic() < deadline, "실제 감시가 이벤트를 전달하지 않았습니다."
            attempt += 1
            (root / f"{name}-{attempt}.txt").write_bytes(b"")
            try:
                changes.get(timeout=0.5)
                return
            except Empty:
                pass

    read_events = folder_watch_adapter.read_events
    failures = []

    def unplugged_once(*args, **kwargs):
        if not failures:
            failures.append(True)
            raise OSError(64, "지정된 네트워크 이름을 더 이상 사용할 수 없습니다")
        return read_events(*args, **kwargs)

    adapter.start((root,), changes.put)
    try:
        touch_until_change("ready")
        assert adapter.reconnect() == ()
        monkeypatch.setattr(folder_watch_adapter, "read_events", unplugged_once)
        # 진행 중인 읽기가 끝난 뒤 다음 읽기가 실패하며 emitter가 이벤트 없이 끝난다.
        (root / "trigger.txt").write_bytes(b"")
        deadline = monotonic() + 10
        with caplog.at_level(logging.WARNING):
            # 폴더는 남아 있으므로 끊김을 확인한 같은 호출에서 다시 설치한다.
            while (recovered := adapter.reconnect()) == ():
                assert monotonic() < deadline
        assert recovered == (root,) and not adapter.failed_folders
        lost, = [record.message for record in caplog.records if "연결이 끊겼습니다" in record.message]
        assert "네트워크 이름" in lost
        while not changes.empty():
            changes.get()
        touch_until_change("after")
    finally:
        adapter.stop()


def test_folder_update_leaves_failed_roots_to_reconnect_timer(tmp_path):
    missing = tmp_path / "missing"
    added = tmp_path / "added"
    added.mkdir()
    adapter = WatchdogFolderWatcher()
    adapter.start((missing,), lambda folders: None)
    try:
        assert adapter.failed_folders == (missing,)
        installed = []
        schedule = adapter._observer.schedule
        adapter._observer.schedule = lambda handler, path, **kwargs: (
            installed.append(path), schedule(handler, path, **kwargs))[1]
        adapter.update((missing, added))
        assert installed == [str(added)] and adapter.failed_folders == (missing,)
        missing.mkdir()
        assert adapter.reconnect() == (missing,) and not adapter.failed_folders
    finally:
        adapter.stop()


def test_reading_failed_folders_under_controller_lock_does_not_deadlock_with_reconnect(core, tmp_path):
    """소유 스레드(컨트롤러 잠금) · 타이머(reconnect) · dispatcher(observer 잠금)가 겹쳐도 모두 끝난다."""
    healthy = tmp_path / "healthy"
    lost = tmp_path / "lost"
    for root in (healthy, lost):
        root.mkdir()
        core.add_watched_folder(root)
    events = Queue()
    adapter = WatchdogFolderWatcher()
    service = core.create_folder_watch(events.put, watcher=adapter, debounce_seconds=0.05,
                                       stable_seconds=0.2, poll_seconds=0.05, reconnect_seconds=3600)
    threads = []
    try:
        service.start()
        wait_until_watching(events, healthy)
        shutil.rmtree(lost)
        deadline = monotonic() + 10
        # reconnect가 unschedule할 대상(스스로 멈춘 emitter)을 만든다.
        while any(emitter.is_alive() for emitter in tuple(adapter._observer.emitters)
                  if emitter.watch.path == str(lost)):
            assert monotonic() < deadline
            sleep(0.05)
        holding, results = Event(), {}

        def owner():
            with service._lock:
                holding.set()
                sleep(1.0)  # 그 사이 dispatcher가 observer 잠금을 쥔 채 이 잠금을 기다린다.
                results["failed"] = service.failed_folders

        def timer():
            results["recovered"] = adapter.reconnect()

        threads += [Thread(target=owner, daemon=True), Thread(target=timer, daemon=True)]
        threads[0].start()
        holding.wait()
        video_file(healthy, "during-lock.mkv")
        sleep(0.3)
        threads[1].start()
        for thread in threads:
            thread.join(10)
        assert not any(thread.is_alive() for thread in threads), "잠금 순환으로 멈췄습니다."
        assert results["recovered"] == () and adapter.failed_folders == (lost,)
        deadline = monotonic() + 10
        while healthy not in events.get(timeout=max(0.01, deadline - monotonic())):
            pass  # dispatcher도 끝나 묶음이 전달된다.
    finally:
        if not any(thread.is_alive() for thread in threads):
            service.stop()  # 멈춘 스레드가 있으면 stop도 멈추므로 실패만 보고한다.


def test_same_folders_with_failed_root_keeps_stabilization_in_progress(core, tmp_path):
    healthy = video_file(tmp_path / "healthy").parent
    missing = tmp_path / "missing"
    missing.mkdir()
    for root in (healthy, missing):
        core.add_watched_folder(root)
    missing.rmdir()
    watcher, time, batches = ReconnectingWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    service.start()
    assert service.failed_folders == (missing,)
    watcher.emit(healthy)
    time.advance(4)
    service.set_folders(folder.path for folder in core.watched_folders())
    time.advance(2)
    assert batches == [(healthy,)]
    service.stop()


@pytest.mark.parametrize("present", [False, True])
def test_root_removed_and_readded_during_reconnect_check_is_still_retried(tmp_path, monkeypatch, present):
    """reconnect가 끊긴 루트의 존재를 확인하는 동안 해제·재추가되어도 그 루트를 잃지 않는다."""
    from my_video_manager import folder_watch_adapter

    lost = tmp_path / "lost"
    other = tmp_path / "other"
    other.mkdir()
    changes = Queue()
    adapter = WatchdogFolderWatcher()
    isdir = folder_watch_adapter.os.path.isdir
    checking, release = Event(), Event()

    def slow_isdir(path):
        if Path(path) == lost and not release.is_set():
            checking.set()
            release.wait(10)
            return present
        return isdir(path)

    adapter.start((lost, other), changes.put)
    try:
        assert adapter.failed_folders == (lost,)
        monkeypatch.setattr(folder_watch_adapter.os.path, "isdir", slow_isdir)
        results = {}
        thread = Thread(target=lambda: results.setdefault("recovered", adapter.reconnect()), daemon=True)
        thread.start()
        assert checking.wait(10)
        adapter.update((other,))
        adapter.update((lost, other))
        if present:
            lost.mkdir()
        release.set()
        thread.join(10)
        assert not thread.is_alive()
        monkeypatch.undo()
        if present:
            assert not adapter.failed_folders
        else:
            # 다음 재연결 주기에 다시 시도하고, 나타나면 감시한다.
            assert adapter.failed_folders == (lost,)
            assert adapter.reconnect() == ()
            lost.mkdir()
            assert adapter.reconnect() == (lost,)
            assert not adapter.failed_folders
        deadline = monotonic() + 10
        attempt = 0
        while True:
            assert monotonic() < deadline, "다시 추가한 루트가 감시되지 않습니다."
            attempt += 1
            (lost / f"probe-{attempt}.txt").write_bytes(b"")
            try:
                if lost in changes.get(timeout=0.5):
                    break
            except Empty:
                pass
    finally:
        adapter.stop()
