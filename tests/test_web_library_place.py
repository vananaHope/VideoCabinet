"""#263 안내·필터 칩·폴더 패널이 라이브러리 목록을 밀지 않는지 실제 웹 셸(offscreen)에서 검증한다.

보던 선택 카드의 화면 위치(격자 보기 영역 위쪽 기준)·열 수·스크롤을 동작 전후와 그 사이 그린 프레임마다 잰다.
"""
from datetime import datetime, timezone
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest

from qt_wait import wait_for
from test_library_return_ui import Player
from test_web_library_data import Media
from test_web_library_loading import click, js
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.subtitle_preparation_ui import preparation_state
from my_video_manager.ui import MainWindow

GRID = 'document.getElementById("library-grid")'
CELLS = 'document.querySelectorAll("#library-grid [role=gridcell]").length'
SHELL = '[aria-label="앱 안내"]'
BAND = '[aria-label="라이브러리 안내"]'


@pytest.fixture
def library(tmp_path):
    """감시 폴더 영상 30개와 직접 추가한 영상 30개. 제목순으로 섞여 보이고, 모두 제목에 clip이 들어 있다."""
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / 'data/library.sqlite3')
    watched = tmp_path / 'watched'
    for folder in (watched, tmp_path / 'direct'):
        folder.mkdir()
    for index in range(60):
        path = (watched if index % 2 else tmp_path / 'direct') / f'clip {index:03}.mkv'
        path.write_bytes(f'video {index}'.encode())
        core.add_file(path)
    core.add_watched_folder(watched)
    # 시작 검사·자동 감지의 작업 알림이 시험 중의 셸 안내를 바꾸지 않게 끈다.
    core.set_automatic_detection_enabled(False)
    return core


@pytest.fixture
def open_window(library, qapp):
    windows = []

    def create(**options):
        library.save_library_view_options({**default_options(), 'card_size': 'small', **options})
        window = MainWindow(library, player_factory=Player)
        windows.append(window)
        window.resize(1100, 720)
        window.show()
        host = window.web_host
        wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
        wait_for(lambda: js(window, CELLS) > 0)
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def view(window):
    return window.web_host.view.focusProxy()


def place(window, video_id):
    """선택 카드의 경계(세로는 격자 보기 영역 위쪽 기준), 격자 경계, 스크롤, 열 수."""
    return json.loads(js(window, f"""(() => {{
      const grid = {GRID}, g = grid.getBoundingClientRect(), card = document.getElementById('video-{video_id}')
      const c = card?.getBoundingClientRect()
      return JSON.stringify({{ grid: [g.x, g.y, g.width, g.height].map(Math.round), top: Math.round(grid.scrollTop),
        columns: Number(grid.getAttribute('aria-colcount')), x: c ? Math.round(c.x) : null, y: c ? Math.round(c.y - g.y) : null,
        shown: !!c && c.bottom > g.top && c.top < g.bottom }})
    }})()"""))


def record(window, video_id):
    """그린 프레임마다 선택 카드 자리를 남긴다."""
    js(window, f"""(() => {{
      const frames = window.__placeFrames = []
      window.__placeStop = false
      const sample = () => {{
        const grid = {GRID}, g = grid.getBoundingClientRect(), c = document.getElementById('video-{video_id}')?.getBoundingClientRect()
        frames.push({{ grid: [g.x, g.y, g.width, g.height].map(Math.round), columns: Number(grid.getAttribute('aria-colcount')),
          x: c ? Math.round(c.x) : null, y: c ? Math.round(c.y - g.y) : null }})
        if (!window.__placeStop) requestAnimationFrame(sample)
      }}
      requestAnimationFrame(sample)
      return true
    }})()""")


def frames(window):
    js(window, 'window.__placeStop = true')
    return json.loads(js(window, 'JSON.stringify(window.__placeFrames)'))


