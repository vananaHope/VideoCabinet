"""통계 첫 계산·기간 변경의 자리 표시·기다림 표시와 배치 안정을 실제 웹 셸(offscreen)에서 검증한다.

계산 지연은 테스트에서 core.statistics_dashboard를 작업자 스레드 안에서 붙잡아 재현한다. 제품 코드에는 시험용 지연이 없다.
"""
import json
import os
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript

from qt_wait import wait_for
from test_library_return_ui import Player
from test_web_library_data import core
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost

# 문서가 만들어질 때부터, 통계 페이지가 보이는 동안 그린 프레임마다 사용자가 보는 배치를 기록한다.
# 결과 영역은 시작 위치(x·y·폭)만 비교한다. 전체 높이는 데이터에 따라 달라도 된다.
FRAME_RECORDER = """(() => {
  const frames = window.__statisticsFrames = []
  const box = element => {
    if (!element) return null
    const r = element.getBoundingClientRect()
    return [r.x, r.y, r.width, r.height].map(value => Math.round(value * 10) / 10)
  }
  const sample = () => {
    const main = document.querySelector('main[aria-label="통계"]')
    if (main?.getClientRects().length) {
      const results = main.querySelector('[data-statistics-results]')
      const card = results?.querySelector('section')
      frames.push({
        t: performance.now(),
        boxes: {
          header: box(main.firstElementChild), period: box(main.querySelector('nav[aria-label="통계 기간"]')),
          status: box(main.querySelector('[data-statistics-status]')), sections: box(main.querySelector('nav[aria-label="통계 구역"]')),
          results: box(results)?.slice(0, 3) ?? null,
          cards: card ? [...card.parentElement.children].map(box) : null,
          chart: box(results?.querySelector('[data-slot=chart], [data-chart-placeholder]')),
        },
        skeletons: main.querySelectorAll('[data-slot=skeleton]').length,
        busy: [...main.querySelectorAll('[aria-busy=true]')].map(element => element.hasAttribute('data-statistics-results') ? 'results' : element.tagName),
        pending: main.querySelector('[data-slot=pending-status]')?.textContent ?? null,
        text: main.innerText,
      })
    }
    if (!window.__stopStatisticsFrames) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
})()"""

PENDING = 'document.querySelector("main[aria-label=\\"통계\\"] [data-slot=pending-status]").textContent'
RESULTS_BUSY = 'document.querySelector("[data-statistics-results]")?.getAttribute("aria-busy") ?? null'
PAGE_TEXT = 'document.querySelector("main[aria-label=\\"통계\\"]").innerText'
CHARTS = 'document.querySelectorAll("[data-statistics-results] [data-slot=chart]").length'
ZERO_TEXTS = ('이 기간에는 시청 기록이 없습니다', '아직 시청한 영상이 없어요')


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


@pytest.fixture
def open_window(core, monkeypatch, qapp):
    windows = []
    start = WebShellHost.start

    def record_frames(host):
        script = QWebEngineScript()
        script.setName('statistics-frames')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(FRAME_RECORDER)
        host.engine_page.scripts().insert(script)
        start(host)

    monkeypatch.setattr(WebShellHost, 'start', record_frames)

    def create():
        window = MainWindow(core, player_factory=Player)
        windows.append(window)
        window.show()
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def hold(core, monkeypatch):
    """다음 통계 계산 한 번을 작업자 안에서 붙잡는다. 테스트가 끝나면 늘 풀어 작업자가 남지 않게 한다."""
    original = core.statistics_dashboard
    holds = []

    def start():
        started, release = Event(), Event()
        holds.append(release)

        def slow(days):
            monkeypatch.setattr(core, 'statistics_dashboard', original)
            started.set()
            assert release.wait(30)
            return original(days)

        monkeypatch.setattr(core, 'statistics_dashboard', slow)
        return started, release

    yield start
    for release in holds:
        release.set()


def watch(core, video, seconds=40):
    core.playback.start(video.id, 0)
    core.playback.report(seconds)
    core.playback.end()


def stop_recording(window):
    js(window, 'window.__stopStatisticsFrames = true')
    return json.loads(js(window, 'JSON.stringify(window.__statisticsFrames)'))


def click(window, element):
    """element(JS 식)가 가리키는 요소의 가운데를 실제 마우스로 누른다."""
    center = json.loads(js(window, f'(() => {{ const r = ({element}).getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) }})()'))
    QTest.mouseClick(window.web_host.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(*map(round, center)))


def settled(window):
    return js(window, RESULTS_BUSY) == 'false' and js(window, CHARTS) == 3


