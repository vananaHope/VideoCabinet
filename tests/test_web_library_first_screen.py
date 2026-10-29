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
# 문서를 만들 때 넣는다. 첫 스냅숏이나 나머지 카드 응답을 붙잡고, 그린 프레임마다 사용자가 보는 배치를 기록한다.
RECORDER = """(() => {
  let channelClass, holdSnapshot = %(hold_snapshot)s, releaseSnapshot = null
  const heldVideos = []
  window.__holdVideos = %(hold_videos)s
  window.__videoRequests = 0
  window.__releaseLibrary = () => { holdSnapshot = false; releaseSnapshot?.() }
  window.__releaseVideos = () => { window.__holdVideos = false; for (const deliver of heldVideos.splice(0)) deliver() }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const library = channel.objects.library, snapshot = library.snapshot, videos = library.videos
        library.snapshot = reply => snapshot.call(library, json => { if (holdSnapshot) releaseSnapshot = () => reply(json); else reply(json) })
        library.videos = (ids, reply) => {
          window.__videoRequests++
          videos.call(library, ids, json => { if (window.__holdVideos) heldVideos.push(() => reply(json)); else reply(json) })
        }
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

    def create(*, hold_snapshot=False, hold_videos=False, **options):
        library.save_library_view_options({**default_options(), **options})
        recorder.update(hold_snapshot=hold_snapshot, hold_videos=hold_videos)
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
    reply = json.loads(page.bridge.videos(json.dumps([*known, 999999])))
    assert [card['id'] for card in reply['videos']] == known
    assert reply['videos'] == [page.card_index[video_id] for video_id in known]
    assert 'error' in json.loads(page.bridge.videos('{broken'))
    assert 'error' in json.loads(page.bridge.videos(json.dumps(['1'])))
    assert 'error' in json.loads(page.bridge.videos(json.dumps({'ids': [1]})))
