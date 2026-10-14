"""코어 공개 API의 결과가 JSON 계약과 화면 필터에서 보존되는지 검증한다."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.web_library_data import snapshot_data, filter_ids, details_data, thumbnail_video_id


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
    assert video['thumbnail'] == f'mvm-thumb://video/{first.id}'
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    assert str(core.database.parent) not in encoded
    assert json.loads(encoded) == data
    core.exclude_video(first.id)
    assert first.id not in filter_ids(snapshot_data(core.library_snapshot()), '', None)


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
