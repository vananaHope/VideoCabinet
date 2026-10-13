from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment


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
    def transcribe(self, path, spoken_language, *, cancellation):
        return TranscriberResult("en", (TranscriptSegment(1, 3, "remember this"),))


def open_core(database, media=None):
    return AppCore(media=media or Media(), clock=lambda: NOW, database=database, transcriber=Transcriber())


@pytest.fixture
def core(tmp_path):
    return open_core(tmp_path / "data/library.sqlite3")


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
    core.playback.end()
    core.request_subtitles(video_id)
    core.process_next_subtitle()
    core.rename_video(video_id, "직접 정한 제목")


def records(core, video_id):
    return core.viewings(video_id), core.highlights(video_id), core.transcript(video_id), core.series_for_video(video_id)


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


def test_unchanged_nonvideo_and_registered_locations_skip_reading_after_restart(core, tmp_path, monkeypatch):
    media = Media()
    path = video_file(tmp_path / "watched")
    document = video_file(path.parent, "subtitle.srt", b"subtitle")
    core = open_core(core.database, media)
    core.add_watched_folder(path.parent)
    core.scan()
    assert set(media.reads) == {path, document}
    media.reads.clear()
    core = open_core(core.database, media)
    original_open = Path.open
    reads = []
    def open_file(self, *args, **kwargs):
        if self in (path, document):
            reads.append(self)
        return original_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    core.scan()
    core.scan()
    assert media.reads == []
    assert reads == []


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


@pytest.mark.parametrize("version", [0, 1])
def test_legacy_database_migration_preserves_records_and_reopens(tmp_path, version):
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
            INSERT INTO highlights VALUES (7, 42, 10, NULL, '옛 메모');
            INSERT INTO series VALUES (3, '내 시리즈', NULL, NULL, 1);
            INSERT INTO series_videos VALUES (3, 42, 0);
            INSERT INTO series_overrides VALUES (42);
        ''')
        db.execute("INSERT INTO videos VALUES (42, ?, '옛 제목', 20, 'matroska', 'old.jpg', ?)",
                   (f"v1:3:{digest}", NOW.isoformat()))
        db.execute("INSERT INTO locations VALUES (?, 42)", (str(path),))
        db.execute("INSERT INTO watched_folders VALUES (?)", (str(path.parent),))
        db.execute("INSERT INTO viewings VALUES (5, 42, 20, ?, ?, ?, '[[0, 19]]', 19)", (NOW.isoformat(),) * 3)
        db.execute("INSERT INTO transcripts VALUES (42, 'old-transcript', 'en', 0, ?)", (NOW.isoformat(),))
        db.execute("INSERT INTO transcript_lines VALUES ('old-line', 'old-transcript', 0, 1, 3, 'old words')")
        db.execute(f"PRAGMA user_version={version}")
    core = open_core(database)
    video, = core.videos()
    assert video.id == 42 and video.title == "옛 제목" and video.duration == 20
    assert core.highlights(42)[0].note.text == "옛 메모"
    assert core.viewing_status(42).finished
    assert core.transcript(42).lines[0].id == "old-line"
    assert core.series_for_video(42).name == "내 시리즈"
    expected = records(core, 42)
    assert core.scan().added == 0  # 기존 1분 미만 영상도 기록을 보존한다.
    core = open_core(database)
    assert records(core, 42) == expected
    assert core.videos() == (video,)
    assert core.watched_folders()[0].path == path.parent
    core.exclude_video(42)
    assert core.excluded_videos()[0].id == 42
