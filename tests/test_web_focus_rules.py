"""#264 키보드 초점 규칙. 실제 웹 셸(offscreen)과 가짜 플레이어에 키·마우스를 넣고 초점이 간 자리(document.activeElement)를 본다.

늦게 오는 초점 요청은 WebChannel 전송에서 그 신호를 붙잡았다가 넘겨 재현한다(제품 코드에 시험용 지연을 넣지 않는다).
"""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import rename_dialog
from test_web_dialogs import within
from test_web_library_loading import click, js
from test_web_tab_reshow import GRID, QUERY, SELECTED, active_element, library, open_window, switch, view  # noqa: F401
from my_video_manager.subtitle_queue_kind import TRANSCRIPTION

QUICK_SEARCH = '[aria-label="영상 제목 빠른 검색"]'
RANDOM_MENU = '[data-page=library] [aria-label="무작위 재생 범위"]'
DIALOG = '[role=dialog], [role=alertdialog]'

# 페이지 초점 신호(대상 이름 문자열)를 붙잡는다. 상태 메시지(JSON)는 대상 이름과 겹치지 않는다.
HOLD_FOCUS = """(() => {
  if (window.mvmFocusHolds) return;
  window.mvmFocusHolds = [];
  const transport = qt.webChannelTransport, receive = transport.onmessage;
  transport.onmessage = function(event) {
    const data = JSON.parse(event.data);
    const target = data.type === 1 ? data.args?.[0] : undefined;
    const hold = window.mvmFocusHolds.find(entry => !entry.release && entry.object === data.object && entry.targets.includes(target));
    if (hold) { hold.release = () => receive.call(transport, event); return; }
    receive.call(transport, event);
  };
})()"""

# 웹 셸을 다시 불러온 문서에서 라이브러리의 첫 초점 요청을 붙잡는다. 문서가 생길 때 넣어 첫 신호 전에 준비한다.
HOLD_FIRST_LIBRARY_FOCUS = """(() => {
  let channelClass;
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function(transport, ready) {
      return new Original(transport, channel => {
        const signal = channel.objects.library.libraryFocusRequested, connect = signal.connect;
        signal.connect = callback => connect.call(signal, target => {
          if (window.mvmFirstFocus === undefined) { window.mvmFirstFocus = () => callback(target); return; }
          callback(target);
        });
        ready(channel);
      });
    };
  }});
})()"""


# 웹 셸을 다시 불러온 문서에서 첫 셸 스냅숏 응답을 붙잡고, 라이브러리 초점 요청이 몇 번 왔는지 센다.
HOLD_FIRST_SHELL_SNAPSHOT = """(() => {
  let channelClass;
  window.mvmLibraryFocusCount = 0;
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function(transport, ready) {
      return new Original(transport, channel => {
        const shell = channel.objects.shell, snapshot = shell.shellSnapshot;
        shell.shellSnapshot = callback => snapshot.call(shell, state => { window.mvmReleaseSnapshot = () => callback(state) });
        const signal = channel.objects.library.libraryFocusRequested, connect = signal.connect;
        signal.connect = callback => connect.call(signal, target => { window.mvmLibraryFocusCount++; callback(target) });
        ready(channel);
      });
    };
  }});
})()"""


def reload_with(window, name, source):
    """문서가 생길 때 넣을 스크립트를 붙이고 웹 셸을 다시 불러온다. 첫 신호보다 먼저 준비된다."""
    from PySide6.QtWebEngineCore import QWebEngineScript
    script = QWebEngineScript()
    script.setName(name)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setSourceCode(source)
    window.web_host.engine_page.scripts().insert(script)
    window.web_host.view.reload()


def hold_focus(window, page, *targets):
    js(window, HOLD_FOCUS)
    return js(window, f'window.mvmFocusHolds.push({{ object: "{page}", targets: {list(targets)}, release: null }}) - 1')


def focus_held(window, index):
    return js(window, f'typeof window.mvmFocusHolds[{index}].release === "function"')


