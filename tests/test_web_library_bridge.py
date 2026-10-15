"""WebChannel 공개 슬롯의 선택·필터·작업 허용 범위와 오류 응답."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
import pytest

from test_web_library_data import core
from my_video_manager.web_library_bridge import LibraryBridge
from my_video_manager.web_library_data import snapshot_data, filter_ids


class Page(QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.cards = snapshot_data(core.library_snapshot())
        self.video_ids = {v['id'] for v in self.cards}
        self.visible_ids = list(self.video_ids)
        self.gem_ids = []
        self.selected_id = self.visible_ids[0]
        self.query, self.tag_id = '', None
        self.worker = None
        self.played = []
        self.window = SimpleNamespace(play=self.played.append)

    def is_active(self):
        return self.isVisible()

    def payload(self):
        return {'videos': self.cards, 'visibleIds': self.visible_ids, 'selectedId': self.selected_id}

    def apply_filters(self):
        self.visible_ids = filter_ids(self.cards, self.query, self.tag_id)
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)

    def visible_video_ids(self):
        return tuple(self.visible_ids)

    def refresh_details(self, video_id):
        pass


@pytest.fixture
def bridge(core):
    app = QApplication.instance() or QApplication([])
    page = Page(core)
    bridge = LibraryBridge(page)
    yield bridge, page, app


def test_slots_serialize_core_data_filter_and_selection(bridge):
    bridge, page, app = bridge
    state = json.loads(bridge.snapshot())
    assert len(state['videos']) == len(page.core.videos())
    filtered = json.loads(bridge.filter('한글', 0))
    video_id, = filtered['visibleIds']
    assert json.loads(bridge.select(video_id)) == {'selectedId': video_id}
    assert json.loads(bridge.details(video_id))['has_transcript'] is False
    assert 'error' in json.loads(bridge.select(999999))
    assert 'error' in json.loads(bridge.details(999999))


def test_details_include_external_tracks_partial_success_and_failure(bridge, monkeypatch):
    bridge, page, app = bridge
    core = page.core
    video = core.videos()[0]
    path = video.locations[0].path
    assert json.loads(bridge.details(video.id))['externalSubtitles'] == []
    path.with_suffix('.smi').write_text(
        '<SYNC Start=1000><P Class=KRCC>한국어<P Class=ENCC>English', encoding='utf-8')
    path.with_suffix('.srt').write_text(
        '1\n00:00:01,000 --> 00:00:02,000\n부분 성공\n\n깨진 블록', encoding='utf-8')
    path.with_suffix('.broken.vtt').write_bytes(b'\xff\xfeX')
    core.scan()
    monkeypatch.setattr(core, 'external_subtitles', lambda *_: pytest.fail('본문 조회는 불필요'))
    data = json.loads(bridge.details(video.id))
    files = {file['name']: file for file in data['externalSubtitles']}
    assert len(files) == 3
    tracks = files[path.with_suffix('.smi').name]['subtitles']
    assert [(s['language'], s['languageLabel'], s['lineCount']) for s in tracks] == [
        ('ko', '한국어', 1), ('en', '영어', 1)]
    partial = files[path.with_suffix('.srt').name]
    assert partial['warning'] == '외부 자막: 1개 블록을 건너뜀'
    assert partial['subtitles'][0]['languageLabel'] == '언어 모름'
    assert partial['subtitles'][0]['lineCount'] == 1
    failure = files[path.with_suffix('.broken.vtt').name]
    assert failure['warning'] and failure['subtitles'] == []
    assert str(path.parent) not in json.dumps(data)
    assert data['original_lines'] == data['translated_lines'] == 0


def test_action_rejects_arbitrary_methods_and_missing_ids(bridge):
    bridge, page, app = bridge
    video_id = page.selected_id
    for name, target in [('delete_file', video_id), ('play', 999999), ('playGem', video_id), ('dismiss', video_id)]:
        assert 'error' in json.loads(bridge.action(name, target))
    assert page.played == []
    assert len(page.core.videos()) == 3


def test_play_is_queued_and_duplicate_request_cannot_reenter(bridge):
    bridge, page, app = bridge
    video_id = page.selected_id
    assert json.loads(bridge.action('play', video_id)) == {'ok': True}
    assert page.played == []
    assert 'error' in json.loads(bridge.action('play', video_id))
    app.processEvents()
    assert page.played == [video_id]
    assert not bridge.busy


def test_scanning_rejects_library_mutation(bridge):
    bridge, page, app = bridge
    page.worker = object()
    for action in ('rename', 'reconnect', 'exclude'):
        assert 'error' in json.loads(bridge.action(action, page.selected_id))


def add_highlight(core, video_id):
    core.playback.start(video_id, 12.125)
    core.execute_highlight_command(core.command_for_key('Insert'))
    core.playback.end()
    highlight, = core.highlights(video_id)
    core.update_highlight(highlight.id, start=12.125, end=20.5, note='다시 볼 장면')
    core.add_highlight_tag(highlight.id, '중요')
    return highlight.id


def test_highlight_list_serializes_times_note_and_tags_and_validates_owner(bridge):
    bridge, page, app = bridge
    video_id = page.selected_id
    assert json.loads(bridge.highlights(video_id)) == []
    hid = add_highlight(page.core, video_id)
    entry, = json.loads(bridge.highlights(video_id))
    assert (entry['id'], entry['start'], entry['end'], entry['note']) == (hid, 12.125, 20.5, '다시 볼 장면')
    assert entry['tags'][0]['name'] == '중요'
    other = next(vid for vid in page.video_ids if vid != video_id)
    for method in (bridge.playHighlight, bridge.editHighlight):
        assert 'error' in json.loads(method(other, hid))
        assert 'error' in json.loads(method(video_id, 999999))
    assert 'error' in json.loads(bridge.highlights(999999))


def test_highlight_play_uses_existing_entry_at_exact_time_and_preserves_playlist(bridge):
    bridge, page, app = bridge
    video_id = page.selected_id
    hid = add_highlight(page.core, video_id)
    page.window.play_video = lambda vid, **kwargs: page.played.append((vid, kwargs))
    assert json.loads(bridge.playHighlight(video_id, hid)) == {'ok': True}
    assert not page.played
    assert 'error' in json.loads(bridge.playHighlight(video_id, hid))
    app.processEvents()
    assert page.played == [(video_id, {'start': 12.125})]
    assert page.window.playback_list == tuple(page.visible_ids)
    assert not bridge.busy


def test_deleted_highlight_is_revalidated_before_queued_play(bridge):
    bridge, page, app = bridge
    hid = add_highlight(page.core, page.selected_id)
    errors = []
    bridge.libraryError.connect(errors.append)
    bridge.playHighlight(page.selected_id, hid)
    page.core.delete_highlight(hid)
    app.processEvents()
    assert errors and page.played == [] and not bridge.busy


def test_highlight_edit_opens_existing_editor_and_refreshes_details(bridge, monkeypatch):
    from my_video_manager.web_dialogs_entries import HighlightEditor
    bridge, page, app = bridge
    hid = add_highlight(page.core, page.selected_id)
    refreshed = []
    page.refresh_details = refreshed.append

    def save(dialog):
        assert dialog.highlight.id == hid
        dialog.core.update_highlight(hid, start=dialog.highlight.start,
                                     end=dialog.highlight.end, note='수정한 메모')

    monkeypatch.setattr(HighlightEditor, 'exec', save)
    assert json.loads(bridge.editHighlight(page.selected_id, hid)) == {'ok': True}
    app.processEvents()
    assert json.loads(bridge.highlights(page.selected_id))[0]['note'] == '수정한 메모'
    assert refreshed == [page.selected_id] and not bridge.busy
