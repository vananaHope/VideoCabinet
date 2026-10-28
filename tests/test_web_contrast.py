"""면 단계와 대비: 실제 웹 셸에서 계산된 색을 읽어 바탕·카드·떠 있는 층 위의 글자·조작 경계·초점 윤곽,
상태 배지·안내·하이라이트 글자의 WCAG 대비를 잰다. 반투명 면은 실제로 그 뒤에 칠해진 면과 합성한다."""

from datetime import datetime, timezone
import json

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, settle, view
from test_emergency_hide_ui import Media, Player, app

TEXT, UI = 4.5, 3.0

# 요소 하나의 글자·테두리 색과 그 뒤에 실제로 칠해진 면. 조상의 배경을 바깥에서부터 차례로 합성한다.
# 계산된 색(oklab·color-mix 포함)은 canvas로 sRGB 바이트로 바꾼다.
PROBE = """(() => {
  const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
  const rgba = color => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data] }
  const over = (top, bottom) => top.slice(0, 3).map((v, i) => v * top[3] / 255 + bottom[i] * (1 - top[3] / 255))
  const surface = el => { const chain = []; for (let p = el; p; p = p.parentElement) chain.unshift(p)
    return chain.reduce((bg, p) => over(rgba(getComputedStyle(p).backgroundColor), bg), [0, 0, 0]) }
  window.probe = el => {
    const style = getComputedStyle(el), own = surface(el), outer = surface(el.parentElement)
    return { text: over(rgba(style.color), own), surface: own, outer,
      border: over(rgba(style.borderTopColor), outer),
      focusVisible: el.matches(':focus-visible'), hovered: el.matches(':hover') }
  }
  // 보이는 요소 중 글자가 정확히 같은 가장 안쪽 요소.
  window.byText = (root, text) => [...root.querySelectorAll('*')].filter(e => e.getClientRects().length && e.textContent.trim() === text).at(-1)
})()"""


def luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = map(channel, rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def probe(window, element):
    """element는 요소를 돌려주는 JS 식이다."""
    return json.loads(js(window, f"(() => {{ const e = {element}; return e ? JSON.stringify(window.probe(e)) : 'null' }})()"))


def text_in(root, text):
    return f"window.byText({root}, {json.dumps(text)})"


def button_in(root, text):
    return f"[...{root}.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(text)})"


def point(window, element):
    rect = json.loads(js(window, f"JSON.stringify(({element}).getBoundingClientRect())"))
    return QPoint(round(rect['x'] + rect['width'] / 2), round(rect['y'] + rect['height'] / 2))


def hover(window, element):
    QTest.mouseMove(view(window), point(window, element))
    wait_for(lambda: probe(window, element)['hovered'])
    settle(window)
    return probe(window, element)


def keyboard_focus(window, element):
    """키보드로 움직인 뒤의 초점처럼 :focus-visible 상태로 둔다.

    시작 때 예약된 페이지 초점 요청이 늦게 올 수 있으므로 초점이 남아 있을 때까지 다시 준다.
    """
    # offscreen 플랫폼은 운영체제 창 초점을 Chromium에 넘기지 않아 :focus가 맞지 않는다. 실창처럼 웹 뷰가 초점을 얻은 상태를 만든다.
    QApplication.sendEvent(view(window), QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    QTest.keyClick(view(window), Qt.Key.Key_Shift)

    def focused():
        js(window, f"(() => {{ const e = {element}; if (document.activeElement !== e) e.focus() }})()")
        settle(window)
        return probe(window, element)['focusVisible']
    wait_for(focused)
    return probe(window, element)


@pytest.fixture
def window(tmp_path, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=tmp_path / "data/library.sqlite3")
    for index in (1, 2, 3):
        path = tmp_path / f"강의 {index:02}강.mkv"
        path.write_bytes(bytes([index]))
        core.add_file(path)
    ids = [video.id for video in sorted(core.videos(), key=lambda video: video.title)]
    # 아직 안 봄 · 보다 만 · 다 봄 배지가 모두 보이게 하고, 첫 영상에는 하이라이트를 둔다.
    for video_id, position in ((ids[1], 30), (ids[2], 120)):
        core.playback.start(video_id, 0)
        core.playback.report(position)
        core.playback.end()
    core.playback.start(ids[0], 10)
    core.execute_highlight_command(core.command_for_key('Insert'))
    core.playback.end()
    window = MainWindow(core, player_factory=Player)
    window.resize(1100, 720)
    window.show()
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 3)
    window.activateWindow()
    host.view.setFocus()
    js(window, PROBE)
    settle(window)
    yield window
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def surfaces_rise(background, card, floating):
    assert luminance(background) < luminance(card) < luminance(floating)
    # 카드와 떠 있는 층은 그림자 없이 면만으로도 구별된다.
    assert ratio(card, floating) >= 1.15


def test_text_boundaries_and_focus_meet_contrast_on_background_card_and_floating_layer(window):
    page, aside = "document.querySelector('[data-page=library]')", "document.querySelector('aside')"
    card = "document.querySelector('#library-grid [role=gridcell]')"

    # 바탕: 머리글 본문, 비선택 탭 글자, 검색 입력란 경계, 그 초점 경계.
    header = probe(window, "document.querySelector('header')")
    tab = probe(window, "document.querySelector('nav [data-tab=recommend]')")
    search = f"{page}.querySelector('input')"
    field = probe(window, search)
    assert ratio(header['text'], header['surface']) >= TEXT
    assert ratio(tab['text'], tab['surface']) >= TEXT
    assert ratio(field['border'], field['outer']) >= UI
    focused = keyboard_focus(window, search)
    assert ratio(focused['border'], focused['outer']) >= UI

    # 카드: 영상 제목·길이 글자, 상세 패널의 윤곽선 단추 경계와 초점 경계.
    title = probe(window, text_in(card, '강의 01강'))
    length = probe(window, text_in(card, '2:00'))
    assert ratio(title['text'], title['surface']) >= TEXT
    assert ratio(length['text'], length['surface']) >= TEXT
    outline = button_in(aside, '태그 편집')
    button = probe(window, outline)
    assert ratio(button['border'], button['outer']) >= UI
    assert ratio(button['text'], button['surface']) >= TEXT
    focused = keyboard_focus(window, outline)
    assert ratio(focused['border'], focused['outer']) >= UI
    surface_card = button['outer']

    # 떠 있는 층(필터 팝오버): 제목·보조 글자, 태그 입력란·윤곽선 단추 경계, 입력란 초점 경계.
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=point(window, button_in(page, '필터')))
    panel = "document.querySelector('[aria-label=\"라이브러리 필터 패널\"]')"
    wait_for(lambda: js(window, f"!!{panel}"))
    settle(window)
    heading = probe(window, text_in(panel, '검색 조건'))
    legend = probe(window, text_in(panel, '태그 · 모두 포함(AND)'))
    assert ratio(heading['text'], heading['surface']) >= TEXT
    assert ratio(legend['text'], legend['surface']) >= TEXT
    tags = probe(window, f"{panel}.querySelector('input')")
    choice = probe(window, button_in(panel, '외부 자막 있음'))
    assert ratio(tags['border'], tags['outer']) >= UI
    assert ratio(choice['border'], choice['outer']) >= UI
    focused = keyboard_focus(window, f"{panel}.querySelector('input')")
    assert ratio(focused['border'], focused['outer']) >= UI
    surfaces_rise(header['surface'], surface_card, heading['surface'])
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not js(window, f"!!{panel}"))

    # 떠 있는 층(대화상자): 설명 글자와 닫기 단추 경계·초점 윤곽.
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_for(lambda: js(window, "!!document.querySelector('[role=dialog]')"))
    settle(window)
    dialog = "document.querySelector('[role=dialog]')"
    description = probe(window, f"{dialog}.querySelector('p')")
    close = button_in(dialog, '닫기')
    button = probe(window, close)
    assert ratio(description['text'], description['surface']) >= TEXT
    assert ratio(button['border'], button['outer']) >= UI
    focused = keyboard_focus(window, close)
    assert ratio(focused['border'], focused['outer']) >= UI
    assert ratio(surface_card, description['surface']) >= 1.15
    QTest.keyClick(view(window), Qt.Key.Key_Escape)