def frames(window, count=4):
    """초점 규칙이 기다리는 렌더(두 프레임)보다 넉넉히 지났는지 기다린다."""
    js(window, f"""window.mvmFrames = 0; (function next() {{ if (++window.mvmFrames < {count}) requestAnimationFrame(next) }})(); true""")
    wait_for(lambda: js(window, f'window.mvmFrames >= {count}'))


def release_focus(window, index):
    js(window, f'window.mvmFocusHolds[{index}].release(); true')
    frames(window)


def active_label(window):
    return js(window, 'document.activeElement?.getAttribute("aria-label") ?? ""')


def active_text(window):
    return js(window, 'document.activeElement?.textContent.trim() ?? ""')


def dialog_open(window):
    return js(window, f'!!document.querySelector("{DIALOG}")')


def wait_dialog_closed(window):
    wait_for(lambda: not dialog_open(window) and not window.web_host.dialogs.blocks_shell_actions)


def arrow_moves(window, selector, key=Qt.Key.Key_Down):
    """방향키 한 번으로 그 목록의 고른 항목(aria-activedescendant)이 바뀌는지."""
    before = js(window, f'document.querySelector("{selector}").getAttribute("aria-activedescendant")')
    QTest.keyClick(view(window), key)
    wait_for(lambda: js(window, f'document.querySelector("{selector}").getAttribute("aria-activedescendant")') != before)


def outside(window):
    """대화상자 바깥(창 왼쪽 아래)을 누른다. 여는 전환이 끝나 바깥 누르기를 받을 수 있을 때 누른다."""
    wait_for(lambda: js(window, 'document.getAnimations().length === 0'))
    frames(window)
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(4, view(window).height() - 4))


def test_late_focus_after_tab_switch_keeps_focus_the_user_moved(open_window):
    window = open_window()
    switch(window, 2, 'recommend', 'recommendations')
    # 라이브러리로 돌아가는 초점 요청이 늦는 동안 사용자가 빠른 검색 칸을 누른다.
    held = hold_focus(window, 'library', 'grid', 'restore')
    switch(window, 1, 'library', None)
    wait_for(lambda: focus_held(window, held))
    click(window, QUICK_SEARCH)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    release_focus(window, held)
    # 늦게 온 요청은 사용자가 옮긴 초점을 덮지 않고, 이어서 친 글자는 그 칸에 들어간다.
    assert active_element(window) == '영상 제목 빠른 검색'
    QTest.keyClicks(view(window), 'clip 01')
    wait_for(lambda: window.library_page.options['query'] == 'clip 01')
    assert js(window, f'{QUERY}.value') == 'clip 01'

    # 사용자 입력이 없으면 늦게 와도 규칙대로 둔다. 숨은 추천 탭에 남은 초점이 아니라 라이브러리에 남은 초점(빠른 검색 칸)이다.
    switch(window, 2, 'recommend', 'recommendations')
    held = hold_focus(window, 'library', 'grid', 'restore')
    switch(window, 1, 'library', None)
    wait_for(lambda: focus_held(window, held))
    # 요청이 오기 전 초점은 숨은 추천 탭의 목록이거나 거기서 빠져 body다.
    assert active_element(window) in ('', 'recommendations')
    release_focus(window, held)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')


def test_late_default_focus_on_first_visit_keeps_focus_the_user_moved(open_window):
    window = open_window()
    excluded = '[data-page=folders] nav[aria-label="폴더 관리 구역"] [data-tab=excluded]'
    # 처음 여는 폴더 관리의 기본 초점('감시 폴더 추가') 요청이 늦는 동안 사용자가 제외 목록 구역 단추를 누른다.
    held = hold_focus(window, 'folders', 'folders-add')
    switch(window, 7, 'folders', None)
    wait_for(lambda: focus_held(window, held) and js(window, f'!!document.querySelector(`{excluded}`)'))
    click(window, excluded)
    wait_for(lambda: active_text(window).startswith('제외 목록'))
    release_focus(window, held)
    assert active_text(window).startswith('제외 목록')


