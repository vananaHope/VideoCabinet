"""#267 첫 진입은 첫 화면의 카드와 저장된 보기 조건을 먼저 보내고, 나머지 카드는 화면을 그린 뒤 나눠 받는다.

실제 웹 셸(offscreen)과 가짜 플레이어로 검증한다. 응답 지연은 웹 쪽 WebChannel 객체를 감싸 첫 라이브러리 스냅숏이나
나머지 카드(videos) 응답을 붙잡았다가 넘기는 방식으로 재현한다(제품 코드에 시험용 지연을 넣지 않는다).
"""
from datetime import datetime, timezone
import json
import math
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QSystemTrayIcon

from qt_wait import wait_for
from test_emergency_hide_ui import Player
from test_web_library_data import Media
from test_web_library_loading import click, js
from test_web_tab_reshow import COUNT, GRID, QUERY, SELECTED, active_element, view
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.ui import MainWindow
from my_video_manager.web_library_page import SCREEN_VIDEOS
from my_video_manager.web_shell import WebShellHost

VIDEOS = 200
# 문서를 만들 때 넣는다. 첫 스냅숏·나머지 카드 응답·밀어 보내는 갱신을 붙잡고, 그린 프레임마다 사용자가 보는 배치를 기록한다.
# 붙잡은 갱신은 __releasePushes(true)로 도착 순서를 뒤집어 넘길 수 있다. 나머지 카드 요청은 코어에 보내기 전에 붙잡아
# (__deferVideos) 코어가 나중의 라이브러리 상태로 응답하게 할 수 있다.
RECORDER = """(() => {
  let channelClass, holdSnapshot = %(hold_snapshot)s, releaseSnapshot = null
  const heldVideos = [], heldPushes = [], deferredVideos = []
  window.__holdVideos = %(hold_videos)s
  window.__deferVideos = %(defer_videos)s
  window.__holdPushes = false
  window.__videoRequests = 0
  window.__requestedIds = []
  window.__videoReplies = []
  window.__releaseLibrary = () => { holdSnapshot = false; releaseSnapshot?.() }
  window.__releaseVideos = () => { window.__holdVideos = false; for (const deliver of heldVideos.splice(0)) deliver() }
  window.__heldVideos = () => heldVideos.length
  window.__deferredVideos = () => deferredVideos.length
  window.__sendVideos = () => { window.__deferVideos = false; for (const send of deferredVideos.splice(0)) send() }
  window.__heldPushes = () => heldPushes.length
  window.__releasePushes = reversed => {
    window.__holdPushes = false
    const pushes = heldPushes.splice(0)
    for (const deliver of reversed ? pushes.reverse() : pushes) deliver()
  }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const library = channel.objects.library, snapshot = library.snapshot, videos = library.videos
        library.snapshot = reply => snapshot.call(library, json => {
          if (holdSnapshot) { releaseSnapshot = () => reply(json); window.__heldSnapshot = true } else reply(json)
        })
        library.videos = (ids, reply) => {
          window.__videoRequests++
          window.__requestedIds.push(JSON.parse(ids))
          const send = () => videos.call(library, ids, json => {
            window.__videoReplies.push(JSON.parse(json))
            if (window.__holdVideos) heldVideos.push(() => reply(json)); else reply(json)
          })
          if (window.__deferVideos) deferredVideos.push(send); else send()
        }
        const changed = library.libraryChanged, connect = changed.connect.bind(changed), disconnect = changed.disconnect.bind(changed)
        const wrapped = new Map()
        changed.connect = callback => {
          const hold = json => { if (window.__holdPushes) heldPushes.push(() => callback(json)); else callback(json) }
          wrapped.set(callback, hold)
          connect(hold)
        }
        changed.disconnect = callback => disconnect(wrapped.get(callback) ?? callback)
        ready(channel)
      })
    }
  } })
  const box = element => {
    if (!element) return null
    const r = element.getBoundingClientRect()
    return [r.x, r.y, r.width, r.height].map(value => Math.round(value * 10) / 10)
  }
  const frames = window.__frames = []
  const sample = () => {
    const grid = document.getElementById('library-grid')
    if (grid) {
      const columns = Number(grid.getAttribute('aria-colcount'))
      const first = [...grid.querySelectorAll('[role=gridcell], [data-slot=video-card-placeholder]')].slice(0, columns)
      frames.push({
        busy: grid.getAttribute('aria-busy') === 'true', columns, cells: first.map(box),
        controls: Object.fromEntries(['#library-grid', '#library-folder-panel', 'aside[aria-label="선택 영상 상세"]', '[aria-label="적용한 검색 조건"]']
          .map(selector => [selector, box(document.querySelector(selector))])),
        chips: [...document.querySelectorAll('[aria-label="적용한 검색 조건"] button[title]')].map(button => button.title),
      })
    }
    if (!window.__stopFrames) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
})()"""
PLACEHOLDER_CELLS = f'{GRID}.querySelectorAll("[data-slot=video-card-placeholder][role=gridcell]").length'
CARD_CELLS = f'{GRID}.querySelectorAll("button[role=gridcell]").length'
DETAIL_BUSY = '!!document.querySelector(\'aside[aria-label="선택 영상 상세"] [aria-busy=true]\')'
DETAIL_TEXT = 'document.querySelector(\'aside[aria-label="선택 영상 상세"]\').innerText'


