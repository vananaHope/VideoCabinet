"""가짜 이벤트·시계와 공개 AppCore 동작으로 자동 감지 계약을 검증한다."""

from pathlib import Path
from queue import Empty, Queue
import os
import shutil
import sys
from threading import Event, Thread
from time import monotonic

import pytest

from my_video_manager.folder_watch import AUTOMATIC_DETECTION_KEY, MAX_BATCH_WAIT_SECONDS, folder_snapshot
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
    if operation == "start":
        with pytest.raises(OSError):
            service.start()
        assert watcher.callback is None and watcher.stops >= 1
    else:
        service.start()
        other = video_file(tmp_path / "other")
        core.add_watched_folder(other.parent)
        assert {folder.path for folder in core.watched_folders()} == {path.parent, other.parent}
        assert service.failed_folders
        assert watcher.callback is not None
    watcher.fail = False
    if operation == "start":
        service.start()
    else:
        core.add_watched_folder(other.parent)
        assert not service.failed_folders
    watcher.emit(path.parent)
    time.advance(6)
    assert batches == [(path.parent,)]
    service.stop()


def test_locked_file_waits_and_restarts_stabilization_before_delivery(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    locked, checked = True, []

    def ready(candidate):
        checked.append(candidate)
        return not locked

    service, watcher, time, batches = watch(core, ready=ready)
    watcher.emit(path.parent)
    time.advance(11)
    assert checked == [path, path]
    assert batches == []
    locked = False
    time.advance(4)
    assert batches == []
    time.advance(1)
    assert batches == [(path.parent,)]
    # 직전 전달 때와 서명이 같은 파일은 다시 열지 않는다.
    checked.clear()
    watcher.emit(path.parent)
    time.advance(6)
    assert checked == []
    service.stop()


def test_remove_folder_still_regroups_when_watcher_update_fails(core, tmp_path, caplog):
    first = video_file(tmp_path / "a", "Class 1.mkv", b"a")
    video_file(first.parent, "Class 2.mkv", b"b")
    other = video_file(tmp_path / "b", "Other 1.mkv", b"a")
    video_file(other.parent, "Other 2.mkv", b"c")
    for folder in (first.parent, other.parent):
        core.add_watched_folder(folder)
    core.scan()
    video = next(video for video in core.videos() if len(video.locations) == 2)
    assert core.series_for_video(video.id).name == "Class"

    class Watcher(FakeWatcher):
        def update(self, folders):
            if len(folders) < 2:
                raise OSError("cannot update")
            super().update(folders)

    service = core.create_folder_watch(lambda _: None, watcher=Watcher())
    try:
        service.start()
        core.remove_watched_folder(first.parent)
        assert core.series_for_video(video.id).name == "Other"
        assert [folder.path for folder in core.watched_folders()] == [other.parent]
        assert first.parent in service.failed_folders
        assert len(caplog.records) == 1 and caplog.records[0].exc_info is None
    finally:
        service.stop()


def test_final_stat_recheck_detects_changes_even_with_stale_directory_signature(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    stale = folder_snapshot((path.parent,))
    use_stale = True
    service, watcher, time, batches = watch(
        core, snapshot=lambda folders: stale if use_stale else folder_snapshot(folders), ready=lambda _: True)
    watcher.emit(path.parent)
    time.advance(4)
    path.write_bytes(b"changed while the directory cache stayed stale")
    time.advance(3)
    assert batches == []
    use_stale = False
    time.advance(6)
    assert batches == [(path.parent,)]
    service.stop()


def test_inaccessible_descendant_is_stable_and_does_not_block_batch(core, tmp_path, monkeypatch):
    path = video_file(tmp_path / "watched")
    locked = path.parent / "locked"
    locked.mkdir()
    core.add_watched_folder(path.parent)
    scandir = os.scandir

    def denied(directory):
        if Path(directory) == locked:
            raise PermissionError("denied child")
        return scandir(directory)

    monkeypatch.setattr(os, "scandir", denied)
    assert folder_snapshot((path.parent,))[locked] is None
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    time.advance(6)
    assert batches == [(path.parent,)]
    result = core.scan(folders=batches[0])
    assert result.added == 1
    assert any(issue.path == locked and issue.failed for issue in result.issues)
    service.stop()


@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_inaccessible_requested_folder_delivers_with_other_folder(core, tmp_path, monkeypatch, error_type):
    path = video_file(tmp_path / "watched")
    other = video_file(tmp_path / "other", content=b"other")
    core.add_watched_folder(path.parent)
    core.add_watched_folder(other.parent)
    scandir = os.scandir
    locked = True

    def denied(directory):
        if locked and Path(directory) == path.parent:
            raise error_type("denied root")
        return scandir(directory)

    monkeypatch.setattr(os, "scandir", denied)
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent, other.parent)
    time.advance(6)
    assert len(batches) == 1 and set(batches[0]) == {path.parent, other.parent}
    assert folder_snapshot((path.parent,))[path.parent] is None
    result = core.scan(folders=batches[0])
    assert result.added == 1
    assert any(issue.path == path.parent and issue.failed for issue in result.issues)
    locked = False
    watcher.emit(path.parent)
    time.advance(6)
    assert batches[-1] == (path.parent,)
    assert core.scan(folders=batches[-1]).added == 1
    service.stop()


def test_snapshot_adapter_errors_have_bounded_retry(core, tmp_path, caplog):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)

    def failed(_):
        raise PermissionError("adapter cannot enumerate")

    service, watcher, time, batches = watch(core, snapshot=failed)
    watcher.emit(path.parent)
    time.advance(12)
    assert batches == [(path.parent,)]
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None
    service.stop()


