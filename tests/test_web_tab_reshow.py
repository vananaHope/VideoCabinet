"""#265 다시 보인 탭은 즉시, 늦은 응답은 공용 세대 가드로 막는다. 실제 웹 셸(offscreen)과 가짜 플레이어로 검증한다.

웹이 받은 상태 메시지는 WebChannel 전송을 감싸 세대가 붙은 신호를 페이지별로 센다. 지연은 그 전송에서 특정 메시지를
붙잡았다가 나중에 넘기는 방식으로 재현한다(제품 코드에 시험용 지연을 넣지 않는다).
"""
from datetime import datetime, timezone
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from qt_wait import wait_for
from test_emergency_hide_ui import Player
from test_web_library_data import Media
from test_web_library_loading import click, js
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.random_continuous_play import RandomPlayScope
from my_video_manager.ui import MainWindow

GRID = 'document.getElementById("library-grid")'
COUNT = 'document.querySelector("[aria-label=\'라이브러리 등록·표시 개수\']")?.textContent ?? ""'
QUERY = 'document.querySelector("[aria-label=\'영상 제목 빠른 검색\']")'
SELECTED = f'{GRID}.getAttribute("aria-activedescendant")'
STATISTICS_PERIOD = '!!document.querySelector(\'[data-page=statistics] nav[aria-label="통계 기간"]\')'

# 세대가 붙은 신호(밀어 보내는 상태)를 페이지별로 세고, 시험이 고른 메시지를 붙잡았다가 넘긴다.
RECORDER = """(() => {
  if (window.mvmReceived) return;
  window.mvmReceived = {};
  window.mvmHolds = [];
  window.mvmFocusLog = [];
  const describe = node => (node?.id || node?.tagName || '?') + (node?.closest?.('[hidden]') ? '(hidden)' : '');
  document.addEventListener('focusin', event => window.mvmFocusLog.push('in:' + describe(event.target)), true);
  document.addEventListener('focusout', event => window.mvmFocusLog.push('out:' + describe(event.target)), true);
  const transport = qt.webChannelTransport, receive = transport.onmessage;
  transport.onmessage = function(event) {
    const data = JSON.parse(event.data);
    const raw = data.type === 1 ? data.args?.[0] : data.type === 10 ? data.data : undefined;
    let state = null;
    try { state = typeof raw === 'string' ? JSON.parse(raw) : null } catch (error) { state = null }
    const stamped = state !== null && typeof state === 'object' && 'generation' in state;
    if (stamped && data.type === 1) window.mvmReceived[data.object] = (window.mvmReceived[data.object] ?? 0) + 1;
    const hold = stamped && window.mvmHolds.find(entry => !entry.release && entry.test(data.type === 1 ? 'signal' : 'reply', data.object, state));
    if (hold) { hold.release = () => receive.call(transport, event); return; }
    receive.call(transport, event);
  };
})()"""


@pytest.fixture
def library(tmp_path):
    """제목에 clip이 들어간 영상 60개. 시작 검사·자동 감지는 꺼서 시험 중 다른 갱신이 끼지 않게 한다."""
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / 'data/library.sqlite3')
    for index in range(60):
        path = tmp_path / f'clip {index:03}.mkv'
        path.write_bytes(f'video {index}'.encode())
        core.add_file(path)
    core.set_automatic_detection_enabled(False)
    return core


