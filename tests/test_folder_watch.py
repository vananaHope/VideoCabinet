"""가짜 이벤트·시계와 공개 AppCore 동작으로 자동 감지 계약을 검증한다."""

from queue import Queue
import shutil
from time import monotonic

import pytest

from my_video_manager.folder_watch import AUTOMATIC_DETECTION_KEY, folder_snapshot
from my_video_manager.folder_watch_adapter import WatchdogFolderWatcher
from test_library import core, open_core, record, records, video_file


class FakeWatcher:
    def __init__(self):
        self.folders = ()
        self.callback = None
        self.starts = 0
        self.stops = 0

    def start(self, folders, on_change):
        self.starts += 1
        self.callback = on_change
        self.update(folders)

    def update(self, folders):
        self.folders = folders

    def stop(self):
        self.stops += 1
        self.callback = None

    def emit(self, *folders):
        if self.callback:
            self.callback(tuple(folders))


class FakeCall:
    def __init__(self, when, callback):
        self.when = when
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.calls = []

    def __call__(self):
        return self.now

    def call_later(self, seconds, callback):
        call = FakeCall(self.now + seconds, callback)
        self.calls.append(call)
        return call

    def advance(self, seconds):
        target = self.now + seconds
        callbacks = 0
        while ready := [call for call in self.calls if not call.cancelled and call.when <= target]:
            callbacks += 1
            assert callbacks < 1000, "타이머가 시간이 흐르지 않는 재예약 루프에 빠졌습니다."
            call = min(ready, key=lambda item: item.when)
            call.cancelled = True
            self.now = call.when
            call.callback()
        self.now = target


def watch(core, callback=None, **options):
    watcher, time, batches = FakeWatcher(), FakeTime(), []
    service = core.create_folder_watch(callback or batches.append, watcher=watcher,
                                      clock=time, scheduler=time, **options)
    service.start()
    return service, watcher, time, batches


def test_copy_waits_for_size_and_mtime_stability_then_registers_and_deletes(core, tmp_path):
    folder = tmp_path / "watched/nested"
    folder.mkdir(parents=True)
    core.add_watched_folder(folder.parent)
    core.set_auto_subtitle_rule(folder=folder.parent, spoken_language="en")
    service, watcher, time, batches = watch(core)
    path = video_file(folder, content=b"first chunk")
    watcher.emit(folder)
    time.advance(4)
    path.write_bytes(b"last chunk with a different size")
    # 마지막 OS 이벤트가 없더라도 stat 확인으로 안정화 시간을 다시 센다.
    time.advance(4)
    assert batches == []
    assert core.videos() == ()
    time.advance(2)
    assert batches == [(folder,)]
    assert core.scan(folders=batches.pop()).added == 1
    video, = core.videos()
    entry, = core.subtitle_queue()
    assert entry.video_id == video.id and entry.spoken_language == "en"
    path.unlink()
    watcher.emit(folder)
    time.advance(6)
    core.scan(folders=batches.pop())
    assert core.video(video.id).missing
    service.stop()


@pytest.mark.parametrize("rename_only", [False, True])
def test_move_delivers_source_and_target_once_preserving_identity_and_records(core, tmp_path, rename_only):
    source = video_file(tmp_path / "watched/a")
    target = (source.parent if rename_only else tmp_path / "watched/b") / "renamed.mkv"
    target.parent.mkdir(exist_ok=True)
    core.add_watched_folder(source.parent.parent)
    core.scan()
    video, = core.videos()
    record(core, video.id)
    expected = records(core, video.id)
    service, watcher, time, batches = watch(core)
    source.rename(target)
    watcher.emit(source.parent, target.parent)
    time.advance(6)
    batch, = batches
    assert set(batch) == {source.parent, target.parent}
    result = core.scan(folders=batch)
    assert result.added == 0 and not result.reconnected and not result.issues
    assert len(core.videos()) == 1
    assert [location.path for location in core.video(video.id).locations] == [target]
    assert records(core, video.id) == expected
    service.stop()


