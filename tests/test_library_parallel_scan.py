"""새 파일 등록의 ffprobe·지문·썸네일 동시 실행(#173)."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading

import pytest

from my_video_manager import scan_prefetch
from my_video_manager.library import Library, MediaInfo, ScanIssue, ScanResult
from my_video_manager.settings import Settings


NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


class ContentMedia:
    """파일 내용으로 판정하는 스레드 안전 가짜 미디어."""

    def __init__(self):
        self.lock = threading.Lock()
        self.captures = []
        self.reads = []
        self.broken = True

    def read(self, path):
        with self.lock:
            self.reads.append(path)
        if path.suffix == ".txt":
            return None
        content = path.read_bytes()
        if self.broken and content.startswith(b"broken"):
            raise RuntimeError(f"손상된 영상: {path.name}")
        if path.suffix == ".gif":
            return MediaInfo(3, "gif")
        return MediaInfo(20 if content.startswith(b"short") else 100, "matroska", 1920, 1080)

    def capture(self, path, destination, seconds):
        if self.broken and path.read_bytes().startswith(b"nothumb"):
            raise RuntimeError(f"썸네일 실패: {path.name}")
        with self.lock:
            self.captures.append(path.read_bytes())
        destination.write_bytes(b"thumbnail")


def open_library(root, media):
    database = root / "data/library.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    thumbnails = database.parent / "thumbnails"
    thumbnails.mkdir(exist_ok=True)

    @contextmanager
    def connect():
        db = sqlite3.connect(database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    return Library(connect, media, lambda: NOW, thumbnails, Settings(connect))


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def thumbnail_files(root, library):
    # 썸네일 폴더에는 등록된 영상이 가리키는 파일만 남아야 한다(미리 캡처 임시 파일 포함).
    videos = library.videos() + library.videos(excluded=True)
    return (sorted(path.name for path in (root / "data/thumbnails").iterdir()),
            sorted(video.thumbnail.name for video in videos))


def scan(library):
    calls = []
    result = library.scan(on_registered=lambda video_id: calls.append((video_id, threading.current_thread())))
    return result, calls


def test_scan_reads_and_captures_new_files_concurrently(tmp_path):
    # 순차 실행이면 두 번째 참가자가 오지 않아 장벽이 깨지고 해당 파일이 오류가 된다.
    reads, captures = threading.Barrier(2, timeout=10), threading.Barrier(2, timeout=10)

    class MeetingMedia(ContentMedia):
        def read(self, path):
            reads.wait()
            return super().read(path)

        def capture(self, path, destination, seconds):
            captures.wait()
            super().capture(path, destination, seconds)

    library = open_library(tmp_path, MeetingMedia())
    folder = tmp_path / "watched"
    for index in range(4):
        write(folder / f"{index}.mkv", f"video {index}".encode())
    library.add_watched_folder(folder)
    assert library.scan() == ScanResult(4, ())
    assert len(library.videos()) == 4


def test_on_registered_runs_on_scan_thread_in_registration_order(tmp_path):
    folder = tmp_path / "watched"
    for index in range(4):
        write(folder / f"{index}.mkv", f"video {index}".encode())
    names = [entry.name for entry in os.scandir(folder)]
    first, last = folder / names[0], folder / names[-1]
    last_read = threading.Event()

    class ReverseMedia(ContentMedia):
        def read(self, path):
            # 처리 순서의 첫 파일은 마지막 파일을 읽기 시작한 뒤에야 끝난다.
            if path == last:
                last_read.set()
            if path == first:
                assert last_read.wait(10)
            return super().read(path)

    library = open_library(tmp_path, ReverseMedia())
    library.add_watched_folder(folder)
    result, calls = scan(library)
    assert result == ScanResult(4, ())
    assert {thread for _, thread in calls} == {threading.current_thread()}
    titles = {video.id: video.title for video in library.videos()}
    assert [titles[video_id] for video_id, _ in calls] == [Path(name).stem for name in names]


@pytest.mark.parametrize("workers", [1, 4])
def test_same_content_in_one_scan_is_captured_once_and_registered_as_one_video(tmp_path, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    first_capture = threading.Event()

    class OrderedMedia(ContentMedia):
        def read(self, path):
            # 뒤 복사본은 앞 복사본이 캡처를 맡은 뒤 지문을 계산한다(처리 순서대로 끝나는 일반 경우).
            if workers > 1 and path.name != "copy1.mkv" and path.read_bytes() == b"same":
                assert first_capture.wait(10)
            return super().read(path)

        def capture(self, path, destination, seconds):
            if path.name == "copy1.mkv":
                first_capture.set()
            super().capture(path, destination, seconds)

    media = OrderedMedia()
    library = open_library(tmp_path, media)
    folder = tmp_path / "watched"
    copies = [write(folder / f"copy{index}.mkv", b"same") for index in (1, 2, 3)]
    write(folder / "other.mkv", b"other")
    library.add_watched_folder(folder)
    assert library.scan() == ScanResult(2, ())
    same, = (video for video in library.videos() if video.fingerprint.startswith("v1:4:"))
    assert same.title == "copy1"
    assert {location.path for location in same.locations} == set(copies)
    assert media.captures.count(b"same") == 1
    assert same.thumbnail.read_bytes() == b"thumbnail"
    files, referenced = thumbnail_files(tmp_path, library)
    assert files == referenced


class SecondFirstMedia(ContentMedia):
    """동시 실행이면 a를 읽기 전에 b의 미리 읽기·캡처가 끝나게 한다."""

    def __init__(self, folder, workers):
        super().__init__()
        self.first, self.second, self.workers = folder / "a.mkv", folder / "b.mkv", workers
        self.second_captured = threading.Event()

    def read(self, path):
        if path == self.first:
            assert self.workers == 1 or self.second_captured.wait(10)
        return super().read(path)

    def capture(self, path, destination, seconds):
        super().capture(path, destination, seconds)
        if path == self.second:
            self.second_captured.set()


@pytest.mark.parametrize("workers", [1, 4])
def test_content_replaced_after_prefetch_is_registered_with_thumbnail_of_final_content(
        tmp_path, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    folder = tmp_path / "watched"
    write(folder / "a.mkv", b"first")
    second = write(folder / "b.mkv", b"old content")
    library = open_library(tmp_path, SecondFirstMedia(folder, workers))
    library.add_watched_folder(folder)

    def replace(video_id):
        if library.video(video_id).title == "a":
            second.write_bytes(b"new final content")  # a 반영 뒤, b 반영 전에 내용이 바뀐다.

    assert library.scan(on_registered=replace) == ScanResult(2, ())
    video, = (video for video in library.videos() if video.locations[0].path == second)
    assert video.fingerprint.startswith(f"v1:{len(b'new final content')}:")
    assert video.thumbnail.read_bytes() == b"thumbnail"
    files, referenced = thumbnail_files(tmp_path, library)
    assert files == referenced


@pytest.mark.parametrize("workers", [1, 4])
def test_later_copy_capture_does_not_hide_earlier_copy_failure(tmp_path, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    folder = tmp_path / "watched"
    first = write(folder / "a.mkv", b"same")
    second = write(folder / "b.mkv", b"same")

    class DeniedMedia(SecondFirstMedia):
        # 동시 실행이면 뒤 복사본 b가 먼저 캡처를 맡아 성공한다. a의 캡처만 실패한다.
        def capture(self, path, destination, seconds):
            if path == first:
                raise RuntimeError("capture denied: a.mkv")
            super().capture(path, destination, seconds)

    library = open_library(tmp_path, DeniedMedia(folder, workers))
    library.add_watched_folder(folder)
    assert library.scan() == ScanResult(1, (ScanIssue(first, "capture denied: a.mkv"),))
    video, = library.videos()
    assert video.title == "b"
    assert [location.path for location in video.locations] == [second]
    files, referenced = thumbnail_files(tmp_path, library)
    assert files == referenced


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize("change", ["delete", "error"])
def test_unused_prefetched_thumbnail_is_removed(tmp_path, monkeypatch, workers, change):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    folder = tmp_path / "watched"
    write(folder / "a.mkv", b"first")
    second = write(folder / "b.mkv", b"second")
    library = open_library(tmp_path, SecondFirstMedia(folder, workers))
    library.add_watched_folder(folder)

    def registered(video_id):
        # b를 미리 캡처한 뒤 a 반영 직후에 b가 사라지거나 검사가 예외로 끝난다.
        if change == "delete":
            second.unlink()
        else:
            raise KeyError("예상하지 못한 오류")

    if change == "delete":
        result = library.scan(on_registered=registered)
        assert result.added == 1 and [issue.path for issue in result.issues] == [second]
    else:
        with pytest.raises(KeyError):
            library.scan(on_registered=registered)
    assert [video.title for video in library.videos()] == ["a"]
    files, referenced = thumbnail_files(tmp_path, library)
    assert files == referenced


@pytest.mark.parametrize("workers", [1, 4])
def test_scan_removes_prefetch_files_left_by_interrupted_scan(tmp_path, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    library = open_library(tmp_path, ContentMedia())
    folder = tmp_path / "watched"
    write(folder / "a.mkv", b"first")
    library.add_watched_folder(folder)
    left = tmp_path / "data/thumbnails" / f"{scan_prefetch.TEMPORARY_PREFIX}left-by-crash.jpg"
    left.write_bytes(b"partial")
    assert library.scan() == ScanResult(1, ())
    files, referenced = thumbnail_files(tmp_path, library)
    assert files == referenced


def test_failed_read_or_capture_does_not_block_others_and_is_retried(tmp_path):
    media = ContentMedia()
    library = open_library(tmp_path, media)
    folder = tmp_path / "watched"
    broken = write(folder / "a/broken.mkv", b"broken")
    write(folder / "a/good.mkv", b"good")
    nothumb = write(folder / "b/nothumb.mkv", b"nothumb")
    write(folder / "b/fine.mkv", b"fine")
    library.add_watched_folder(folder)
    result = library.scan()
    assert result.added == 2 and set(result.issues) == {
        ScanIssue(broken, "손상된 영상: broken.mkv"), ScanIssue(nothumb, "썸네일 실패: nothumb.mkv")}
    media.broken = False
    assert library.scan() == ScanResult(2, ())
    assert len(library.videos()) == 4
    assert library.scan() == ScanResult(0, ())


def build_scenario(root):
    folder = root / "watched"
    write(folder / "a/1.mkv", b"alpha")
    write(folder / "a/2.mkv", b"beta")
    write(folder / "b/copy.mkv", b"alpha")
    write(folder / "b/short.mkv", b"short")
    write(folder / "b/anim.gif", b"gif")
    write(folder / "c/notes.txt", b"notes")
    write(folder / "c/broken.mkv", b"broken")
    write(folder / "c/nothumb.mkv", b"nothumb")
    write(folder / "c/nothumb-copy.mkv", b"nothumb")
    write(folder / "d/x.mkv", b"gamma")
    for index in range(12):
        write(folder / f"e{index % 3}/{index}.mkv", f"bulk {index}".encode())
    return folder


def run_scenario(root, monkeypatch, workers):
    monkeypatch.setattr(scan_prefetch, "SCAN_WORKERS", workers)
    media = ContentMedia()
    library = open_library(root, media)
    folder = build_scenario(root)
    library.add_watched_folder(folder)
    steps = []

    def step():
        result, calls = scan(library)
        assert {thread for _, thread in calls} <= {threading.current_thread()}
        titles = {video.id: video.title for video in library.videos() + library.videos(excluded=True)}
        files, referenced = thumbnail_files(root, library)
        assert files == referenced
        steps.append((
            result.added, result.reconnected,
            [(issue.path.relative_to(root), issue.message, issue.failed) for issue in result.issues],
            [titles[video_id] for video_id, _ in calls],
            sorted((video.title, video.fingerprint, video.duration, video.format, video.excluded,
                    video.width, video.height, video.thumbnail.name,
                    tuple(location.path.relative_to(root) for location in video.locations))
                   for video in library.videos() + library.videos(excluded=True))))

    step()
    (folder / "a/2.mkv").rename(folder / "d/2-moved.mkv")
    (folder / "d/x.mkv").unlink()
    step()
    write(folder / "d/x-back.mkv", b"gamma")
    excluded = next(video for video in library.videos() if video.title == "0")
    library.set_excluded(excluded.id, True)
    write(folder / "f/excluded-copy.mkv", b"bulk 0")
    library.set_minimum_duration(10)
    media.broken = False
    step()
    return steps, sorted(set(media.captures))


def test_parallel_scan_matches_sequential_scan(tmp_path, monkeypatch):
    sequential = run_scenario(tmp_path / "sequential", monkeypatch, 1)
    parallel = run_scenario(tmp_path / "parallel", monkeypatch, 4)
    assert parallel == sequential
    first, second, third = sequential[0]
    assert first[0] == 15 and sorted(issue[1] for issue in first[2]) == [
        "손상된 영상: broken.mkv", "썸네일 실패: nothumb-copy.mkv", "썸네일 실패: nothumb.mkv"]
    assert third[1] and "파일 없음이던 영상을 다시 찾았습니다." in [issue[1] for issue in third[2]]


def test_unexpected_error_stops_scan_and_closes_workers(tmp_path):
    raised = threading.Event()

    class ExplodingMedia(ContentMedia):
        def read(self, path):
            if path.name == "0.mkv":
                raised.set()
                raise KeyError("예상하지 못한 오류")
            assert raised.wait(10)
            return super().read(path)

    library = open_library(tmp_path, ExplodingMedia())
    folder = tmp_path / "watched"
    write(folder / "0.mkv", b"first")
    for index in range(1, 20):
        write(folder / f"later/{index}.mkv", f"video {index}".encode())
    library.add_watched_folder(folder)
    before = set(threading.enumerate())
    with pytest.raises(KeyError):
        library.scan()
    assert set(threading.enumerate()) <= before
    assert library.videos() == ()



def test_copy_does_not_reuse_thumbnail_captured_while_other_copy_changed(tmp_path):
    changed = []

    class ChangingMedia(ContentMedia):
        def capture(self, path, destination, seconds):
            with self.lock:
                first = not changed
                changed.append(path)
            if first:
                path.write_bytes(b"replaced while capturing")  # 캡처 중 파일이 바뀐다.
            destination.write_bytes(b"thumbnail of " + path.read_bytes())

    library = open_library(tmp_path, ChangingMedia())
    folder = tmp_path / "watched"
    copies = [write(folder / name / "copy.mkv", b"same") for name in ("a", "b")]
    library.add_watched_folder(folder)
    library.scan()
    same, = (video for video in library.videos() if video.fingerprint.startswith("v1:4:"))
    unchanged, = (path for path in copies if path != changed[0])
    assert [location.path for location in same.locations] == [unchanged]
    assert same.thumbnail.read_bytes() == b"thumbnail of same"