@pytest.fixture
def open_window(library, qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    windows = []

    def create():
        library.save_library_view_options({**default_options(), 'card_size': 'small'})
        window = MainWindow(library, player_factory=Player)
        monkeypatch.setattr(window.tray.icon, 'showMessage', lambda *args: None)
        windows.append(window)
        window.resize(1100, 720)
        window.show()
        window.activateWindow()
        host = window.web_host
        wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
        wait_for(lambda: js(window, f'{GRID}.querySelectorAll("[role=gridcell]").length') > 0)
        # 첫 진입의 기본 초점이 자리 잡은 뒤에 조작한다. 늦게 온 첫 초점이 시험의 입력을 가로채지 않게 한다.
        wait_for(lambda: active_element(window) == 'library-grid')
        js(window, RECORDER)
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def view(window):
    return window.web_host.view.focusProxy()


def received(window):
    return json.loads(js(window, 'JSON.stringify(window.mvmReceived)'))


def active_element(window):
    return js(window, '(e => !e || e === document.body ? "" : e.id || e.getAttribute("aria-label") || e.title || e.textContent.trim())(document.activeElement)')


def middle_card(window):
    """격자 보기 영역 가운데에 그려진 카드의 영상 ID."""
    return int(js(window, f"""(() => {{ const g = {GRID}.getBoundingClientRect();
      return document.elementFromPoint(g.x + g.width / 2, g.y + g.height / 2).closest('[role=gridcell]').id.slice(6) }})()"""))


def switch(window, number, tab, focused):
    """Ctrl+숫자로 탭을 바꾸고 그 탭에서 초점이 자리 잡을 때까지 기다린다.

    셸은 갱신을 보낸 뒤 초점 요청을 보내므로, 초점이 자리 잡았으면 그 전의 메시지는 모두 반영됐다.
    focused가 None이면 초점은 보지 않는다.
    """
    window.activateWindow()
    QTest.keyClick(view(window), getattr(Qt.Key, f'Key_{number}'), Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: window.web_host.active_tab == tab)
    wait_for(lambda: js(window, f'!document.querySelector("[data-page={tab}]").hidden'))
    if focused is None:
        return
    try:
        wait_for(lambda: active_element(window) == focused)
    except AssertionError:
        log = js(window, 'JSON.stringify((window.mvmFocusLog ?? []).slice(-8))')
        raise AssertionError(f'{tab} 탭 초점: {active_element(window)!r} (기대 {focused!r}) 최근 초점 {log}') from None


def hold(window, test):
    """test(kind, object, state)가 참인 다음 메시지를 붙잡는다. 붙잡은 번호를 돌려준다."""
    return js(window, f'window.mvmHolds.push({{ test: {test}, release: null }}) - 1')


def held(window, index):
    return js(window, f'typeof window.mvmHolds[{index}].release === "function"')


def release(window, index):
    """붙잡은 메시지를 넘기고, 그 결과가 그려질 때까지(두 프레임) 기다린다."""
    js(window, f"""window.mvmHolds[{index}].release(); window.mvmDrawn = false;
      requestAnimationFrame(() => requestAnimationFrame(() => {{ window.mvmDrawn = true }})); true""")
    wait_for(lambda: js(window, 'window.mvmDrawn === true'))


def visit_all_tabs(window):
    """한 번씩 열어 각 탭의 첫 데이터를 만든다. 처음 보이는 탭은 기본 위치에 초점을 둔다."""
    for number, tab, focused in ((2, 'recommend', 'recommendations'), (3, 'reel', 'reel-list'),
                                 (4, 'search', 'search-query'), (5, 'queue', 'queue-list'), (6, 'statistics', '30일'),
                                 (7, 'folders', 'folders-add'), (8, 'settings', '일반'), (1, 'library', 'library-grid')):
        switch(window, number, tab, focused)
        if tab == 'statistics':
            # 첫 계산 결과가 도착할 때까지 기다린다.
            wait_for(lambda: js(window, STATISTICS_PERIOD)
                     and not window.web_host.controllers['statistics'].loading)


def test_reshown_tabs_keep_state_and_receive_nothing_without_changes(open_window):
    window = open_window()
    visit_all_tabs(window)
    # 라이브러리: 아래쪽 카드를 고르고 스크롤한 채 빠른 검색 칸에 초점과 검색어를 둔다.
    js(window, f'{GRID}.scrollTop = 600; true')
    wait_for(lambda: js(window, f'{GRID}.scrollTop') == 600)
    target = middle_card(window)
    click(window, f'#video-{target}')
    wait_for(lambda: window.library_page.selected_id == target)
    scroll = js(window, f'{GRID}.scrollTop')
    click(window, '[aria-label="영상 제목 빠른 검색"]')
    QTest.keyClicks(view(window), 'clip')
    wait_for(lambda: window.library_page.options['query'] == 'clip')
    wait_for(lambda: js(window, f'{QUERY}.value') == 'clip' and active_element(window) == '영상 제목 빠른 검색')
    # 검색: 검색어를 넣고 두 번째 결과를 고른 채 결과 목록에 초점을 둔다.
    switch(window, 4, 'search', 'search-query')
    QTest.keyClicks(view(window), 'clip 01')
    wait_for(lambda: window.web_host.controllers['search'].query == 'clip 01')
    wait_for(lambda: js(window, 'document.getElementById("search-results").getAttribute("aria-busy")') == 'false'
             and js(window, 'document.querySelectorAll("#search-results [role=option]").length') > 2)
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_for(lambda: active_element(window) == 'search-results')
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_for(lambda: window.web_host.controllers['search'].selected_index == 1)
    before = received(window)

    switch(window, 2, 'recommend', 'recommendations')
    switch(window, 1, 'library', '영상 제목 빠른 검색')
    switch(window, 4, 'search', 'search-results')
    switch(window, 1, 'library', '영상 제목 빠른 검색')

    # 바뀐 것이 없으면 어느 탭도 상태를 다시 받지 않는다.
    assert received(window) == before
    assert js(window, SELECTED) == f'video-{target}'
    assert js(window, f'{GRID}.scrollTop') == scroll
    assert js(window, f'{QUERY}.value') == 'clip'
    switch(window, 4, 'search', 'search-results')
    assert js(window, 'document.getElementById("search-query").value') == 'clip 01'
    assert js(window, 'document.getElementById("search-results").getAttribute("aria-activedescendant")') == 'search-result-1'
    # 스크롤을 스스로 기억하지 않는 페이지(통계)도 숨겼다 보이면 보던 자리에 있다.
    statistics = '[data-page=statistics] main'
    switch(window, 6, 'statistics', '30일')
    js(window, f'document.querySelector("{statistics}").scrollTop = 120; true')
    switch(window, 1, 'library', '영상 제목 빠른 검색')
    switch(window, 6, 'statistics', '30일')
    assert js(window, f'document.querySelector("{statistics}").scrollTop') == 120
    assert received(window) == before


def test_changes_while_hidden_reach_the_tab_once_when_reshown(open_window):
    window = open_window()
    visit_all_tabs(window)
    videos = window.core.videos()
    js(window, f'{GRID}.scrollTop = 900; true')
    wait_for(lambda: js(window, f'{GRID}.scrollTop') == 900)
    keep = middle_card(window)
    click(window, f'#video-{keep}')
    wait_for(lambda: window.library_page.selected_id == keep)
    scroll = js(window, f'{GRID}.scrollTop')
    gone, finished = [video.id for video in videos if video.id != keep][:2]
    switch(window, 2, 'recommend', 'recommendations')
    before = received(window)

    # 검사 결과 반영처럼 라이브러리를 다시 읽는 변경과 자막 완료가 숨은 라이브러리에 생긴다.
    window.core.exclude_video(gone)
    window.refresh()
    window.subtitles.video_changed.emit(finished)

    switch(window, 1, 'library', 'library-grid')
    after = received(window)
    assert after.get('library', 0) == before.get('library', 0) + 1
    assert js(window, COUNT) == '등록 영상 59개 · 표시 59개'
    assert js(window, SELECTED) == f'video-{keep}'
    assert abs(js(window, f'{GRID}.scrollTop') - scroll) <= 1
    # 같은 변경은 숨어 있던 다른 탭에도 다시 보일 때 한 번 반영된다.
    switch(window, 7, 'folders', 'folders-add')
    assert received(window).get('folders', 0) == after.get('folders', 0) + 1


def test_late_view_reply_does_not_overwrite_newer_library(open_window):
    window = open_window()
    videos = window.core.videos()
    click(window, '[aria-label="영상 제목 빠른 검색"]')
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: js(window, COUNT) == '등록 영상 60개 · 표시 60개' and window.library_page.options['query'] == 'clip 0')
    # 마지막 글자의 보기 응답(표시 10개)을 붙잡는다.
    reply = hold(window, "(kind, object, state) => kind === 'reply' && 'visibleIds' in state && !('videos' in state)")
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: window.library_page.options['query'] == 'clip 00')
    wait_for(lambda: held(window, reply))
    # 응답이 늦는 동안 검사 결과가 같은 조건의 새 목록을 먼저 보낸다.
    window.core.exclude_video(videos[3].id)
    window.refresh()
    wait_for(lambda: js(window, COUNT) == '등록 영상 59개 · 표시 9개')
    # 늦게 온 이전 세대 응답은 지금 화면을 바꾸지 않는다.
    release(window, reply)
    assert js(window, COUNT) == '등록 영상 59개 · 표시 9개'
    assert js(window, f'{QUERY}.value') == 'clip 00'


