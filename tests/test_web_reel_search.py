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
from my_video_manager.search_matching import match_spans


class ReelPlayer(Player):
    def seek_to(self, position, *, resume=False):
        self.seek = position

    def playback_options(self):
        return None


def snapshot(page):
    return json.loads(page.bridge.snapshot())


def test_reel_play_uses_web_filter_without_populating_hidden_qt_list(window_factory, core):
    video = core.videos()[0]
    mark(core, video, 10, 15)
    selected = mark(core, video, 30, 35)
    tag = core.add_highlight_tag(selected.id, '선택 태그')
    window = window_factory()
    window.player_factory = ReelPlayer
    window.navigate_web_tab('reel')
    page = window.web_host.controllers['reel']
    page.bridge.filter(tag.id)
    page.bridge.play(0)
    QApplication.processEvents()
    assert core.reel_playback.entry.highlight.id == selected.id
    assert window.pages.count() == 2


def test_reel_navigation_and_playback_return_read_entries_once(window_factory, core, monkeypatch):
    mark(core, core.videos()[0], 10, 15)
    window = window_factory()
    window.player_factory = ReelPlayer
    calls = []
    original = core.reel_entries
    monkeypatch.setattr(core, 'reel_entries', lambda *args: (calls.append(args), original(*args))[1])
    window.navigate_web_tab('reel')
    assert len(calls) == 1
    window.web_host.controllers['reel'].bridge.play(0)
    QApplication.processEvents()
    calls.clear()
    window.back_to_list()
    assert len(calls) == 1
    window.play_video(core.videos()[0].id)
    calls.clear()
    window.back_to_list()
    assert len(calls) == 1


@pytest.mark.parametrize('tab,action,args', [('reel', 'refresh', ()), ('reel', 'filter', (0,)), ('search', 'find', ('Python',))])
def test_result_changes_have_one_data_message_and_small_ack(window_factory, core, tab, action, args):
    core.prepare_search()
    window = window_factory()
    window.navigate_web_tab(tab)
    page = window.web_host.controllers[tab]
    changes = []
    page.bridge.changed.connect(changes.append)
    assert json.loads(getattr(page.bridge, action)(*args)) == {'ok': True}
    assert len(changes) == 1
    assert json.loads(changes[0]) == snapshot(page)


def test_reel_filter_selection_missing_and_current_keys(window_factory, core):
    window = window_factory()
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
    page.bridge.filter(tag.id)
    assert [e['id'] for e in snapshot(page)['entries']] == [h2.id]
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
    window = window_factory()
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
    assert snapshot(page)['status'] == '모아보기를 마쳤습니다. 다시 재생할 하이라이트를 고르세요.'
    assert core.viewings(video.id) == ()
    page.bridge.play(second.id)
    QApplication.processEvents()
    assert snapshot(page)['status'] == ''
    assert core.reel_playback.entry.highlight.id == second.id
    window.back_to_list()
    assert snapshot(page)['selectedId'] == second.id
    assert window.web_host.active_tab == 'reel'


@pytest.mark.parametrize('action', ['refresh', 'filter', 'tab-return'])
def test_reel_completion_status_clears_on_list_update(window_factory, core, action):
    highlight = mark(core, core.videos()[0], 10, 15)
    tag = core.add_highlight_tag(highlight.id, '복습')
    window = window_factory()
    window.player_factory = ReelPlayer
    window.navigate_web_tab('reel')
    page = window.web_host.controllers['reel']
    page.bridge.play(0)
    QApplication.processEvents()
    changes = []
    page.bridge.changed.connect(lambda value: changes.append(json.loads(value)))
    core.playback.report(15)
    core.advance_reel_if_due()
    window.reel.sync()
    completed = '모아보기를 마쳤습니다. 다시 재생할 하이라이트를 고르세요.'
    assert snapshot(page)['status'] == completed
    assert changes[-1]['status'] == completed
    assert sum(change['status'] == completed for change in changes) == 1
    window.reel.sync()
    assert sum(change['status'] == completed for change in changes) == 1

    if action == 'tab-return':
        window.navigate_web_tab('library')
        window.navigate_web_tab('reel')
    elif action == 'filter':
        page.bridge.filter(tag.id)
    else:
        page.bridge.refresh()
    assert snapshot(page)['status'] == ''
    assert changes[-1]['status'] == ''
    assert len(snapshot(page)['entries']) == 1