@pytest.fixture
def library(tmp_path):
    """제목에 clip이 들어간 영상 200개(첫 화면 카드 수보다 많다). 시작 검사·자동 감지는 꺼서 다른 갱신이 끼지 않게 한다."""
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / 'data/library.sqlite3')
    for index in range(VIDEOS):
        path = tmp_path / f'clip {index:03}.mkv'
        path.write_bytes(f'video {index}'.encode())
        core.add_file(path)
    core.set_automatic_detection_enabled(False)
    return core


@pytest.fixture
def open_window(library, qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []
    start = WebShellHost.start
    recorder = {}

    def start_recorded(host):
        script = QWebEngineScript()
        script.setName('first-screen-recorder')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(RECORDER % {key: json.dumps(value) for key, value in recorder.items()})
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', start_recorded)

    def create(*, hold_snapshot=False, hold_videos=False, defer_videos=False, **options):
        library.save_library_view_options({**default_options(), **options})
        recorder.update(hold_snapshot=hold_snapshot, hold_videos=hold_videos, defer_videos=defer_videos)
        window = MainWindow(library, player_factory=Player)
        monkeypatch.setattr(window.tray.icon, 'showMessage', lambda *args: None)
        windows.append(window)
        window.resize(1100, 720)
        window.show()
        window.activateWindow()
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def ready(window):
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    wait_for(lambda: js(window, CARD_CELLS) > 0)
    # 첫 진입의 기본 초점이 자리 잡은 뒤에 조작한다. 늦게 온 첫 초점이 시험의 입력을 가로채지 않게 한다.
    wait_for(lambda: active_element(window) == 'library-grid')


def selects(window, video_id):
    """화면 선택과 코어 선택이 모두 video_id다."""
    return js(window, SELECTED) == f'video-{video_id}' and window.library_page.selected_video_id() == video_id


@pytest.mark.parametrize('options', [dict(card_size='small', query='clip'), dict(card_size='small', query='clip', mode='folders')],
                         ids=['small-chip', 'folder-panel'])
def test_placeholders_use_saved_card_size_chips_and_folder_panel(open_window, options):
    # 저장된 카드 크기 '작게'·검색어 칩·폴더 패널. 기본 보기 조건으로 자리 표시를 그리면 데이터가 올 때 열 수가 바뀌고
    # 칩 줄이 채워지며 폴더 패널이 나타나 격자가 밀린다(#260 한계).
    window = open_window(hold_snapshot=True, **options)
    wait_for(lambda: js(window, 'window.__frames.some(frame => frame.busy)'))
    # 데이터 전부터 저장된 검색어가 입력란에 있다.
    assert js(window, f'{QUERY}.value') == 'clip'
    js(window, 'window.__releaseLibrary()')
    ready(window)
    wait_for(lambda: js(window, 'window.__frames.at(-1).busy === false && window.__frames.at(-1).cells.length > 0'))
    js(window, 'window.__stopFrames = true')
    frames = json.loads(js(window, 'JSON.stringify(window.__frames)'))
    loading, final = [frame for frame in frames if frame['busy']], frames[-1]
    assert loading and final['chips'] == ['제목: clip']
    if options.get('mode') == 'folders':
        assert final['controls']['#library-folder-panel'], final
    else:
        # 기본 카드 크기(보통)는 이 폭에서 2열이다. 작은 카드는 그보다 많다.
        assert final['columns'] > 2 and not final['controls']['#library-folder-panel'], final
    for frame in frames:
        # 자리 표시의 첫 프레임부터 열 수·첫 줄 칸·격자·폴더 패널·상세 패널·칩 줄의 경계와 칩이 데이터 뒤와 같다.
        assert frame['columns'] == final['columns'] and frame['cells'] == final['cells'], frame
        assert frame['controls'] == final['controls'] and frame['chips'] == final['chips'], frame


def test_scroll_select_and_search_before_remaining_cards_arrive(open_window, library):
    window = open_window(hold_videos=True, card_size='small')
    ready(window)
    page = window.library_page
    order = page.visible_ids
    # 첫 화면의 카드만 받았다. 개수와 격자 줄 수(스크롤 높이)는 처음부터 결과 전체 기준이다.
    wait_for(lambda: js(window, 'window.__videoRequests') > 0)
    assert js(window, COUNT) == f'등록 영상 {VIDEOS}개 · 표시 {VIDEOS}개'
    columns = int(js(window, f'{GRID}.getAttribute("aria-colcount")'))
    assert int(js(window, f'{GRID}.getAttribute("aria-rowcount")')) == math.ceil(VIDEOS / columns)
    height = js(window, f'{GRID}.scrollHeight')

    # 아직 받지 못한 끝까지 스크롤하면 같은 크기의 자리 표시가 보이고 스크롤 높이가 그대로다.
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    last = order[-1]
    wait_for(lambda: js(window, f'document.getElementById("video-{last}")?.dataset.slot ?? ""') == 'video-card-placeholder')
    assert js(window, CARD_CELLS) == 0 and js(window, PLACEHOLDER_CELLS) > 0
    assert js(window, f'{GRID}.scrollHeight') == height

    # 자리 표시를 눌러 고르고 방향키로 옮긴다. 화면과 코어 선택이 같고, 상세는 카드가 올 때까지 기다림 표시를 둔다.
    click(window, f'#video-{last}')
    wait_for(lambda: selects(window, last))
    assert js(window, DETAIL_BUSY)
    wait_for(lambda: active_element(window) == 'library-grid')
    QTest.keyClick(view(window), Qt.Key.Key_Left)
    wait_for(lambda: selects(window, order[-2]))
    assert js(window, DETAIL_BUSY)

    # 빠른 검색 결과는 카드를 기다리지 않고 바로 보인다. 고른 영상이 결과에 남으므로 선택도 그대로다.
    click(window, '[aria-label="영상 제목 빠른 검색"]')
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    QTest.keyClicks(view(window), 'clip 19')
    wait_for(lambda: js(window, COUNT) == f'등록 영상 {VIDEOS}개 · 표시 10개')
    assert js(window, f'{QUERY}.value') == 'clip 19'
    assert page.visible_ids == order[-10:]
    wait_for(lambda: js(window, PLACEHOLDER_CELLS) == 10)
    assert selects(window, order[-2])

    # 나머지 카드가 오면 같은 자리를 채운다. 결과·선택·검색어는 그대로다.
    js(window, 'window.__releaseVideos()')
    wait_for(lambda: js(window, PLACEHOLDER_CELLS) == 0 and js(window, CARD_CELLS) == 10)
    assert js(window, f'{GRID}.querySelector("[role=gridcell]").textContent').startswith('clip 190')
    wait_for(lambda: not js(window, DETAIL_BUSY) and 'clip 198' in js(window, DETAIL_TEXT))
    assert selects(window, order[-2]) and js(window, f'{QUERY}.value') == 'clip 19'
    # 받은 카드를 Enter로 재생한다.
    js(window, f'{GRID}.focus(); true')
    wait_for(lambda: active_element(window) == 'library-grid')
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    assert window.core.playback.session.video_id == order[-2]


def test_remaining_cards_fill_after_first_screen_without_moving_the_view(open_window):
    window = open_window(card_size='small')
    ready(window)
    page = window.library_page
    first = js(window, f'{GRID}.querySelector("[role=gridcell]").id')
    # 나머지 카드는 따로 나눠 받아 끝까지 스크롤해도 카드가 있다. 보던 자리와 선택은 그대로다.
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: js(window, f'!!document.getElementById("video-{page.visible_ids[-1]}")'))
    wait_for(lambda: js(window, PLACEHOLDER_CELLS) == 0 and js(window, CARD_CELLS) > 0)
    assert js(window, f'{GRID}.scrollTop') > 0
    assert first == f'video-{page.visible_ids[0]}' and selects(window, page.visible_ids[0])