@pytest.mark.parametrize('viewed', [True, False], ids=['viewed', 'no-viewing'])
def test_first_calculation_shows_placeholder_without_moving_layout(open_window, hold, core, viewed):
    if viewed:
        watch(core, core.videos()[0])
    started, release = hold()
    window = open_window()
    window.navigate_web_tab('statistics')
    wait_for(started.is_set)
    # 계산이 300ms 넘게 이어지면 상태 줄에 기다림 표시가 나타나고, 결과 자리는 자리 표시(aria-busy)다.
    wait_for(lambda: js(window, PENDING) == '30일 시청 기록을 계산하고 있어요…')
    assert js(window, RESULTS_BUSY) == 'true'
    assert js(window, 'document.querySelector("main[aria-label=\\"통계\\"]").hasAttribute("aria-busy")') is False
    assert js(window, "document.querySelector('main[aria-label=\"통계\"] [data-slot=pending-status]').getAttribute('role')") == 'status'
    text = js(window, PAGE_TEXT)
    assert not any(zero in text for zero in ZERO_TEXTS) and '통계를 계산하지 못했어요' not in text

    release.set()
    wait_for(lambda: settled(window))
    frames = stop_recording(window)
    loading, final = [frame for frame in frames if frame['skeletons']], frames[-1]
    assert loading and final['skeletons'] == 0 and final['busy'] == [] and final['pending'] == ''
    assert len(final['boxes']['cards']) == 6 and final['boxes']['chart']
    for frame in frames:
        # 첫 프레임부터 머리글·기간 선택·상태 줄·구역 탭·결과 영역 시작·첫 카드 줄·첫 차트의 경계가 결과와 같다.
        assert frame['boxes'] == final['boxes'], frame
    # 자리 표시는 결과 영역에만 aria-busy를 단다. 데이터 0개 안내는 자리 표시 동안 보이지 않는다.
    assert all(frame['busy'] == ['results'] for frame in loading)
    assert not any(zero in frame['text'] for frame in loading for zero in ZERO_TEXTS)
    # 결과 없음(시청 기록 0개)은 자리 표시와 다른 안내로 보인다.
    if viewed:
        assert not any(zero in final['text'] for zero in ZERO_TEXTS)
    else:
        assert all(zero in final['text'] for zero in ZERO_TEXTS)


def test_period_change_keeps_previous_result_and_shows_only_pending_status(open_window, hold, core):
    watch(core, core.videos()[0])
    window = open_window()
    window.navigate_web_tab('statistics')
    wait_for(lambda: settled(window))
    js(window, 'window.__statisticsFrames.length = 0')
    previous = js(window, 'document.querySelector("[data-statistics-status] p").textContent')
    page = window.web_host.controllers['statistics']

    started, release = hold()
    click(window, 'document.querySelector(\'nav[aria-label="통계 기간"] [data-tab="365"]\')')
    wait_for(started.is_set)
    wait_for(lambda: js(window, PENDING) == '365일 시청 기록을 계산하고 있어요…')
    # 이전 결과(30일)를 그대로 두고 결과 영역만 aria-busy다. 자리 표시로 바꾸지 않는다.
    assert js(window, RESULTS_BUSY) == 'true'
    assert js(window, 'document.querySelector("[data-statistics-status] p").textContent') == previous
    assert js(window, 'document.querySelectorAll("main[aria-label=\\"통계\\"] [data-slot=skeleton]").length') == 0
    assert js(window, CHARTS) == 3

    release.set()
    wait_for(lambda: page.result['period']['days'] == 365 and settled(window)
             and js(window, 'document.querySelector("[data-statistics-status] p").textContent') != previous)
    frames = stop_recording(window)
    final = frames[-1]
    assert any(frame['pending'] for frame in frames) and final['pending'] == ''
    for frame in frames:
        # 도착 전후로 아무것도 움직이지 않고, 이전 결과가 자리 표시로 바뀌는 프레임이 없다.
        assert frame['boxes'] == final['boxes'], frame
        assert frame['skeletons'] == 0, frame


def test_failed_first_calculation_ends_waiting_and_retry_recovers(open_window, core, monkeypatch):
    original = core.statistics_dashboard

    def fail(days):
        raise ValueError('통계 읽기 실패')

    monkeypatch.setattr(core, 'statistics_dashboard', fail)
    window = open_window()
    window.navigate_web_tab('statistics')
    wait_for(lambda: '통계 읽기 실패' in js(window, PAGE_TEXT))
    # 실패는 끝난 상태다. 자리 표시·aria-busy·기다림 표시를 끝내고 오류 안내와 결과 없음 안내를 보인다.
    failed_at = js(window, 'performance.now()')
    wait_for(lambda: js(window, 'performance.now()') - failed_at > 600)
    frames = [frame for frame in stop_recording(window) if frame['t'] >= failed_at]
    assert frames
    for frame in frames:
        assert frame['skeletons'] == 0 and frame['busy'] == [] and frame['pending'] == '', frame
        assert '통계를 계산하지 못했어요' in frame['text'] and '통계 읽기 실패' in frame['text']

    monkeypatch.setattr(core, 'statistics_dashboard', original)
    click(window, '[...document.querySelectorAll("main[aria-label=\\"통계\\"] button")].find(button => button.textContent === "다시 시도")')
    wait_for(lambda: settled(window))
    text = js(window, PAGE_TEXT)
    assert '통계 읽기 실패' not in text and '통계를 계산하지 못했어요' not in text
    assert js(window, PENDING) == ''