def choose_middle_card(window):
    """격자를 몇 줄 내린 뒤 보이는 둘째 줄 카드를 클릭해 고른다."""
    js(window, f'{GRID}.scrollTop = 900')
    wait_for(lambda: js(window, f'{GRID}.scrollTop') == 900)
    # 가상화된 줄은 스크롤 다음 프레임에 그려진다.
    second = f"""(() => {{
      const g = {GRID}.getBoundingClientRect()
      const cells = [...document.querySelectorAll('#library-grid [role=gridcell]')].filter(cell => cell.getBoundingClientRect().top > g.top + 100)
      return cells.length > 1 ? Number(cells[1].id.slice(6)) : 0
    }})()"""
    wait_for(lambda: js(window, second) > 0)
    target = int(js(window, second))
    click(window, f'#video-{target}')
    wait_for(lambda: window.library_page.selected_id == target)
    return target


def box(window, selector):
    return json.loads(js(window, f"""(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return 'null'
      const r = e.getBoundingClientRect(); return JSON.stringify({{ left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }}) }})()"""))


def near(a, b):
    # 줄 높이가 소수 픽셀이라 스크롤 위치를 다시 맞출 때 1px까지 반올림 차이가 날 수 있다.
    return abs(a - b) <= 1


def overlaps(a, b):
    return a['left'] < b['right'] and b['left'] < a['right'] and a['top'] < b['bottom'] and b['top'] < a['bottom']


def press(window, selector, key=Qt.Key.Key_Return):
    js(window, f'document.querySelector({json.dumps(selector)}).focus(); true')
    wait_for(lambda: js(window, f'document.activeElement === document.querySelector({json.dumps(selector)})'))
    QTest.keyClick(view(window), key)


def test_page_and_shell_notices_float_without_moving_selected_card(open_window):
    window = open_window()
    selected = choose_middle_card(window)
    before = place(window, selected)
    assert before['shown'] and before['top'] > 0
    record(window, selected)

    # 페이지 안내(라이브러리 오류)와 셸 안내(작업 알림·자막 기능 준비)가 함께 생긴다.
    window.library_page.bridge.libraryError.emit('라이브러리 요청 실패: ' + '아주 긴 오류 설명이 이어집니다. ' * 12)
    window.show_status('검사 실패: ' + '접근할 수 없는 감시 폴더가 있습니다. ' * 10)
    window.subtitles.timer.stop()
    window.subtitles.set_preparation(preparation_state('failed', kind='error', message='자막 기능 준비 실패: ' + '파일을 받지 못했습니다. ' * 8))
    wait_for(lambda: js(window, f"document.querySelectorAll('{SHELL} [data-slot=notice]').length") == 2)
    wait_for(lambda: js(window, f"document.querySelectorAll('{BAND} [data-slot=notice]').length") == 1)
    assert place(window, selected) == before

    # 안내 위계는 그대로다: 띠의 오류는 alert, 셸 묶음은 자막 기능 준비 → 작업 알림 순서로 쌓인다.
    assert js(window, f"document.querySelector('{BAND} [data-slot=notice]').getAttribute('role')") == 'alert'
    assert json.loads(js(window, f"JSON.stringify([...document.querySelectorAll('{SHELL} [data-slot=notice]')].map(e => e.dataset.tone))")) == ['error', 'error'], js(window, f"document.querySelector('{SHELL}').innerText")
    assert '오류 2개' in js(window, f"document.querySelector('{SHELL}').innerText")

    # 띠는 격자 위쪽에만 겹치고 툴바·칩 줄·상세 패널을 덮지 않는다. 셸 묶음은 오른쪽 아래에 떠서 머리글·툴바·상세 패널 위쪽 단추를 덮지 않는다.
    band, shell, grid = box(window, BAND), box(window, SHELL), box(window, '#library-grid')
    covered = ['header', '[aria-label="영상 제목 빠른 검색"]', '[aria-label="무작위 재생"]', '[aria-label="적용한 검색 조건"]',
               'aside[aria-label="선택 영상 상세"] h2', '[aria-label="영상 상세 탭"]', '[aria-label="영상 작업"]', 'button[aria-label="폴더 패널"]']
    for selector in covered:
        assert not overlaps(band, box(window, selector)), selector
        assert not overlaps(shell, box(window, selector)), selector
    assert grid['left'] <= band['left'] and band['right'] <= grid['right'] and band['top'] >= grid['top'] and band['height'] <= grid['height'] / 2 + 1
    page = box(window, '[data-page="library"]')
    assert shell['width'] <= 448 + 1 and shell['height'] <= page['height'] * 0.4 + 1, shell
    assert shell['right'] <= page['right'] and shell['bottom'] <= page['bottom'] and shell['top'] >= page['top']

    # 셸 묶음은 키보드로 접고 편다. 접어도 오류 개수는 남는다.
    toggle = f'{SHELL} button[aria-expanded]'
    press(window, toggle)
    wait_for(lambda: js(window, f"document.querySelector('{toggle}').getAttribute('aria-expanded')") == 'false')
    assert js(window, f"document.querySelector('{SHELL} [data-slot=notice]').checkVisibility()") is False
    assert '오류 2개' in js(window, f"document.querySelector('{SHELL}').innerText")
    assert box(window, SHELL)['height'] < 48
    press(window, toggle)
    wait_for(lambda: js(window, f"document.querySelector('{toggle}').getAttribute('aria-expanded')") == 'true')

    # 닫을 수 있는 안내는 키보드로 닫는다. 닫아도 목록은 그대로다.
    press(window, f'{BAND} button[aria-label="안내 닫기"]')
    wait_for(lambda: js(window, f"!document.querySelector('{BAND}')"))
    press(window, f'{SHELL} [aria-label="작업 알림"] button[aria-label="안내 닫기"]', Qt.Key.Key_Space)
    wait_for(lambda: js(window, f"document.querySelectorAll('{SHELL} [data-slot=notice]').length") == 1)
    window.subtitles.set_preparation(preparation_state('ready'))
    wait_for(lambda: js(window, f"document.querySelector('{SHELL}').checkVisibility()") is False)
    assert place(window, selected) == before
    recorded = frames(window)
    assert recorded and all(frame == recorded[0] for frame in recorded), [f for f in recorded if f != recorded[0]][:3]
    assert recorded[0]['y'] == before['y'] and recorded[0]['x'] == before['x']


