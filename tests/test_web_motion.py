"""전환 토큰과 움직임 줄이기: 실제 웹 셸에서 대화상자·메뉴·선택 목록·탭 내용·안내의 전환 유무와 전환 중 입력을 본다.

offscreen QtWebEngine은 기본이 `prefers-reduced-motion: reduce`다. 움직임 줄이기를 끈 상태는
Chromium 플래그를 준 자식 pytest 프로세스에서 같은 테스트를 다시 돌려 확인한다.
"""
import json
import re
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from my_video_manager.web_tokens import web_tokens
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, press_emergency, restore, settle, view
from test_emergency_hide_ui import app, window
from wait_helpers import CHILD_READY_TIMEOUT

MOTION_CHILD = os.environ.get('MVM_MOTION_CHILD') == '1'
MOTION = web_tokens()['motion']
CTRL = Qt.KeyboardModifier.ControlModifier

# 전환이 시작되는 순간 그 애니메이션을 멈춰 붙잡는다. 멈춘 동안(=전환 중) 넣은 입력이 바로 적용되는지 본다.
HOLD = """(() => {
  window.motionHeld = []
  document.addEventListener('animationstart', event => {
    const target = event.target
    const slot = target.dataset.slot ?? target.dataset.page
      ?? (target.matches('[role=dialog],[role=alertdialog]') || target.querySelector('[role=dialog],[role=alertdialog]') ? 'dialog' : target.tagName)
    for (const animation of target.getAnimations()) {
      if (animation.animationName !== event.animationName || animation.playState !== 'running') continue
      animation.pause()
      window.motionHeld.push({ name: event.animationName, slot, time: animation.currentTime,
        duration: animation.effect.getComputedTiming().duration, opacity: Number(getComputedStyle(target).opacity) })
    }
  }, true)
})()"""


def milliseconds(token):
    return float(token.removesuffix('ms'))


def seconds(token):
    return f'{milliseconds(token) / 1000:g}s'


def ready(window):
    """라이브러리 목록이 그려진 셸에서 시작한다."""
    host = window.web_host
    wait_for(lambda: not host.return_pending and host._frontend_ready and 'library' in host._ready_pages)
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 2)
    window.activateWindow()
    host.view.setFocus()


def held(window, slot):
    return [entry for entry in json.loads(js(window, 'JSON.stringify(window.motionHeld)')) if entry['slot'] == slot]


def wait_held(window, slot, name, duration):
    wait_for(lambda: bool(held(window, slot)))
    entry = held(window, slot)[-1]
    assert entry['name'] == name and entry['duration'] == milliseconds(duration)
    # 멈춘 시점은 전환 도중이다. 아직 다 보이지 않은 상태에서 입력을 넣는다.
    assert entry['time'] < entry['duration'] and entry['opacity'] < 1
    return entry


def style(window, selector, name):
    return js(window, f"(() => {{ const e = document.querySelector({json.dumps(selector)}); return e ? getComputedStyle(e).{name} : null }})()")


def center(window, selector):
    rect = json.loads(js(window, f"JSON.stringify(document.querySelector({json.dumps(selector)}).getBoundingClientRect())"))
    return QPoint(round(rect['x'] + rect['width'] / 2), round(rect['y'] + rect['height'] / 2))


