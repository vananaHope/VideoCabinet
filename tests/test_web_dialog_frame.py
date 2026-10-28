"""#296 공용 대화상자 틀: 어느 대화상자든 같은 면·제목·설명·단추 줄이고, 끝내는 동작은 오른쪽 아래 [취소][확인]이다."""
import json

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from my_video_manager.web_dialogs_entries import TagManager
from test_emergency_hide_ui import app, window
from test_emergency_hide_dialogs_ui import js, rename_dialog, settle, view
from test_web_dialogs import within
from qt_wait import wait_for

OPEN = "Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog]')).filter(e => e.getClientRects().length).at(-1)"

# 보이는 결과만 잰다: 계산된 면·글자 모양, 틀 폭, 단추 줄의 위치와 단추 색(주 색·위험 색·윤곽선).
MEASURE = f"""(() => {{
  const content = {OPEN}
  if (!content) return null
  const tone = name => {{ const e = document.createElement('div'); e.style.background = `var(${{name}})`; document.body.append(e); const value = getComputedStyle(e).backgroundColor; e.remove(); return value }}
  const box = e => e.getBoundingClientRect()
  const style = getComputedStyle(content), frame = box(content)
  const title = content.querySelector('h2'), description = title.nextElementSibling
  const footer = content.lastElementChild, end = footer.lastElementChild
  const buttons = Array.from(end.querySelectorAll('button'))
  const kind = b => {{ const s = getComputedStyle(b); return s.backgroundColor === tone('--primary') ? 'primary'
    : s.backgroundColor === tone('--destructive') ? 'destructive' : s.borderTopWidth !== '0px' ? 'outline' : 'other' }}
  return JSON.stringify({{
    look: [style.borderRadius, style.padding, style.borderTopWidth, style.backgroundColor, style.boxShadow, style.rowGap,
      getComputedStyle(content.parentElement).backgroundColor, getComputedStyle(title).fontSize, getComputedStyle(title).fontWeight,
      getComputedStyle(description).fontSize, getComputedStyle(description).color, Math.round(box(title).top - frame.top)],
    width: Math.round(frame.width),
    footer: footer.tagName,
    end: buttons.map(b => [b.textContent, kind(b)]),
    right: Math.round(frame.left + content.clientLeft + content.clientWidth - parseFloat(style.paddingRight) - box(buttons.at(-1)).right),
    bottom: Math.round(frame.top + content.clientTop + content.clientHeight - parseFloat(style.paddingBottom) - box(footer).bottom),
    row: buttons.every((b, i) => !i || Math.abs(box(b).top - box(buttons[0]).top) < 1 && box(buttons[i - 1]).right <= box(b).left),
    start: footer.childElementCount > 1 && box(footer.firstElementChild).right <= box(buttons[0]).left,
  }})
}})()"""


def measure(window):
    shown = []
    def ready():
        result = js(window, MEASURE)
        shown[:] = [result]
        return result is not None
    wait_for(ready)
    settle(window)
    return json.loads(js(window, MEASURE))


def focus_view(window):
    """Qt 초점을 웹 뷰에 둔다. 앞 대화상자가 닫힌 뒤 늦게 돌려주는 초점보다 나중에 준다."""
    def focused():
        window.activateWindow()
        window.web_host.view.setFocus()
        return view(window).hasFocus()
    wait_for(focused)


def closed(window):
    wait_for(lambda: js(window, f"!{OPEN}") and not window.web_host.dialogs.blocks_shell_actions)


def test_every_dialog_shares_frame_and_bottom_right_buttons(window):
    window.resize(1100, 720)
    host, dialogs = window.web_host, window.web_host.dialogs
    wait_for(lambda: window.loaded and 'library' in host._ready_pages)
    shots = {}

    def task():
        shots['task'] = measure(window)
    within(rename_dialog(window), dialogs, task)

    def manager():
        shots['manager'] = measure(window)
    within(lambda: TagManager(window.core, window).exec(), dialogs, manager)

    def exclude():
        shots['confirm'] = measure(window)
    within(window.library_page.library_controls.exclude, dialogs, exclude)

    focus_view(window)
    js(window, "document.getElementById('library-grid').focus()")
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    shots['guide'] = measure(window)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    closed(window)

    # 닫은 키 안내가 초점을 격자로 돌려준 뒤에 무작위 범위 단추로 옮긴다.
    wait_for(lambda: js(window, "document.activeElement?.id") == 'library-grid')
    js(window, "document.querySelector('[data-page=library] [aria-label=\"무작위 재생 범위\"]').focus()")
    wait_for(lambda: js(window, "document.activeElement?.getAttribute('aria-label')") == '무작위 재생 범위')
    focus_view(window)
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    # 메뉴가 뜨면 End로 마지막 항목('태그에서…')에 간다. 첫 초점이 메뉴 자체여도 End가 항목으로 옮긴다.
    wait_for(lambda: js(window, "!!document.querySelector('[data-slot=dropdown-menu-content]')"))
    QTest.keyClick(view(window), Qt.Key.Key_End)
    wait_for(lambda: js(window, "document.activeElement?.textContent.startsWith('태그에서')") is True)
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    shots['random'] = measure(window)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    closed(window)

    window.navigate_web_tab('settings')
    wait_for(lambda: host.active_tab == 'settings')
    js(window, "document.querySelector('#settings-category [data-category=keys]').click()")
    wait_for(lambda: js(window, "!!document.querySelector('button[data-command]')?.getClientRects().length"))
    js(window, "document.querySelector('button[data-command]').click()")
    shots['capture'] = measure(window)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    closed(window)

    # 면·덮개·제목·설명 모양과 제목 자리는 어느 대화상자든 같다.
    looks = {name: shot['look'] for name, shot in shots.items()}
    assert len({json.dumps(look) for look in looks.values()}) == 1, looks
    # 폭은 확인·짧은 입력 512px, 업무 대화상자 640px, 키 안내 896px 그대로다.
    assert {name: shot['width'] for name, shot in shots.items()} == {
        'task': 640, 'manager': 640, 'confirm': 512, 'guide': 896, 'random': 512, 'capture': 512}
    # 단추 줄은 틀의 마지막 줄이고, 끝내는 동작은 한 줄로 오른쪽 아래 끝에 붙는다.
    for name, shot in shots.items():
        assert shot['footer'] == 'FOOTER' and shot['right'] == 0 and shot['bottom'] == 0 and shot['row'], (name, shot)
    assert shots['task']['end'] == [['취소', 'outline'], ['저장', 'primary']]
    assert shots['manager']['end'] == [['닫기', 'outline']] and shots['manager']['start']
    assert shots['confirm']['end'][0] == ['취소', 'outline'] and shots['confirm']['end'][1][1] == 'destructive'
    assert shots['guide']['end'] == [['닫기', 'outline']] and shots['guide']['start']
    assert shots['random']['end'] == [['취소', 'outline'], ['재생', 'primary']]
    assert shots['capture']['end'] == [['캡처 취소', 'outline']]
