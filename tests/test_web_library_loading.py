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
from web_frames import stop_recording as stop_frames
from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost

# 문서가 만들어질 때부터 그린 프레임마다 사용자가 보는 배치를 기록한다.
# hold면 웹 채널의 첫 라이브러리 스냅숏 응답을 window.__releaseLibrary()까지 붙잡고, fail이면 오류 응답으로 바꾼다.
# Python 슬롯 안에서 기다리면 WebEngine 작업이 멈추므로 응답은 웹 쪽에서 늦춘다.
FRAME_RECORDER = """(() => {
  const frames = window.__libraryFrames = []
  let held = %(hold)s, release = null, channelClass
  const failed = %(fail)s
  window.__releaseLibrary = () => { held = false; release?.() }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const library = channel.objects.library, snapshot = library.snapshot
        library.snapshot = reply => snapshot.call(library, json => {
          if (failed) json = JSON.stringify({ error: '라이브러리를 읽지 못했습니다.' })
          if (held) release = () => reply(json); else reply(json)
        })
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
  // grid는 격자(자리 표시)가 문서에 붙은 때, pending은 기다림 표시 문구가 처음 채워진 때다.
  // 노드를 붙이거나 글자를 바꾸는 DOM 호출 바로 뒤에 재므로 실제 변경과의 차이는 그 호출 하나다.
  // 격자는 기다림 타이머를 거는 effect보다 먼저 붙는다.
  const moments = window.__libraryMoments = {}, statuses = window.__libraryStatuses = []
  const mark = () => {
    if (moments.grid === undefined && document.getElementById('library-grid')) moments.grid = performance.now()
    if (moments.pending === undefined && document.querySelector('[data-slot=pending-status]')?.textContent) moments.pending = performance.now()
  }
  for (const name of ['appendChild', 'insertBefore']) {
    const original = Node.prototype[name]
    Node.prototype[name] = function (...args) { const result = original.apply(this, args); mark(); return result }
  }
  for (const [prototype, name] of [[Node.prototype, 'textContent'], [Node.prototype, 'nodeValue'], [CharacterData.prototype, 'data']]) {
    const descriptor = Object.getOwnPropertyDescriptor(prototype, name)
    Object.defineProperty(prototype, name, { ...descriptor, set(value) { descriptor.set.call(this, value); mark() } })
  }
  // 나머지는 DOM이 바뀐 것을 본 시각이다. 관찰자는 바뀐 작업이 끝난 뒤 불리므로 실제로 바뀐 때보다 늦거나 같다.
  // statuses는 기다림 표시 문구가 바뀔 때마다 남겨, 프레임 사이에 잠깐 나타났다 사라져도 놓치지 않는다.
  new MutationObserver(() => {
    const grid = document.getElementById('library-grid'), status = document.querySelector('[data-slot=pending-status]')
    const now = performance.now(), text = status?.textContent ?? null
    if (text !== (statuses.at(-1)?.[1] ?? null)) statuses.push([now, text])
    if (grid?.getAttribute('aria-busy') === 'false' && moments.data === undefined) moments.data = now
    if (moments.error === undefined && document.querySelector('main')?.innerText.includes('라이브러리를 읽지 못했습니다.')) moments.error = now
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true })
})()"""

FIRST_ROW = 'document.querySelectorAll("#library-grid [role=gridcell]").length'
GRID_BUSY = 'document.getElementById("library-grid").getAttribute("aria-busy")'
PENDING = 'document.querySelector("[data-slot=pending-status]")?.textContent ?? null'
PAGE_TEXT = 'document.querySelector("main[aria-label=\\"라이브러리\\"]").innerText'
SEARCH_DISABLED = 'document.querySelector("[aria-label=\\"영상 제목 빠른 검색\\"]").disabled'


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


@pytest.fixture
def open_window(core, monkeypatch, qapp):
    """프레임 기록을 켠 MainWindow를 연다. hold_data면 첫 라이브러리 데이터가 오지 않은 채로 돌려주고, fail_data면 첫 데이터가 실패한다."""
    windows = []
    start = WebShellHost.start
    first_reply = []

    def record_frames(host):
        script = QWebEngineScript()
        script.setName('library-frames')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        hold, fail = first_reply[-1]
        script.setSourceCode(FRAME_RECORDER % {'hold': json.dumps(hold), 'fail': json.dumps(fail)})
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', record_frames)

    def create(*, hold_data=False, fail_data=False, library=None):
        first_reply.append((hold_data, fail_data))
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