def click(window, selector, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(view(window), button, pos=center(window, selector))


def present(window, selector):
    return js(window, f"!!document.querySelector({json.dumps(selector)})")


def active_page(window):
    return js(window, "document.activeElement?.closest('[data-page]')?.dataset.page ?? null")


GUIDE = '[role=dialog]'
NOTICE = '[aria-label="앱 안내"] [data-slot=notice]'


def test_reduced_motion_draws_every_layer_instantly(window):
    ready(window)
    assert js(window, "matchMedia('(prefers-reduced-motion: reduce)').matches") is True
    js(window, HOLD)
    # 단추·탭 hover 색 전환도 없다.
    assert style(window, 'nav [data-tab="recommend"]', 'transitionDuration') == '0s'
    QTest.keyClick(view(window), Qt.Key.Key_2, CTRL)
    wait_for(lambda: window.web_host.active_tab == 'recommend')
    assert style(window, '[data-page="recommend"]', 'animationName') == 'none'
    QTest.keyClick(view(window), Qt.Key.Key_1, CTRL)
    wait_for(lambda: active_page(window) == 'library')
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_for(lambda: present(window, GUIDE))
    assert style(window, f'[data-state=open]:has(> {GUIDE})', 'animationName') == 'none'
    assert style(window, f'[data-state=open]:has(> {GUIDE})', 'opacity') == '1'
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, GUIDE) and not window.web_host.dialogs.blocks_shell_actions)
    click(window, '#library-grid [role=gridcell]', Qt.MouseButton.RightButton)
    wait_for(lambda: present(window, '[data-slot=context-menu-content]'))
    assert style(window, '[data-slot=context-menu-content]', 'animationName') == 'none'
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, '[data-slot=context-menu-content]'))
    window.statusBar().showMessage('전환 시험 알림')
    wait_for(lambda: present(window, NOTICE))
    assert style(window, NOTICE, 'animationName') == 'none'
    settle(window)
    assert json.loads(js(window, 'JSON.stringify(window.motionHeld)')) == []