def test_older_push_after_fast_tab_switches_does_not_replace_newer_list(open_window):
    window = open_window()
    visit_all_tabs(window)
    videos = window.core.videos()
    switch(window, 2, 'recommend', 'recommendations')
    window.core.exclude_video(videos[0].id)
    window.refresh()
    late = hold(window, "(kind, object, state) => kind === 'signal' && object === 'library' && 'videos' in state")
    # 라이브러리를 잠깐 보였다가 곧바로 다른 탭으로 간다. 다시 보일 때 보낸 목록이 늦게 도착한다.
    window.navigate_web_tab('library')
    wait_for(lambda: held(window, late))
    switch(window, 2, 'recommend', 'recommendations')
    window.core.exclude_video(videos[1].id)
    window.refresh()
    switch(window, 1, 'library', 'library-grid')
    wait_for(lambda: js(window, COUNT) == '등록 영상 58개 · 표시 58개')
    # 먼저 보낸 목록(59개)이 이제 도착해도 지금 화면은 그대로다.
    release(window, late)
    assert js(window, COUNT) == '등록 영상 58개 · 표시 58개'


def test_playback_return_and_tray_restore_bring_hidden_changes(open_window):
    window = open_window()
    visit_all_tabs(window)
    videos = window.core.videos()
    # 재생 중 다른 영상이 빠지면(외부 변경) 복귀한 라이브러리와 숨은 추천 탭에 반영된다.
    switch(window, 2, 'recommend', 'recommendations')
    recommend = received(window).get('recommend', 0)
    switch(window, 1, 'library', 'library-grid')
    window.play(videos[5].id)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.core.exclude_video(videos[0].id)
    window.refresh()
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    wait_for(lambda: js(window, COUNT) == '등록 영상 59개 · 표시 59개')
    switch(window, 2, 'recommend', 'recommendations')
    assert received(window).get('recommend', 0) > recommend

    # 추천 탭에서 무작위 연속 재생을 시작해 다음 영상으로 넘긴 뒤 창을 닫아 트레이로 숨긴다(#257 점검 항목).
    # 코어가 바꾼 선택은 트레이로 다시 연 추천 탭이 아니라 숨은 라이브러리에 다시 보일 때 알린다.
    window.play(videos[10].id, random_scope=RandomPlayScope())
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.activateWindow()
    QTest.keyClick(QApplication.focusWidget() or window, Qt.Key.Key_PageDown)
    wait_for(lambda: window.core.playback.session.video_id != videos[10].id)
    last = window.core.playback.session.video_id
    window.close()
    wait_for(lambda: not window.isVisible())
    assert window.web_host.active_tab == 'recommend'
    library = received(window).get('library', 0)
    window.tray.open()
    wait_for(lambda: window.isVisible() and window.web_host.active_tab == 'recommend')
    switch(window, 1, 'library', 'library-grid')
    assert received(window).get('library', 0) == library + 1
    wait_for(lambda: js(window, SELECTED) == f'video-{last}')
    assert window.library_page.selected_id == last
