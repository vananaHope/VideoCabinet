"""웹 공개 브리지로 재생·복습과 검색 상태 보존을 검증한다."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from test_web_library_data import core
from test_web_library_page import window_factory
from test_library_return_ui import Player
from test_reel import mark
from my_video_manager.core import Command, CommandType
from my_video_manager.search import SearchResponse, SearchResult
from my_video_manager.web_search_data import matched_parts


class ReelPlayer(Player):
    def seek_to(self, position, *, resume=False):
        self.seek = position

    def playback_options(self):
        return None


def snapshot(page):
    return json.loads(page.bridge.snapshot())


def test_reel_filter_selection_missing_and_current_keys(window_factory, core):
    window = window_factory('1')
    window.navigate_web_tab('reel')
    page = window.web_host.controllers['reel']
    assert 'Insert' in snapshot(page)['emptyDescription']
    bindings = {row.command: row.keys for row in core.key_bindings()}
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ('F7',)
    core.save_key_bindings(bindings)
    window.reel.refresh_guidance()
    assert 'F7' in snapshot(page)['emptyDescription']
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ('Insert',)
    core.save_key_bindings(bindings)
    first, second = core.videos()[:2]
    h1, h2 = mark(core, first, 10, 20), mark(core, second, 30)
    tag = core.add_highlight_tag(h2.id, '복습')
    page.bridge.refresh()
    assert len(snapshot(page)['entries']) == 2
    page.bridge.select(h2.id)
    page.bridge.refresh()
    assert snapshot(page)['selectedId'] == h2.id
    assert [e['id'] for e in json.loads(page.bridge.filter(tag.id))['entries']] == [h2.id]
    assert 'error' in json.loads(page.bridge.play(h1.id))
    for location in second.locations:
        location.path.unlink()
    core.scan()
    page.bridge.refresh()
    assert snapshot(page)['entries'][0]['missing']
    assert 'error' in json.loads(page.bridge.play(h2.id))
    core.delete_tag(tag.id)
    page.bridge.refresh()
    assert snapshot(page)['tagId'] == 0


def test_reel_reuses_playback_auto_advance_repeat_and_records_only_revisit(window_factory, core):
    video = core.videos()[0]
    first, second = mark(core, video, 10, 15), mark(core, video, 30, 35)
    window = window_factory('1')
    window.player_factory = ReelPlayer
    window.navigate_web_tab('reel')
    page = window.web_host.controllers['reel']
    assert json.loads(page.bridge.play(0)) == {'ok': True}
    assert 'error' in json.loads(page.bridge.play(0))
    QApplication.processEvents()
    assert core.reel_playback.entry.highlight.id == first.id
    assert window.pages.currentWidget() is window.playback_page
    core.execute_highlight_command(Command(CommandType.TOGGLE_REEL_REPEAT))
    core.playback.report(15)
    core.advance_reel_if_due()
    window.reel.sync()
    assert core.reel_playback.entry.highlight.id == first.id
    core.execute_highlight_command(Command(CommandType.TOGGLE_REEL_REPEAT))
    core.playback.report(15)
    core.advance_reel_if_due()
    window.reel.sync()
    assert core.reel_playback.entry.highlight.id == second.id
    core.playback.report(35)
    core.advance_reel_if_due()
    window.reel.sync()
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == 'reel'
    assert all(e['lastRevisited'] for e in snapshot(page)['entries'])
    assert core.viewings(video.id) == ()
    page.bridge.play(second.id)
    QApplication.processEvents()
    assert core.reel_playback.entry.highlight.id == second.id
    window.back_to_list()
    assert snapshot(page)['selectedId'] == second.id
    assert window.web_host.active_tab == 'reel'


def test_search_scene_return_keeps_query_results_selection_and_playlist(window_factory, core):
    video = core.videos()[0]
    h = mark(core, video, 12.125)
    core.update_highlight(h.id, start=h.start, end=None, note='Python 장면')
    core.prepare_search()
    window = window_factory('1')
    window.player_factory = Player
    window.show_search()
    page = window.web_host.controllers['search']
    data = json.loads(page.bridge.find('Python'))
    index = next(i for i, r in enumerate(data['results']) if r['start'] == 12.125)
    page.bridge.select(index)
    expected = snapshot(page)
    assert json.loads(page.bridge.play(index)) == {'ok': True}
    QApplication.processEvents()
    assert core.playback.position == 12.125
    assert window.playback_list == tuple(dict.fromkeys(r['videoId'] for r in data['results']))
    window.back_to_list()
    assert window.pages.currentWidget() is window.web_host and window.web_host.active_tab == 'search'
    assert snapshot(page) == expected
    window.navigate_web_tab('library')
    window.navigate_web_tab('search')
    assert snapshot(page) == expected


def test_search_preparing_empty_no_results_limit_and_missing(window_factory, core, monkeypatch):
    core.prepare_search()
    window = window_factory('1')
    window.show_search()
    page = window.web_host.controllers['search']
    assert json.loads(page.bridge.find(''))['state'] == 'empty'
    assert json.loads(page.bridge.find('없는낱말'))['state'] == 'no-results'
    page.preparation = SimpleNamespace(ready=lambda: False)
    assert json.loads(page.bridge.find('장면'))['state'] == 'preparing'
    assert page.timer.isActive()
    window.navigate_web_tab('library')
    assert not page.timer.isActive()
    page.preparation = SimpleNamespace(ready=lambda: True)
    monkeypatch.setattr(core, 'search', lambda query: SearchResponse(tuple(
        SearchResult(1, '영상', 'note', '장면', 12, True) for _ in range(500)), True))
    window.show_search()
    data = snapshot(page)
    assert len(data['results']) == 500 and data['truncated']
    assert 'error' in json.loads(page.bridge.play(0))
    assert core.playback.session is None
    assert 'error' in json.loads(page.bridge.select(500))


@pytest.mark.parametrize('text,query,match', [
    ('앞 Hello World 뒤', 'helloworld', 'Hello World'),
    ('앞 ＡＢＣ 뒤', 'abc', 'ＡＢＣ'), ('앞 Straße 뒤', 'strasse', 'Straße'),
    ('앞 가 뒤', '가', '가'), ('😀 <장면>', '장면', '장면'),
])
def test_web_search_highlight_preserves_normalized_match_and_literal_markup(text, query, match):
    parts = matched_parts(text, query)
    assert ''.join(p['text'] for p in parts) == text
    assert [p['text'] for p in parts if p['matched']] == [match]
