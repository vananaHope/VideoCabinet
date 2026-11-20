"""#268 누름·마우스 올림·키보드 초점 표시. 실제 웹 셸(offscreen)과 가짜 플레이어에 마우스 올림·누름·Tab을 넣고
사용자가 보는 결과(계산된 스타일, 재생 조작 줄 단추의 픽셀 색)를 본다.

움직임 줄이기 켜짐·꺼짐은 이 PC의 Windows 설정에 기대지 않고 Chromium 플래그를 준 자식 pytest 프로세스에서 확인한다.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.core import Command, CommandType
from my_video_manager.web_tokens import web_tokens
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, settle, view
from test_emergency_hide_ui import app, window  # noqa: F401
from wait_helpers import CHILD_READY_TIMEOUT

MOTION_CHILD = os.environ.get('MVM_PRESS_MOTION_CHILD')
TOKENS = web_tokens()
SCALE = float(TOKENS['motion']['motion-enter-scale'])
PRESSED = f'matrix({SCALE:g}, 0, 0, {SCALE:g}, 0, 0)'
RING = QColor(TOKENS['colors']['ring'])
RING_CSS = f'rgb({RING.red()}, {RING.green()}, {RING.blue()})'
NEUTRAL = QPoint(2, 2)  # 머리글 왼쪽 위 빈 자리. 조작 요소가 아니다.

# 같은 종류가 여러 화면·변형에 있다. 모두 같은 누름·초점 모양이어야 한다.
KINDS = {
    '머리글 탭': ('nav [data-tab="recommend"]', None),
    '패널 탭': ('[data-page=library] nav [data-tab]:not([aria-current])', None),
    '주 단추': ('[data-page=library] [data-slot=button][data-variant=default]', None),
    '윤곽선 단추': ('[data-page=library] [data-slot=button][data-variant=outline]', None),
    # 라이브러리의 위험 윤곽선 단추(제외)는 상세 패널의 "다른 작업" 메뉴 항목이 됐다(#381). 툴바의 고스트 아이콘 단추(폴더 패널)를 잰다.
    '고스트 아이콘 단추': ('[data-page=library] [data-slot=button][data-variant=ghost]', None),
    '영상 카드': ('#library-grid [role=gridcell][aria-selected=false]', '#library-grid'),
}


def shown(selector):
    return f"Array.from(document.querySelectorAll({json.dumps(selector)})).find(e => e.getClientRects().length > 0)"


def still(window, selector):
    """올림·초점 색 전환(motion-duration-quick)이 끝난 모습을 본다."""
    wait_for(lambda: js(window, f"{shown(selector)}.getAnimations().length === 0"))


def state(window, selector):
    return json.loads(js(window, f"""(() => {{ const e = {shown(selector)}, s = getComputedStyle(e);
      return JSON.stringify({{ transform: s.transform, background: s.backgroundColor, color: s.color, border: s.borderTopColor,
        decoration: s.textDecorationLine, outline: [s.outlineStyle, s.outlineWidth, s.outlineColor, s.outlineOffset], shadow: s.boxShadow,
        transition: s.transitionDuration, hover: e.matches(':hover'), active: e.matches(':active'),
        focusVisible: e.matches(':focus-visible'), focused: e === document.activeElement }}) }})()"""))


def center(window, selector):
    rect = json.loads(js(window, f"JSON.stringify({shown(selector)}.getBoundingClientRect())"))
    return QPoint(round(rect['x'] + rect['width'] / 2), round(rect['y'] + rect['height'] / 2))


def ready(window):
    host = window.web_host
    wait_for(lambda: not host.return_pending and host._frontend_ready and 'library' in host._ready_pages)
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 2)
    more_actions = shown('[data-page=library] aside button[aria-label="다른 작업"]')
    wait_for(lambda: js(window, f"!!{more_actions}"))
    # offscreen은 OS 창 초점을 Chromium에 넘기지 않는다. 실창처럼 웹 뷰가 초점을 얻은 상태를 만든다.
    QApplication.sendEvent(view(window), QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.ActiveWindowFocusReason))
    away(window)


def away(window):
    QTest.mouseMove(view(window), NEUTRAL)
    settle(window)


def hover(window, selector):
    QTest.mouseMove(view(window), center(window, selector))
    wait_for(lambda: state(window, selector)['hover'])
    still(window, selector)
    return state(window, selector)


def press(window, selector):
    """누른 채로 본 모습. 놓기 전에 빈 자리로 옮겨 놓으므로 그 조작은 실행되지 않는다."""
    QTest.mousePress(view(window), Qt.MouseButton.LeftButton, pos=center(window, selector))
    wait_for(lambda: state(window, selector)['active'])
    still(window, selector)
    pressed = state(window, selector)
    QTest.mouseMove(view(window), NEUTRAL)
    QTest.mouseRelease(view(window), Qt.MouseButton.LeftButton, pos=NEUTRAL)
    wait_for(lambda: not state(window, selector)['active'])
    return pressed


def tab_to(window, selector):
    """빈 자리를 눌러 초점을 걷은 뒤 Tab만 눌러 그 요소에 초점을 옮긴다."""
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=NEUTRAL)
    settle(window)
    for _ in range(80):
        QTest.keyClick(view(window), Qt.Key.Key_Tab)
        settle(window)
        if js(window, f"{shown(selector)} === document.activeElement"):
            break
    else:
        raise AssertionError(f'Tab으로 {selector}에 가지 못함')
    wait_for(lambda: state(window, selector)['focusVisible'])
    still(window, selector)
    return state(window, selector)


def assert_focus_outline(focused):
    """키보드 초점은 ring 색 2px 윤곽선을 2px 띄워 두르고, 초점 때문에 생기는 box-shadow 링은 없다."""
    assert focused['focusVisible'] and focused['outline'] == ['solid', '2px', RING_CSS, '2px'], focused
    assert RING_CSS not in focused['shadow'], focused


def test_hover_press_and_keyboard_focus_are_distinct_and_same_for_each_kind(window):
    ready(window)
    for name, (selector, focus_target) in KINDS.items():
        away(window)
        still(window, selector)
        rest = state(window, selector)
        assert rest['transform'] == 'none' and rest['outline'][0] == 'none', (name, rest)
        hovered = hover(window, selector)
        # 올림: 면·글자가 바뀌고 크기는 그대로다.
        assert hovered['transform'] == 'none', (name, hovered)
        assert (hovered['background'], hovered['color']) != (rest['background'], rest['color']), (name, rest, hovered)
        # 누름: 올림과 같은 색에서 한 규칙의 크기만 작아진다.
        pressed = press(window, selector)
        assert pressed['transform'] == PRESSED, (name, pressed)
        assert (pressed['background'], pressed['color'], pressed['border']) == (hovered['background'], hovered['color'], hovered['border']), name
        # 키보드 초점: 모든 종류가 같은 윤곽선이다. 목록 안 카드는 목록 상자가 초점을 받는다.
        away(window)
        focused = tab_to(window, focus_target or selector)
        assert_focus_outline(focused)
        assert focused['transform'] == 'none', (name, focused)


def test_text_field_keyboard_focus_uses_the_same_outline_without_border_change(window):
    ready(window)
    field = '[aria-label="영상 제목 빠른 검색"]'
    rest = state(window, field)
    focused = tab_to(window, field)
    assert_focus_outline(focused)
    assert focused['border'] == rest['border']


def test_pressing_a_button_inside_a_row_shrinks_only_the_button(window):
    core = window.core
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(10)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    ready(window)
    js(window, f"{shown('[data-page=library] nav [data-tab]:not([aria-current])')}.click()")
    row = '#detail-scroll [role=option]'
    wait_for(lambda: js(window, f"!!{shown(row)}"))
    for inner in (f'{row} > button', f'{row} [data-slot=button]'):
        QTest.mousePress(view(window), Qt.MouseButton.LeftButton, pos=center(window, inner))
        wait_for(lambda: state(window, inner)['active'])
        assert state(window, inner)['transform'] == PRESSED
        assert state(window, row)['active'] and state(window, row)['transform'] == 'none'
        QTest.mouseMove(view(window), NEUTRAL)
        QTest.mouseRelease(view(window), Qt.MouseButton.LeftButton, pos=NEUTRAL)
        wait_for(lambda: not state(window, row)['active'])


def run_motion_child(request, mode):
    flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    flag = {'reduce': '--force-prefers-reduced-motion', 'no-preference': '--force-prefers-no-reduced-motion'}[mode]
    test = f'{Path(__file__).resolve()}::{request.node.name}'
    result = subprocess.run([sys.executable, '-m', 'pytest', test, '-q', '-p', 'no:cacheprovider', '-p', 'no:randomly', '-rs'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=CHILD_READY_TIMEOUT * 2,
                            env={**os.environ, 'MVM_PRESS_MOTION_CHILD': mode, 'QT_QPA_PLATFORM': 'offscreen',
                                 'QTWEBENGINE_CHROMIUM_FLAGS': f'{flags} {flag}'})
    skipped = re.search(r'^SKIPPED \[1\] [^\n]*?:\d+: (.+)$', result.stdout, re.MULTILINE)
    if result.returncode == 0 and skipped:
        pytest.skip(skipped.group(1))
    assert result.returncode == 0 and re.search(r'\b1 passed\b', result.stdout), result.stdout[-4000:] + result.stderr[-2000:]


@pytest.mark.parametrize('mode', ['reduce', 'no-preference'])
def test_press_shrinks_at_once_with_and_without_reduced_motion(request, mode):
    """누름의 크기 변화에는 전환이 없다. 움직임 줄이기에서는 색 전환도 0이다. 누른 첫 프레임부터 끝 크기다."""
    if MOTION_CHILD is None:
        run_motion_child(request, mode)
        return
    window = request.getfixturevalue('window')
    ready(window)
    assert js(window, "matchMedia('(prefers-reduced-motion: reduce)').matches") is (MOTION_CHILD == 'reduce')
    tab = 'nav [data-tab="recommend"]'
    if MOTION_CHILD == 'reduce':
        assert state(window, tab)['transition'] == '0s'
    QTest.mouseMove(view(window), center(window, tab))
    QTest.mousePress(view(window), Qt.MouseButton.LeftButton, pos=center(window, tab))
    wait_for(lambda: state(window, tab)['active'])
    assert state(window, tab)['transform'] == PRESSED
    QTest.mouseMove(view(window), NEUTRAL)
    QTest.mouseRelease(view(window), Qt.MouseButton.LeftButton, pos=NEUTRAL)


def colour(button, x):
    return button.grab().toImage().pixelColor(x, button.height() // 2).name()


def test_playback_control_press_uses_accent_and_differs_from_hover_and_focus(window):
    window.play(window.core.videos()[0].id)
    window.sync_position()
    page = window.playback_page
    wait_for(lambda: page.isVisible())
    button = page.pause_button
    colors = TOKENS['colors']
    QTest.mouseMove(window.surface, window.surface.rect().center())
    wait_for(lambda: not button.underMouse())
    assert colour(button, 4) == colors['secondary']
    QTest.mouseMove(button, button.rect().center())
    wait_for(button.underMouse)
    # 올림은 테두리만 밝아지고 면은 쉼과 같다.
    assert colour(button, 4) == colors['secondary']
    assert colour(button, 0) == colors['muted-foreground']
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
    wait_for(button.isDown)
    assert colour(button, 4) == colors['accent']
    # 단추 밖에서 놓아 명령은 실행되지 않는다.
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=QPoint(-10, -10))
    wait_for(lambda: not button.isDown())
    assert window.player.paused is False
    QTest.mouseMove(window.surface, window.surface.rect().center())
    button.setFocus(Qt.FocusReason.TabFocusReason)
    wait_for(button.hasFocus)
    assert colour(button, 0) == colors['ring'] and colour(button, 4) == colors['secondary']


def edge_points(rect):
    """요소의 왼쪽·오른쪽·위·아래 가장자리에서 안쪽 1px(가로·세로 가운데)."""
    left, top = rect['x'], rect['y']
    right, bottom = left + rect['width'], top + rect['height']
    middle_x, middle_y = math.floor(left + rect['width'] / 2), math.floor(top + rect['height'] / 2)
    return {'왼쪽': QPoint(math.floor(left) + 1, middle_y), '오른쪽': QPoint(math.ceil(right) - 2, middle_y),
            '위': QPoint(middle_x, math.floor(top) + 1), '아래': QPoint(middle_x, math.ceil(bottom) - 2)}


def click_in_place(window, point):
    """마우스를 그 자리에 두고 눌렀다가 움직이지 않고 같은 자리에서 놓는다."""
    QTest.mouseMove(view(window), point)
    settle(window)
    QTest.mousePress(view(window), Qt.MouseButton.LeftButton, pos=point)
    settle(window)
    QTest.mouseRelease(view(window), Qt.MouseButton.LeftButton, pos=point)
    settle(window)


def rect_of(window, selector):
    return json.loads(js(window, f"JSON.stringify({shown(selector)}.getBoundingClientRect())"))


def make_highlights(window):
    core = window.core
    for video in core.videos():
        core.playback.start(video.id, 0)
        core.playback.report(10)
        core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
        core.playback.end()


def pressable_cases(window):
    """가장자리 시험 대상: (이름, 준비). 준비는 대상 선택자와 '그 요소의 동작이 실행됐는가'를 돌려준다."""
    def settings_category():
        js(window, "document.querySelector('nav [data-tab=settings]').click()")
        wait_for(lambda: js(window, f"!!{shown('#settings-category [data-category=keys]')}"))
        js(window, "document.querySelector('#settings-category [data-category=general]').click()")
        wait_for(lambda: js(window, "document.querySelector('#settings-category [aria-current=true]')?.dataset.category") == 'general')
        return '#settings-category [data-category=keys]', lambda: js(window, "document.querySelector('#settings-category [aria-current=true]')?.dataset.category") == 'keys'

    def video_card():
        js(window, "document.querySelector('nav [data-tab=library]').click()")
        wait_for(lambda: js(window, f"!!{shown('#library-grid [role=gridcell][aria-selected=false]')}"))
        card = f'#{js(window, shown("#library-grid [role=gridcell][aria-selected=false]") + ".id")}'
        return card, lambda: js(window, f"document.querySelector('{card}').getAttribute('aria-selected')") == 'true'

    def reel_row():
        js(window, "document.querySelector('nav [data-tab=reel]').click()")
        wait_for(lambda: js(window, f"!!{shown('#reel-list [role=option][aria-selected=false]')}"))
        row = f'#{js(window, shown("#reel-list [role=option][aria-selected=false]") + ".id")}'
        return row, lambda: js(window, f"document.querySelector('{row}').getAttribute('aria-selected')") == 'true'

    def icon_button():
        js(window, "document.querySelector('nav [data-tab=library]').click()")
        wait_for(lambda: js(window, "!document.querySelector('[role=dialog]')"))
        return 'header [data-slot=button][data-size=icon-sm]', lambda: js(window, "!!document.querySelector('[role=dialog]')")

    return (('설정 분류', settings_category), ('영상 카드', video_card), ('모아보기 행', reel_row), ('키 안내 아이콘 단추', icon_button))


def undo(window, name, done):
    """키 안내 대화상자가 열렸으면 닫아 다음 시도를 같은 상태에서 시작한다."""
    if name == '키 안내 아이콘 단추' and done():
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: js(window, "!document.querySelector('[role=dialog]')") and not window.web_host.dialogs.blocks_shell_actions)


def outside_points(rect):
    """요소의 왼쪽·오른쪽·위·아래 가장자리 바깥 2px(가로·세로 가운데)."""
    left, top = rect['x'], rect['y']
    right, bottom = left + rect['width'], top + rect['height']
    middle_x, middle_y = math.floor(left + rect['width'] / 2), math.floor(top + rect['height'] / 2)
    return {'왼쪽': QPoint(math.floor(left) - 2, middle_y), '오른쪽': QPoint(math.ceil(right) + 1, middle_y),
            '위': QPoint(middle_x, math.floor(top) - 2), '아래': QPoint(middle_x, math.ceil(bottom) + 1)}


def drag(window, start, end):
    """start에서 누르고, 누른 채 end로 옮겨 end에서 놓는다."""
    QTest.mouseMove(view(window), start)
    settle(window)
    QTest.mousePress(view(window), Qt.MouseButton.LeftButton, pos=start)
    settle(window)
    QTest.mouseMove(view(window), end)
    settle(window)
    QTest.mouseRelease(view(window), Qt.MouseButton.LeftButton, pos=end)
    settle(window)


def test_pressing_an_edge_and_releasing_in_place_runs_that_element(window):
    """누르는 동안 작아져도, 원래 영역 가장자리 안쪽 1px에서 누르고 같은 자리에서 놓으면 그 요소의 동작이 실행된다."""
    make_highlights(window)
    ready(window)
    cases = []
    for name, prepare in pressable_cases(window):
        for edge in ('왼쪽', '오른쪽', '위', '아래'):
            selector, done = prepare()
            away(window)
            point = edge_points(rect_of(window, selector))[edge]
            assert js(window, f"document.elementFromPoint({point.x()}, {point.y()})?.closest({json.dumps(selector)}) === {shown(selector)}"), (name, edge)
            click_in_place(window, point)
            if not done():
                cases.append((name, edge))
            undo(window, name, done)
    assert cases == [], f'가장자리 클릭이 그 요소에 가지 않음: {cases}'


def test_pressing_the_middle_and_releasing_anywhere_in_the_original_area_runs_that_element(window):
    """가운데에서 누른 채 원래 영역 가장자리 안쪽 1px로 옮겨 놓으면 그 요소의 동작이 실행된다(누르는 동안 작아진 면과 무관)."""
    make_highlights(window)
    ready(window)
    cases = []
    for name, prepare in pressable_cases(window):
        for edge in ('왼쪽', '오른쪽', '위', '아래'):
            selector, done = prepare()
            away(window)
            rect = rect_of(window, selector)
            drag(window, center(window, selector), edge_points(rect)[edge])
            if not done():
                cases.append((name, edge))
            undo(window, name, done)
    assert cases == [], f'원래 영역 안에서 놓은 클릭이 그 요소에 가지 않음: {cases}'


def test_pressing_the_middle_and_releasing_outside_the_original_area_cancels(window):
    """가운데에서 누른 채 원래 영역 바깥 2px로 옮겨 놓으면 지금처럼 취소되어 그 요소의 동작이 실행되지 않는다."""
    make_highlights(window)
    ready(window)
    cases = []
    for name, prepare in pressable_cases(window):
        for side in ('왼쪽', '오른쪽', '위', '아래'):
            selector, done = prepare()
            away(window)
            rect = rect_of(window, selector)
            point = outside_points(rect)[side]
            assert not js(window, f"document.elementFromPoint({point.x()}, {point.y()})?.closest({json.dumps(selector)})"), (name, side)
            drag(window, center(window, selector), point)
            if done():
                cases.append((name, side))
            undo(window, name, done)
    assert cases == [], f'원래 영역 밖에서 놓았는데 동작이 실행됨: {cases}'


def test_tag_picker_option_shows_its_keyboard_focus(window):
    """태그 고르기 목록은 입력란이 초점을 갖고 방향키로 옵션을 고른다(aria-activedescendant).
    입력란은 P-2 윤곽선을, 키보드로 고른 옵션은 그 목록이 정한 초점 표시(ring 2px 안쪽 링)를 보인다."""
    from my_video_manager.web_dialogs_entries import TagEditor
    from test_web_dialogs import within
    core = window.core
    video, other = core.videos()[:2]
    core.add_video_tag(other.id, '배움')
    core.add_video_tag(other.id, '휴식')
    ready(window)
    dialogs = window.web_host.dialogs
    field = '[role=dialog] [role=combobox]'
    option = '[role=dialog] [role=option][data-active]'

    def check():
        wait_for(lambda: js(window, f"!!{shown(field)}"))
        focused = tab_to(window, field)
        assert_focus_outline(focused)
        QTest.keyClick(view(window), Qt.Key.Key_Down)
        wait_for(lambda: js(window, f"!!{shown(option)}"))
        still(window, option)
        active = state(window, option)
        assert js(window, f"{shown(field)}.getAttribute('aria-activedescendant') === {shown(option)}.id")
        assert re.search(rf'{re.escape(RING_CSS)} 0px 0px 0px 2px inset', active['shadow']), active
        assert state(window, field)['focusVisible']
    within(lambda: TagEditor(core, video_id=video.id, parent=window).exec(), dialogs, check)