def test_change_push_carries_changed_cards_and_names_the_rest(open_window, library):
    window = open_window(card_size='small')
    ready(window)
    page = window.library_page
    order = list(page.visible_ids)
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: js(window, f'!!document.getElementById("video-{order[-1]}")') and js(window, PLACEHOLDER_CELLS) == 0)
    js(window, f'{GRID}.scrollTop = 0; true')
    pushes = []
    page.bridge.libraryChanged.connect(lambda value: pushes.append(json.loads(value)))

    # 한 영상만 바뀌면 그 카드 하나만 보낸다. 웹은 그 카드만 바꾼다.
    tag = '나중에 볼 영상'
    library.add_video_tag(order[0], tag)
    window.refresh()
    wait_for(lambda: len(pushes) == 1)
    assert [card['id'] for card in pushes[0]['videos']] == [order[0]] and pushes[0]['staleIds'] == []
    assert pushes[0]['videoCount'] == VIDEOS and pushes[0]['visibleIds'] == order
    wait_for(lambda: tag in js(window, f'document.getElementById("video-{order[0]}").textContent'))

    # 첫 화면보다 많이 바뀌면 결과 앞쪽 카드만 담고 나머지는 ID로 알린다. 웹은 그 카드를 다시 받아 바꾼다.
    changed = order[-100:]
    for video_id in changed:
        library.add_video_tag(video_id, '정리')
    window.refresh()
    wait_for(lambda: len(pushes) == 2)
    assert [card['id'] for card in pushes[1]['videos']] == changed[:SCREEN_VIDEOS]
    assert pushes[1]['staleIds'] == changed[SCREEN_VIDEOS:]
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: '정리' in js(window, f'document.getElementById("video-{order[-1]}")?.textContent ?? ""'))
    assert js(window, PLACEHOLDER_CELLS) == 0


