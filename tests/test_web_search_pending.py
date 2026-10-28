"""검색어를 바꾸는 동안 이전 결과를 흐리게 남기는 동작을 실제 웹 셸(offscreen)에서 검증한다.

새 결과(`changed` 신호)는 테스트에서만 웹 쪽에서 붙잡아 늦춘다. 제품 코드에는 시험용 지연이 없다.
"""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript

from qt_wait import wait_for
from test_library_return_ui import Player
from test_reel import mark
from test_web_library_data import core
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost

# 문서가 만들어질 때부터 검색 브리지를 감싸고, 그린 프레임마다 사용자가 보는 검색 목록을 기록한다.
# __searchHold면 검색 결과 신호를 __releaseSearch(query)까지 붙잡고, __searchFail이면 검색 요청을 오류 응답으로 바꾼다.
# Python 슬롯 안에서 기다리면 WebEngine 작업이 멈추므로 결과는 웹 쪽에서 늦춘다.
SEARCH_RECORDER = """(() => {
  let channelClass
  const held = [], log = window.__searchLog = { sent: [], delivered: [], statuses: [], frames: [], keys: 0, clicks: 0 }
  window.__searchHold = false
  window.__searchFail = false
  window.__releaseSearch = query => {
    for (const item of held.filter(item => item.query === query)) { held.splice(held.indexOf(item), 1); item.deliver() }
  }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const search = window.__search = channel.objects.search
        const connect = search.changed.connect, find = search.find
        search.changed.connect = callback => connect.call(search.changed, json => {
          const query = JSON.parse(json).query
          const deliver = () => { log.delivered.push([performance.now(), query]); callback(json) }
          if (window.__searchHold) held.push({ query, deliver }); else deliver()
        })
        search.find = (value, reply) => {
          log.sent.push([performance.now(), value])
          if (window.__searchFail) reply(JSON.stringify({ error: '검색 요청을 보내지 못했습니다.' }))
          else find.call(search, value, reply)
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
  const sample = () => {
    const list = document.getElementById('search-results')
    if (list) {
      const options = [...list.querySelectorAll('[role=option]')]
      log.frames.push({
        t: performance.now(), busy: list.getAttribute('aria-busy') === 'true', list: box(list), first: box(options[0]),
        options: options.length, stale: options.filter(option => option.getAttribute('aria-disabled') === 'true').length,
        text: document.querySelector('main[aria-label="검색"]').innerText,
      })
    }
    if (!window.__stopSearchFrames) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
  // 기다림 표시 문구가 바뀔 때마다 시각을 남긴다. 노드를 붙이거나 글자를 바꾸는 DOM 호출 바로 뒤에 재므로
  // 실제 변경과의 차이는 그 호출 하나다. 관찰자는 그 밖의 변경을 놓치지 않으려고 함께 둔다.
  const mark = () => {
    const text = document.querySelector('main[aria-label="검색"] [data-slot=pending-status]')?.textContent ?? null
    if (text !== (log.statuses.at(-1)?.[1] ?? null)) log.statuses.push([performance.now(), text])
  }
  for (const name of ['appendChild', 'insertBefore']) {
    const original = Node.prototype[name]
    Node.prototype[name] = function (...args) { const result = original.apply(this, args); mark(); return result }
  }
  for (const [prototype, name] of [[Node.prototype, 'textContent'], [Node.prototype, 'nodeValue'], [CharacterData.prototype, 'data']]) {
    const descriptor = Object.getOwnPropertyDescriptor(prototype, name)
    Object.defineProperty(prototype, name, { ...descriptor, set(value) { descriptor.set.call(this, value); mark() } })
  }
  new MutationObserver(mark).observe(document, { subtree: true, childList: true, characterData: true })
  document.addEventListener('keydown', () => { log.keys += 1 }, true)
  document.addEventListener('click', () => { log.clicks += 1 }, true)
})()"""

