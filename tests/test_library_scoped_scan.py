from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Event, get_ident

import pytest

from my_video_manager.library import ScanResult
from test_library import Media, core, open_core, record, records, video_file
from test_external_subtitles import srt


def test_scoped_scan_registers_only_requested_subtree_and_preserves_other_locations(core, tmp_path):
    selected = tmp_path / "watched/a"
    other = tmp_path / "watched/ab"
    old = video_file(other, content=b"other")
    direct = video_file(tmp_path / "direct", content=b"direct")
    core.add_watched_folder(selected.parent)
    core.add_file(direct)
    core.scan()
    before = core.videos()
    old.unlink()
    direct.unlink()
    nested = video_file(selected / "nested", content=b"new")
    video_file(other, "unseen.mkv", b"unseen")

    assert core.scan(folders=[selected]) == ScanResult(1, ())
    assert all(core.video(video.id) == video for video in before)
    assert {location.path for video in core.videos() for location in video.locations} == {old, direct, nested}
    assert core.scan().added == 1
    assert all(core.video(video.id).missing for video in before)


@pytest.mark.parametrize("remove_folder", [False, True])
def test_scoped_scan_marks_only_selected_missing_and_prunes_only_selected_cache(tmp_path, remove_folder):
    media = Media()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    selected = tmp_path / "watched/a"
    other = tmp_path / "watched/b"
    videos = [video_file(folder, content=folder.name.encode()) for folder in (selected, other)]
    documents = [video_file(folder, "document.txt") for folder in (selected, other)]
    core.add_watched_folder(selected.parent)
    core.scan()
    before = {video.locations[0].path: video for video in core.videos()}
    signatures = [path.stat() for path in documents]
    for path in videos + documents:
        path.unlink()
    if remove_folder:
        selected.rmdir()
    result = core.scan(folders=[selected])
    assert result.added == 0
    assert len(result.issues) == int(remove_folder)
    assert core.video(before[videos[0]].id).missing
    assert core.video(before[videos[1]].id) == before[videos[1]]
    for path, signature in zip(documents, signatures):
        video_file(path.parent, path.name)
        os.utime(path, ns=(signature.st_atime_ns, signature.st_mtime_ns))
    media.reads.clear()
    core.scan()
    assert media.reads == [documents[0]]


@pytest.mark.parametrize("scan_source", [False, True])
def test_scoped_move_keeps_identity_records_and_defers_outside_location_cleanup(core, tmp_path, scan_source):
    source = video_file(tmp_path / "watched/a")
    target = tmp_path / "watched/b/moved.mkv"
    target.parent.mkdir()
    core.add_watched_folder(source.parent.parent)
    core.scan()
    video, = core.videos()
    record(core, video.id)
    expected = records(core, video.id)
    source.rename(target)
    if scan_source:
        assert core.scan(folders=[source.parent]) == ScanResult(0, ())
        assert core.video(video.id).missing
    result = core.scan(folders=[target.parent])
    assert result.added == 0
    assert result.reconnected is scan_source
    assert len(result.issues) == int(scan_source)
    assert all(not issue.failed for issue in result.issues)
    assert len(core.videos()) == 1
    assert {location.path for location in core.video(video.id).locations} == (
        {target} if scan_source else {source, target})
    assert records(core, video.id) == expected
    core.scan(folders=[source.parent])
    assert [location.path for location in core.video(video.id).locations] == [target]


@pytest.mark.parametrize("scope", ["root", "overlap", "relative"])
def test_scoped_roots_normalize_and_scan_each_file_once(tmp_path, monkeypatch, scope):
    media = Media()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    path = video_file(tmp_path / "watched/nested")
    core.add_watched_folder(path.parent.parent)
    core.add_watched_folder(path.parent)
    monkeypatch.chdir(tmp_path)
    folders = {"root": [path.parent.parent],
               "overlap": [path.parent, path.parent.parent, path.parent],
               "relative": [Path("watched/nested/../nested")]}[scope]
    assert core.scan(folders=iter(folders)) == ScanResult(1, ())
    assert media.reads == [path]
    assert core.scan(folders=folders) == ScanResult(0, ())
    assert media.reads == [path]


