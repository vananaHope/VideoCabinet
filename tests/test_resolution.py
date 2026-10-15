from contextlib import closing
from dataclasses import replace
import json
import os
import shutil
import sqlite3
from threading import Event, Thread
from time import perf_counter
import zipfile

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.media import parse_ffprobe_result
from test_library import NOW, Media, records, record, Transcriber, video_file


class ResolutionMedia(Media):
    width, height = 1920, 1080

    def read(self, path):
        return replace(super().read(path), width=self.width, height=self.height)


def open_core(database, media=None):
    return AppCore(database=database, media=media or ResolutionMedia(), clock=lambda: NOW, transcriber=Transcriber())


def downgrade_v2(database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('DROP INDEX videos_resolution_pending')
        for column in ('width', 'height', 'resolution_checked'):
            db.execute(f'ALTER TABLE videos DROP COLUMN {column}')
        db.execute('PRAGMA user_version=2')


def legacy(tmp_path, count=2, media=None):
    core = open_core(tmp_path / 'data/library.sqlite3', media)
    for i in range(count):
        core.add_file(video_file(tmp_path / 'videos', f'{i}.mkv', str(i).encode()))
    downgrade_v2(core.database)
    return open_core(core.database, media)


@pytest.mark.parametrize('rotation', [0, 90, -90, 180, 270, 450])
@pytest.mark.parametrize('source', ['tag', 'matrix'])
def test_display_dimensions(rotation, source):
    stream = dict(codec_type='video', width=1920, height=1080)
    if source == 'tag':
        stream['tags'] = {'rotate': str(rotation)}
    else:
        stream['tags'] = {'rotate': '0'}
        stream['side_data_list'] = [dict(side_data_type='Display Matrix', rotation=rotation)]
    output = json.dumps(dict(format=dict(duration='100', format_name='mp4'), streams=[
        dict(codec_type='video', width=800, height=800, disposition=dict(attached_pic=1)), stream]))
    info = parse_ffprobe_result(output, suffix='.mp4')
    assert (info.width, info.height) == ((1080, 1920) if rotation % 180 == 90 else (1920, 1080))


@pytest.mark.parametrize('dimensions', [(None, 1080), (0, 1080), (-1, 1080), ('N/A', 1080)])
def test_invalid_dimensions_are_unknown(dimensions):
    output = json.dumps(dict(format=dict(duration='100'), streams=[dict(codec_type='video', width=dimensions[0], height=dimensions[1])]))
    info = parse_ffprobe_result(output, suffix='.mp4')
    assert (info.width, info.height) == (None, None)


def test_registration_and_rescan_store_dimensions_without_changing_records(tmp_path):
    media = ResolutionMedia()
    core = open_core(tmp_path / 'library.sqlite3', media)
    path = video_file(tmp_path / 'videos')
    core.add_file(path)
    video, = core.videos()
    assert (video.width, video.height) == (1920, 1080)
    record(core, video.id)
    before = records(core, video.id)
    media.width, media.height = 1080, 1920
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    assert core.scan().added == 0
    assert (core.video(video.id).width, core.video(video.id).height) == (1080, 1920)
    assert records(core, video.id) == before
    assert open_core(core.database).video(video.id) == core.video(video.id)


def test_resolution_and_external_subtitles_both_refresh_on_registration_and_scan(tmp_path):
    media = ResolutionMedia()
    core = open_core(tmp_path / 'library.sqlite3', media)
    path = video_file(tmp_path / 'videos')
    subtitle = path.with_suffix('.ko.srt')
    subtitle.write_text('1\n00:00:01,000 --> 00:00:03,000\n첫번째 자막\n', encoding='utf-8')
    core.add_file(path)
    video, = core.videos()
    assert (video.width, video.height) == (1920, 1080)
    assert core.external_subtitles(video.id)[0].subtitles[0].lines[0].text == '첫번째 자막'
    assert core.search('첫번째').results[0].source == 'external'
    # 영상 캐시가 그대로여도 외부 자막은 새로 검사한다.
    subtitle.write_text('1\n00:00:01,000 --> 00:00:03,000\n바뀐 두번째 자막\n', encoding='utf-8')
    core.scan()
    assert core.video(video.id).width == 1920
    assert core.search('두번째').results[0].video_id == video.id
    # 해상도 재확인이 필요한 변경 검사에서도 양쪽이 함께 갱신된다.
    media.width, media.height = 1080, 1920
    signature = path.stat()
    os.utime(path, ns=(signature.st_atime_ns, signature.st_mtime_ns + 1000000))
    subtitle.write_text('1\n00:00:01,000 --> 00:00:03,000\n마지막 세번째 자막\n', encoding='utf-8')
    core.scan()
    assert (core.video(video.id).width, core.video(video.id).height) == (1080, 1920)
    assert core.search('세번째').results[0].source == 'external'


def test_v2_migration_backs_up_before_ddl_and_preserves_all_existing_columns(tmp_path, monkeypatch):
    core = open_core(tmp_path / 'data/library.sqlite3')
    core.add_file(video_file(tmp_path / 'videos'))
    record(core, core.videos()[0].id)
    downgrade_v2(core.database)
    with closing(sqlite3.connect(core.database)) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = {table: ','.join(row[1] for row in db.execute(f'PRAGMA table_info({table})')) for table in tables}
        before = {table: db.execute(f'SELECT {columns[table]} FROM {table}').fetchall() for table in tables}
    upgraded = open_core(core.database)
    archive, = upgraded.automatic_backups()
    assert upgraded.inspect_backup(archive).db_version == 2
    with zipfile.ZipFile(archive) as source:
        name = next(name for name in source.namelist() if name.endswith('.sqlite3'))
        saved = tmp_path / 'saved.sqlite3'
        saved.write_bytes(source.read(name))
    for database, version in ((saved, 2), (core.database, 3)):
        with closing(sqlite3.connect(database)) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == version
            assert {table: db.execute(f'SELECT {columns[table]} FROM {table}').fetchall() for table in tables} == before
            assert ('width' in [r[1] for r in db.execute('PRAGMA table_info(videos)')]) == (version == 3)
    open_core(core.database)
    assert upgraded.automatic_backups() == (archive,)
    import my_video_manager.library as library
    monkeypatch.setattr(library, 'LIBRARY_DB_VERSION', 2)
    with pytest.raises(ValueError, match='더 최신 버전'):
        open_core(core.database)


def test_backfill_resumes_after_reopening_and_skips_missing_and_duplicate_locations(tmp_path):
    media = ResolutionMedia()
    core = legacy(tmp_path, 3, media)
    videos = core.videos()
    duplicate = tmp_path / 'copy.mkv'
    shutil.copyfile(videos[0].locations[0].path, duplicate)
    core.reconnect_video(videos[0].id, duplicate)
    videos[2].locations[0].path.unlink()
    media.reads.clear()
    event = Event()
    first = core.fill_next_resolution(cancellation=event)
    assert first.state == 'completed'
    event.set()
    assert core.fill_next_resolution(cancellation=event).state == 'cancelled'
    core = open_core(core.database, media)
    event.clear()
    assert core.fill_next_resolution(cancellation=event).state == 'completed'
    assert core.fill_next_resolution(cancellation=event).state == 'unknown'
    assert core.fill_next_resolution(cancellation=event).state == 'exhausted'
    assert len(media.reads) == 2
    assert core.video(videos[2].id).width is None
    buckets = {b.label: b.video_count for b in core.statistics_dashboard(30).inventory.resolution_distribution}
    assert buckets['1080p'] == 2 and buckets['알 수 없음'] == 1


def test_backfill_cancelled_during_probe_retries_and_does_not_hold_database_lock(tmp_path):
    entered, release, cancel = Event(), Event(), Event()
    class SlowMedia(ResolutionMedia):
        def read_resolution(self, path, *, cancellation):
            entered.set()
            assert release.wait(5)
            return self.read(path)
    core = legacy(tmp_path, 1, SlowMedia())
    video, = core.videos()
    results = []
    worker = Thread(target=lambda: results.append(core.fill_next_resolution(cancellation=cancel)))
    worker.start()
    try:
        assert entered.wait(5)
        core.rename_video(video.id, '읽는 동안 저장')
        cancel.set()
    finally:
        release.set()
        worker.join(5)
    assert results[0].state == 'cancelled'
    assert core.video(video.id).width is None
    cancel.clear()
    assert core.fill_next_resolution(cancellation=cancel).state == 'completed'
    assert core.video(video.id).title == '읽는 동안 저장'


def test_probe_failure_finishes_once_and_scan_retries_without_losing_location(tmp_path):
    class BrokenMedia(ResolutionMedia):
        def read_resolution(self, path, *, cancellation):
            raise RuntimeError('probe timeout')
    core = legacy(tmp_path, 1, BrokenMedia())
    result = core.fill_next_resolution(cancellation=Event())
    assert result.state == 'unknown' and 'timeout' in result.message
    assert core.fill_next_resolution(cancellation=Event()).state == 'exhausted'
    core.scan()
    assert core.videos()[0].width == 1920
    assert not core.videos()[0].missing


@pytest.mark.parametrize('lock', ['IMMEDIATE', 'EXCLUSIVE'])
def test_busy_database_yields_and_retries(tmp_path, lock):
    core = legacy(tmp_path, 1)
    with closing(sqlite3.connect(core.database)) as db:
        db.execute(f'BEGIN {lock}')
        started = perf_counter()
        result = core.fill_next_resolution(cancellation=Event())
        assert result.state == 'retry'
        assert perf_counter() - started < 0.5
        db.rollback()
    assert core.fill_next_resolution(cancellation=Event()).state == 'completed'


def test_v2_backup_failure_prevents_ddl(tmp_path, monkeypatch):
    core = open_core(tmp_path / 'library.sqlite3')
    core.add_file(video_file(tmp_path / 'videos'))
    downgrade_v2(core.database)
    original = core.database.read_bytes()
    import my_video_manager.backup as backup
    def fail(*args):
        raise OSError('backup disk full')
    monkeypatch.setattr(backup, 'backup_before_migration', fail)
    with pytest.raises(OSError, match='disk full'):
        open_core(core.database)
    assert core.database.read_bytes() == original


def test_replaced_file_is_not_used_for_old_video_resolution(tmp_path):
    core = legacy(tmp_path, 1)
    video, = core.videos()
    video.locations[0].path.write_bytes(b'a different video')
    assert core.fill_next_resolution(cancellation=Event()).state == 'unknown'
    assert core.video(video.id).width is None


@pytest.mark.parametrize('reason', ['cancelled', 'timeout'])
def test_probe_process_is_reaped_on_cancellation_or_timeout(tmp_path, monkeypatch, reason):
    import subprocess
    import sys
    import my_video_manager.adapters as adapters
    reader = adapters.FFmpegMediaReader()
    popen = subprocess.Popen
    children = []
    def sleeping_process(arguments, **kwargs):
        child = popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(adapters.subprocess, 'Popen', sleeping_process)
    cancellation = Event()
    started = perf_counter()
    if reason == 'timeout':
        times = iter((0, 16))
        monkeypatch.setattr(adapters.time, 'monotonic', lambda: next(times))
        with pytest.raises(RuntimeError, match='15초'):
            reader.read_resolution(tmp_path / 'slow.mkv', cancellation=cancellation)
    else:
        cancellation.set()
        assert reader.read_resolution(tmp_path / 'slow.mkv', cancellation=cancellation) is None
    assert len(children) == 1 and children[0].poll() is not None
    assert perf_counter() - started < 5  # 60초 자연 종료를 기다렸다면 정리 성공이 아니다.


@pytest.mark.parametrize('short_side,label', [(1, 'SD'), (480, 'SD'), (576, 'SD'), (719, 'SD'),
    (720, '720p'), (1079, '720p'), (1080, '1080p'), (1439, '1080p'), (1440, '1440p'),
    (1600, '1440p'), (2159, '1440p'), (2160, '4K 이상'), (4320, '4K 이상')])
@pytest.mark.parametrize('portrait', [False, True])
def test_resolution_distribution_boundaries_use_short_side(tmp_path, short_side, label, portrait):
    media = ResolutionMedia()
    media.width, media.height = (short_side, 8000) if portrait else (8000, short_side)
    core = open_core(tmp_path / 'library.sqlite3', media)
    path = video_file(tmp_path / 'videos')
    core.add_file(path)
    copy = tmp_path / 'copy.mkv'
    shutil.copyfile(path, copy)
    core.add_file(copy)
    buckets = core.statistics_dashboard(30).inventory.resolution_distribution
    assert [(b.label, b.video_count) for b in buckets if b.video_count] == [(label, 1)]
    core.exclude_video(core.videos()[0].id)
    assert sum(b.video_count for b in core.statistics_dashboard(30).inventory.resolution_distribution) == 0