def test_burst_batches_only_changed_folders_and_never_polls_while_idle(core, tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    core.add_watched_folder(root)
    snapshots = []

    def snapshot(folders):
        snapshots.append(folders)
        return {}

    service, watcher, time, batches = watch(core, snapshot=snapshot)
    time.advance(100)
    assert time.calls == []
    for index in range(5000):
        watcher.emit(root / f"changed-{index % 3}")
    assert len(time.calls) == 1
    time.advance(0.4)
    watcher.emit(root / "changed-0/nested")
    time.advance(0.2)
    assert snapshots == []  # 마지막 이벤트부터 디바운스.
    time.advance(6)
    batch, = batches
    assert set(batch) == {root / f"changed-{index}" for index in range(3)}
    assert all(set(item) == set(batch) for item in snapshots)
    assert len(snapshots) == 6
    calls = len(time.calls)
    time.advance(100)
    assert len(time.calls) == calls
    service.stop()


def test_folder_add_remove_updates_observer_and_drops_unwatched_pending_changes(core, tmp_path):
    first = video_file(tmp_path / "one")
    second = video_file(tmp_path / "two")
    core.add_watched_folder(first.parent)
    service, watcher, time, batches = watch(core)
    assert watcher.folders == (first.parent,)
    core.add_watched_folder(second.parent)
    assert set(watcher.folders) == {first.parent, second.parent}
    watcher.emit(first.parent, second.parent)
    core.remove_watched_folder(first.parent)
    assert watcher.folders == (second.parent,)
    watcher.emit(first.parent)  # 이미 큐에 있던 OS 이벤트도 버린다.
    time.advance(6)
    assert batches == [(second.parent,)]
    service.stop()


def test_overlapping_watches_keep_child_after_parent_removed(core, tmp_path):
    path = video_file(tmp_path / "watched/child")
    core.add_watched_folder(path.parent.parent)
    core.add_watched_folder(path.parent)
    service, watcher, time, batches = watch(core)
    assert watcher.folders == (path.parent.parent,)
    core.remove_watched_folder(path.parent.parent)
    assert watcher.folders == (path.parent,)
    watcher.emit(path.parent)
    time.advance(6)
    assert batches == [(path.parent,)]
    service.stop()


def test_setting_defaults_persists_and_stops_restarts_without_stale_callbacks(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    assert core.automatic_detection_enabled() is True
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    old_callback, old_timer = watcher.callback, time.calls[-1].callback
    core.set_automatic_detection_enabled(False)
    assert not service.enabled and not core.automatic_detection_enabled()
    assert open_core(core.database).automatic_detection_enabled() is False
    time.advance(10)
    watcher.emit(path.parent)
    assert batches == []
    core.set_automatic_detection_enabled(True)
    old_callback((path.parent,))
    old_timer()
    time.advance(10)
    assert batches == []
    watcher.emit(path.parent)
    time.advance(6)
    assert batches == [(path.parent,)]
    assert watcher.starts == 2
    assert open_core(core.database).automatic_detection_enabled() is True
    service.stop()
    core.set_automatic_detection_enabled(False)
    core.set_automatic_detection_enabled(True)
    assert watcher.starts == 2  # 설정 변경은 종료한 앱 수명을 다시 시작하지 않는다.


def test_disabled_before_creation_and_idempotent_lifecycle(core, tmp_path):
    core.set_automatic_detection_enabled(False)
    service, watcher, time, batches = watch(core)
    assert watcher.starts == 0
    service.start()
    core.set_automatic_detection_enabled(True)
    service.start()
    assert watcher.starts == 1
    service.stop()
    service.stop()
    service.start()
    assert watcher.starts == 2
    service.stop()


@pytest.mark.parametrize("value", [None, "false", 0, [], {}])
def test_invalid_setting_uses_default_and_api_rejects_non_boolean(core, value):
    core.settings.set(AUTOMATIC_DETECTION_KEY, value)
    assert core.automatic_detection_enabled() is True
    with pytest.raises(TypeError):
        core.set_automatic_detection_enabled(value)


def test_deleted_subfolder_is_informational_but_missing_root_is_failure(core, tmp_path):
    path = video_file(tmp_path / "watched/child")
    root = path.parent.parent
    core.add_watched_folder(root)
    core.scan()
    video, = core.videos()
    service, watcher, time, batches = watch(core)
    shutil.rmtree(path.parent)
    watcher.emit(path.parent)
    time.advance(6)
    result = core.scan(folders=batches.pop())
    assert not any(issue.failed for issue in result.issues)
    assert core.video(video.id).missing
    root.rmdir()
    result = core.scan(folders=[root])
    assert result.issues and all(issue.failed for issue in result.issues)
    service.stop()


def test_directory_move_waits_for_all_nested_files_even_without_child_events(core, tmp_path):
    source = tmp_path / "watched/source"
    nested = video_file(source / "nested")
    target = source.with_name("target")
    core.add_watched_folder(source.parent)
    service, watcher, time, batches = watch(core)
    source.rename(target)
    watcher.emit(source, target)
    time.advance(4)
    (target / "nested" / nested.name).write_bytes(b"still copying")
    time.advance(4)
    assert batches == []
    time.advance(2)
    assert set(batches[0]) == {source, target}
    assert core.scan(folders=batches[0]).added == 1
    service.stop()


def test_snapshot_and_delivery_failures_retry_without_losing_batch(core, tmp_path, caplog):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    readings, deliveries = [], []

    def snapshot(folders):
        readings.append(folders)
        if len(readings) == 1:
            raise PermissionError("busy file")
        return folder_snapshot(folders)

    def deliver(folders):
        deliveries.append(folders)
        if len(deliveries) == 1:
            raise RuntimeError("queue unavailable")

    service, watcher, time, _ = watch(core, deliver, snapshot=snapshot)
    watcher.emit(path.parent)
    time.advance(8)
    assert deliveries == [(path.parent,), (path.parent,)]
    assert len(caplog.records) == 2
    service.stop()


def test_events_during_snapshot_are_not_lost(core, tmp_path):
    path = video_file(tmp_path / "watched/a")
    other = video_file(tmp_path / "watched/b")
    core.add_watched_folder(path.parent.parent)
    fired = False

    def snapshot(folders):
        nonlocal fired
        if not fired:
            fired = True
            watcher.emit(other.parent)
        return folder_snapshot(folders)

    service, watcher, time, batches = watch(core, snapshot=snapshot)
    watcher.emit(path.parent)
    time.advance(7)
    assert len(batches) == 1 and set(batches[0]) == {path.parent, other.parent}
    service.stop()


def test_cancelled_timer_cannot_deliver_after_pending_folder_removed(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    old_timer = time.calls[-1].callback
    core.remove_watched_folder(path.parent)
    core.add_watched_folder(path.parent)
    watcher.emit(path.parent)
    old_timer()
    time.advance(6)
    assert batches == [(path.parent,)]
    service.stop()


def test_stop_during_snapshot_prevents_delivery_and_rescheduling(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)

    def snapshot(folders):
        service.stop()
        return folder_snapshot(folders)

    service, watcher, time, batches = watch(core, snapshot=snapshot)
    watcher.emit(path.parent)
    time.advance(10)
    assert batches == [] and len(time.calls) == 1
    assert watcher.callback is None


def test_separate_events_between_two_watched_roots_share_one_scan(core, tmp_path):
    source = video_file(tmp_path / "source")
    target = video_file(tmp_path / "target", "placeholder.txt")
    target.unlink()
    target = target.with_name("moved.mkv")
    for folder in (source.parent, target.parent):
        core.add_watched_folder(folder)
    core.scan()
    video, = core.videos()
    service, watcher, time, batches = watch(core)
    source.rename(target)
    watcher.emit(source.parent)
    time.advance(0.2)
    watcher.emit(target.parent)
    time.advance(6)
    batch, = batches
    assert set(batch) == {source.parent, target.parent}
    core.scan(folders=batch)
    assert [location.path for location in core.video(video.id).locations] == [target]
    service.stop()


def test_real_recursive_watcher_delivers_create_move_delete_and_restarts(core, tmp_path):
    root = tmp_path / "watched"
    source = root / "a/nested/video.mkv"
    target = root / "b/renamed.mkv"
    source.parent.mkdir(parents=True)
    target.parent.mkdir()
    events = Queue()
    core.add_watched_folder(root)
    watcher = core.create_folder_watch(events.put, watcher=WatchdogFolderWatcher(),
                                       debounce_seconds=0.05, stable_seconds=0.2, poll_seconds=0.05)

    def wait_for(predicate):
        deadline = monotonic() + 10
        while True:
            batch = events.get(timeout=max(0.01, deadline - monotonic()))
            if predicate(batch):
                return batch
            assert monotonic() < deadline

    try:
        watcher.start()
        source.write_bytes(b"video")
        batch = wait_for(lambda batch: source.parent in batch)
        assert core.scan(folders=batch).added == 1
        video, = core.videos()
        source.rename(target)
        # Windows의 폴더 간 이동은 delete/create로 나뉠 수도 있다.
        batch = wait_for(lambda batch: set(batch) == {source.parent, target.parent})
        result = core.scan(folders=batch)
        assert not result.reconnected and not result.issues
        assert [location.path for location in core.video(video.id).locations] == [target]
        target.unlink()
        core.scan(folders=wait_for(lambda batch: target.parent in batch))
        assert core.video(video.id).missing
        watcher.stop()
        watcher.start()
        source.write_bytes(b"again")
        wait_for(lambda batch: source.parent in batch)
    finally:
        watcher.stop()


def test_same_size_modification_also_restarts_stabilization(core, tmp_path):
    import os
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    time.advance(4)
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    time.advance(4)
    assert batches == []
    time.advance(2)
    assert batches == [(path.parent,)]
    service.stop()


@pytest.mark.parametrize("operation", ["start", "update"])
def test_watcher_failure_cleans_up_and_allows_explicit_restart(core, tmp_path, operation):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)

    class FailingWatcher(FakeWatcher):
        fail = True

        def start(self, folders, on_change):
            self.callback = on_change
            if operation == "start" and self.fail:
                raise OSError("watch unavailable")
            super().start(folders, on_change)

        def update(self, folders):
            if operation == "update" and self.fail and len(folders) > 1:
                raise OSError("watch unavailable")
            super().update(folders)

    watcher, time, batches = FailingWatcher(), FakeTime(), []
    service = core.create_folder_watch(batches.append, watcher=watcher, clock=time, scheduler=time)
    with pytest.raises(OSError):
        service.start()
        other = video_file(tmp_path / "other")
        core.add_watched_folder(other.parent)
    assert watcher.callback is None and watcher.stops >= 1
    watcher.fail = False
    service.start()
    watcher.emit(path.parent)
    time.advance(6)
    assert batches == [(path.parent,)]
    service.stop()