@pytest.mark.parametrize("kind", ["empty", "outside", "removed", "mixed"])
def test_scoped_invalid_or_unwatched_paths_are_ignored(core, tmp_path, caplog, kind):
    selected = video_file(tmp_path / "watched")
    outside = video_file(tmp_path / "outside", content=b"outside")
    core.add_watched_folder(selected.parent)
    if kind == "removed":
        core.add_watched_folder(outside.parent)
        core.remove_watched_folder(outside.parent)
    folders = [] if kind == "empty" else [outside.parent]
    if kind == "mixed":
        folders.append(selected.parent)
    with caplog.at_level(logging.INFO, logger="my_video_manager.library"):
        assert core.scan(folders=folders) == ScanResult(int(kind == "mixed"), ())
    assert len(core.videos()) == int(kind == "mixed")
    assert bool(caplog.records) is (kind != "empty")
    if caplog.records:
        assert str(outside.parent) in caplog.text


def test_scoped_fast_path_keeps_exclusions_and_reconsiders_changed_or_short_files(tmp_path):
    media = Media()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    path = video_file(tmp_path / "watched/a")
    core.add_watched_folder(path.parent.parent)
    core.scan(folders=[path.parent])
    video, = core.videos()
    core.exclude_video(video.id)
    document = video_file(path.parent, "document.txt")
    short = video_file(path.parent, "short.mkv", b"short")
    media.duration = 20
    core.scan(folders=[path.parent])
    media.reads.clear()
    assert core.scan(folders=[path.parent]) == ScanResult(0, ())
    assert media.reads == []
    assert core.excluded_videos() == (core.video(video.id),)
    core.set_minimum_duration(10)
    assert core.scan(folders=[path.parent]).added == 1
    assert media.reads == [short]
    document.write_bytes(b"changed document")
    assert core.scan(folders=[path.parent]) == ScanResult(0, ())
    assert media.reads == [short, document]


def test_scoped_scan_applies_folder_rules_and_preserves_tag_rule_on_reconnection(core, tmp_path):
    path = video_file(tmp_path / "watched/a")
    other = video_file(tmp_path / "watched/b", content=b"other")
    core.add_watched_folder(path.parent.parent)
    core.set_auto_subtitle_rule(folder=path.parent.parent, spoken_language="ja")
    assert core.scan(folders=[path.parent]).added == 1
    video, = core.videos()
    entry, = core.subtitle_queue()
    assert (entry.video_id, entry.spoken_language) == (video.id, "ja")
    core.remove_from_subtitle_queue(video.id)
    core.scan(folders=[path.parent])
    assert core.subtitle_queue() == ()
    tag = core.create_tag("영어")
    core.set_auto_subtitle_rule(tag_id=tag.id, spoken_language="en")
    core.add_video_tag(video.id, tag.name)
    entry, = core.subtitle_queue()
    assert entry.spoken_language == "en"
    target = other.parent / "moved.mkv"
    path.rename(target)
    assert core.scan(folders=[path.parent, target.parent]).added == 1
    assert core.video_tags(video.id) == (tag,)
    assert {entry.video_id: entry.spoken_language for entry in core.subtitle_queue()} == {
        video.id: "en", next(v.id for v in core.videos() if v.id != video.id): "ja"}


