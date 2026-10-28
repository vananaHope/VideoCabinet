"""라이브러리 첫 진입의 자리 표시와 기다림 표시를 실제 웹 셸(offscreen)에서 검증한다.

첫 라이브러리 데이터 응답은 테스트에서만 늦춘다. 제품 코드에는 시험용 지연이 없다.
"""
from datetime import datetime, timezone
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript

from qt_wait import wait_for
from test_library_return_ui import Player
from test_web_library_data import Media, core
from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost

# 문서가 만들어질 때부터 그린 프레임마다 사용자가 보는 배치를 기록한다.
# hold면 웹 채널의 첫 라이브러리 스냅숏 응답을 window.__releaseLibrary()까지 붙잡는다.
# Python 슬롯 안에서 기다리면 WebEngine 작업이 멈추므로 응답은 웹 쪽에서 늦춘다.
FRAME_RECORDER = """(() => {
  const frames = window.__libraryFrames = []
  let held = %(hold)s, release = null, channelClass
  window.__releaseLibrary = () => { held = false; release?.() }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const library = channel.objects.library, snapshot = library.snapshot
        library.snapshot = reply => snapshot.call(library, json => { if (held) release = () => reply(json); else reply(json) })
        ready(channel)
      })
    }
  } })
  const box = element => {
    if (!element) return null
    const r = element.getBoundingClientRect()
    return [r.x, r.y, r.width, r.height].map(value => Math.round(value * 10) / 10)
  }
  const controls = {
    search: '[aria-label="영상 제목 빠른 검색"]', cardSize: 'button[role=combobox][aria-label="카드 크기"]',
    sort: 'button[role=combobox][aria-label="정렬"]', direction: 'button[aria-label="정렬 방향"]',
    random: '[aria-label="무작위 재생"]', folders: 'button[aria-label="폴더 패널"]',
    grid: '#library-grid', detail: 'aside[aria-label="선택 영상 상세"]',
  }
  const sample = () => {
    const grid = document.getElementById('library-grid')
    if (grid) {
      const columns = Number(grid.getAttribute('aria-colcount'))
      const first = [...grid.querySelectorAll('[role=gridcell], [data-slot=video-card-placeholder]')].slice(0, columns)
      frames.push({
        t: performance.now(), busy: grid.getAttribute('aria-busy') === 'true', columns,
        placeholders: first.filter(cell => cell.dataset.slot === 'video-card-placeholder').length,
        cells: first.map(box), controls: Object.fromEntries(Object.entries(controls).map(([name, selector]) => [name, box(document.querySelector(selector))])),
        text: document.querySelector('main[aria-label="라이브러리"]').innerText,
      })
    }
    if (!window.__stopLibraryFrames) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
  // DOM이 바뀐 시각. 관찰자는 바뀐 작업이 끝날 때 불리므로 50ms 넘는 작업은 시작 시각도 남긴다.
  const moments = window.__libraryMoments = {}, tasks = window.__libraryTasks = []
  new PerformanceObserver(list => tasks.push(...list.getEntries().map(entry => [entry.startTime, entry.duration]))).observe({ type: 'longtask' })
  new MutationObserver(() => {
    const grid = document.getElementById('library-grid'), status = document.querySelector('[data-slot=pending-status]')
    const now = performance.now()
    if (grid && moments.grid === undefined) moments.grid = now
    if (status?.textContent && moments.pending === undefined) moments.pending = now
    if (grid?.getAttribute('aria-busy') === 'false' && moments.data === undefined) moments.data = now
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true })
})()"""

FIRST_ROW = 'document.querySelectorAll("#library-grid [role=gridcell]").length'
GRID_BUSY = 'document.getElementById("library-grid").getAttribute("aria-busy")'
PENDING = 'document.querySelector("[data-slot=pending-status]")?.textContent ?? null'
PAGE_TEXT = 'document.querySelector("main[aria-label=\\"라이브러리\\"]").innerText'


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


@pytest.fixture
def open_window(core, monkeypatch, qapp):
    """프레임 기록을 켠 MainWindow를 연다. hold_data면 첫 라이브러리 데이터가 오지 않은 채로 돌려준다."""
    windows = []
    start = WebShellHost.start
    hold = []

    def record_frames(host):
        script = QWebEngineScript()
        script.setName('library-frames')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(FRAME_RECORDER % {'hold': 'true' if hold[-1] else 'false'})
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', record_frames)

    def create(*, hold_data=False, library=None):
        hold.append(hold_data)
        window = MainWindow(library or core, player_factory=Player)
        windows.append(window)
        window.show()
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def release(window):
    js(window, 'window.__releaseLibrary()')
    wait_for(lambda: js(window, GRID_BUSY) == 'false')


def stop_recording(window):
    js(window, 'window.__stopLibraryFrames = true')
    return json.loads(js(window, 'JSON.stringify({frames: window.__libraryFrames, moments: window.__libraryMoments, tasks: window.__libraryTasks})'))


