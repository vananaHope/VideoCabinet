from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import threading

import pytest

from my_video_manager import scan_prefetch
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library import ScanIssue, ScanResult
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class Media:
    def __init__(self):
        self.reads = []
        self.duration = 100

    def read(self, path):
        self.reads.append(path)
        if path.suffix in (".srt", ".txt"):
            return None
        return MediaInfo(self.duration, "gif" if path.suffix == ".gif" else "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Transcriber:
    def transcribe(self, path, spoken_language, *, cancellation, progress=None):
        return TranscriberResult("en", (TranscriptSegment(1, 3, "remember this"),))


def open_core(database, media=None):
    return AppCore(media=media or Media(), clock=lambda: NOW, database=database, transcriber=Transcriber())


@pytest.fixture
def core(tmp_path):
    return open_core(tmp_path / "data/library.sqlite3")


def test_add_file_distinguishes_missing_return_from_unchanged_registration(core, tmp_path):
    path = video_file(tmp_path / "videos")
    core.add_file(path)
    video, = core.videos()
    unchanged = core.add_file(path)
    assert unchanged.issues[0].message == "이미 등록된 영상입니다."
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert core.add_file(path).issues[0].message == "이미 등록된 영상입니다."

    core.add_watched_folder(path.parent)
    moved = path.with_name("moved.mkv")
    path.rename(moved)
    result = core.scan()
    assert result.issues == ()
    assert core.video(video.id).locations[0].path == moved
    moved.unlink()
    core.scan()
    moved.write_bytes(b"original video")
    result = core.scan()
    assert [(issue.path, issue.message) for issue in result.issues] == [
        (moved, "파일 없음이던 영상을 다시 찾았습니다.")]
    path = moved
    contents = path.read_bytes()
    path.unlink()
    core.scan()
    assert core.video(video.id).missing
    path.write_bytes(contents)
    returned = core.add_file(path)
    assert returned.added == 0
    assert returned.issues[0].message == "파일 없음이던 영상을 다시 찾았습니다."
    assert not returned.issues[0].failed
    assert not core.video(video.id).missing
    assert core.add_file(path).issues[0].message == "이미 등록된 영상입니다."


def video_file(folder, name="video.mkv", content=b"original video"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    return path


def record(core, video_id):
    core.switch_to(video_id)
    core.playback.report(20)
    core.execute_highlight_command(core.command_for_key("Insert"))
    highlight, = core.highlights(video_id)
    core.update_highlight(highlight.id, start=20, end=None, note="기억할 장면")
    core.add_video_tag(video_id, "영상 기록")
    core.add_highlight_tag(highlight.id, "하이라이트 기록")
    core.playback.end()
    core.request_subtitles(video_id)
    core.process_next_subtitle()
    core.rename_video(video_id, "직접 정한 제목")


def records(core, video_id):
    return (core.viewings(video_id), core.highlights(video_id), core.transcript(video_id),
            core.series_for_video(video_id), core.video_tags(video_id),
            tuple(core.highlight_tags(h.id) for h in core.highlights(video_id)))


def test_move_rename_missing_return_keeps_identity_and_all_records(core, tmp_path):
    first = video_file(tmp_path / "a", "수업 1강.mkv")
    second = video_file(tmp_path / "a", "수업 2강.mkv", b"second")
    destination = tmp_path / "b"
    destination.mkdir()
    core.add_watched_folder(first.parent)
    core.add_watched_folder(destination)
    core.scan()
    video = core.videos()[0]
    series, = core.series()
    core.update_series(series.id, name="내 수업", video_ids=tuple(reversed(series.video_ids)))
    record(core, video.id)
    expected = records(core, video.id)
    moved = destination / "다른 이름.mkv"
    first.rename(moved)
    assert core.scan().added == 0
    current = next(v for v in core.videos() if v.id == video.id)
    assert current.title == "직접 정한 제목"
    assert [loc.path for loc in current.locations] == [moved]
    assert records(core, video.id) == expected
    outside = tmp_path / "outside.mkv"
    moved.rename(outside)
    core.scan()
    assert next(v for v in core.videos() if v.id == video.id).missing
    assert records(core, video.id) == expected
    with pytest.raises(ValueError, match="파일 없음"):
        core.switch_to(video.id)
    with pytest.raises(ValueError, match="파일 없음"):
        core.request_subtitles(video.id)
    assert core.subtitle_queue() == ()
    outside.rename(moved)
    assert core.scan().added == 0
    core = open_core(core.database)
    assert not next(v for v in core.videos() if v.id == video.id).missing
    assert records(core, video.id) == expected
    assert second.is_file()


@pytest.mark.parametrize("missing_count", [1, 2, 3])
def test_automatic_series_keeps_missing_members_and_order(core, tmp_path, missing_count):
    paths = [video_file(tmp_path / "series", f"수업 {i}강.mkv", str(i).encode()) for i in range(1, 4)]
    core.add_watched_folder(paths[0].parent)
    core.scan()
    expected = core.series()
    saved = [p.read_bytes() for p in paths]
    for path in paths[:missing_count]:
        path.unlink()
    for _ in range(2):
        core.scan()
        assert core.series() == expected
    for path, content in zip(paths, saved):
        path.write_bytes(content)
    core.scan()
    assert core.series() == expected


def test_remove_folder_drops_only_its_locations_and_never_files(core, tmp_path):
    first = video_file(tmp_path / "a")
    copy = video_file(tmp_path / "b")
    unique = video_file(first.parent, "unique.mkv", b"unique")
    for folder in (first.parent, copy.parent):
        core.add_watched_folder(folder)
    core.scan()
    core.remove_watched_folder(first.parent)
    assert [f.path for f in core.watched_folders()] == [copy.parent]
    assert {v.title: v.missing for v in core.videos()} == {"unique": True, "video": False}
    assert [loc.path for v in core.videos() for loc in v.locations] == [copy]
    core.remove_watched_folder(copy.parent)
    assert all(v.missing for v in core.videos())
    assert all(p.is_file() for p in (first, copy, unique))
    assert core.scan().added == 0
    assert all(v.missing for v in core.videos())
    core.add_watched_folder(first.parent)
    core.scan()
    assert all(not v.missing for v in core.videos())


def test_remove_overlapping_folder_also_removes_direct_locations_until_scan(core, tmp_path):
    path = video_file(tmp_path / "root" / "nested")
    core.add_watched_folder(path.parent.parent)
    core.add_watched_folder(path.parent)
    core.add_file(path)
    core.remove_watched_folder(path.parent.parent)
    assert core.videos()[0].missing
    core.scan()
    assert not core.videos()[0].missing


def test_direct_file_is_checked_after_restart_and_reconnected_only_if_same(core, tmp_path):
    path = video_file(tmp_path / "outside")
    assert core.add_file(path).added == 1
    video, = core.videos()
    record(core, video.id)
    expected = records(core, video.id)
    renamed = path.with_name("renamed.mkv")
    path.rename(renamed)
    core = open_core(core.database)
    core.scan()
    assert core.videos()[0].missing
    wrong = video_file(tmp_path / "outside", "different.mkv", b"different")
    with pytest.raises(ValueError, match="다른 내용"):
        core.reconnect_video(video.id, wrong)
    assert core.videos()[0].missing
    assert len(core.videos()) == 1
    core.reconnect_video(video.id, renamed)
    assert core.playback_location(video.id).path == renamed
    assert records(core, video.id) == expected
    assert core.watched_folders() == ()


def test_excluded_fingerprint_survives_copy_rename_restart_and_restore(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    core.scan()
    video, = core.videos()
    record(core, video.id)
    expected = records(core, video.id)
    core.exclude_video(video.id)
    assert core.videos() == ()
    assert core.excluded_videos()[0].excluded
    with pytest.raises(ValueError, match="제외"):
        core.request_subtitles(video.id)
    core = open_core(core.database)
    copy = path.with_name("copy.mkv")
    shutil.copyfile(path, copy)
    path.rename(path.with_name("renamed.mkv"))
    assert core.scan().added == 0
    assert core.videos() == ()
    assert len(core.excluded_videos()[0].locations) == 2
    assert core.add_file(copy).added == 0
    core.restore_video(video.id)
    assert core.excluded_videos() == ()
    assert core.videos()[0].id == video.id
    assert records(core, video.id) == expected
    assert sorted(p.name for p in copy.parent.iterdir()) == ["copy.mkv", "renamed.mkv"]


def test_excluded_automatic_series_survives_scan(core, tmp_path):
    for i in (1, 2):
        path = video_file(tmp_path / "watched", f"show {i}화.mkv", str(i).encode())
    core.add_watched_folder(path.parent)
    core.scan()
    expected = core.series()
    for video in core.videos():
        core.exclude_video(video.id)
    core.scan()
    assert core.series()[0].video_ids == ()
    for video in core.excluded_videos():
        core.restore_video(video.id)
    assert core.series() == expected


@pytest.mark.parametrize("duration, added", [(59.99, 0), (60, 1), (60.01, 1)])
def test_default_minimum_boundary(core, tmp_path, duration, added):
    media = Media()
    media.duration = duration
    core = open_core(core.database, media)
    path = video_file(tmp_path / "watched")
    assert core.minimum_duration == 60
    assert core.add_file(path).added == added


def test_minimum_setting_persists_rechecks_short_files_and_keeps_registered(core, tmp_path):
    media = Media()
    media.duration = 20
    core = open_core(core.database, media)
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    assert core.scan().added == 0
    assert core.scan().added == 0
    assert len(media.reads) == 1
    core.set_minimum_duration(10)
    core = open_core(core.database, media)
    assert core.minimum_duration == 10
    assert core.scan().added == 1
    core.set_minimum_duration(200)
    core.scan()
    copy = path.with_name("copy.mkv")
    shutil.copyfile(path, copy)
    core.scan()
    assert len(core.videos()[0].locations) == 2
    assert core.settings.get("library.min_duration_seconds") == 200


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_minimum_does_not_change_setting(core, value):
    with pytest.raises(ValueError):
        core.set_minimum_duration(value)
    assert core.minimum_duration == 60


def test_gif_is_never_registered_even_without_minimum(core, tmp_path):
    core.set_minimum_duration(0)
    path = video_file(tmp_path / "watched", "animation.gif")
    assert core.add_file(path).added == 0
    assert core.videos() == ()


def test_cached_short_copy_attaches_after_same_video_was_registered_elsewhere(core, tmp_path):
    media = Media()
    media.duration = 20
    core = open_core(core.database, media)
    a = video_file(tmp_path / "watched")
    b = video_file(tmp_path / "outside")
    core.add_watched_folder(a.parent)
    core.scan()
    core.set_minimum_duration(0)
    core.add_file(b)
    core.set_minimum_duration(60)
    core.scan()
    assert {loc.path for loc in core.videos()[0].locations} == {a, b}


def test_unchanged_nonvideo_and_registered_locations_skip_reading_after_restart(core, tmp_path):
    media = Media()
    path = video_file(tmp_path / "watched")
    document = video_file(path.parent, "subtitle.srt", b"subtitle")
    core = open_core(core.database, media)
    core.add_watched_folder(path.parent)
    core.scan()
    assert set(media.reads) == {path, document}
    media.reads.clear()
    core = open_core(core.database, media)
    core.scan()
    core.scan()
    assert media.reads == []


@pytest.mark.parametrize("stage", ["read", "capture"])
@pytest.mark.parametrize("failure", [ValueError, RuntimeError, TimeoutError, PermissionError])
def test_scan_retries_failed_files_with_unchanged_signature(tmp_path, stage, failure):
    class FailingMedia(Media):
        failing = True

        def read(self, path):
            info = super().read(path)
            if self.failing and stage == "read":
                raise failure("media failed")
            return info

        def capture(self, path, destination, seconds):
            if self.failing and stage == "capture":
                raise failure("media failed")
            super().capture(path, destination, seconds)

    media = FailingMedia()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    signature = path.stat()
    for _ in range(2):
        assert core.scan() == ScanResult(0, (ScanIssue(path, "media failed"),))
        assert core.videos() == ()
    media.failing = False
    assert core.scan() == ScanResult(1, ())
    assert media.reads == [path, path, path]
    assert core.videos()[0].locations[0].path == path
    assert path.stat().st_mtime_ns == signature.st_mtime_ns
    assert core.scan() == ScanResult(0, ())
    assert len(media.reads) == 3


@pytest.mark.parametrize("workers", [1, 4])
def test_scan_registers_final_content_changed_before_its_registration(tmp_path, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    final_content = b"finished copying the second video"
    paths = [video_file(tmp_path / "watched", name, name.encode())
             for name in ("a.mkv", "b.mkv")]
    changed = []
    # 검사 순서상 첫 파일을 읽을 때 다음 파일의 복사가 끝난다. 동시 실행에서는 다음 파일의
    # 미리 읽기·캡처가 옛 내용으로 끝난 뒤 바꿔, 그 값을 버리고 최종 내용으로 등록하는지 본다.
    first, second = (paths[0].parent / entry.name for entry in os.scandir(paths[0].parent))
    second_captured = threading.Event()

    class ChangingMedia(Media):
        def read(self, path):
            if path == first and not changed:
                assert workers == 1 or second_captured.wait(10)
                second.write_bytes(final_content)
                changed.append(second)
            return super().read(path)

        def capture(self, path, destination, seconds):
            super().capture(path, destination, seconds)
            if path == second:
                second_captured.set()

    core = open_core(tmp_path / "data/library.sqlite3", ChangingMedia())
    core.add_watched_folder(paths[0].parent)
    assert core.scan() == ScanResult(2, ())
    video, = (video for video in core.videos()
              if video.locations[0].path == changed[0])
    digest = hashlib.sha256(str(len(final_content)).encode("ascii") + final_content * 3)
    assert video.fingerprint == f"v1:{len(final_content)}:{digest.hexdigest()}"
    assert video.thumbnail.is_file()
    assert sorted(path.name for path in video.thumbnail.parent.iterdir()) == sorted(
        video.thumbnail.name for video in core.videos())


@pytest.mark.skipif(os.name != "nt", reason="Windows directory entry metadata cache")
def test_scan_registers_file_changed_through_hard_link_before_scan(tmp_path):
    core = open_core(tmp_path / "data/library.sqlite3")
    path = video_file(tmp_path / "watched", content=b"a" * 1000)
    core.add_watched_folder(path.parent)
    other = tmp_path / "other.mkv"
    os.link(path, other)
    with other.open("ab") as target:
        target.write(b"b" * 5000)
    with os.scandir(path.parent) as entries:
        cached_size = next(entries).stat().st_size
    if cached_size != 1000:
        pytest.skip("Filesystem did not retain stale directory entry metadata")
    assert core.scan() == ScanResult(1, ())
    video, = core.videos()
    final_content = b"a" * 1000 + b"b" * 5000
    digest = hashlib.sha256(b"6000" + final_content * 3)
    assert video.fingerprint == f"v1:6000:{digest.hexdigest()}"
    assert video.locations[0].path == path


@pytest.mark.parametrize("stage", ["read", "capture"])
def test_scan_rejects_file_changed_during_registration_and_retries(tmp_path, stage):
    class ChangingMedia(Media):
        changing = True

        def read(self, path):
            info = super().read(path)
            if self.changing and stage == "read":
                path.write_bytes(b"changed during read")
            return info

        def capture(self, path, destination, seconds):
            super().capture(path, destination, seconds)
            if self.changing and stage == "capture":
                path.write_bytes(b"changed during capture")

    media = ChangingMedia()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    result = core.scan()
    assert result.added == 0 and not result.reconnected
    assert len(result.issues) == 1
    assert result.issues[0].path == path and result.issues[0].failed
    assert core.videos() == ()
    media.changing = False
    assert core.scan() == ScanResult(1, ())
    assert core.videos()[0].locations[0].path == path


def test_cached_short_copy_attaches_to_video_registered_during_same_scan(core, tmp_path):
    media = Media()
    core = open_core(core.database, media)
    direct = video_file(tmp_path / "outside", content=b"different")
    core.add_file(direct)
    old, = core.videos()
    short = video_file(tmp_path / "watched", content=b"short")
    core.add_watched_folder(short.parent)
    media.duration = 20
    assert core.scan() == ScanResult(0, ())
    direct.write_bytes(b"short")
    media.duration = 100
    media.reads.clear()
    assert core.scan() == ScanResult(1, ())
    assert core.video(old.id).missing
    new, = (video for video in core.videos() if video.id != old.id)
    assert {location.path for location in new.locations} == {short, direct}
    assert media.reads == [direct]


def test_unchanged_scan_database_work_does_not_grow_per_file(core, tmp_path, monkeypatch):
    media = Media()
    core = open_core(core.database, media)
    folder = tmp_path / "watched"
    video_file(folder)
    core.add_watched_folder(folder)
    core.scan()
    connect = sqlite3.connect
    connections, statements = [], []

    def counted_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(1)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", counted_connect)
    assert core.scan() == ScanResult(0, ())
    one_file_connections = len(connections)
    one_file_settings = sum("FROM settings" in sql for sql in statements)
    for i in range(40):
        video_file(folder, f"video-{i}.mkv", str(i).encode())
        video_file(folder, f"document-{i}.txt")
    core.scan()
    media.duration = 20
    for i in range(40):
        video_file(folder, f"short-{i}.mkv", f"short-{i}".encode())
    core.scan()
    core.exclude_video(core.videos()[0].id)
    connections.clear()
    statements.clear()
    media.reads.clear()
    assert core.scan() == ScanResult(0, ())
    assert media.reads == []
    assert len(core.excluded_videos()) == 1
    # 공개 scan의 SQLite 경계 비용을 비교한다. 캐시 구조나 private 호출에는 의존하지 않는다.
    assert len(connections) <= one_file_connections + 1  # excluded_videos 조회 1회 포함
    assert sum("FROM settings" in sql for sql in statements) == one_file_settings


def test_inaccessible_folder_preserves_cached_checks_until_successful_scan(core, tmp_path, monkeypatch):
    media = Media()
    core = open_core(core.database, media)
    path = video_file(tmp_path / "watched/nested", "document.txt")
    core.add_watched_folder(path.parent.parent)
    core.scan()
    scandir = os.scandir

    def denied(directory):
        if Path(directory) == path.parent:
            raise PermissionError("folder denied")
        return scandir(directory)

    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", denied)
        assert core.scan() == ScanResult(0, (ScanIssue(path.parent, "folder denied"),))
    assert core.scan() == ScanResult(0, ())
    assert media.reads == [path]


def test_registered_location_permission_failure_is_not_missing(core, tmp_path, monkeypatch):
    path = video_file(tmp_path / "outside")
    core.add_file(path)
    video, = core.videos()
    original_stat = Path.stat

    def denied(file, *args, **kwargs):
        if file == path:
            raise PermissionError("file denied")
        return original_stat(file, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", denied)
        result = core.scan()
        assert ScanIssue(path, "file denied") in result.issues
        assert not core.video(video.id).missing
    assert core.scan() == ScanResult(0, ())
    assert core.video(video.id) == video


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_changed_registered_file_becomes_new_video_and_rechecks_nonvideo(core, tmp_path, change):
    media = Media()
    core = open_core(core.database, media)
    path = video_file(tmp_path / "watched", content=b"aaa")
    document = video_file(path.parent, "subtitle.srt", b"aaa")
    core.add_watched_folder(path.parent)
    core.scan()
    old, = core.videos()
    record(core, old.id)
    expected = records(core, old.id)
    for file in (path, document):
        before = file.stat()
        file.write_bytes(b"bbbb" if change == "size" else b"bbb")
        os.utime(file, ns=(before.st_atime_ns, before.st_mtime_ns if change == "size" else before.st_mtime_ns + 10000000))
    media.reads.clear()
    assert core.scan().added == 1
    assert set(media.reads) == {path, document}
    assert next(v for v in core.videos() if v.id == old.id).missing
    assert records(core, old.id) == expected
    assert core.playback_location(next(v.id for v in core.videos() if v.id != old.id)).path == path


def test_replaced_with_nonvideo_or_failed_read_never_retains_wrong_location(core, tmp_path):
    class ChangingMedia(Media):
        def read(self, path):
            if path.read_bytes() == b"not video":
                return None
            if path.read_bytes() == b"broken":
                raise ValueError("손상")
            return super().read(path)
    core = open_core(core.database, ChangingMedia())
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    core.scan()
    for content in (b"not video", b"original video", b"broken"):
        path.write_bytes(content)
        core.scan()
        assert core.videos()[0].missing == (content != b"original video")


def test_playback_falls_back_to_existing_copy_and_missing_requests_fail_without_scan(core, tmp_path):
    a = video_file(tmp_path / "outside", "a.mkv")
    b = video_file(a.parent, "b.mkv")
    core.add_file(a)
    core.add_file(b)
    video, = core.videos()
    a.unlink()
    assert core.playback_location(video.id).path == b
    b.unlink()
    with pytest.raises(ValueError, match="파일 없음"):
        core.request_subtitles(video.id)
    assert core.videos()[0].missing


def test_empty_title_is_rejected(core, tmp_path):
    core.add_file(video_file(tmp_path / "outside"))
    video, = core.videos()
    with pytest.raises(ValueError):
        core.rename_video(video.id, "  ")
    assert core.videos()[0].title == video.title


def test_series_edit_hides_excluded_but_preserves_its_original_slot(core, tmp_path):
    paths = [video_file(tmp_path / "series", f"수업 {i}강.mkv", str(i).encode()) for i in (1, 2, 3)]
    core.add_watched_folder(paths[0].parent)
    core.scan()
    series, = core.series()
    a, excluded, c = series.video_ids
    core.exclude_video(excluded)
    visible, = core.series()
    assert visible.video_ids == (a, c)
    assert core.series_for_video(excluded) is None
    edited = core.update_series(series.id, name="편집한 수업", video_ids=visible.video_ids)
    assert edited.video_ids == (a, c)
    core = open_core(core.database)
    core.scan()
    core.restore_video(excluded)
    assert core.series()[0].video_ids == (a, excluded, c)


@pytest.mark.parametrize("in_series", [True, False])
def test_navigation_skips_missing_and_excluded_in_both_directions(core, tmp_path, in_series):
    paths = [video_file(tmp_path / "videos", f"video-{name}.mkv", name.encode()) for name in ("a", "b", "c", "d")]
    for path in paths:
        core.add_file(path)
    ids = tuple(v.id for v in core.videos())
    a, missing, excluded, d = ids
    if in_series:
        core.create_series("수업", ids)
    paths[1].unlink()
    core.scan()
    core.exclude_video(excluded)
    assert core.adjacent_video(a, ids, forward=True) == d
    assert core.adjacent_video(d, ids, forward=False) == a
    assert core.adjacent_video(a, ids, forward=False) is None
    assert core.adjacent_video(d, ids, forward=True) is None
    core.exclude_video(d)
    assert core.adjacent_video(a, ids, forward=True) is None
    if in_series:
        assert core.series()[0].video_ids == (a, missing)


def legacy_database(tmp_path, version, media_format="matroska"):
    # 이전 릴리스의 저장 형식을 독립적으로 재현한다. 검증은 AppCore 공개 동작으로 한다.
    path = video_file(tmp_path / "outside", content=b"old")
    digest = hashlib.sha256(b"3" + b"old" * 3).hexdigest()
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as db:
        db.executescript('''
            CREATE TABLE watched_folders(path TEXT PRIMARY KEY);
            CREATE TABLE videos(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL, duration REAL NOT NULL, format TEXT NOT NULL,
                thumbnail TEXT NOT NULL, registered_at TEXT NOT NULL);
            CREATE TABLE locations(path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id));
            CREATE TABLE highlights(id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                start REAL NOT NULL, end REAL, note TEXT);
            CREATE TABLE viewings(id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                duration REAL NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                ended_at TEXT, intervals TEXT NOT NULL, last_position REAL);
            CREATE TABLE transcripts(video_id INTEGER PRIMARY KEY REFERENCES videos(id), id TEXT NOT NULL UNIQUE,
                spoken_language TEXT NOT NULL, language_specified INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE transcript_lines(id TEXT PRIMARY KEY, transcript_id TEXT NOT NULL REFERENCES transcripts(id),
                ordinal INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL);
            CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT NOT NULL, folder TEXT,
                title_template TEXT, edited INTEGER NOT NULL DEFAULT 0, UNIQUE(folder, title_template));
            CREATE TABLE series_videos(series_id INTEGER NOT NULL REFERENCES series(id),
                video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id), position INTEGER NOT NULL,
                PRIMARY KEY(series_id, position));
            CREATE TABLE series_overrides(video_id INTEGER PRIMARY KEY REFERENCES videos(id));
            CREATE TABLE tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE);
            CREATE TABLE video_tags(video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(video_id, tag_id));
            CREATE TABLE highlight_tags(highlight_id INTEGER NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(highlight_id, tag_id));
            INSERT INTO highlights VALUES (7, 42, 10, NULL, '옛 메모');
            INSERT INTO series VALUES (3, '내 시리즈', NULL, NULL, 1);
            INSERT INTO series_videos VALUES (3, 42, 0);
            INSERT INTO series_overrides VALUES (42);
            INSERT INTO tags VALUES (1, '옛 태그', '옛 태그');
            INSERT INTO video_tags VALUES (42, 1);
            INSERT INTO highlight_tags VALUES (7, 1);
        ''')
        db.execute("INSERT INTO videos VALUES (42, ?, '옛 제목', 20, 'matroska', 'old.jpg', ?)",
                   (f"v1:3:{digest}", NOW.isoformat()))
        db.execute("INSERT INTO locations VALUES (?, 42)", (str(path),))
        db.execute("INSERT INTO watched_folders VALUES (?)", (str(path.parent),))
        db.execute("INSERT INTO viewings VALUES (5, 42, 20, ?, ?, ?, '[[0, 19]]', 19)", (NOW.isoformat(),) * 3)
        db.execute("INSERT INTO transcripts VALUES (42, 'old-transcript', 'en', 0, ?)", (NOW.isoformat(),))
        db.execute("INSERT INTO transcript_lines VALUES ('old-line', 'old-transcript', 0, 1, 3, 'old words')")
        db.execute("UPDATE videos SET format=? WHERE id=42", (media_format,))
        db.execute(f"PRAGMA user_version={version}")
    return database, path


@pytest.mark.parametrize("version", [0, 1])
def test_legacy_database_migration_preserves_records_and_reopens(tmp_path, version):
    database, path = legacy_database(tmp_path, version)
    core = open_core(database)
    video, = core.videos()
    assert video.id == 42 and video.title == "옛 제목" and video.duration == 20
    assert core.highlights(42)[0].note.text == "옛 메모"
    assert core.viewing_status(42).finished
    assert core.transcript(42).lines[0].id == "old-line"
    assert core.series_for_video(42).name == "내 시리즈"
    assert core.video_tags(42)[0].name == "옛 태그"
    assert core.highlight_tags(7) == core.video_tags(42)
    expected = records(core, 42)
    assert core.scan().added == 0  # 기존 1분 미만 영상도 기록을 보존한다.
    core = open_core(database)
    assert records(core, 42) == expected
    assert core.videos() == (video,)
    assert core.watched_folders()[0].path == path.parent
    core.exclude_video(42)
    assert core.excluded_videos()[0].id == 42


@pytest.mark.parametrize("state", ["completed", "queued", "held"])
def test_v1_translation_records_survive_migration_identity_changes_and_resume(tmp_path, state):
    database, path = legacy_database(tmp_path, 1)
    retry_at = NOW + timedelta(minutes=15)
    # 번역 기능이 추가된 v1 저장 형식: 완성본과 재번역 진행 중인 묶음을 함께 보존한다.
    with sqlite3.connect(database) as db:
        db.executescript('''
            CREATE TABLE translation_lines (
                line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                text TEXT NOT NULL);
            CREATE TABLE translation_queue (
                id TEXT PRIMARY KEY, video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                requested_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                retry_at TEXT, error_kind TEXT, error_detail TEXT);
            CREATE TABLE translation_targets (
                queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                line_id TEXT NOT NULL REFERENCES transcript_lines(id) ON DELETE CASCADE,
                text TEXT, PRIMARY KEY(queue_id, line_id));
            CREATE TABLE translation_cli_backoff (cli TEXT PRIMARY KEY, retry_at TEXT NOT NULL);
            CREATE TABLE translation_limit_attempts (
                queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                cli TEXT NOT NULL, attempts INTEGER NOT NULL, PRIMARY KEY(queue_id, cli));
            INSERT INTO transcript_lines VALUES ('old-line-2', 'old-transcript', 1, 4, 6, 'more words');
            INSERT INTO translation_lines VALUES ('old-line', '옛 번역 첫 줄'), ('old-line-2', '옛 번역 둘째 줄');
        ''')
        if state != "completed":
            db.execute("INSERT INTO translation_queue VALUES ('old-queue', 42, 'old-transcript', ?, ?, ?, ?, ?)",
                       (NOW.isoformat(), state, retry_at.isoformat() if state == "held" else None,
                        "usage_limit" if state == "held" else None, "이전 한도 응답" if state == "held" else None))
            db.execute("INSERT INTO translation_targets VALUES ('old-queue', 'old-line', '저장된 새 번역'), "
                       "('old-queue', 'old-line-2', NULL)")
        if state == "held":
            db.execute("INSERT INTO translation_cli_backoff VALUES ('codex', ?)", (retry_at.isoformat(),))
            db.execute("INSERT INTO translation_limit_attempts VALUES ('old-queue', 'codex', 1)")

    class Translator:
        def __init__(self):
            self.calls = []

        def translate(self, lines, spoken_language, *, cli, cancellation, model="", effort="", context=(), glossary=()):
            self.calls.append(tuple(line.id for line in lines))
            return tuple(TranslatedLine(line.id, "이어서 번역") for line in lines)

    translator, time = Translator(), [NOW]

    def reopen():
        return AppCore(media=Media(), clock=lambda: time[0], database=database, translator=translator)

    core = reopen()
    translated = core.translation(42)
    assert translated.transcript_id == "old-transcript"
    assert [(line.id, line.start, line.end, line.text) for line in translated.lines] == [
        ("old-line", 1, 3, "옛 번역 첫 줄"), ("old-line-2", 4, 6, "옛 번역 둘째 줄")]
    queue = core.translation_queue()
    if state == "completed":
        assert queue == ()
    else:
        entry, = queue
        assert (entry.id, entry.video_id, entry.state, entry.completed_lines, entry.total_lines) == (
            "old-queue", 42, state, 1, 2)
        assert entry.retry_at == (retry_at if state == "held" else None)
        assert entry.error_detail == ("이전 한도 응답" if state == "held" else None)

    moved = path.with_name("renamed.mkv")
    path.rename(moved)
    assert core.scan().added == 0
    assert core.videos()[0].id == 42
    assert core.playback_location(42).path == moved
    assert core.translation(42) == translated and core.translation_queue() == queue
    outside = tmp_path / "reconnected.mkv"
    moved.rename(outside)
    core.scan()
    assert core.videos()[0].missing
    core.exclude_video(42)
    assert core.translation(42) == translated and core.translation_queue() == queue
    core.restore_video(42)
    core.reconnect_video(42, outside)
    core = reopen()
    assert core.playback_location(42).path == outside
    assert core.translation(42) == translated and core.translation_queue() == queue
    assert translator.calls == []

    if state == "held":
        assert not core.translation_ready()
        assert core.process_next_translation() is None
        time[0] = retry_at
    if state != "completed":
        assert core.translation_ready()
        assert core.process_next_translation().state == "completed"
        assert translator.calls == [("old-line-2",)]
        assert [line.text for line in reopen().translation(42).lines] == ["저장된 새 번역", "이어서 번역"]
    assert reopen().translation_queue() == ()


@pytest.mark.parametrize("version", [0, 1])
def test_legacy_gif_is_excluded_and_user_restore_survives_scan_and_move(tmp_path, version):
    class GifMedia(Media):
        def read(self, path):
            self.reads.append(path)
            return None  # 현재 어댑터는 GIF를 비영상으로 판정한다.

    database, path = legacy_database(tmp_path, version, "gif")
    core = open_core(database, GifMedia())
    assert core.videos() == ()
    gif, = core.excluded_videos()
    assert gif.id == 42 and not gif.missing
    assert core.scan().added == 0
    assert not core.excluded_videos()[0].missing
    core.restore_video(42)
    expected = records(core, 42)
    assert core.videos()[0].id == 42
    core.scan()
    before = path.stat()
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 10000000))
    core.scan()
    assert not core.videos()[0].missing
    moved = path.with_name("renamed.gif")
    path.rename(moved)
    core = open_core(database, GifMedia())
    core.scan()
    assert core.playback_location(42).path == moved
    assert core.excluded_videos() == ()
    assert core.video_tags(42) == expected[4]
    assert core.highlights(42) == expected[1]
    assert core.transcript(42) == expected[2]


@pytest.mark.parametrize("kind, reason", [
    ("short", "최소 길이(60초) 미만"), ("gif", "영상이 아닙니다"),
    ("document", "영상이 아닙니다"), ("excluded", "제외 목록"), ("registered", "이미 등록"),
])
def test_direct_add_reports_why_no_video_was_added(core, tmp_path, kind, reason):
    media = Media()
    media.duration = 20 if kind == "short" else 100
    core = open_core(core.database, media)
    suffix = {"gif": ".gif", "document": ".txt"}.get(kind, ".mkv")
    path = video_file(tmp_path / "outside", "video" + suffix)
    if kind in ("excluded", "registered"):
        core.add_file(path)
        if kind == "excluded":
            core.exclude_video(core.videos()[0].id)
    for _ in range(2):  # 최초 판정과 캐시 사용 모두 같은 안내다.
        result = core.add_file(path)
        assert result.added == 0
        assert len(result.issues) == 1
        assert result.issues[0].path == path
        assert reason in result.issues[0].message


@pytest.mark.parametrize("remove_folder", [False, True])
def test_scan_discards_unseen_file_checks_in_its_scope(core, tmp_path, remove_folder):
    media = Media()
    core = open_core(core.database, media)
    path = video_file(tmp_path / "watched", "document.txt")
    signature = path.stat()
    core.add_watched_folder(path.parent)
    core.scan()
    assert media.reads == [path]
    path.unlink()
    if remove_folder:
        path.parent.rmdir()
    core.scan()
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"original video")
    os.utime(path, ns=(signature.st_atime_ns, signature.st_mtime_ns))
    core.scan()
    assert media.reads == [path, path]  # 사라졌다 돌아온 동일 서명도 새 판정한다.


def test_scan_keeps_file_checks_outside_its_scope(core, tmp_path):
    media = Media()
    core = open_core(core.database, media)
    path = video_file(tmp_path / "outside", "document.txt")
    core.add_file(path)
    other = tmp_path / "watched"
    other.mkdir()
    core.add_watched_folder(other)
    core.scan()
    core.add_file(path)
    assert media.reads == [path]


def test_reconnect_recalculates_automatic_series_immediately(core, tmp_path):
    a = video_file(tmp_path / "series", "수업 1강.mkv", b"a")
    video_file(a.parent, "수업 2강.mkv", b"b")
    core.add_watched_folder(a.parent)
    core.scan()
    first = core.series()[0].video_ids[0]
    moved = tmp_path / "unrelated.mkv"
    a.rename(moved)
    core.scan()
    assert core.series_for_video(first) is not None
    core.reconnect_video(first, moved)
    assert core.series_for_video(first) is None


def test_remove_folder_recalculates_using_remaining_copy_immediately(core, tmp_path):
    a = video_file(tmp_path / "a-series", "수업 1강.mkv", b"a")
    video_file(a.parent, "수업 2강.mkv", b"b")
    b = video_file(tmp_path / "b-series", "다른 1강.mkv", b"a")
    video_file(b.parent, "다른 2강.mkv", b"c")
    core.add_watched_folder(a.parent)
    core.add_watched_folder(b.parent)
    core.scan()
    first = next(v.id for v in core.videos() if len(v.locations) == 2)
    assert core.series_for_video(first).name == "수업"
    core.remove_watched_folder(a.parent)
    assert core.series_for_video(first).name == "다른"


def test_series_edit_preserves_excluded_slots_during_reorder_and_removal(core, tmp_path):
    for name in ("a", "b", "c", "d", "e"):
        core.add_file(video_file(tmp_path / "videos", name + ".mkv", name.encode()))
    a, b, c, d, e = (video.id for video in core.videos())
    series = core.create_series("수업", (a, b, c, d, e))
    core.exclude_video(b)
    core.exclude_video(d)
    core.update_series(series.id, name="편집", video_ids=(e, c))
    assert core.series()[0].video_ids == (e, c)
    core.restore_video(b)
    core.restore_video(d)
    assert core.series()[0].video_ids == (e, b, c, d)
    assert core.series_for_video(a) is None


def set_modified(path, moment):
    stamp = int(moment.timestamp()) * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def test_modified_date_uses_earliest_location_mtime_and_ignores_unknown(core, tmp_path):
    content = b"same video"
    first = video_file(tmp_path / "first", "video.mkv", content)
    second = video_file(tmp_path / "second", "copy.mkv", content)
    newer = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    older = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    set_modified(first, newer)
    set_modified(second, older)
    core.add_file(first)
    core.add_file(second)
    video, = core.videos()
    assert video.modified_at == older

    # 수정 시각을 기록하지 않은 옛 위치 행은 계산에서 뺀다.
    with sqlite3.connect(core.database) as db:
        db.execute("UPDATE locations SET mtime_ns=NULL WHERE path=?", (str(second),))
    assert core.video(video.id).modified_at == newer
    with sqlite3.connect(core.database) as db:
        db.execute("UPDATE locations SET mtime_ns=NULL WHERE path=?", (str(first),))
    assert core.video(video.id).modified_at is None

    second.unlink()
    first.unlink()
    core.scan()
    assert core.video(video.id).missing
    assert core.video(video.id).modified_at is None


def test_rescan_updates_modified_date_after_replacing_file(core, tmp_path):
    path = video_file(tmp_path / "watched")
    core.add_watched_folder(path.parent)
    core.scan()
    video, = core.videos()
    first = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    set_modified(path, first)
    core.scan()
    assert core.video(video.id).modified_at == first

    # 같은 내용이면 영상은 그대로이고 수정 시각만 새 값으로 바뀐다.
    second = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    set_modified(path, second)
    core.scan()
    assert core.video(video.id).modified_at == second

    # 내용까지 바뀌면 새 영상이 되고 새 수정 시각을 쓴다.
    third = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    path.write_bytes(b"replaced content")
    set_modified(path, third)
    core.scan()
    current = next(v for v in core.videos() if not v.missing)
    assert current.id != video.id
    assert current.modified_at == third