def card_text(window, video_id):
    return js(window, f'document.getElementById("video-{video_id}")?.textContent ?? ""')


def deliver(window, release):
    """붙잡은 응답을 넘기고 그 처리가 그려진 두 프레임 뒤까지 기다린다."""
    js(window, f'window.__deliveredPaint = false; {release}; '
               'requestAnimationFrame(() => requestAnimationFrame(() => window.__deliveredPaint = true)); true')
    wait_for(lambda: js(window, 'window.__deliveredPaint === true'))


def test_late_first_snapshot_keeps_newer_card(open_window, library):
    # 첫 스냅숏 응답이 그 뒤의 갱신보다 늦게 와도, 갱신이 담은 더 새 카드(방금 붙인 태그)를 옛 카드로 되돌리지 않는다.
    window = open_window(hold_snapshot=True)
    wait_for(lambda: js(window, 'window.__heldSnapshot === true'))
    target = window.library_page.visible_ids[0]
    library.add_video_tag(target, 'LATEST267')
    window.refresh()
    wait_for(lambda: 'LATEST267' in card_text(window, target))
    deliver(window, 'window.__releaseLibrary()')
    assert 'LATEST267' in card_text(window, target), card_text(window, target)


def test_late_card_reply_keeps_newer_card(open_window, library):
    # 화면을 그린 뒤 요청한 나머지 카드 응답이 바뀐 카드를 담은 갱신보다 늦게 와도 더 새 카드를 덮지 않는다.
    window = open_window(hold_videos=True, card_size='small')
    ready(window)
    wait_for(lambda: js(window, 'window.__videoRequests') > 0)
    target = window.library_page.visible_ids[-1]
    library.add_video_tag(target, 'LATEST267')
    window.refresh()
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: 'LATEST267' in card_text(window, target))
    deliver(window, 'window.__releaseVideos()')
    assert 'LATEST267' in card_text(window, target), card_text(window, target)


def test_out_of_order_pushes_keep_each_newest_card(open_window, library):
    # 연속한 갱신이 뒤바뀐 순서로 도착해도 카드마다 가장 새 내용이 남는다. 늦게 온 앞 갱신에만 든 다른 카드의 변경도 잃지 않는다.
    window = open_window(card_size='small')
    ready(window)
    first, second = window.library_page.visible_ids[:2]
    pushes = []
    window.library_page.bridge.libraryChanged.connect(pushes.append)
    js(window, 'window.__holdPushes = true')
    library.add_video_tag(first, '앞변경')
    library.add_video_tag(second, '앞변경')
    window.refresh()
    library.add_video_tag(first, '뒤변경')
    window.refresh()
    wait_for(lambda: len(pushes) == 2 and js(window, 'window.__heldPushes()') == 2)
    deliver(window, 'window.__releasePushes(true)')
    assert '뒤변경' in card_text(window, first), card_text(window, first)
    assert '앞변경' in card_text(window, second), card_text(window, second)