def stop_recording(window, done=None):
    """기록을 멈추고 프레임·시각·문구 기록을 돌려준다. done이 있으면 마지막 프레임이 done을 만족할 때까지 기다린 뒤 멈춘다."""
    if done:
        stop_frames(window, 'library', done)
    js(window, 'window.__stopLibraryFrames = true')
    return json.loads(js(window, 'JSON.stringify({frames: window.__libraryFrames, moments: window.__libraryMoments, statuses: window.__libraryStatuses})'))


def no_pending_text(statuses):
    return all(text in ('', None) for _, text in statuses)


def click(window, selector):
    # 배열 결과는 Python 목록으로 오지 않으므로 JSON으로 받는다.
    center = json.loads(js(window, f"(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) }})()"))
    QTest.mouseClick(window.web_host.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(*map(round, center)))


def test_first_entry_placeholders_keep_toolbar_and_first_row_in_place(open_window, core):
    window = open_window(hold_data=True)
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
    # 마우스 입력은 렌더러에 비동기로 닿는다. 뒤이은 표지 클릭이 처리될 때까지 기다려 앞선 두 클릭이 데이터 전에 처리됐음을 보장한다.
    js(window, "window.__marked = 0; document.querySelector('[data-slot=pending-status]').addEventListener('click', () => window.__marked++)")
    click(window, '[data-slot=pending-status]')
    wait_for(lambda: js(window, 'window.__marked') == 1)
    assert js(window, "document.querySelector('button[aria-label=\"정렬 방향\"]').textContent") == '오름차순 ↑'
    assert js(window, "document.querySelector('button[aria-label=\"폴더 패널\"]').getAttribute('aria-expanded')") == 'false'
    assert js(window, "document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]').disabled")

    release(window)
    wait_for(lambda: js(window, FIRST_ROW) > 0)
    # 마지막 표본이 결과(aria-busy·자리 표시 없음, 첫 줄 카드 있음)를 담을 때까지 기록한다.
    recorded = stop_recording(window, lambda frame: not frame['busy'] and frame['placeholders'] == 0 and frame['cells'])
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
    # 두 시각 모두 DOM 호출 바로 뒤에 쟀으므로 이 간격은 자리 표시가 생긴 뒤 문구가 나타날 때까지의 실제 시간이다
    # (1ms는 시계 해상도와 호출 하나의 여유).
    moments = recorded['moments']
    assert moments['pending'] - moments['grid'] >= 299, moments
    assert any('불러오는 중…' not in frame['text'] for frame in loading)
    assert '불러오는 중…' not in final['text'] and '등록 영상 3개 · 표시 3개' in final['text']


def library_with_video(root):
    """영상 하나를 등록한 새 라이브러리. 폴더 감시 컨트롤러는 라이브러리마다 하나라 창을 다시 열 때 쓴다."""
    library = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                      database=root / 'data/library.sqlite3')
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'Python 기초.mkv'
    path.write_bytes(b'video')
    library.add_file(path)
    return library


def test_pending_status_does_not_flash_when_data_arrives_quickly(open_window, tmp_path):
    # 300ms 안에 데이터가 오면 기다림 표시는 한 번도 나타나지 않는다.
    # 격자가 붙은 시각(기다림 타이머 시작보다 늦지 않다)부터 데이터를 본 시각(실제 반영보다 이르지 않다)까지가
    # 250ms 안일 때만 타이머가 끝나기 전에 데이터가 왔다고 말할 수 있다.
    # 부하로 늦은 실행은 이 경우의 재현이 아니므로 검증 없이 통과시키지 않고, 창을 새 라이브러리로 새로 열어 다시 재현한다.
    attempts = []
    for attempt in range(3):
        window = open_window(library=library_with_video(tmp_path / f'attempt-{attempt}'))
        wait_for(lambda: js(window, FIRST_ROW) > 0)
        recorded = stop_recording(window, lambda frame: not frame['busy'])
        moments = recorded['moments']
        attempts.append(moments)
        if moments['data'] - moments['grid'] < 250:
            break
    else:
        pytest.fail(f'데이터가 250ms 안에 오는 경우를 재현하지 못했다: {attempts}')
    assert 'pending' not in moments and no_pending_text(recorded['statuses']), recorded
    assert '불러오는 중…' not in recorded['frames'][-1]['text']