def test_late_default_focus_on_first_visit_without_input_focuses_default(open_window):
    window = open_window()
    # 사용자 입력이 없으면 처음 여는 폴더 관리의 기본 초점 요청이 늦게 와도 기본 초점에 둔다.
    held = hold_focus(window, 'folders', 'folders-add')
    switch(window, 7, 'folders', None)
    wait_for(lambda: focus_held(window, held))
    release_focus(window, held)
    wait_for(lambda: active_element(window) == 'folders-add')


def test_late_first_entry_focus_after_reload_keeps_focus_the_user_moved(open_window):
    window = open_window()
    reload_with(window, 'hold-first-library-focus', HOLD_FIRST_LIBRARY_FOCUS)
    # 첫 진입의 격자 초점 요청이 늦는 동안 목록이 보이고, 사용자가 빠른 검색 칸을 눌러 친다(#257 점검).
    wait_for(lambda: js(window, 'typeof window.mvmFirstFocus === "function"'))
    wait_for(lambda: js(window, f'{GRID}.querySelectorAll("[role=gridcell]").length') > 0
             and not js(window, f'{QUERY}.disabled'))
    click(window, QUICK_SEARCH)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    QTest.keyClicks(view(window), 'cl')
    js(window, 'window.mvmFirstFocus(); true')
    frames(window)
    assert active_element(window) == '영상 제목 빠른 검색'
    QTest.keyClicks(view(window), 'ip')
    wait_for(lambda: window.library_page.options['query'] == 'clip')


def test_late_first_shell_snapshot_keeps_focus_the_user_moved(open_window):
    window = open_window()
    reload_with(window, 'hold-first-shell-snapshot', HOLD_FIRST_SHELL_SNAPSHOT)
    # 첫 셸 스냅숏 응답이 늦는 동안 이미 보인 라이브러리에서 사용자가 빠른 검색 칸을 눌러 친다.
    wait_for(lambda: js(window, 'typeof window.mvmReleaseSnapshot === "function"'))
    wait_for(lambda: js(window, f'!!{QUERY} && !{QUERY}.disabled'))
    click(window, QUICK_SEARCH)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    QTest.keyClicks(view(window), 'cl')
    # 늦은 스냅숏은 같은 탭을 새로 보인 것으로 치지 않으므로 그 뒤 첫 진입의 격자 초점 요청이 입력을 덮지 않는다.
    js(window, 'window.mvmReleaseSnapshot(); true')
    wait_for(lambda: js(window, 'window.mvmLibraryFocusCount') >= 1)
    frames(window)
    assert active_element(window) == '영상 제목 빠른 검색'
    QTest.keyClicks(view(window), 'ip')
    wait_for(lambda: window.library_page.options['query'] == 'clip')


def test_first_visit_of_each_list_tab_focuses_where_arrow_keys_work(open_window):
    window = open_window()
    window.subtitles.timer.stop()  # 받아쓰기는 시작하지 않고 대기열 표시만 본다.
    for video in window.core.videos()[:3]:
        window.core.request_subtitles(video.id)
    # 처음 연 자막 대기열은 처리 상태 목록에, 다시 연 라이브러리는 격자에 초점이 있고 방향키가 바로 고른 항목을 옮긴다.
    switch(window, 5, 'queue', 'queue-list')
    wait_for(lambda: js(window, 'document.querySelectorAll("#queue-list [data-queue-row]").length') == 3)
    arrow_moves(window, '#queue-list')
    switch(window, 1, 'library', 'library-grid')
    arrow_moves(window, '#library-grid', Qt.Key.Key_Right)
    switch(window, 5, 'queue', 'queue-list')
    arrow_moves(window, '#queue-list', Qt.Key.Key_Up)