OPTIONS = 'document.querySelectorAll("#search-results [role=option]").length'
STALE = 'document.querySelectorAll("#search-results [role=option][aria-disabled=true]").length'
BUSY = 'document.getElementById("search-results").getAttribute("aria-busy")'
ACTIVE = 'document.getElementById("search-results").getAttribute("aria-activedescendant")'
PENDING = 'document.querySelector("main[aria-label=\\"검색\\"] [data-slot=pending-status]").textContent'
PAGE_TEXT = 'document.querySelector("main[aria-label=\\"검색\\"]").innerText'
FIRST_TITLE = 'document.querySelector("#search-results [role=option] p")?.textContent ?? null'
LIST_BOX = ('JSON.stringify((r => [r.x, r.y, r.width, r.height].map(v => Math.round(v * 10) / 10))'
            '(document.getElementById("search-results").getBoundingClientRect()))')


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


def read(window, expression):
    return json.loads(js(window, f'JSON.stringify({expression})'))


@pytest.fixture
def open_window(core, monkeypatch, qapp):
    """검색 기록을 켠 MainWindow를 검색 탭에 연다. 첫 검색어로 결과를 받아 둔 채 돌려준다."""
    windows = []
    start = WebShellHost.start

    def record(host):
        script = QWebEngineScript()
        script.setName('search-recorder')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(SEARCH_RECORDER)
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', record)
    core.prepare_search()

    def create(first='Python'):
        window = MainWindow(core, player_factory=Player)
        windows.append(window)
        window.show()
        wait_for(lambda: window.web_host._frontend_ready)
        window.show_search()
        wait_for(lambda: read(window, "!!window.__search && !document.querySelector('main[aria-label=\"검색\"]').parentElement.hidden"))
        type_query(window, first)
        expected = len(core.search(first).results)
        wait_for(lambda: js(window, OPTIONS) == expected and js(window, BUSY) == 'false')
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def type_query(window, text):
    """사용자가 검색 칸에 글자를 넣은 것처럼 React의 입력 이벤트를 낸다."""
    js(window, "(() => { const input = document.getElementById('search-query'); input.focus(); "
       f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, {json.dumps(text)}); "
       "input.dispatchEvent(new Event('input', { bubbles: true })) })()")


def hold(window):
    js(window, 'window.__searchHold = true')


def release(window, query):
    js(window, f'window.__releaseSearch({json.dumps(query)})')


def page_of(window):
    return window.web_host.controllers['search']


def backend_selected(window):
    # 웹 채널 메시지는 순서대로 처리되므로, 이 왕복이 끝나면 그 전에 보낸 선택·재생 요청도 Python에 닿았다.
    js(window, "window.__snapshot = null; window.__search.snapshot(json => { window.__snapshot = JSON.parse(json) })")
    wait_for(lambda: read(window, 'window.__snapshot !== null'))
    return read(window, 'window.__snapshot.selectedIndex')


def view(window):
    return window.web_host.view.focusProxy() or window.web_host.view


def click(window, selector):
    center = json.loads(js(window, f"(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) }})()"))
    clicks = read(window, 'window.__searchLog.clicks')
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*map(round, center)))
    wait_for(lambda: read(window, 'window.__searchLog.clicks') > clicks)


def press(window, *keys):
    count = read(window, 'window.__searchLog.keys')
    for key in keys:
        QTest.keyClick(view(window), key)
    wait_for(lambda: read(window, 'window.__searchLog.keys') >= count + len(keys))


def frames_since(window, moment):
    return [frame for frame in read(window, 'window.__searchLog.frames') if frame['t'] >= moment]


def no_pending_text(statuses):
    return all(text in ('', None) for _, text in statuses)


def count(core, query):
    return len(core.search(query).results)