def test_new_shell_notice_reopens_collapsed_layer(open_window):
    window = open_window()
    window.show_status('영상 3개 등록 · 전체 10개')
    wait_for(lambda: js(window, f"document.querySelector('{SHELL}').checkVisibility()") is True)
    toggle = f'{SHELL} button[aria-expanded]'
    press(window, toggle)
    wait_for(lambda: js(window, f"document.querySelector('{toggle}').getAttribute('aria-expanded')") == 'false')
    assert '오류' not in js(window, f"document.querySelector('{SHELL}').innerText")
    # 같은 자리의 알림이 오류로 바뀌면(오류가 늘면) 접은 묶음이 다시 펴진다.
    window.show_status('검사 실패: 폴더에 접근할 수 없습니다.')
    wait_for(lambda: js(window, f"document.querySelector('{toggle}').getAttribute('aria-expanded')") == 'true')
    assert js(window, f"document.querySelector('{SHELL} [data-slot=notice]').getAttribute('role')") == 'alert'


def test_filter_chip_row_keeps_grid_and_selected_card_in_place(open_window):
    window = open_window()
    selected = choose_middle_card(window)
    before = place(window, selected)
    chips = box(window, '[aria-label="적용한 검색 조건"]')
    assert chips['height'] > 24
    record(window, selected)

    # 모든 제목에 들어 있는 글자를 입력하면 결과는 같고 제목 칩이 생긴다.
    click(window, '[aria-label="영상 제목 빠른 검색"]')
    QTest.keyClicks(view(window), 'clip')
    wait_for(lambda: js(window, "document.querySelector('[aria-label=\"적용한 검색 조건\"]').innerText").startswith('제목: clip'))
    wait_for(lambda: window.library_page.options['query'] == 'clip')
    assert place(window, selected) == before
    assert box(window, '[aria-label="적용한 검색 조건"]') == chips

    # 칩을 눌러 지우면 칩 줄은 비지만 높이는 그대로다.
    click(window, '[aria-label="제목: clip 지우기"]')
    wait_for(lambda: js(window, "document.querySelectorAll('[aria-label=\"적용한 검색 조건\"] button').length") == 0)
    wait_for(lambda: window.library_page.options['query'] == '')
    assert place(window, selected) == before
    assert box(window, '[aria-label="적용한 검색 조건"]') == chips
    recorded = frames(window)
    assert recorded and all(frame == recorded[0] for frame in recorded), [f for f in recorded if f != recorded[0]][:3]


