from datetime import datetime, timezone
from pathlib import Path

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class FakeMedia:
    def read(self, path):
        if path.suffix == ".txt":
            return None
        if path.name == "broken.mkv":
            raise ValueError("손상된 영상")
        return MediaInfo(12.5, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"fake-thumbnail")


@pytest.fixture
def core(tmp_path):
    return AppCore(media=FakeMedia(), clock=lambda: NOW, database=tmp_path / "data/library.sqlite3")


def test_watch_scan_register_and_reopen(core, tmp_path):
    folder = tmp_path / "영상"
    nested = folder / "하위"
    nested.mkdir(parents=True)
    (folder / "첫 영상.mkv").write_bytes(b"video one")
    (nested / "둘째 영상.MKV").write_bytes(b"video two")
    (folder / "readme.txt").write_text("not video")

    core.add_watched_folder(folder)
    result = core.scan()

    assert result.added == 2
    assert not result.issues
    videos = core.videos()
    assert {video.title for video in videos} == {"첫 영상", "둘째 영상"}
    assert all(video.duration == 12.5 and video.format == "matroska" for video in videos)
    assert all(video.thumbnail.read_bytes() == b"fake-thumbnail" for video in videos)
    assert all(video.registered_at == NOW for video in videos)
    assert all(core.playback_location(video.id) in video.locations for video in videos)

    reopened = AppCore(media=FakeMedia(), clock=lambda: NOW, database=core.database)
    assert reopened.videos() == videos
    assert reopened.watched_folders() == core.watched_folders()
    assert reopened.scan().added == 0
    assert reopened.videos() == videos


def test_copies_have_one_video_and_multiple_locations(core, tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "original.mkv").write_bytes(b"same content")
    (folder / "copy.mkv").write_bytes(b"same content")
    core.add_watched_folder(folder)
    assert core.scan().added == 1
    video, = core.videos()
    assert {location.path.name for location in video.locations} == {"original.mkv", "copy.mkv"}
    assert video.fingerprint.startswith("v1:12:")


@pytest.mark.parametrize("changed_offset", [0, 512 * 1024, 1024 * 1024 - 1, None])
def test_fingerprint_distinguishes_front_middle_back_and_size(core, tmp_path, changed_offset):
    folder = tmp_path / "videos"
    folder.mkdir()
    content = bytearray(1024 * 1024)
    (folder / "original.mkv").write_bytes(content)
    if changed_offset is None:
        content.append(0)
    else:
        content[changed_offset] = 1
    (folder / "different.mkv").write_bytes(content)
    core.add_watched_folder(folder)
    assert core.scan().added == 2
    first, second = core.videos()
    assert first.fingerprint != second.fingerprint


def test_overlapping_watched_folders_and_repeat_scan_are_idempotent(core, tmp_path):
    folder = tmp_path / "videos"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (nested / "video.mkv").write_bytes(b"video")
    core.add_watched_folder(folder)
    core.add_watched_folder(folder / ".")
    core.add_watched_folder(nested)
    assert len(core.watched_folders()) == 2
    assert core.scan().added == 1
    assert core.scan().added == 0
    assert len(core.videos()[0].locations) == 1


def test_invalid_folder_does_not_register(core, tmp_path):
    with pytest.raises(ValueError):
        core.add_watched_folder(tmp_path / "absent")
    assert core.watched_folders() == ()


def test_bad_media_does_not_prevent_other_registration(core, tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "broken.mkv").write_bytes(b"bad")
    (folder / "valid.mkv").write_bytes(b"good")
    core.add_watched_folder(folder)
    result = core.scan()
    assert result.added == 1
    assert result.issues[0].path.name == "broken.mkv"
    assert [video.title for video in core.videos()] == ["valid"]


def test_thumbnail_failure_can_be_retried_without_partial_registration(tmp_path):
    class FailingCapture(FakeMedia):
        def capture(self, path, destination, seconds):
            raise RuntimeError("캡처 실패")

    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "video.mkv").write_bytes(b"video")
    database = tmp_path / "data/library.sqlite3"
    failing = AppCore(media=FailingCapture(), clock=lambda: NOW, database=database)
    failing.add_watched_folder(folder)
    assert len(failing.scan().issues) == 1
    assert failing.videos() == ()
    recovered = AppCore(media=FakeMedia(), clock=lambda: NOW, database=database)
    assert recovered.scan().added == 1


@pytest.mark.parametrize("key, kind, amount", [
    ("Enter", CommandType.TOGGLE_PAUSE, 0),
    ("Left", CommandType.SEEK, -5),
    ("Right", CommandType.SEEK, 5),
    (",", CommandType.SEEK, -3),
    ("Up", CommandType.CHANGE_SPEED, 0.25),
    ("Down", CommandType.CHANGE_SPEED, -0.25),
])
def test_default_key_commands(core, key, kind, amount):
    assert core.command_for_key(key) == Command(kind, amount)


def test_key_bindings_can_be_replaced_without_ui(core):
    bindings = {"Space": Command(CommandType.TOGGLE_PAUSE)}
    core.set_key_bindings(bindings)
    bindings.clear()
    assert core.command_for_key("Space") == Command(CommandType.TOGGLE_PAUSE)
    assert core.command_for_key("Enter") is None
    assert core.command_for_key("unknown") is None


def test_key_bindings_can_be_injected_at_start(tmp_path):
    core = AppCore(media=FakeMedia(), clock=lambda: NOW, database=tmp_path / "library.sqlite3", key_bindings={})
    assert core.command_for_key("Enter") is None