def pending_delay(recorded):
    """자리 표시를 그린 작업이 시작한 때부터 기다림 표시가 나타날 때까지(ms). 기다림 타이머는 그 작업 안에서 시작한다."""
    moments = recorded['moments']
    starts = [start for start, duration in recorded['tasks'] if start <= moments['grid'] <= start + duration + 1]
    # 50ms 넘는 작업만 기록되므로 기록이 없으면 그 작업은 관찰 시각보다 50ms 안쪽에서 시작했다.
    began = starts[0] if starts else moments['grid'] - 50
    return moments['pending'] - began


def click(window, selector):
    center = js(window, f"(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})()")
    QTest.mouseClick(window.web_host.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(*map(round, center)))


def test_first_entry_placeholders_keep_toolbar_and_first_row_in_place(open_window, core):
    window = open_window(hold_data=True)
    assert js(window, "PerformanceObserver.supportedEntryTypes.includes('longtask')")
    # 데이터가 300ms 넘게 오지 않으면 개수 자리에 기다림 표시가 나타난다.
    wait_for(lambda: js(window, PENDING) == '불러오는 중…')
    assert js(window, GRID_BUSY) == 'true'
    assert js(window, "document.querySelector('[data-slot=pending-status]').getAttribute('role')") == 'status'
    assert js(window, "!!document.querySelector('aside[aria-label=\"선택 영상 상세\"] [aria-busy=true]')")
    text = js(window, PAGE_TEXT)
    assert '라이브러리가 비어 있습니다' not in text and '선택한 영상 없음' not in text and '0개' not in text

    # 데이터 전 툴바는 같은 자리에 있지만 누를 수 없다.
    click(window, 'button[aria-label="정렬 방향"]')
    click(window, 'button[aria-label="폴더 패널"]')
    assert js(window, "document.querySelector('button[aria-label=\"정렬 방향\"]').textContent") == '오름차순 ↑'
    assert js(window, "document.querySelector('button[aria-label=\"폴더 패널\"]').getAttribute('aria-expanded')") == 'false'
    assert js(window, "document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]').disabled")

    release(window)
    wait_for(lambda: js(window, FIRST_ROW) > 0)
    recorded = stop_recording(window)
    frames = recorded['frames']
    loading = [frame for frame in frames if frame['busy']]
    final = frames[-1]
    assert loading and not final['busy']
    assert final['placeholders'] == 0 and len(final['cells']) == final['columns'] == 2
    assert not core.library_view_options()['descending'], '데이터 전 클릭이 보기 조건을 바꾸지 않아야 한다'
    for frame in frames:
        # 첫 프레임부터 툴바·격자·상세 패널·첫 줄 카드의 경계가 실제 목록과 같다(임시 열 수나 늦게 나타나는 툴바가 없다).
        assert frame['controls'] == final['controls'], frame
        assert frame['columns'] == final['columns'] and frame['cells'] == final['cells'], frame
        assert '라이브러리가 비어 있습니다' not in frame['text'] and '선택한 영상 없음' not in frame['text']
    assert all(frame['placeholders'] == final['columns'] for frame in loading)
    # 기다림 표시는 자리 표시가 생기고 300ms가 지나서야 나타나고, 데이터가 오면 개수로 바뀐다.
    assert pending_delay(recorded) >= 299, recorded['moments']
    assert any('불러오는 중…' not in frame['text'] for frame in loading)
    assert '불러오는 중…' not in final['text'] and '등록 영상 3개 · 표시 3개' in final['text']


def test_pending_status_does_not_flash_when_data_arrives_quickly(open_window):
    window = open_window()
    wait_for(lambda: js(window, FIRST_ROW) > 0)
    recorded = stop_recording(window)
    moments = recorded['moments']
    # 300ms 안에 데이터가 오면 기다림 표시는 한 번도 나타나지 않는다. 부하로 늦었다면 300ms 전에는 나타나지 않는다.
    if moments['data'] - moments['grid'] < 290:
        assert 'pending' not in moments, moments
    else:
        assert 'pending' not in moments or pending_delay(recorded) >= 299, moments
    assert '불러오는 중…' not in recorded['frames'][-1]['text']


def test_empty_library_message_appears_only_after_data(open_window, tmp_path):
    empty = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                    database=tmp_path / 'empty/library.sqlite3')
    window = open_window(hold_data=True, library=empty)
    wait_for(lambda: js(window, PENDING) == '불러오는 중…')
    release(window)
    wait_for(lambda: '라이브러리가 비어 있습니다' in js(window, PAGE_TEXT))
    recorded = stop_recording(window)
    assert not any('라이브러리가 비어 있습니다' in frame['text'] or '선택한 영상 없음' in frame['text']
                   for frame in recorded['frames'] if frame['busy'])
    final = js(window, PAGE_TEXT)
    assert '선택한 영상 없음' in final and '등록 영상 0개 · 표시 0개' in final