def test_search_scene_return_keeps_query_results_selection_and_playlist(window_factory, core):
    video = core.videos()[0]
    h = mark(core, video, 12.125)
    core.update_highlight(h.id, start=h.start, end=None, note='Python 장면')
    core.prepare_search()
    window = window_factory()
    window.player_factory = Player
    window.show_search()
    page = window.web_host.controllers['search']
    page.bridge.find('Python')
    data = snapshot(page)
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


@pytest.mark.parametrize('suffix,language,label', [('.ko.srt', 'ko', '한국어'), ('.srt', None, '언어 모름')])
def test_external_search_scene_language_and_return(window_factory, core, suffix, language, label):
    video = core.videos()[0]
    video.locations[0].path.with_suffix(suffix).write_text(
        '1\n00:00:12,125 --> 00:00:15,000\n외부 장면', encoding='utf-8')
    core.scan()
    core.prepare_search()
    window = window_factory()
    window.player_factory = Player
    window.show_search()
    page = window.web_host.controllers['search']
    page.bridge.find('외부장면')
    expected = snapshot(page)
    result, = expected['results']
    assert (result['source'], result['language'], result['languageLabel']) == ('외부 자막', language, label)
    assert [p['text'] for p in result['text'] if p['matched']] == ['외부 장면']
    assert json.loads(page.bridge.play(0)) == {'ok': True}
    QApplication.processEvents()
    assert core.playback.position == 12.125
    window.back_to_list()
    assert window.web_host.active_tab == 'search'
    assert snapshot(page) == expected


@pytest.mark.parametrize('source', ['transcript', 'translation'])
def test_original_and_translation_results_do_not_gain_language_chip(source):
    from my_video_manager.web_search_data import result_data

    result = result_data(SearchResult(1, '영상', source, '자막', 1, False), '자막')
    assert result['languageLabel'] is None


def test_search_preparing_empty_no_results_limit_and_missing(window_factory, core, monkeypatch):
    core.prepare_search()
    window = window_factory()
    window.show_search()
    page = window.web_host.controllers['search']
    page.bridge.find('')
    assert snapshot(page)['state'] == 'empty'
    page.bridge.find('없는낱말')
    assert snapshot(page)['state'] == 'no-results'
    page.preparation = SimpleNamespace(ready=lambda: False)
    page.bridge.find('장면')
    assert snapshot(page)['state'] == 'preparing'
    assert page.timer.isActive()
    window.navigate_web_tab('library')
    assert not page.timer.isActive()
    page.preparation = SimpleNamespace(ready=lambda: True)
    monkeypatch.setattr(core, 'search', lambda query: SearchResponse(tuple(
        SearchResult(1, '영상', 'note', '장면', 12, True) for _ in range(500)), True))
    window.show_search()
    data = snapshot(page)
    assert len(data['results']) == 500 and data['truncated']
    assert data['limit'] == 500
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


@pytest.mark.parametrize('text,query,expected', [
    ('😀 <장면>', '장면', [(3, 5)]),
    ('Straße', 's', [(0, 1), (4, 5)]),
    ('가나', '가나', [(0, 4)]),
    ('e\u0301 & <Ｅ>', 'é', [(0, 2)]),
    ('👩\u200d💻 장면 장 면', '장면', [(4, 6), (7, 10)]),
    ('한글', ' ', []),
])
def test_shared_match_spans_are_original_slices_and_web_parts_stay_equivalent(text, query, expected):
    assert match_spans(text, query) == expected
    parts = matched_parts(text, query)
    assert ''.join(part['text'] for part in parts) == text
    assert [part['text'] for part in parts if part['matched']] == [text[start:end] for start, end in expected]
