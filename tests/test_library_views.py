"""공개 AppCore 조건 조합, 폴더 복사본, 날짜·정렬과 설정 복원."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from my_video_manager.core import AppCore, Command, CommandType
from my_video_manager.library_views import default_options
from test_library_details import Media, Transcriber, Translator


@pytest.fixture
def library(tmp_path):
    now = [datetime(2026, 10, 15, 12, tzinfo=timezone.utc)]
    core = AppCore(media=Media(), clock=lambda: now[0], database=tmp_path / 'data/library.sqlite3',
                   transcriber=Transcriber(), translator=Translator())
    for i, name in enumerate(('Alpha', 'beta', '한글')):
        now[0] -= timedelta(days=i * 10)
        path = tmp_path / f'{name}.mp4'
        path.write_bytes(name.encode())
        core.add_file(path)
    now[0] = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    return core


def ids(core, **changes):
    return core.library_view_ids({**default_options(), **changes})


def test_state_filters_use_shared_viewing_summary_including_glances_and_favorites(library):
    core = library
    a, b, c = core.videos()
    for vid, ends in ((a.id, [4]), (b.id, [40, 1]), (c.id, [95, 95, 2])):
        for end in ends:
            core.playback.start(vid, 0)
            core.playback.report(end)
            core.playback.end()
    assert ids(core, viewing='unwatched') == [a.id]
    assert ids(core, viewing='abandoned') == [b.id]
    assert ids(core, viewing='finished') == [c.id]
    assert ids(core, viewing='favorite') == [c.id]
    assert ids(core, sort='count', descending=True) == [c.id, b.id, a.id]
    assert ids(core, viewed_preset='today') == [a.id, b.id, c.id]
    assert core.library_snapshot().statuses[b.id].resume_point == 1


def test_presence_multi_tag_title_and_missing_combine(library):
    core = library
    a, b, c = core.videos()
    t1 = core.add_video_tag(a.id, '공통')
    t2 = core.add_video_tag(a.id, '특별')
    core.add_video_tag(b.id, '공통')
    assert ids(core, tags=[t1.id, t2.id], query=' ALPHA ') == [a.id]
    assert ids(core, tags=[t1.id, t2.id], query='beta') == []
    core.request_subtitles(a.id, 'en')
    core.process_next_subtitle()
    assert ids(core, original='yes', translated='no') == [a.id]
    core.process_next_translation()
    core.playback.start(a.id, 0)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    a.locations[0].path.with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nhello\n', encoding='utf-8')
    core.scan()
    assert ids(core, original='yes', translated='yes', external=True, highlights=True, tags=[t1.id, t2.id]) == [a.id]
    assert ids(core, original='no') == [b.id, c.id]
    a.locations[0].path.unlink()
    core.scan()
    assert ids(core, missing=True, translated='yes', highlights=True) == [a.id]
    assert ids(core, external=True) == []
    core.exclude_video(a.id)
    assert ids(core, missing=True) == []


def test_folder_counts_descendants_copies_direct_and_missing_without_disk_io(library, tmp_path, monkeypatch):
    core = library
    a, b, c = core.videos()
    root = tmp_path / 'root'
    nested = root / '긴 이름' / 'deep'
    nested.mkdir(parents=True)
    copy = nested / a.locations[0].path.name
    copy.write_bytes(a.locations[0].path.read_bytes())
    core.add_file(copy)
    other = root / 'other.mp4'
    other.write_bytes(b.locations[0].path.read_bytes())
    core.add_file(other)
    core.add_watched_folder(root)
    core.add_watched_folder(nested)
    c.locations[0].path.unlink()
    core.scan()
    monkeypatch.setattr(Path, 'stat', lambda *_args, **_kwargs: pytest.fail('폴더 보기에서 디스크 접근'))
    index = core.library_view_index()
    node = next(n for n in index.folders if n['path'] == str(root))
    assert node['count'] == 2
    assert core.library_view_ids({**default_options(), 'mode': 'folders', 'folder': node['id']}, index=index) == [a.id, b.id]
    assert len([n for n in index.folders if n['path'] == str(nested)]) == 2
    assert index.members['direct'] == {a.id, b.id}
    assert index.members['missing'] == {c.id}
    assert ids(core, mode='folders', folder='missing') == [c.id]


def test_date_presets_inclusive_custom_and_order(library):
    core = library
    a, b, c = core.videos()
    assert ids(core, added_preset='today') == [a.id]
    assert ids(core, added_preset='7') == [a.id]
    assert ids(core, added_preset='30') == [a.id, b.id]
    day = b.registered_at.astimezone().date().isoformat()
    assert ids(core, added_preset='custom', added_from=day, added_to=day) == [b.id]
    assert ids(core, sort='added') == [c.id, b.id, a.id]
    assert ids(core, sort='added', descending=True) == [a.id, b.id, c.id]
    assert ids(core, viewed_preset='7') == []
    core.playback.start(b.id, 0)
    core.playback.end()
    assert ids(core, sort='viewed') == [b.id, a.id, c.id]
    assert ids(core, sort='viewed', descending=True) == [b.id, a.id, c.id]


def test_cached_filter_changes_do_not_query_database_or_details(library, monkeypatch):
    core = library
    index = core.library_view_index()
    monkeypatch.setattr(core, '_connect', lambda: pytest.fail('조건 변경마다 DB 조회'))
    monkeypatch.setattr(core, 'library_details', lambda *_: pytest.fail('목록에서 상세 조회'))
    assert len(core.library_view_ids(default_options(), index=index)) == 3
    assert len(core.library_view_ids({**default_options(), 'query': 'alpha'}, index=index)) == 1


def test_options_persist_and_invalid_options_preserve_saved_settings(library):
    core = library
    options = {**default_options(), 'mode': 'folders', 'folder': 'direct', 'viewing': 'unwatched',
               'tags': [1, 2], 'sort': 'duration', 'descending': True, 'card_size': 'large'}
    core.save_library_view_options(options)
    reopened = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database)
    assert reopened.library_view_options() == options
    for invalid in ({'sort': 'unknown'}, {'descending': 1}, {'tags': [True]}, {'added_from': 'bad-date'},
                    {'added_preset': 'custom', 'added_from': '2026-02-02', 'added_to': '2026-01-01'}):
        with pytest.raises(ValueError):
            core.save_library_view_options({**options, **invalid})
        assert core.library_view_options() == options
    with sqlite3.connect(core.database) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
