"""코어 공개 API의 결과가 JSON 계약과 화면 필터에서 보존되는지 검증한다."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.web_library_data import snapshot_data, filter_ids, details_data, key_bindings_data, thumbnail_video_id
from my_video_manager.external_subtitles import LANGUAGES
from my_video_manager.web_external_subtitle_data import language_label


def test_every_external_language_code_has_a_display_label():
    codes = set(LANGUAGES.values())
    assert codes
    for code in codes:
        assert language_label(code) not in (code, '', '언어 모름')
    assert language_label(None) == '언어 모름'


class Media:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        destination.write_bytes(b'thumbnail')


@pytest.fixture
def core(tmp_path):
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / 'data/library.sqlite3')
    for name in ('Python 기초', 'PYTHON 응용', '한글 영상'):
        path = tmp_path / f'{name}.mkv'
        path.write_bytes(name.encode())
        core.add_file(path)
    return core


def test_snapshot_preserves_core_status_tags_and_json_without_file_paths(core):
    first = core.videos()[0]
    tag = core.add_video_tag(first.id, '강의')
    core.playback.start(first.id, 0)
    core.playback.report(40)
    core.playback.end()
    data = snapshot_data(core.library_snapshot())
    video = next(v for v in data if v['id'] == first.id)
    assert video['abandoned'] and video['resumePoint'] == 40
    assert video['stoppedPercent'] == 40
    assert video['tags'] == [{'id': tag.id, 'name': '강의'}]
    assert video['thumbnail'] == f'mvm-thumb://video/{first.id}?v=640'
    assert video['viewingCount'] == 1
    assert video['watchedSeconds'] == 40
    assert video['lastViewedAt'] == core.video_viewing_statistics()[first.id].last_viewed_at
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    assert str(core.database.parent) not in encoded
    assert json.loads(encoded) == data
    core.exclude_video(first.id)
    assert first.id not in filter_ids(snapshot_data(core.library_snapshot()), '', None)


def test_snapshot_carries_modified_date_and_rescan_refreshes_it(core, tmp_path):
    path = tmp_path / 'Python 기초.mkv'
    moment = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    os.utime(path, (moment.timestamp(), moment.timestamp()))
    core.scan()
    data = {v['id']: v for v in snapshot_data(core.library_snapshot())}
    video = next(v for v in core.videos() if v.locations[0].path == path)
    assert data[video.id]['modifiedAt'] == moment.isoformat()
    assert datetime.fromisoformat(data[video.id]['modifiedAt']) == video.modified_at

    # 파일을 바꾼 뒤 다시 검사하면 화면이 받는 값과 거르기 결과가 새 시각을 따른다.
    newer = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    os.utime(path, (newer.timestamp(), newer.timestamp()))
    core.scan()
    data = {v['id']: v for v in snapshot_data(core.library_snapshot())}
    assert data[video.id]['modifiedAt'] == newer.isoformat()
    options = {**core.library_view_options(), 'modified_preset': 'custom',
               'modified_from': '2026-10-10', 'modified_to': '2026-10-14'}
    assert core.library_view_ids(options) == [video.id]

    path.unlink()
    core.scan()
    data = {v['id']: v for v in snapshot_data(core.library_snapshot())}
    assert data[video.id]['missing'] and data[video.id]['modifiedAt'] is None


def test_combined_filter_unicode_casefold_and_details_match_public_core(core):
    video = next(v for v in core.videos() if '응용' in v.title)
    tag = core.add_video_tag(video.id, '강의')
    data = snapshot_data(core.library_snapshot())
    assert len(filter_ids(data, ' python ', None)) == 2
    assert filter_ids(data, 'python', tag.id) == [video.id]
    assert filter_ids(data, '한글', tag.id) == []
    assert filter_ids(data, '한글', None)
    details = details_data(core.library_details(video.id))
    assert details['original_lines'] == 0 and details['highlight_count'] == 0
    assert details['has_transcript'] is False
    assert details['no_speech'] is False and details['translation_skip_reason'] is None


@pytest.mark.parametrize('url', [
    'file:///C:/secret', 'mvm-thumb://1/../../secret', 'mvm-thumb://1?path=secret',
    'mvm-thumb://1#secret', 'mvm-thumb://user@1', 'mvm-thumb://1:80',
    'mvm-thumb://%31', 'mvm-thumb://0', 'mvm-thumb://-1', 'mvm-thumb://１',
    'mvm-thumb://2147483648', 'mvm-thumb:///C:/secret',
    'mvm-thumb://video/1/../../secret', 'mvm-thumb://video/%31',
    'mvm-thumb://video/1?path=secret', 'mvm-thumb://video/1#secret',
    'mvm-thumb://video/0', 'mvm-thumb://video/2147483648',
])
def test_thumbnail_url_rejects_paths_and_non_ids(url):
    assert thumbnail_video_id(url) is None


def test_thumbnail_url_accepts_only_positive_id():
    assert thumbnail_video_id('mvm-thumb://video/123?v=640') == 123
    assert thumbnail_video_id('mvm-thumb://video/123?v=640&path=secret') is None
    assert thumbnail_video_id('mvm-thumb://video/123') == 123
    assert thumbnail_video_id('mvm-thumb://video/123/') is None


def test_generated_types_match_python_contract():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/generate_web_types.py'), '--check'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout


def test_data_adapter_does_not_import_qt():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import my_video_manager.web_library_data; assert not any(n.startswith('PySide6') for n in sys.modules)"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_snapshot_statistics_keep_glance_and_reel_rules(core):
    first, second, untouched = core.videos()
    core.playback.start(first.id, 0)
    core.playback.report(3)
    core.playback.end()
    core.playback.start(second.id, 0, record_viewing=False)
    core.playback.report(80)
    core.playback.end()
    data = {v['id']: v for v in snapshot_data(core.library_snapshot())}
    for video in data.values():
        assert video['viewingCount'] == 0 and video['watchedSeconds'] == 0
    assert data[first.id]['lastViewedAt'] is not None
    assert data[second.id]['lastViewedAt'] is None
    assert data[untouched.id]['lastViewedAt'] is None


def test_subtitle_badge_matches_statistics_including_empty_transcript(core):
    from my_video_manager.subtitles import TranscriberResult

    class EmptyTranscriber:
        def transcribe(self, *args, **kwargs):
            return TranscriberResult('ko', ())

    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=core.database, transcriber=EmptyTranscriber())
    first = core.videos()[0]
    core.request_subtitles(first.id)
    core.process_next_subtitle()
    ids = core.subtitled_video_ids()
    assert ids == {first.id}
    assert core.library_details(first.id).has_transcript
    data = snapshot_data(core.library_snapshot(), ids)
    assert sum(v['hasSubtitles'] for v in data) == core.viewing_statistics(7).library.subtitled_video_count == 1
    core.exclude_video(first.id)
    data = snapshot_data(core.library_snapshot(), core.subtitled_video_ids())
    assert sum(v['hasSubtitles'] for v in data) == core.viewing_statistics(7).library.subtitled_video_count == 0


def test_highlight_tags_are_scoped_sorted_and_complete(core):
    from my_video_manager.web_library_data import highlights_data

    first, other, _ = core.videos()
    for video in (first, other):
        core.playback.start(video.id, 1)
        for index in range(25):
            core.playback.report(index + 1)
            core.execute_highlight_command(core.command_for_key('Insert'))
        core.playback.end()
    highlight = core.highlights(first.id)[0]
    core.add_highlight_tag(highlight.id, 'Zulu')
    core.add_highlight_tag(highlight.id, 'Alpha')
    expected = {h.id: core.highlight_tags(h.id) for h in core.highlights(first.id)}
    assert core.highlight_tags_map(first.id) == expected
    entries = highlights_data(core, first.id)
    assert len(entries) == 25
    assert [h['id'] for h in entries] == [h.id for h in core.highlights(first.id)]
    assert not {h['id'] for h in entries} & {h.id for h in core.highlights(other.id)}
    assert [t['name'] for t in entries[0]['tags']] == ['Alpha', 'Zulu']
    assert all(h['tags'] == [] for h in entries[1:])


def test_key_bindings_follow_current_bindings_including_multiple_and_unassigned_keys(core):
    data = key_bindings_data(core.key_bindings())
    assert data == {'randomPlay': 'Ctrl+Shift+R', 'highlightGuidance': '재생 중 Insert 또는 Delete로 기억할 장면을 남기세요.'}

    def save(**changes):
        core.save_key_bindings({row.command: changes.get(row.command.kind.value, row.keys) for row in core.key_bindings()})

    save(random_play=('Ctrl+Alt+R', 'Alt+Shift+F12'), point_highlight=(), range_highlight=('N', 'Shift+N'))
    data = key_bindings_data(core.key_bindings())
    assert data == {'randomPlay': 'Ctrl+Alt+R / Alt+Shift+F12', 'highlightGuidance': '재생 중 N / Shift+N로 기억할 장면을 남기세요.'}
    save(random_play=(), range_highlight=())
    data = key_bindings_data(core.key_bindings())
    assert data['randomPlay'] == '' and 'Insert' not in data['highlightGuidance'] and '키 배치에서' in data['highlightGuidance']