def test_late_card_reply_after_many_stale_ids_shows_newest_cards(open_window, library):
    # 첫 화면보다 많이 바뀌어 일부만 담고 나머지를 staleIds로 알린 갱신 뒤에, 그 전에 요청한 옛 카드 응답이 와도
    # 갱신이 담은 카드는 그대로이고 알린 카드는 다시 받아 최신이 된다.
    window = open_window(hold_videos=True, card_size='small')
    ready(window)
    wait_for(lambda: js(window, 'window.__videoRequests') > 0)
    order = list(window.library_page.visible_ids)
    pushes = []
    window.library_page.bridge.libraryChanged.connect(lambda value: pushes.append(json.loads(value)))
    changed = order[-100:]
    for video_id in changed:
        library.add_video_tag(video_id, '정리')
    window.refresh()
    wait_for(lambda: len(pushes) == 1)
    sent, stale = changed[:SCREEN_VIDEOS], changed[SCREEN_VIDEOS:]
    assert pushes[0]['staleIds'] == stale
    deliver(window, 'window.__releaseVideos()')
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight * {order.index(sent[0])} / {len(order)}; true')
    wait_for(lambda: card_text(window, sent[0]) != '')
    assert '정리' in card_text(window, sent[0]), card_text(window, sent[0])
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: '정리' in card_text(window, stale[-1]))
    assert js(window, PLACEHOLDER_CELLS) == 0


def value(window, expression):
    """배열·객체는 Python 값으로 오지 않으므로 JSON으로 받는다."""
    return json.loads(js(window, f'JSON.stringify({expression})'))


def settle(window):
    """브라우저가 쉬는 틈과 그 뒤 두 프레임까지 기다린다. 그사이 나머지 카드를 요청할 차례가 돈다."""
    js(window, 'window.__settled = false; requestIdleCallback(() => requestAnimationFrame(() => '
               'requestAnimationFrame(() => window.__settled = true))); true')
    wait_for(lambda: js(window, 'window.__settled === true'))


def exclude_with_held_push(window, library, video_ids):
    """영상을 빼고, 웹이 아직 모르게 그 갱신을 붙잡는다. 웹의 결과에는 뺀 영상이 남는다."""
    js(window, 'window.__holdPushes = true')
    for video_id in video_ids:
        library.exclude_video(video_id)
    window.refresh()
    wait_for(lambda: js(window, 'window.__heldPushes()') == 1)


def test_late_missing_reply_does_not_block_restored_cards(open_window, library):
    # 뺀 영상을 빠뜨린 나머지 카드 응답이, 그 영상을 되살린 더 새 갱신보다 늦게 와도 되살린 카드를 다시 받는다.
    # 오래된 응답의 누락으로 "라이브러리에 없음"을 기록하면 스크롤·선택으로도 다시 요청하지 않아 자리 표시에 갇힌다.
    window = open_window(hold_videos=True, defer_videos=True, card_size='small')
    ready(window)
    wait_for(lambda: js(window, 'window.__deferredVideos()') > 0)
    order = list(window.library_page.visible_ids)
    changed = order[-100:]
    target = changed[-1]
    exclude_with_held_push(window, library, changed)
    js(window, 'window.__sendVideos(); true')
    wait_for(lambda: js(window, 'window.__heldVideos()') == 1)
    old = value(window, 'window.__videoReplies[0]')
    assert target in value(window, 'window.__requestedIds[0]')
    assert target not in [card['id'] for card in old['videos']]
    pushes = []
    window.library_page.bridge.libraryChanged.connect(lambda value: pushes.append(json.loads(value)))
    for video_id in changed:
        library.restore_video(video_id)
        library.add_video_tag(video_id, 'RESTORED267')
    window.refresh()
    wait_for(lambda: js(window, 'window.__heldPushes()') == 2)
    assert target in pushes[-1]['staleIds'] and pushes[-1]['generation'] > old['generation']
    # 빼고 되살린 갱신이 먼저, 그보다 오래된 누락 응답이 나중에 도착한다.
    deliver(window, 'window.__releasePushes()')
    deliver(window, 'window.__releaseVideos()')
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: js(window, f'!!document.getElementById("video-{target}")'))
    click(window, f'#video-{target}')
    wait_for(lambda: selects(window, target))
    wait_for(lambda: 'RESTORED267' in card_text(window, target))
    assert js(window, PLACEHOLDER_CELLS) == 0