def test_previous_results_stay_dimmed_and_inert_until_new_results(open_window, core):
    window = open_window('Python')
    old, new = count(core, 'Python'), count(core, 'Python 기초')
    assert old > new > 0
    before = json.loads(js(window, LIST_BOX))
    first_row = read(window, 'document.querySelector("#search-results [role=option]").getBoundingClientRect().height')
    hold(window)
    typed = read(window, 'performance.now()')
    type_query(window, 'Python 기초')
    wait_for(lambda: page_of(window).query == 'Python 기초')
    # 백엔드 목록은 이미 새 검색 결과지만 화면은 이전 결과를 모두 흐리게 남기고 바쁨을 알린다.
    assert len(page_of(window).results) == new
    assert js(window, OPTIONS) == old and js(window, STALE) == old
    assert js(window, BUSY) == 'true'
    assert read(window, 'getComputedStyle(document.querySelector("#search-results [role=option]")).opacity') == '0.5'
    assert json.loads(js(window, LIST_BOX)) == before

    # 기다림 표시는 검색 요청을 보내고 300ms가 지나서야 나타난다.
    wait_for(lambda: js(window, PENDING) == '검색 중…')
    log = read(window, 'window.__searchLog')
    sent = next(t for t, value in log['sent'] if value == 'Python 기초')
    shown = next(t for t, text in log['statuses'] if t >= sent and text == '검색 중…')
    assert shown - sent >= 299, (sent, log['statuses'])
    text = js(window, PAGE_TEXT)
    assert f'검색 결과 {old}개' in text and '검색 결과가 없습니다' not in text

    # 흐린 결과는 보이기만 한다. 클릭·방향키·Enter가 이전 결과를 고르거나 재생하지 않는다.
    active = js(window, ACTIVE)
    click(window, '#search-result-1')
    assert backend_selected(window) == 0
    assert window.pages.currentWidget() is window.web_host and core.playback.session is None
    js(window, "document.getElementById('search-results').focus()")
    press(window, Qt.Key.Key_Down, Qt.Key.Key_End, Qt.Key.Key_Return)
    assert backend_selected(window) == 0
    assert js(window, ACTIVE) == active
    assert window.pages.currentWidget() is window.web_host and core.playback.session is None
    # 검색 입력은 막지 않는다.
    assert not read(window, 'document.getElementById("search-query").disabled')

    release(window, 'Python 기초')
    wait_for(lambda: js(window, OPTIONS) == new and js(window, BUSY) == 'false')
    assert js(window, STALE) == 0 and js(window, PENDING) == ''
    assert json.loads(js(window, LIST_BOX)) == before
    assert f'검색 결과 {new}개' in js(window, PAGE_TEXT)
    frames = frames_since(window, typed)
    # 새 결과가 올 때까지 목록은 한 번도 비지 않고, 목록 상자와 첫 결과의 높이도 그대로다.
    assert frames and all(frame['options'] > 0 for frame in frames), frames
    assert all(frame['list'] == before for frame in frames)
    assert all(frame['first'][3] == first_row for frame in frames)
    assert any(frame['stale'] == old and frame['busy'] for frame in frames)

    # 새 결과가 오면 지금 규칙대로 첫 결과가 선택되고 조작이 돌아온다.
    assert js(window, ACTIVE) == 'search-result-0'
    js(window, "document.getElementById('search-results').focus()")
    press(window, Qt.Key.Key_Return)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    assert core.playback.session.video_id == page_of(window).results[0].video_id


def test_pending_status_does_not_flash_when_results_arrive_quickly(open_window):
    # 검색 요청부터 결과까지 300ms 안이면 기다림 표시는 한 번도 나타나지 않는다(흐림만 잠깐 보인다).
    # 결과를 본 시각은 실제 반영보다 이르지 않으므로 250ms 안일 때만 유예 안에 왔다고 말할 수 있다.
    # 부하로 늦은 실행은 이 경우의 재현이 아니므로 검증 없이 통과시키지 않고 검색어를 바꿔 다시 재현한다.
    window = open_window('Python')
    attempts = []
    for query in ('한글', 'Python 응용', 'PYTHON'):
        typed = read(window, 'performance.now()')
        type_query(window, query)
        wait_for(lambda: js(window, BUSY) == 'false' and any(value == query for _, value in read(window, 'window.__searchLog.delivered')))
        log = read(window, 'window.__searchLog')
        sent = next(t for t, value in log['sent'] if t >= typed and value == query)
        delivered = next(t for t, value in log['delivered'] if t >= sent and value == query)
        attempts.append(delivered - sent)
        if delivered - sent < 250:
            break
    else:
        pytest.fail(f'결과가 250ms 안에 오는 경우를 재현하지 못했다: {attempts}')
    statuses = [entry for entry in log['statuses'] if entry[0] >= typed]
    assert no_pending_text(statuses), statuses
    assert all(frame['options'] > 0 for frame in frames_since(window, typed))