def test_polling_uses_directory_metadata_and_fresh_stat_only_before_delivery(core, tmp_path, monkeypatch):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    original_stat, calls = os.stat, []

    def counted(candidate, **kwargs):
        if Path(candidate) == path:
            calls.append(candidate)
        return original_stat(candidate, **kwargs)

    monkeypatch.setattr(os, "stat", counted)
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    time.advance(5)
    assert calls == [] and batches == []
    time.advance(1)
    assert calls == [path] and batches == [(path.parent,)]
    service.stop()


@pytest.mark.parametrize("busy_kind", ["growing", "locked"])
def test_batch_deadline_delivers_stable_folder_and_keeps_busy_folder(core, tmp_path, busy_kind):
    movie = video_file(tmp_path / "movies")
    growing = video_file(tmp_path / "recordings", "obs.mkv", b"recording")
    for folder in (movie.parent, growing.parent):
        core.add_watched_folder(folder)
    busy = True
    service, watcher, time, batches = watch(
        core, ready=lambda path: not (busy and busy_kind == "locked" and path == growing))
    watcher.emit(movie.parent, growing.parent)
    for second in range(int(MAX_BATCH_WAIT_SECONDS) - 1):
        if busy_kind == "growing":
            growing.write_bytes(b"x" * (second + 1))
        time.advance(1)
    assert batches == []
    for second in range(3):
        if busy_kind == "growing":
            growing.write_bytes(b"y" * (100 + second))
        time.advance(1)
    assert batches == [(movie.parent,)]
    assert core.scan(folders=batches[0]).added == 1
    busy = False
    time.advance(6)
    assert batches == [(movie.parent,), (growing.parent,)]
    assert core.scan(folders=batches[1]).added == 1
    service.stop()


def test_partial_batch_delivery_failure_retries_without_losing_pending_folder(core, tmp_path):
    movie = video_file(tmp_path / "movies")
    locked = video_file(tmp_path / "recordings", "obs.mkv")
    for folder in (movie.parent, locked.parent):
        core.add_watched_folder(folder)
    attempts, delivered = [], []
    busy = True

    def deliver(batch):
        attempts.append(batch)
        if len(attempts) == 1:
            raise OSError("queue unavailable")
        delivered.append(batch)

    service, watcher, time, _ = watch(
        core, deliver, ready=lambda path: not busy or path != locked)
    watcher.emit(movie.parent, locked.parent)
    time.advance(MAX_BATCH_WAIT_SECONDS + 3)
    assert attempts == [(movie.parent,), (movie.parent,)]
    assert delivered == [(movie.parent,)]
    busy = False
    time.advance(6)
    assert delivered == [(movie.parent,), (locked.parent,)]
    service.stop()
    time.advance(MAX_BATCH_WAIT_SECONDS)
    assert len(delivered) == 2


def test_continuous_events_cannot_extend_batch_deadline_forever(core, tmp_path):
    movie = video_file(tmp_path / "movies")
    growing = video_file(tmp_path / "recordings", "obs.mkv")
    for folder in (movie.parent, growing.parent):
        core.add_watched_folder(folder)
    service, watcher, time, batches = watch(core)
    watcher.emit(movie.parent)
    time.advance(1)  # 안정 폴더의 첫 스냅숏을 확보한다.
    for step in range(280):
        growing.write_bytes(b"x" * (step + 1))
        watcher.emit(growing.parent)
        time.advance(0.25)  # debounce보다 잦은 이벤트.
        if time.now < MAX_BATCH_WAIT_SECONDS:
            assert batches == []
    assert batches == [(movie.parent,)]
    time.advance(6)
    assert batches[-1] == (growing.parent,)
    service.stop()


