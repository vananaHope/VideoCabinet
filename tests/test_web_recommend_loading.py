"""추천 첫 표시의 자리 표시, 갱신 중 줄 유지와 기다림 표시를 실제 웹 셸(offscreen)에서 검증한다.

첫 추천 데이터(changed 신호)와 관심 없음 응답은 테스트에서만 웹 쪽에서 붙잡아 늦춘다. 제품 코드에는 시험용 지연이 없다.
"""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript

from qt_wait import wait_for
from test_library_return_ui import Player
from test_web_library_data import core
from test_web_recommend_page import abandon, finish
from web_frames import stop_recording as stop_frames
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost

# holdData면 추천 데이터(첫 스냅숏 응답과 changed 신호)를 window.__releaseData()까지, holdDismiss면 관심 없음 응답을
# window.__releaseDismiss()까지 붙잡는다. Python 슬롯 안에서 기다리면 WebEngine 작업이 멈추므로 웹 쪽에서 늦춘다.
# 추천 페이지가 보이는 동안 그린 프레임마다 사용자가 보는 배치를 기록한다.
FRAME_RECORDER = """(() => {
  const frames = window.__recommendFrames = []
  let holdData = %(hold_data)s, holdDismiss = %(hold_dismiss)s, channelClass
  const data = [], dismissed = []
  window.__releaseData = () => { holdData = false; data.splice(0).forEach(run => run()) }
  window.__releaseDismiss = () => { holdDismiss = false; dismissed.splice(0).forEach(run => run()) }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const recommend = channel.objects.recommend, connect = recommend.changed.connect, snapshot = recommend.snapshot, dismiss = recommend.dismiss
        const deliver = callback => json => holdData ? data.push(() => callback(json)) : callback(json)
        recommend.changed.connect = callback => connect.call(recommend.changed, deliver(callback))
        recommend.snapshot = reply => snapshot.call(recommend, deliver(reply))
        recommend.dismiss = (id, reply) => dismiss.call(recommend, id, json => holdDismiss ? dismissed.push(() => reply(json)) : reply(json))
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
    const main = document.querySelector('main[aria-label="추천"]')
    if (main?.getClientRects().length) {
      const list = main.querySelector('[data-recommend-list]'), row = list?.querySelector('section')
      frames.push({
        t: performance.now(),
        boxes: {
          header: box(main.firstElementChild), status: box(main.querySelector('[data-recommend-status]')), list: box(list),
          rowHeader: box(row?.children[0]), strip: box(row?.children[1]), card: box(row?.children[1].children[0]),
        },
        skeletons: main.querySelectorAll('[data-slot=skeleton]').length,
        cells: main.querySelectorAll('[role=gridcell]').length,
        busy: main.querySelectorAll('[aria-busy=true]').length,
        pending: main.querySelector('[data-slot=pending-status]')?.textContent ?? null,
        text: main.innerText,
      })
    }
    if (!window.__stopRecommendFrames) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
})()"""

PENDING = 'document.querySelector("main[aria-label=\\"추천\\"] [data-slot=pending-status]").textContent'
CELLS = 'document.querySelectorAll("main[aria-label=\\"추천\\"] [role=gridcell]").length'
PAGE_TEXT = 'document.querySelector("main[aria-label=\\"추천\\"]").innerText'
EMPTY = '지금은 추천할 영상이 없어요'


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


@pytest.fixture
def open_window(core, monkeypatch, qapp):
    windows = []
    start = WebShellHost.start
    options = []

    def record_frames(host):
        script = QWebEngineScript()
        script.setName('recommend-frames')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        hold_data, hold_dismiss = options[-1]
        script.setSourceCode(FRAME_RECORDER % {'hold_data': json.dumps(hold_data), 'hold_dismiss': json.dumps(hold_dismiss)})
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', record_frames)

    def create(*, hold_data=False, hold_dismiss=False):
        options.append((hold_data, hold_dismiss))
        window = MainWindow(core, player_factory=Player)
        windows.append(window)
        window.show()
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def recommendations(core):
    # 첫 두 영상은 이어 보기 줄에 든다. 셋째는 다 봐서 새로 추가됨 줄이 끼어들지 않는다.
    first, second, third = core.videos()
    abandon(core, first, second)
    finish(core, third)


LONG_TITLE = '공백없는아주긴기준영상제목' * 20


def long_title_recommendations(core):
    # 긴 제목의 첫 영상을 다 보고 세 영상에 같은 태그를 붙여, 첫 줄이 『긴 제목』을 봤다면 줄(나머지 두 영상)이 된다.
    source = core.videos()[0]
    core.rename_video(source.id, LONG_TITLE)
    finish(core, source)
    for video in core.videos():
        core.add_video_tag(video.id, '자연다큐멘터리')


def stop_recording(window, done):
    return stop_frames(window, 'recommend', done)


def elapse(window, milliseconds):
    """페이지 시계로 milliseconds가 지날 때까지 조건 대기한다."""
    start = js(window, 'performance.now()')
    wait_for(lambda: js(window, 'performance.now()') - start > milliseconds)