def test_late_result_of_previous_query_does_not_overwrite(open_window, core):
    for index in range(30):
        highlight = mark(core, core.videos()[0], 10 + index)
        core.update_highlight(highlight.id, start=highlight.start, end=None, note=f'Python 장면 {index:02d}')
    core.prepare_search()
    window = open_window('Python')
    many = len(core.search('Python').results)
    assert many > 20
    # 이전 결과를 내려 둔 채 검색어를 바꾼다.
    js(window, "document.getElementById('search-results').scrollTop = 600")
    wait_for(lambda: read(window, 'document.getElementById("search-results").scrollTop') > 0)
    hold(window)
    type_query(window, '한글')
    wait_for(lambda: page_of(window).query == '한글')
    type_query(window, '장면')
    wait_for(lambda: page_of(window).query == '장면')

    # 앞선 검색어의 결과가 늦게 와도 버린다. 화면은 계속 새 결과를 기다린다.
    release(window, '한글')
    frames = read(window, 'window.__searchLog.frames.length')
    wait_for(lambda: read(window, 'window.__searchLog.frames.length') >= frames + 3)
    assert js(window, OPTIONS) == many and js(window, STALE) == many and js(window, BUSY) == 'true'
    assert '한글 영상' not in js(window, PAGE_TEXT)

    release(window, '장면')
    wait_for(lambda: js(window, OPTIONS) == count(core, '장면') and js(window, BUSY) == 'false')
    # 새 결과도 600px 넘게 내릴 수 있지만, 첫 결과를 고른 채 맨 위부터 보인다.
    assert read(window, '(list => list.scrollHeight - list.clientHeight)(document.getElementById("search-results"))') > 600
    assert '한글 영상' not in js(window, PAGE_TEXT)
    assert js(window, ACTIVE) == 'search-result-0'
    assert read(window, 'document.getElementById("search-results").scrollTop') == 0

    # 현재 결과가 보인 뒤 더 앞선 결과가 와도 덮어쓰지 않는다.
    hold(window)
    type_query(window, '한글')
    wait_for(lambda: page_of(window).query == '한글')
    type_query(window, 'PYTHON 응용')
    wait_for(lambda: page_of(window).query == 'PYTHON 응용')
    release(window, 'PYTHON 응용')
    wait_for(lambda: js(window, FIRST_TITLE) == 'PYTHON 응용' and js(window, BUSY) == 'false')
    moment = read(window, 'performance.now()')
    release(window, '한글')
    wait_for(lambda: len(frames_since(window, moment)) >= 3)
    assert all('한글 영상' not in frame['text'] and frame['options'] == count(core, 'PYTHON 응용') and not frame['busy'] for frame in frames_since(window, moment))


def test_no_previous_results_shows_only_pending_status(open_window, core):
    window = open_window('없는낱말')
    assert '검색 결과가 없습니다' in js(window, PAGE_TEXT)
    before = json.loads(js(window, LIST_BOX))
    hold(window)
    typed = read(window, 'performance.now()')
    type_query(window, '없는낱말 더')
    wait_for(lambda: page_of(window).query == '없는낱말 더')
    wait_for(lambda: js(window, PENDING) == '검색 중…')
    # 새 검색 중에는 직전의 "없음" 안내도, 결과 개수도 보이지 않고 기다림 표시만 남는다. 목록 자리는 그대로다.
    text = js(window, PAGE_TEXT)
    assert '검색 결과가 없습니다' not in text and '검색 결과 0개' not in text
    assert js(window, BUSY) == 'true' and js(window, OPTIONS) == 0
    assert json.loads(js(window, LIST_BOX)) == before
    release(window, '없는낱말 더')
    wait_for(lambda: '검색 결과가 없습니다' in js(window, PAGE_TEXT) and js(window, BUSY) == 'false')
    assert js(window, PENDING) == ''
    assert all(frame['list'] == before for frame in frames_since(window, typed))