def test_move_pair_stays_together_until_destination_is_ready_before_deadline(core, tmp_path):
    source = video_file(tmp_path / "source")
    target = tmp_path / "target/moved.mkv"
    target.parent.mkdir()
    for folder in (source.parent, target.parent):
        core.add_watched_folder(folder)
    core.scan()
    video, = core.videos()
    copying = True
    service, watcher, time, batches = watch(core, ready=lambda path: not copying or path != target)
    source.rename(target)
    watcher.emit(source.parent)
    time.advance(0.2)
    watcher.emit(target.parent)
    time.advance(45)
    assert batches == []
    copying = False
    time.advance(6)
    assert len(batches) == 1 and set(batches[0]) == {source.parent, target.parent}
    result = core.scan(folders=batches[0])
    assert not result.reconnected and not result.issues
    assert [location.path for location in core.video(video.id).locations] == [target]
    service.stop()


def test_growing_nonvideo_file_does_not_starve_other_folder(core, tmp_path):
    movie = video_file(tmp_path / "movies")
    download = video_file(tmp_path / "downloads", "big.part", b"")
    for folder in (movie.parent, download.parent):
        core.add_watched_folder(folder)
    service, watcher, time, batches = watch(core)
    watcher.emit(movie.parent)
    time.advance(0.2)
    watcher.emit(download.parent)
    for second in range(120):
        download.write_bytes(b"x" * second)
        time.advance(1)
    assert len(batches) == 1 and set(batches[0]) == {movie.parent, download.parent}
    assert download not in folder_snapshot((download.parent,))
    service.stop()


@pytest.mark.parametrize("suffix", [".srt", ".vtt", ".smi"])
def test_external_subtitles_are_included_in_stability(core, tmp_path, suffix):
    path = video_file(tmp_path / "watched", "video" + suffix)
    core.add_watched_folder(path.parent)
    service, watcher, time, batches = watch(core)
    watcher.emit(path.parent)
    time.advance(4)
    path.write_bytes(b"subtitle copying is not complete yet")
    time.advance(4)
    assert batches == []
    time.advance(2)
    assert batches == [(path.parent,)]
    service.stop()


def test_real_missing_root_does_not_disable_healthy_roots(core, tmp_path):
    healthy = tmp_path / "healthy"
    missing = tmp_path / "missing"
    for root in (healthy, missing):
        root.mkdir()
        core.add_watched_folder(root)
    missing.rmdir()
    events = Queue()
    adapter = WatchdogFolderWatcher()
    service = core.create_folder_watch(events.put, watcher=adapter, debounce_seconds=0.05,
                                       stable_seconds=0.2, poll_seconds=0.05)
    try:
        service.start()
        assert adapter.failed_folders == (missing,) == service.failed_folders
        video_file(healthy)
        assert events.get(timeout=10) == (healthy,)
        added = tmp_path / "added"
        added.mkdir()
        core.add_watched_folder(added)
        video_file(added)
        assert events.get(timeout=10) == (added,)
        core.set_automatic_detection_enabled(False)
        core.set_automatic_detection_enabled(True)
        video_file(healthy, "again.mkv")
        assert events.get(timeout=10) == (healthy,)
        core.remove_watched_folder(missing)
        assert not service.failed_folders
    finally:
        service.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CopyFileExW 공유 모드 검증")
@pytest.mark.parametrize("overwrite", [False, True])
def test_real_copyfileex_waits_for_copy_completion(core, tmp_path, overwrite):
    import ctypes
    from ctypes import wintypes

    source = tmp_path / "source.mkv"
    source.write_bytes(b"x" * (4 * 1024 * 1024))
    watched = tmp_path / "watched"
    watched.mkdir()
    core.add_watched_folder(watched)
    copying, release, finished = Event(), Event(), Event()
    events, results = Queue(), []
    progress_type = ctypes.WINFUNCTYPE(
        wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong,
        ctypes.c_longlong, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        wintypes.HANDLE, wintypes.LPVOID)

    @progress_type
    def progress(total, transferred, *args):
        if transferred < total:
            copying.set()
            release.wait(10)
        return 0

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    copy_file = kernel.CopyFileExW
    copy_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, progress_type,
                         wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL), wintypes.DWORD]
    copy_file.restype = wintypes.BOOL

    def copy():
        results.append(bool(copy_file(str(source), str(watched / "copy.mkv"), progress, None, None, 0)))
        finished.set()

    service = core.create_folder_watch(lambda batch: events.put((batch, finished.is_set())),
                                       debounce_seconds=0.02, stable_seconds=0.1, poll_seconds=0.02)
    worker = Thread(target=copy)
    try:
        service.start()
        if overwrite:
            (watched / "copy.mkv").write_bytes(b"y" * (4 * 1024 * 1024))
            assert events.get(timeout=10)[0] == (watched,)
        worker.start()
        assert copying.wait(10)
        # 서명 안정화보다 긴 시간 동안 실제 쓰기 핸들을 연 채 멈춘다.
        with pytest.raises(Empty):
            events.get(timeout=0.6)
        release.set()
        worker.join(10)
        assert not worker.is_alive() and results == [True]
        batch, completed = events.get(timeout=10)
        assert completed and batch == (watched,)
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(10)
        service.stop()