def toggle_folders(window, expanded):
    click(window, 'button[aria-label="폴더 패널"]')
    wait_for(lambda: js(window, "document.querySelector('button[aria-label=\"폴더 패널\"]').getAttribute('aria-expanded')") == str(expanded).lower())
    wait_for(lambda: (window.library_page.options['mode'] == 'folders') == expanded)


def test_folder_panel_keeps_selected_card_at_same_height(open_window):
    window = open_window()
    selected = choose_middle_card(window)
    before = place(window, selected)
    record(window, selected)

    toggle_folders(window, True)
    wait_for(lambda: js(window, '!!document.getElementById("library-folder-panel")'))
    # 열 수는 격자 폭이 바뀐 다음 그리기에서 다시 잰다.
    wait_for(lambda: place(window, selected)['columns'] < before['columns'])
    opened = place(window, selected)
    # 폴더 패널이 목록 옆 자리를 차지해 열 수는 줄지만, 선택 카드는 계속 보이고 세로 위치가 같다.
    assert opened['columns'] < before['columns']
    assert opened['shown'] and near(opened['y'], before['y']), (before, opened)
    assert opened['grid'][1] == before['grid'][1]

    toggle_folders(window, False)
    wait_for(lambda: js(window, '!document.getElementById("library-folder-panel")'))
    wait_for(lambda: place(window, selected)['columns'] == before['columns'])
    closed = place(window, selected)
    assert closed['shown'] and near(closed['y'], before['y']) and closed['columns'] == before['columns'], (before, closed)
    assert near(closed['top'], before['top'])
    # 그 사이 그린 프레임에서도 선택 카드의 세로 위치가 튀지 않는다.
    recorded = frames(window)
    assert recorded and all(near(frame['y'], before['y']) for frame in recorded), [f for f in recorded if not near(f['y'], before['y'])][:3]
    assert window.library_page.selected_id == selected


def test_folder_panel_keeps_scroll_near_when_selected_card_leaves_result(open_window):
    # 패널을 닫아도 남아 있던 폴더(직접 추가)가 열면 다시 적용되어, 감시 폴더의 선택 영상이 결과에서 빠진다.
    window = open_window(folder='direct')
    selected = choose_middle_card(window)
    if selected not in window.library_page.visible_ids[1::2]:
        QTest.keyClick(view(window), Qt.Key.Key_Right)
        wait_for(lambda: window.library_page.selected_id != selected)
        selected = window.library_page.selected_id
    before = place(window, selected)
    assert before['top'] > 0
    shown = json.loads(js(window, f"""JSON.stringify((() => {{ const g = {GRID}.getBoundingClientRect()
      return [...document.querySelectorAll('#library-grid [role=gridcell]')].filter(cell => {{ const r = cell.getBoundingClientRect(); return r.bottom > g.top && r.top < g.bottom }})
        .map(cell => [Number(cell.id.slice(6)), Math.round(cell.getBoundingClientRect().y - g.y)]) }})())"""))

    toggle_folders(window, True)
    wait_for(lambda: len(window.library_page.visible_ids) == 30)
    # 선택은 코어의 규칙(결과의 첫 영상)을 따른다.
    first = window.library_page.visible_ids[0]
    assert window.library_page.selected_id == first
    wait_for(lambda: js(window, f"{GRID}.getAttribute('aria-activedescendant')") == f'video-{first}')
    wait_for(lambda: js(window, f"{GRID}.getAttribute('aria-rowcount')") == str(15))
    # 목록은 맨 위가 아니라 이전 스크롤 근처에 남는다. 보이던 카드 중 결과에 남은 카드가 그대로 보인다.
    remaining = [id for id, _ in shown if id in window.library_page.visible_ids]
    assert remaining and selected not in window.library_page.visible_ids
    after = [place(window, id) for id in remaining]
    assert after[0]['top'] > 0 and any(card['shown'] for card in after), (before, shown, after)
