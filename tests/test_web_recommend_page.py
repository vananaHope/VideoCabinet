"""추천 탭의 공개 브리지·탭 단축키·재생 왕복을 offscreen에서 검증한다."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_web_library_page import window_factory
from test_web_library_data import core
from test_library_return_ui import Player
from qt_wait import wait_for
from my_video_manager.web_contract import TABS


def abandon(core, *videos):
    for video in videos:
        core.playback.start(video.id, 0)
        core.playback.report(40)
        core.playback.end()


def rows(page):
    return [(row['kind'], [item['video']['id'] for item in row['items']]) for row in json.loads(page.bridge.snapshot())['rows']]


@pytest.fixture
def recommend(window_factory, core):
    abandon(core, *core.videos()[:2])
    window = window_factory()
    window.player_factory = Player
    window.navigate_web_tab('recommend')
    return window, window.web_host.controllers['recommend']


def test_recommend_tab_follows_library_and_page_keys_cover_eight_tabs(window_factory):
    assert [name for name, _ in TABS[:3]] == ['library', 'recommend', 'reel']
    window = window_factory()
    host = window.web_host
    window.activateWindow()
    for number, (name, _) in enumerate(TABS, start=1):
        QTest.keyClick(host.view, Qt.Key(Qt.Key.Key_0 + number), Qt.KeyboardModifier.ControlModifier)
        assert host.active_tab == name
    QTest.keyClick(host.view, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert host.active_tab == 'recommend' and window.pages.currentWidget() is host


def test_snapshot_lists_rows_with_video_cards_and_reasons(recommend, core):
    window, page = recommend
    first, second, third = core.videos()
    state = json.loads(page.bridge.snapshot())
    assert state['loaded'] and state['error'] == '' and state['rowLimit'] == 20
    assert [(row['kind'], row['title']) for row in state['rows']] == [('continue_watching', '이어 보기')]
    assert {item['video']['id'] for item in state['rows'][0]['items']} == {first.id, second.id}
    item = state['rows'][0]['items'][0]
    assert item['reason'] == '40%에서 멈췄어요' and item['video']['abandoned']
    assert str(core.database.parent) not in json.dumps(state, ensure_ascii=False)
    # 라이브러리 계약에는 추천 데이터가 남지 않는다.
    assert not {'gems', 'gemError'} & set(json.loads(window.library_page.bridge.snapshot()))


def test_dismiss_and_restore_apply_to_every_row_and_reject_unknown_ids(recommend, core):
    window, page = recommend
    first, second, third = core.videos()
    _, ids = rows(page)[0]
    assert 'error' in json.loads(page.bridge.dismiss(third.id))
    assert 'error' in json.loads(page.bridge.restore(first.id))
    assert json.loads(page.bridge.dismiss(ids[0])) == {'ok': True}
    assert rows(page) == [('continue_watching', ids[1:])]
    assert [v.id for v in core.dismissed_videos()] == [ids[0]]
    assert ids[0] in {v.id for v in core.videos()}  # 라이브러리에는 남는다.
    assert json.loads(page.bridge.restore(ids[0])) == {'ok': True}
    assert rows(page) == [('continue_watching', ids)]
    assert core.dismissed_videos() == ()
    for video_id in ids:
        page.bridge.dismiss(video_id)
    assert rows(page) == []  # 빈 줄은 보이지 않는다.


def test_play_uses_row_order_and_returns_to_recommend_tab_with_card_focus(recommend, core):
    window, page = recommend
    host = window.web_host
    _, ids = rows(page)[0]
    wait_for(lambda: host._frontend_ready and 'recommend' in host._ready_pages and host._pending_focus is None)
    assert 'error' in json.loads(page.bridge.play(core.videos()[2].id))
    assert json.loads(page.bridge.play(ids[1])) == {'ok': True}
    assert 'error' in json.loads(page.bridge.play(ids[1]))  # 대기 중인 재생과 겹치지 않는다.
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    assert not page.bridge.busy
    assert window.playback_list == tuple(ids)
    requests = []
    page.focus_requested.connect(requests.append)
    window.back_to_list()
    assert host.active_tab == 'recommend' and window.pages.currentWidget() is host
    assert requests == ['recommendations']


def test_emergency_hide_during_recommendation_playback_reopens_same_scene_then_returns(recommend, core, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window, page = recommend
    host = window.web_host
    _, ids = rows(page)[0]
    page.bridge.perform_play(ids[0])
    window.emergency_hide()
    assert not window.isVisible() and core.playback.session.video_id == ids[0]
    window.tray.open()
    assert window.pages.currentWidget() is window.playback_page
    window.back_to_list()
    assert host.active_tab == 'recommend'


def test_show_dismissed_opens_folder_section(recommend):
    window, page = recommend
    host = window.web_host
    requested = []
    host.controllers['folders'].bridge.foldersFocusRequested.connect(requested.append)
    host.bridge.ready()
    host.controllers['folders'].bridge.ready()
    page.show_dismissed()
    assert host.active_tab == 'folders' and requested[-1] == 'folders-dismissed'


def test_recommendation_failure_stays_on_recommend_tab(recommend, core, monkeypatch):
    window, page = recommend
    core.settings.set('recommend.revisit_days', -1)
    window.navigate_web_tab('recommend')
    state = json.loads(page.bridge.snapshot())
    assert state['rows'] == [] and '추천 기간' in state['error']
    window.navigate_web_tab('library')
    assert json.loads(window.library_page.bridge.snapshot())['videos']


def test_library_refresh_updates_visible_recommendations(recommend, core):
    window, page = recommend
    _, ids = rows(page)[0]
    core.playback.start(ids[0], 0)
    core.playback.report(95)
    core.playback.end()
    window.refresh()
    assert rows(page) == [('continue_watching', ids[1:])]