@pytest.mark.parametrize('failure', ['search', 'request'])
def test_failed_search_clears_dimmed_results_and_keeps_place(open_window, failure):
    window = open_window('Python')
    before = json.loads(js(window, LIST_BOX))
    status_row = read(window, 'document.querySelector("main[aria-label=\\"검색\\"] [data-slot=pending-status]").parentElement.getBoundingClientRect().height')
    if failure == 'search':
        def fail():
            raise RuntimeError('검증용 색인 오류')
        page_of(window).preparation = type('Preparation', (), {'ready': staticmethod(fail)})()
        message = '검색 실패: 검증용 색인 오류'
    else:
        js(window, 'window.__searchFail = true')
        message = '검색 실패: 검색 요청을 보내지 못했습니다.'
    type_query(window, 'Python 응용')
    wait_for(lambda: message in js(window, PAGE_TEXT))
    # 실패하면 흐린 이전 결과를 지우고 지금의 오류 표시(목록 위 안내 + 목록 자리 문구)를 쓴다. 기다림은 끝난다.
    assert js(window, OPTIONS) == 0 and js(window, BUSY) == 'false' and js(window, PENDING) == ''
    assert '검색하지 못했습니다' in js(window, PAGE_TEXT)
    # 안내가 목록 위에 자리를 잡아도 목록 자리는 최소 높이(min-h-32) 아래로 줄지 않고 폭도 그대로다.
    after = json.loads(js(window, LIST_BOX))
    assert after[0] == before[0] and after[2] == before[2] and after[3] >= 128
    assert read(window, 'document.querySelector("main[aria-label=\\"검색\\"] [data-slot=pending-status]").parentElement.getBoundingClientRect().height') == status_row


def test_ime_enter_and_scene_return_keep_query_results_selection(open_window, core):
    window = open_window('Python')
    full, partial = count(core, 'Python'), count(core, 'Python 기')
    calls = []
    search = core.search
    core.search = lambda text: (calls.append(text), search(text))[1]
    # 한글 조합 중에는 검색하지 않고 이전 결과를 흐리게 둔다. 조합이 끝나면 검색한다.
    js(window, "document.getElementById('search-query').dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))")
    type_query(window, 'Python 기')
    wait_for(lambda: js(window, STALE) == full and js(window, BUSY) == 'true')
    moment = read(window, 'performance.now()')
    wait_for(lambda: read(window, 'performance.now()') - moment > 400)
    assert calls == []
    js(window, "document.getElementById('search-query').dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '기' }))")
    wait_for(lambda: calls == ['Python 기'])
    wait_for(lambda: js(window, OPTIONS) == partial and js(window, BUSY) == 'false')

    # 디바운스 전 Enter는 곧바로 검색하고, 새 결과가 오면 목록으로 초점을 옮긴다.
    hold(window)
    type_query(window, 'Python')
    press(window, Qt.Key.Key_Return)
    wait_for(lambda: page_of(window).query == 'Python')
    assert js(window, STALE) == partial and read(window, 'document.activeElement.id') == 'search-query'
    release(window, 'Python')
    js(window, 'window.__searchHold = false')
    wait_for(lambda: read(window, 'document.activeElement.id') == 'search-results' and js(window, OPTIONS) == full)
    press(window, Qt.Key.Key_Down)
    wait_for(lambda: page_of(window).selected_index == 1)
    expected = {'query': read(window, 'document.getElementById("search-query").value'), 'active': js(window, ACTIVE),
                'text': js(window, PAGE_TEXT)}
    press(window, Qt.Key.Key_Return)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending and window.web_host.active_tab == 'search')
    wait_for(lambda: read(window, 'document.activeElement.id') == 'search-results')
    assert {'query': read(window, 'document.getElementById("search-query").value'), 'active': js(window, ACTIVE),
            'text': js(window, PAGE_TEXT)} == expected
    assert js(window, STALE) == 0 and js(window, BUSY) == 'false'
