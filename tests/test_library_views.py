"""공개 AppCore 조건 조합, 폴더 복사본, 날짜·정렬과 설정 복원."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3

import pytest

from my_video_manager.core import AppCore, Command, CommandType
from my_video_manager.library_views import FILTER_DEFAULTS, default_options, filter_chips
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
    for vid, ends in ((a.id, [4, 4, 4]), (b.id, [40, 1]), (c.id, [95, 40, 40, 2])):
        for end in ends:
            core.playback.start(vid, 0)
            core.playback.report(end)
            core.playback.end()
    assert ids(core, viewing='unwatched') == [a.id]
    assert ids(core, viewing='abandoned') == [b.id]
    assert ids(core, viewing='finished') == [c.id]
    assert ids(core, viewing='favorite') == [c.id]
    # 틀어보기 3회인 a는 즐겨 보는 영상이 아니므로 필터에도 나오지 않는다.
    assert a.id not in ids(core, viewing='favorite')
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
                    {'modified_to': 'bad-date'},
                    {'added_preset': 'custom', 'added_from': '2026-02-02', 'added_to': '2026-01-01'},
                    {'modified_preset': 'custom', 'modified_from': '2026-02-02', 'modified_to': '2026-01-01'}):
        with pytest.raises(ValueError):
            core.save_library_view_options({**options, **invalid})
        assert core.library_view_options() == options
    with sqlite3.connect(core.database) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4


def test_date_chips_and_reset_follow_python_defaults():
    options = {**default_options(), 'added_preset': 'custom'}
    assert filter_chips(options, {}) == []
    options['added_from'] = '2026-01-01'
    chip, = filter_chips(options, {})
    assert chip['label'].endswith('끝 없음')
    assert chip['reset']['added_preset'] == chip['reset']['added_from'] == ''
    assert 'collapsed_folders' not in FILTER_DEFAULTS
    options = {**default_options(), 'external': True, 'tags': [1, 2]}
    chips = filter_chips(options, {1: 'one', 2: 'two'})
    assert chips[0]['reset']['external'] is False
    assert chips[1]['reset']['tags'] == [2]


def set_mtime(path, nanoseconds):
    os.utime(path, ns=(nanoseconds, nanoseconds))


def local_noon_ns(day):
    return int(datetime(day.year, day.month, day.day, 12).timestamp()) * 1_000_000_000


@pytest.fixture
def dated_library(tmp_path):
    now = [datetime(2026, 10, 15, 12, tzinfo=timezone.utc)]
    core = AppCore(media=Media(), clock=lambda: now[0], database=tmp_path / 'data/library.sqlite3',
                   transcriber=Transcriber(), translator=Translator())
    today = now[0].astimezone().date()
    offsets = {'오늘': 0, '닷새': 5, '스무아흐레': 29, '서른': 30, '없음': 3}
    paths = {}
    for title, offset in offsets.items():
        path = tmp_path / f'{title}.mp4'
        path.write_bytes(title.encode())
        core.add_file(path)
        set_mtime(path, local_noon_ns(today - timedelta(days=offset)))
        paths[title] = path
    paths['없음'].unlink()
    core.scan()
    return core, today


def test_modified_date_presets_custom_range_and_missing(dated_library):
    core, today = dated_library
    videos = {video.title: video.id for video in core.videos()}
    day = lambda offset: (today - timedelta(days=offset)).isoformat()

    assert set(ids(core, modified_preset='today')) == {videos['오늘']}
    assert set(ids(core, modified_preset='7')) == {videos['오늘'], videos['닷새']}
    # 30일 프리셋은 29일 전까지 포함하고 30일 전은 뺀다.
    assert set(ids(core, modified_preset='30')) == {
        videos['오늘'], videos['닷새'], videos['스무아흐레']}
    assert videos['없음'] not in ids(core, modified_preset='30')

    assert set(ids(core, modified_preset='custom', modified_from=day(5), modified_to=day(5))) == {videos['닷새']}
    assert set(ids(core, modified_preset='custom', modified_from=day(0), modified_to=day(0))) == {videos['오늘']}
    assert set(ids(core, modified_preset='custom', modified_from=day(30))) == {
        videos['오늘'], videos['닷새'], videos['스무아흐레'], videos['서른']}
    assert set(ids(core, modified_preset='custom', modified_to=day(5))) == {
        videos['닷새'], videos['스무아흐레'], videos['서른']}


def test_modified_date_sort_keeps_missing_last_both_ways(dated_library):
    core, _ = dated_library
    videos = {video.title: video.id for video in core.videos()}
    ascending = ids(core, sort='modified')
    descending = ids(core, sort='modified', descending=True)
    assert ascending == [videos['서른'], videos['스무아흐레'], videos['닷새'], videos['오늘'], videos['없음']]
    assert descending == [videos['오늘'], videos['닷새'], videos['스무아흐레'], videos['서른'], videos['없음']]


def test_modified_date_ignores_out_of_range_mtime_in_views(tmp_path):
    now = [datetime(2026, 10, 15, 12, tzinfo=timezone.utc)]
    core = AppCore(media=Media(), clock=lambda: now[0], database=tmp_path / 'data/library.sqlite3',
                   transcriber=Transcriber(), translator=Translator())
    today = now[0].astimezone().date()
    stamps = {'보통': local_noon_ns(today), '옛날': -86400 * 1_000_000_000}
    for title, stamp in stamps.items():
        path = tmp_path / f'{title}.mp4'
        path.write_bytes(title.encode())
        core.add_file(path)
        set_mtime(path, stamp)
    core.scan()
    videos = {video.title: video.id for video in core.videos()}

    # 범위 밖 값이 있어도 기본 보기와 정렬·거르기가 실패하지 않는다.
    assert set(ids(core)) == set(videos.values())
    assert ids(core, sort='modified') == [videos['보통'], videos['옛날']]
    assert ids(core, sort='modified', descending=True) == [videos['보통'], videos['옛날']]
    assert ids(core, modified_preset='today') == [videos['보통']]
    # 범위 밖 값은 없는 날짜로 다뤄 조건에서 빠진다.
    assert ids(core, modified_preset='custom', modified_from='1970-01-01', modified_to='1970-01-01') == []
    assert ids(core, modified_preset='custom', modified_to='1970-01-02') == []


def test_modified_date_filter_compares_local_dates_not_utc(dated_library, tmp_path):
    core, today = dated_library
    target = today - timedelta(days=7)
    # 로컬 날짜와 UTC 날짜가 갈리는 자정 근처 시각을 고른다. 시간대에 따라 00:30이나
    # 23:30 중 하나가 UTC에서는 다른 날짜가 된다.
    for hour, minute in ((0, 30), (23, 30)):
        seconds = int(datetime(target.year, target.month, target.day, hour, minute).timestamp())
        utc_day = datetime.fromtimestamp(seconds, timezone.utc).date()
        if utc_day != target:
            break
    else:
        pytest.skip('로컬 시간대가 UTC와 같아 로컬 날짜와 UTC 날짜가 갈리지 않는다.')

    path = tmp_path / '자정.mp4'
    path.write_bytes(b'night')
    core.add_file(path)
    set_mtime(path, seconds * 1_000_000_000)
    core.scan()
    video = next(video for video in core.videos() if video.title == '자정')

    assert ids(core, modified_preset='custom', modified_from=target.isoformat(),
               modified_to=target.isoformat()) == [video.id]
    # UTC 날짜로 거르면 이 영상이 나오므로, 위 결과가 로컬 날짜 기준임을 알 수 있다.
    assert ids(core, modified_preset='custom', modified_from=utc_day.isoformat(),
               modified_to=utc_day.isoformat()) == []


def test_modified_date_chip_resets_condition_and_is_in_filter_defaults(dated_library):
    core, _ = dated_library
    options = {**default_options(), 'modified_preset': '7'}
    chip, = filter_chips(options, {})
    assert chip['key'] == 'modified_preset'
    assert chip['label'] == '수정한 날짜: 최근 7일'
    assert core.library_view_ids(chip['reset']) == core.library_view_ids(default_options())
    assert FILTER_DEFAULTS['modified_preset'] == FILTER_DEFAULTS['modified_from'] == FILTER_DEFAULTS['modified_to'] == ''

    custom = {**default_options(), 'modified_preset': 'custom', 'modified_from': '2026-10-01'}
    chip, = filter_chips(custom, {})
    assert chip['label'] == '수정한 날짜: 2026-10-01 ~ 끝 없음'
    assert chip['reset']['modified_preset'] == chip['reset']['modified_from'] == ''
