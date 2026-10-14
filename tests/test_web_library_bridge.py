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

    def payload(self):
        return {'videos': self.cards, 'visibleIds': self.visible_ids, 'selectedId': self.selected_id}

    def apply_filters(self):
        self.visible_ids = filter_ids(self.cards, self.query, self.tag_id)
        if self.selected_id not in self.visible_ids:
            self.selected_id = next(iter(self.visible_ids), None)


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