def test_playback_return_focuses_played_card_even_after_typing_in_page(open_window):
    window = open_window()
    target = window.library_page.visible_ids[1]
    click(window, f'#video-{target}')
    wait_for(lambda: window.library_page.selected_id == target)
    # 재생 전 마지막 입력이 빠른 검색 칸이어도 재생에서 돌아오면 고른 카드(격자)에 초점이 온다.
    click(window, QUICK_SEARCH)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    window.play(target)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    try:
        wait_for(lambda: active_element(window) == 'library-grid')
    except AssertionError:
        log = js(window, 'JSON.stringify((window.mvmFocusLog ?? []).slice(-8))')
        raise AssertionError(f'복귀 초점: {active_element(window)!r} 최근 초점 {log}') from None
    assert js(window, SELECTED) == f'video-{target}'
    arrow_moves(window, '#library-grid', Qt.Key.Key_Right)


def test_tray_return_keeps_focus_where_it_was(open_window):
    window = open_window()
    click(window, QUICK_SEARCH)
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')
    QTest.keyClicks(view(window), 'cl')
    wait_for(lambda: window.library_page.options['query'] == 'cl')
    window.close()
    wait_for(lambda: not window.isVisible())
    window.tray.open()
    wait_for(lambda: window.isVisible())
    frames(window)
    assert active_element(window) == '영상 제목 빠른 검색'
    window.activateWindow()
    QTest.keyClicks(view(window), 'ip')
    wait_for(lambda: window.library_page.options['query'] == 'clip')


def queue_with_one_item(window):
    """자막 대기열 한 줄을 고른 채 '빼기' 단추에 초점을 둔다."""
    window.subtitles.timer.stop()
    video = window.core.videos()[0]
    window.core.request_subtitles(video.id)
    switch(window, 5, 'queue', 'queue-list')
    wait_for(lambda: js(window, 'document.querySelectorAll("#queue-list [data-queue-row]").length') == 1)
    remove = 'Array.from(document.querySelectorAll("[data-page=queue] button")).find(b => b.textContent === "빼기")'
    wait_for(lambda: js(window, f'!{remove}.disabled'))
    js(window, f'{remove}.focus()')
    wait_for(lambda: active_text(window) == '빼기')
    return video


def test_reshown_tab_whose_focused_button_is_gone_focuses_tab_default(open_window):
    window = open_window()
    video = queue_with_one_item(window)
    switch(window, 1, 'library', 'library-grid')
    # 숨은 동안 그 줄이 빠져 초점을 두었던 단추가 비활성이 된다. 다시 보인 탭은 그 단추가 아닌 기본 초점(목록)에 있다.
    window.core.remove_from_subtitle_queue(video.id, kind=TRANSCRIPTION)
    window.web_host.controllers['queue'].refresh()
    switch(window, 5, 'queue', 'queue-list')
    wait_for(lambda: js(window, 'document.querySelectorAll("#queue-list [data-queue-row]").length') == 0)
    assert active_element(window) == 'queue-list'


def test_emergency_return_whose_focused_button_is_gone_focuses_tab_default(open_window):
    window = open_window()
    video = queue_with_one_item(window)
    window.emergency_hide()
    assert not window.isVisible()
    window.core.remove_from_subtitle_queue(video.id, kind=TRANSCRIPTION)
    window.web_host.controllers['queue'].refresh()
    window.tray.open()
    wait_for(lambda: window.isVisible() and window.web_host.active_tab == 'queue')
    wait_for(lambda: js(window, 'document.querySelectorAll("#queue-list [data-queue-row]").length') == 0)
    wait_for(lambda: active_element(window) == 'queue-list')
    assert not js(window, 'document.activeElement.disabled')