def test_transitions_run_without_reduced_motion_and_never_block_input(request):
    if not MOTION_CHILD:
        # 움직임 줄이기를 끈 Chromium으로 이 테스트를 자식 프로세스에서 다시 돌린다.
        flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
        test = f'{Path(__file__).resolve()}::{request.node.name}'
        result = subprocess.run([sys.executable, '-m', 'pytest', test, '-q', '-p', 'no:cacheprovider', '-p', 'no:randomly'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=CHILD_READY_TIMEOUT * 2,
                                env={**os.environ, 'MVM_MOTION_CHILD': '1', 'QT_QPA_PLATFORM': 'offscreen',
                                     'QTWEBENGINE_CHROMIUM_FLAGS': f'{flags} --force-prefers-no-reduced-motion'})
        assert result.returncode == 0 and re.search(r'\b1 passed\b', result.stdout), result.stdout[-4000:] + result.stderr[-2000:]
        return
    window = request.getfixturevalue('window')
    host = window.web_host
    ready(window)
    assert js(window, "matchMedia('(prefers-reduced-motion: reduce)').matches") is False
    # hover 색 전환은 토큰의 시간·곡선을 쓴다.
    assert style(window, 'nav [data-tab="recommend"]', 'transitionDuration') == seconds(MOTION['motion-duration-quick'])
    assert style(window, 'nav [data-tab="recommend"]', 'transitionTimingFunction') == MOTION['motion-ease']
    assert style(window, '[data-slot=button]', 'transitionProperty').startswith('color, background-color')
    js(window, HOLD)

    # 탭 내용: 새 탭이 들어오는 도중에도 키가 바로 새 화면으로 간다. 이전 탭 상태는 그대로다.
    selected = window.library_page.selected_id
    QTest.keyClick(view(window), Qt.Key.Key_2, CTRL)
    wait_held(window, 'recommend', 'fade-enter', MOTION['motion-duration-quick'])
    assert host.active_tab == 'recommend'
    QTest.keyClick(view(window), Qt.Key.Key_1, CTRL)
    wait_held(window, 'library', 'fade-enter', MOTION['motion-duration-quick'])
    wait_for(lambda: active_page(window) == 'library')
    assert window.library_page.selected_id == selected
    QTest.keyClick(view(window), Qt.Key.Key_Right)
    wait_for(lambda: window.library_page.selected_id not in (None, selected))

    # 대화상자: 열리는 도중 Esc가 바로 닫고, 닫힘은 즉시라 다음 클릭을 가로채지 않는다. 초점은 연 자리로 돌아온다.
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_held(window, 'dialog', 'fade-enter', MOTION['motion-duration-enter'])
    wait_for(lambda: window.web_host.dialogs.blocks_shell_actions)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, GUIDE) and not window.web_host.dialogs.blocks_shell_actions)
    wait_for(lambda: js(window, "document.activeElement?.id") == 'library-grid')
    click(window, 'nav [data-tab="search"]')
    wait_for(lambda: host.active_tab == 'search')
    QTest.keyClick(view(window), Qt.Key.Key_1, CTRL)
    wait_for(lambda: active_page(window) == 'library')

    # 우클릭 메뉴: 열리는 도중 Esc로 닫히고, 바로 카드 클릭이 선택을 바꾼다.
    first, second = '#library-grid [role=gridcell]:nth-child(1)', '#library-grid [role=gridcell]:nth-child(2)'
    click(window, second, Qt.MouseButton.RightButton)
    wait_held(window, 'context-menu-content', 'layer-enter', MOTION['motion-duration-enter'])
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, '[data-slot=context-menu-content]'))
    target = int(js(window, f"document.querySelector({json.dumps(first)}).id.slice(6)"))
    click(window, first)
    wait_for(lambda: window.library_page.selected_id == target)

    # 드롭다운 메뉴: 키로 열고, 열리는 도중 방향키가 항목으로 간다.
    js(window, "document.querySelector('[data-page=library] [aria-label=\"무작위 재생 범위\"]').focus()")
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_held(window, 'dropdown-menu-content', 'layer-enter', MOTION['motion-duration-enter'])
    wait_for(lambda: js(window, "document.activeElement?.dataset.slot") == 'dropdown-menu-item')
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, '[data-slot=dropdown-menu-content]'))
    wait_for(lambda: js(window, "document.activeElement?.getAttribute('aria-label')") == '무작위 재생 범위')

    # 필터 팝오버와 그 안의 선택 목록: 선택 목록의 Esc는 목록만 바로 닫는다.
    js(window, "Array.from(document.querySelectorAll('[data-page=library] button')).find(b => b.textContent === '필터').focus()")
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    wait_for(lambda: present(window, '[aria-label="라이브러리 필터 패널"]'))
    js(window, "document.querySelector('[data-slot=select-trigger][aria-label=\"시청 상태\"]').focus()")
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_held(window, 'select-content', 'layer-enter', MOTION['motion-duration-enter'])
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, '[data-slot=select-content]'))
    assert present(window, '[aria-label="라이브러리 필터 패널"]')
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, '[aria-label="라이브러리 필터 패널"]'))

    # 안내는 나타날 때 전환한다.
    window.statusBar().showMessage('전환 시험 알림')
    wait_held(window, 'notice', 'fade-enter', MOTION['motion-duration-enter'])

    # 재생 중 다른 탭으로 가는 복귀는 탭 전환을 건너뛴다. 붙잡힌 전환이 있었다면 복귀 화면이 반투명하게 남는다.
    window.play(window.core.videos()[0].id)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.activateWindow()
    QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_3, CTRL)
    wait_for(lambda: host.active_tab == 'reel')
    wait_for(lambda: not host.return_pending)
    assert window.pages.currentWidget() is host
    settle(window)
    assert style(window, '[data-page="reel"]', 'animationName') == 'none'
    assert style(window, '[data-page="reel"]', 'opacity') == '1'
    QTest.keyClick(view(window), Qt.Key.Key_1, CTRL)
    wait_for(lambda: active_page(window) == 'library')

    # 긴급 탈출은 열리는 중인 대화상자를 그대로 숨기고 되돌린다.
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_for(lambda: present(window, GUIDE) and window.web_host.dialogs.blocks_shell_actions)
    press_emergency(view(window))
    assert not window.isVisible()
    restore(window)
    assert present(window, GUIDE)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not present(window, GUIDE) and not window.web_host.dialogs.blocks_shell_actions)