def test_hover_and_selection_are_distinct_surfaces(window):
    # 머리글 탭: 호버 면은 바탕보다 밝고, 선택 면은 호버 면보다 더 밝다.
    selected = probe(window, "document.querySelector('nav [data-tab=library]')")
    hovered = hover(window, "document.querySelector('nav [data-tab=recommend]')")
    assert ratio(hovered['surface'], hovered['outer']) >= 1.3
    assert luminance(selected['surface']) > luminance(hovered['surface'])
    assert ratio(selected['surface'], hovered['surface']) >= 1.15
    assert ratio(selected['text'], selected['surface']) >= TEXT

    # 영상 카드: 쉬는 테두리는 장식 선이고, 호버에 경계가 눈에 띄게 밝아진다. 선택은 강조색 윤곽.
    grid = "document.getElementById('library-grid')"
    other = f"[...{grid}.querySelectorAll('[role=gridcell]')].find(e => e.id !== {grid}.getAttribute('aria-activedescendant'))"
    rest = probe(window, other)
    hovered = hover(window, other)
    assert ratio(hovered['border'], rest['border']) >= 1.3
    chosen = probe(window, f"document.getElementById({grid}.getAttribute('aria-activedescendant'))")
    assert ratio(chosen['border'], chosen['outer']) >= UI

    # 윤곽선 단추: 호버에 면이 한 단계 밝아진다.
    aside = "document.querySelector('aside')"
    outline = button_in(aside, '태그 편집')
    rest = probe(window, outline)
    hovered = hover(window, outline)
    assert ratio(hovered['surface'], rest['surface']) >= 1.3


def test_status_badges_notices_and_highlight_text_meet_text_contrast(window):
    grid = "document.getElementById('library-grid')"
    for label in ('아직 안 봄', '다 봄'):
        badge = probe(window, text_in(grid, label))
        assert ratio(badge['text'], badge['surface']) >= TEXT, label
    partial = probe(window, f"[...{grid}.querySelectorAll('span')].find(e => e.textContent.startsWith('보다 만'))")
    assert ratio(partial['text'], partial['surface']) >= TEXT

    # 위험 동작 글자(카드 위)와 하이라이트 시각 글자.
    aside = "document.querySelector('aside')"
    danger = probe(window, button_in(aside, '제외'))
    assert ratio(danger['text'], danger['surface']) >= TEXT
    js(window, f"{aside}.querySelector('[data-tab=highlights]').click()")
    wait_for(lambda: js(window, "document.querySelectorAll('#detail-scroll [role=option]').length") == 1)
    settle(window)
    marker = probe(window, "document.querySelector('#detail-scroll [role=option] [title$=\"지점\"]')")
    assert ratio(marker['text'], marker['surface']) >= TEXT

    # 안내: 정보·경고·오류 모두 옅은 상태 면 위 글자 4.5:1, 아이콘 3:1.
    notice = "document.querySelector('[aria-label=\"앱 안내\"] [data-slot=notice]')"
    for message, tone in (('검사 완료', 'info'), ('번역 보류 · 잠시 뒤 다시 시도', 'warning'), ('검사 실패: 폴더 없음', 'error')):
        window.statusBar().showMessage(message)
        wait_for(lambda: js(window, f"{notice}?.dataset.tone") == tone)
        settle(window)
        text = probe(window, text_in(notice, message))
        icon = probe(window, f"{notice}.querySelector('svg')")
        assert ratio(text['text'], text['surface']) >= TEXT, tone
        assert ratio(icon['text'], icon['surface']) >= UI, tone