def test_empty_library_message_appears_only_after_data(open_window, tmp_path):
    empty = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                    database=tmp_path / 'empty/library.sqlite3')
    window = open_window(hold_data=True, library=empty)
    wait_for(lambda: js(window, PENDING) == '불러오는 중…')
    assert '라이브러리가 비어 있습니다' not in js(window, PAGE_TEXT)
    release(window)
    wait_for(lambda: '라이브러리가 비어 있습니다' in js(window, PAGE_TEXT))
    frames = stop_recording(window, lambda frame: '라이브러리가 비어 있습니다' in frame['text'])['frames']
    # 개수가 처음 보인 프레임 전까지가 데이터 전이다.
    arrived = next(index for index, frame in enumerate(frames) if '등록 영상' in frame['text'])
    assert arrived > 0
    assert not any('라이브러리가 비어 있습니다' in frame['text'] or '선택한 영상 없음' in frame['text'] for frame in frames[:arrived])
    final = js(window, PAGE_TEXT)
    assert '선택한 영상 없음' in final and '등록 영상 0개 · 표시 0개' in final


def test_failed_first_data_settles_and_recovers_when_library_arrives(open_window):
    window = open_window(fail_data=True)
    wait_for(lambda: '라이브러리를 읽지 못했습니다.' in js(window, PAGE_TEXT))
    text = js(window, PAGE_TEXT)
    # 실패는 끝난 상태다. 기다림 표시와 aria-busy를 끝내고 격자 자리에 읽지 못했다는 안내를 보인다.
    # 비었다는 거짓 안내, 누를 수 있는 컨트롤, 불러오는 중처럼 보이는 자리 표시는 없다.
    assert js(window, PENDING) == ''
    assert js(window, GRID_BUSY) == 'false'
    # 숨은 다른 탭(통계·추천)의 첫 데이터 전 자리 표시는 세지 않는다.
    assert js(window, "document.querySelector('main[aria-label=\"라이브러리\"]').querySelectorAll('[aria-busy=true], [data-slot=video-card-placeholder], [data-slot=skeleton]').length") == 0
    assert '영상 목록을 읽지 못했습니다' in text
    assert '라이브러리가 비어 있습니다' not in text and '선택한 영상 없음' not in text and '0개' not in text
    assert js(window, SEARCH_DISABLED)

    # 오류 안내를 닫아도 실패한 요청을 다시 기다리는 것처럼 바뀌지 않는다.
    click(window, 'button[aria-label="안내 닫기"]')
    wait_for(lambda: '라이브러리를 읽지 못했습니다.' not in js(window, PAGE_TEXT))
    # 닫은 뒤 기다림 유예(300ms)의 두 배가 지날 때까지 페이지 시계로 조건 대기하고, 그동안 바뀐 문구 기록을 본다.
    closed = js(window, 'performance.now()')
    wait_for(lambda: js(window, 'performance.now()') - closed > 600)
    recorded = stop_recording(window)
    assert no_pending_text(entry for entry in recorded['statuses'] if entry[0] >= recorded['moments']['error']), recorded['statuses']
    assert js(window, PENDING) == '' and js(window, GRID_BUSY) == 'false'
    assert '영상 목록을 읽지 못했습니다' in js(window, PAGE_TEXT)

    # 뒤에 라이브러리 데이터가 오면 정상 목록이 되고 영상을 고를 수 있다.
    window.library_page.refresh()
    wait_for(lambda: js(window, FIRST_ROW) == 3)
    assert '등록 영상 3개 · 표시 3개' in js(window, PAGE_TEXT) and not js(window, SEARCH_DISABLED)
    second = js(window, 'document.querySelectorAll("#library-grid [role=gridcell]")[1].id')
    selected = f"document.getElementById('{second}').getAttribute('aria-selected')"
    assert js(window, selected) == 'false'
    click(window, f'#{second}')
    wait_for(lambda: window.library_page.selected_id == int(second.removeprefix('video-')))
    wait_for(lambda: js(window, selected) == 'true')