def test_missing_cards_are_not_requested_again(open_window, library):
    # 최신 상태에도 없는 영상(응답이 갱신보다 새것)은 다음 전체 상태가 결과를 고칠 때까지 스크롤해도 다시 요청하지 않는다.
    window = open_window(defer_videos=True, card_size='small')
    ready(window)
    wait_for(lambda: js(window, 'window.__deferredVideos()') > 0)
    order = list(window.library_page.visible_ids)
    gone = order[-100:]
    exclude_with_held_push(window, library, gone)
    deliver(window, 'window.__sendVideos()')
    wait_for(lambda: js(window, 'window.__videoReplies.length') == js(window, 'window.__videoRequests'))
    assert not {card['id'] for card in value(window, 'window.__videoReplies[0]')['videos']} & set(gone)
    js(window, f'{GRID}.scrollTop = {GRID}.scrollHeight; true')
    wait_for(lambda: js(window, f'document.getElementById("video-{gone[-1]}")?.dataset.slot ?? ""') == 'video-card-placeholder')
    settle(window)
    settle(window)
    requested = value(window, 'window.__requestedIds')
    assert sum(gone[-1] in ids for ids in requested) == 1, requested
    # 갱신이 결과를 고치면 뺀 영상의 자리 표시도 사라진다.
    deliver(window, 'window.__releasePushes()')
    wait_for(lambda: window.library_page.visible_ids == order[:-100] and js(window, PLACEHOLDER_CELLS) == 0)


def test_first_screen_then_ready_then_hidden_tabs_then_startup_scan(open_window, monkeypatch):
    events = []
    scan = MainWindow.scan_on_startup
    monkeypatch.setattr(MainWindow, 'scan_on_startup', lambda self: (events.append('startup scan'), scan(self)))
    window = open_window(hold_snapshot=True)
    host, page = window.web_host, window.library_page
    snapshot, page_ready, shell_ready = page.snapshot_payload, host.page_ready, host.frontend_ready
    monkeypatch.setattr(page, 'snapshot_payload', lambda: (state := snapshot(), events.append(('snapshot', len(state['videos']))))[0])
    monkeypatch.setattr(host, 'page_ready', lambda tab: (events.append(('ready', tab)), page_ready(tab)))
    monkeypatch.setattr(host, 'frontend_ready', lambda: (events.append(('ready', 'shell')), shell_ready()))
    host.frontend_loaded.connect(lambda: events.append('loaded'))
    # 첫 스냅숏을 붙잡아 둔 동안 숨은 탭은 첫 데이터를 요청하지도 준비를 알리지도 않는다.
    wait_for(lambda: ('snapshot', min(VIDEOS, SCREEN_VIDEOS)) in events and ('ready', 'shell') in events)
    assert not any(event[0] == 'ready' and event[1] not in ('shell',) for event in events if isinstance(event, tuple)), events
    js(window, 'window.__releaseLibrary()')
    wait_for(lambda: 'startup scan' in events and host._ready_pages >= set(host.controllers))
    position = {event: index for index, event in enumerate(events)}
    hidden = [position[('ready', tab)] for tab in host.controllers if tab != 'library']
    # 첫 화면(첫 화면 카드만 담은 스냅숏) → 준비 → 시작 검사 예약 순서다. 숨은 탭은 셸·라이브러리 준비 뒤에 준비된다.
    assert events[0] == ('snapshot', SCREEN_VIDEOS)
    assert position[('ready', 'library')] < position['loaded'] < position['startup scan']
    assert max(position[('ready', 'library')], position[('ready', 'shell')]) < min(hidden)


def test_videos_slot_returns_known_cards_and_rejects_bad_input(open_window):
    window = open_window()
    ready(window)
    page = window.library_page
    known = page.visible_ids[-2:]
    generation = page.generation
    reply = json.loads(page.bridge.videos(json.dumps([*known, 999999])))
    assert [card['id'] for card in reply['videos']] == known
    # 응답은 스냅숏·갱신과 같은 세대 차례를 쓴다. 웹이 카드마다 더 새 내용만 반영하는 기준이다.
    assert reply['generation'] == generation + 1
    assert reply['videos'] == [page.card_index[video_id] for video_id in known]
    assert 'error' in json.loads(page.bridge.videos('{broken'))
    assert 'error' in json.loads(page.bridge.videos(json.dumps(['1'])))
    assert 'error' in json.loads(page.bridge.videos(json.dumps({'ids': [1]})))