@pytest.mark.parametrize('case', ['rows', 'long-title', 'empty'])
def test_first_display_placeholder_keeps_header_status_and_first_row(open_window, core, case):
    recommended = case != 'empty'
    if case == 'rows':
        recommendations(core)
    elif case == 'long-title':
        long_title_recommendations(core)
    else:
        # 모든 영상을 관심 없음으로 빼 추천 줄이 하나도 없게 한다.
        for video in core.videos():
            core.dismiss_video(video.id)
    window = open_window(hold_data=True)
    window.navigate_web_tab('recommend')
    wait_for(lambda: js(window, '!!document.querySelector("main[aria-label=\\"추천\\"]").getClientRects().length'))
    # 데이터가 오기 전에는 줄 자리 표시(aria-busy)를 보인다. 빈 추천 안내나 기다림 문구가 먼저 보이지 않는다.
    elapse(window, 400)
    assert js(window, 'document.querySelectorAll("main[aria-label=\\"추천\\"] [aria-busy=true]").length') == 1
    assert js(window, PENDING) == ''
    assert EMPTY not in js(window, PAGE_TEXT) and js(window, CELLS) == 0
    # 자리 표시를 담은 표본이 기록에 쌓인 뒤에 데이터를 보낸다.
    wait_for(lambda: js(window, 'window.__recommendFrames.some(frame => frame.skeletons > 0)'))

    js(window, 'window.__releaseData()')
    wait_for(lambda: js(window, CELLS) == 2 if recommended else EMPTY in js(window, PAGE_TEXT))
    # 마지막 표본이 결과 상태를 담을 때까지 기록한다.
    frames = stop_recording(window, lambda frame: frame['skeletons'] == 0 and frame['busy'] == 0
                            and (frame['cells'] == 2 if recommended else EMPTY in frame['text']))
    loading, final = [frame for frame in frames if frame['skeletons']], frames[-1]
    assert loading and final['skeletons'] == 0 and final['busy'] == 0
    assert not any(EMPTY in frame['text'] for frame in loading)
    for frame in frames:
        if recommended:
            # 머리글·개수 줄·목록 영역·첫 줄 머리·카드 줄·첫 카드의 경계가 첫 프레임부터 결과와 같다.
            assert frame['boxes'] == final['boxes'], frame
        else:
            # 결과 없음은 자리 표시와 다른 빈 안내로 바뀐다. 그 위의 머리글·개수 줄은 움직이지 않는다.
            assert (frame['boxes']['header'], frame['boxes']['status']) == (final['boxes']['header'], final['boxes']['status']), frame
    if not recommended:
        assert final['boxes']['list'] is None and EMPTY in final['text']
    if case == 'long-title':
        # 긴 줄 제목은 한 줄로 말줄임하고 개수는 그대로 보인다. 전체 제목은 줄 이름과 마우스 올림 제목에 남는다.
        header = json.loads(js(window, """JSON.stringify((() => {
          const row = document.querySelector('#recommendations [role=row]'), title = row.querySelector('[role=rowheader] h2')
          const count = row.querySelector('[role=rowheader] > span')
          return { label: row.getAttribute('aria-label'), title: title.title, text: title.textContent,
            truncated: title.scrollWidth > title.clientWidth, count: count.textContent, countWidth: count.getBoundingClientRect().width }
        })())"""))
        assert header['truncated'] and header['count'] == '2개' and header['countWidth'] > 0, header
        assert LONG_TITLE in header['title'] and LONG_TITLE in header['text'] and header['label'] == f"{header['text']} · 2개", header


def test_dismiss_keeps_rows_while_waiting_and_shows_pending_status(open_window, core):
    recommendations(core)
    window = open_window(hold_dismiss=True)
    host = window.web_host
    window.navigate_web_tab('recommend')
    wait_for(lambda: js(window, CELLS) == 2)
    host.focus_content()
    wait_for(lambda: js(window, 'document.activeElement?.id') == 'recommendations')
    js(window, 'window.__recommendFrames.length = 0')

    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Backspace)
    # 관심 없음 결과(줄 갱신)는 곧바로 반영되고, 응답을 기다리는 동안은 이전 배치 그대로 기다림 표시만 보인다.
    wait_for(lambda: js(window, CELLS) == 1)
    wait_for(lambda: js(window, PENDING) == '추천을 다시 계산하는 중…')
    assert js(window, 'document.getElementById("recommendations").getAttribute("aria-busy")') == 'true'
    waiting = stop_recording(window, lambda frame: frame['cells'] == 1 and frame['pending'] == '추천을 다시 계산하는 중…')
    assert waiting
    for frame in waiting:
        # 줄을 비웠다 채우지 않고, 자리 표시로 바꾸지 않는다. 목록 위 배치도 그대로다.
        assert frame['cells'] >= 1 and frame['skeletons'] == 0, frame
        assert (frame['boxes']['header'], frame['boxes']['status'], frame['boxes']['list']) == \
            (waiting[0]['boxes']['header'], waiting[0]['boxes']['status'], waiting[0]['boxes']['list']), frame

    js(window, 'window.__releaseDismiss()')
    wait_for(lambda: js(window, PENDING) == '' and '관심 없음으로 뺐어요' in js(window, PAGE_TEXT))
    assert js(window, 'document.getElementById("recommendations").getAttribute("aria-busy")') == 'false'
    assert len(core.dismissed_videos()) == 1


def test_refresh_failure_keeps_rows_and_shows_error(open_window, core):
    recommendations(core)
    window = open_window()
    window.navigate_web_tab('recommend')
    wait_for(lambda: js(window, CELLS) == 2)
    js(window, 'window.__recommendFrames.length = 0')

    # 라이브러리 갱신으로 다시 계산하다 실패한다.
    core.settings.set('recommend.revisit_days', -1)
    window.refresh()
    wait_for(lambda: '추천을 불러오지 못했어요' in js(window, PAGE_TEXT))
    elapse(window, 100)
    frames = stop_recording(window, lambda frame: '추천을 불러오지 못했어요' in frame['text'])
    # 보던 줄을 비우지 않고 오류 안내만 더한다. 자리 표시나 기다림 표시가 남지 않는다.
    assert all(frame['cells'] == 2 and frame['skeletons'] == 0 for frame in frames)
    final = frames[-1]
    assert final['busy'] == 0 and final['pending'] == '' and EMPTY not in final['text']