def test_scoped_external_subtitles_are_limited_by_location_even_for_copies(core, tmp_path):
    selected = video_file(tmp_path / "watched/a")
    other = video_file(tmp_path / "watched/b")
    for path in (selected, other):
        path.with_suffix(".srt").write_text(srt(path.parent.name), encoding="utf-8")
    core.add_watched_folder(selected.parent.parent)
    core.scan()
    video, = core.videos()
    before = {item.path: item for item in core.external_subtitles(video.id)}
    other.with_suffix(".srt").unlink()
    selected.with_suffix(".srt").write_text(srt("changed"), encoding="utf-8")
    core.scan(folders=[selected.parent])
    after = {item.path: item for item in core.external_subtitles(video.id)}
    assert after[other.with_suffix(".srt")] == before[other.with_suffix(".srt")]
    assert after[selected.with_suffix(".srt")] != before[selected.with_suffix(".srt")]
    selected.unlink()
    core.scan(folders=[selected.parent])
    assert core.external_subtitles(video.id) == (before[other.with_suffix(".srt")],)
    core.scan()
    assert core.external_subtitles(video.id) == ()


def test_scoped_permission_error_preserves_cache_and_next_scan_succeeds(tmp_path, monkeypatch):
    media = Media()
    core = open_core(tmp_path / "data/library.sqlite3", media)
    path = video_file(tmp_path / "watched/a", "document.txt")
    core.add_watched_folder(path.parent.parent)
    core.scan()
    scandir = os.scandir

    def denied(directory):
        if Path(directory) == path.parent:
            raise PermissionError("denied")
        return scandir(directory)

    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", denied)
        result = core.scan(folders=[path.parent])
    assert result.added == 0
    assert len(result.issues) == 1
    assert result.issues[0].path == path.parent
    assert result.issues[0].failed
    assert core.scan(folders=[path.parent]) == ScanResult(0, ())
    assert media.reads == [path]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
@pytest.mark.parametrize("external", [False, True])
def test_scoped_root_and_ancestor_junctions_cannot_bypass_traversal(core, tmp_path, external):
    watched = tmp_path / "watched"
    watched.mkdir()
    target = (tmp_path / "outside") if external else (watched / "real")
    path = video_file(target / "nested")
    link = watched / "link"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "New-Item -ItemType Junction -Path $env:MVM_TEST_LINK -Target $env:MVM_TEST_TARGET | Out-Null"],
        env={**os.environ, "MVM_TEST_LINK": str(link), "MVM_TEST_TARGET": str(target)},
        check=True, capture_output=True,
    )
    try:
        core.add_watched_folder(watched)
        assert core.scan(folders=[link, link / "nested"]) == ScanResult(0, ())
        assert core.videos() == ()
        result = core.scan(folders=[watched])
        assert result.added == int(not external)
        assert len(result.issues) == 1
        assert result.issues[0].path == link
        assert not result.issues[0].failed
        assert path.is_file()
    finally:
        link.rmdir()


def test_scoped_scan_serializes_full_scan_before_rule_snapshot(tmp_path, monkeypatch):
    entered, release, requested, second_rules = Event(), Event(), Event(), Event()
    second_thread = []

    class BlockingMedia(Media):
        def read(self, path):
            if path.parent.name == "a":
                entered.set()
                assert release.wait(10)
            return super().read(path)

    core = open_core(tmp_path / "data/library.sqlite3", BlockingMedia())
    selected = video_file(tmp_path / "watched/a")
    video_file(tmp_path / "watched/b", content=b"other")
    core.add_watched_folder(selected.parent.parent)
    connect = sqlite3.connect

    def observe(sql):
        if second_thread == [get_ident()] and "SELECT" in sql and "auto_subtitle_rules" in sql:
            second_rules.set()

    def observed_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(observe)
        return db

    def full_scan():
        second_thread.append(get_ident())
        requested.set()
        return core.scan()

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scoped = pool.submit(core.scan, folders=[selected.parent])
        try:
            assert entered.wait(10)
            full = pool.submit(full_scan)
            assert requested.wait(10)
            assert not second_rules.wait(.2)
            assert not full.done()
        finally:
            release.set()
        assert scoped.result(10) == ScanResult(1, ())
        assert full.result(10) == ScanResult(1, ())
    assert second_rules.is_set()
    assert len(core.videos()) == 2