def test_settings_keys_request_does_not_leave_focus_in_hidden_category(open_window):
    window = open_window()
    switch(window, 8, 'settings', '일반')
    js(window, 'document.getElementById("settings-minimum").focus()')
    wait_for(lambda: active_element(window) == 'settings-minimum')
    switch(window, 1, 'library', 'library-grid')
    # 재생 메뉴의 '키 배치'처럼 셸이 키 배치 분류를 열면 남은 초점(일반 분류의 입력 칸)은 숨으므로 지금 분류 단추로 간다.
    window.show_settings()
    wait_for(lambda: window.web_host.active_tab == 'settings')
    wait_for(lambda: active_text(window) == '키 배치')
    assert js(window, 'document.getElementById("settings-minimum").getClientRects().length') == 0
    arrow = 'document.querySelector("#settings-category [aria-current=true]").textContent'
    assert js(window, arrow) == '키 배치'


@pytest.mark.parametrize('how', ['escape', 'cancel'])
def test_confirm_dialog_returns_focus_to_its_opener(open_window, how):
    window = open_window()
    switch(window, 8, 'settings', '일반')
    quit_button = 'Array.from(document.querySelectorAll("[data-page=settings] button")).find(b => b.textContent === "완전 종료")'
    js(window, f'{quit_button}.scrollIntoView({{ block: "center" }}); true')
    point = js(window, f'(r => [r.x + r.width / 2, r.y + r.height / 2].map(Math.round).join(","))({quit_button}.getBoundingClientRect())')
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*map(int, point.split(','))))
    wait_for(lambda: dialog_open(window) and window.web_host.dialogs.blocks_shell_actions)
    wait_for(lambda: active_text(window) == '취소')
    if how == 'escape':
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
    else:
        QTest.keyClick(view(window), Qt.Key.Key_Return)
    wait_dialog_closed(window)
    wait_for(lambda: active_text(window) == '완전 종료')


@pytest.mark.parametrize('how', ['escape', 'cancel', 'outside'])
def test_dialog_opened_from_menu_returns_focus_to_menu_button(open_window, how):
    window = open_window()
    # 실제 마우스로 카드를 눌러 페이지가 키 입력을 받게 한 뒤 ▾에 초점을 둔다.
    target = window.library_page.visible_ids[1]
    click(window, f'#video-{target}')
    # 격자는 클릭 전부터 초점이 있다. 실제 클릭으로 선택이 바뀐 뒤에만 ▾로 초점을 옮긴다.
    wait_for(lambda: js(window, SELECTED) == f'video-{target}' and active_element(window) == 'library-grid')
    js(window, f'document.querySelector(\'{RANDOM_MENU}\').focus()')
    wait_for(lambda: active_label(window) == '무작위 재생 범위')
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_for(lambda: js(window, 'document.activeElement?.dataset.slot') == 'dropdown-menu-item')
    QTest.keyClick(view(window), Qt.Key.Key_End)
    wait_for(lambda: js(window, "document.activeElement?.textContent.startsWith('태그에서')") is True)
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    wait_for(lambda: dialog_open(window) and window.web_host.dialogs.blocks_shell_actions)
    # 연 자리(메뉴 항목)는 사라졌으므로 그 메뉴를 연 단추로 돌아간다.
    if how == 'escape':
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
    elif how == 'cancel':
        js(window, f'Array.from(document.querySelector("{DIALOG}").querySelectorAll("button")).find(b => b.textContent === "취소").click()')
    else:
        outside(window)
    wait_dialog_closed(window)
    wait_for(lambda: active_label(window) == '무작위 재생 범위')


def test_shell_dialog_returns_focus_to_grid_and_arrow_keys_continue(open_window):
    window = open_window()
    dialogs = window.web_host.dialogs
    click(window, f'#video-{window.core.videos()[1].id}')
    wait_for(lambda: active_element(window) == 'library-grid')

    def check():
        wait_for(lambda: dialog_open(window) and active_element(window) != 'library-grid')
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)

    # 셸이 여는 웹 대화상자(제목 변경)도 같은 틀을 쓴다. 닫으면 연 자리(격자)로 돌아오고 방향키가 바로 움직인다.
    within(rename_dialog(window), dialogs, check)
    wait_dialog_closed(window)
    wait_for(lambda: active_element(window) == 'library-grid')
    arrow_moves(window, '#library-grid', Qt.Key.Key_Right)
