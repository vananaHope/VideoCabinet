"""면 단계와 대비: 실제 웹 셸에서 계산된 색을 읽어 바탕·카드·떠 있는 층 위의 글자·조작 경계·초점 윤곽,
상태 배지·안내·하이라이트 글자의 WCAG 대비를 잰다. 반투명 면은 실제로 그 뒤에 칠해진 면과 합성한다."""

from datetime import datetime, timezone
import json

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow
from my_video_manager.web_dialogs_entries import HighlightEditor
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, settle, shown, view
from test_emergency_hide_ui import Media, Player, app

TEXT, UI = 4.5, 3.0

# 요소 하나의 글자·테두리 색과 그 뒤에 실제로 칠해진 면. 조상의 배경을 바깥에서부터 차례로 합성한다.
# 계산된 색(oklab·color-mix 포함)은 canvas로 sRGB 바이트로 바꾼다.
PROBE = r"""(() => {
  const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
  const rgba = color => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data] }
  const over = (top, bottom) => top.slice(0, 3).map((v, i) => v * top[3] / 255 + bottom[i] * (1 - top[3] / 255))
  const surface = el => { const chain = []; for (let p = el; p; p = p.parentElement) chain.unshift(p)
    return chain.reduce((bg, p) => over(rgba(getComputedStyle(p).backgroundColor), bg), [0, 0, 0]) }
  // 실제로 그려지는 윤곽: outline, 또는 퍼짐이 있는 box-shadow(ring). 색은 윤곽이 놓인 면과 합성한다. 없으면 null.
  const ring = (style, own, outer) => {
    if (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0 && rgba(style.outlineColor)[3])
      return { color: over(rgba(style.outlineColor), outer), against: outer, width: parseFloat(style.outlineWidth) }
    const shadows = style.boxShadow === 'none' ? [] : style.boxShadow.split(/,(?![^(]*\))/)
    return shadows.map(shadow => shadow.trim().match(/^([a-z]+\([^)]*\)|[a-z]+)\s+(.*)$/)).filter(Boolean)
      .map(([, color, rest]) => ({ color: rgba(color), inset: rest.includes('inset'), width: (rest.match(/-?[\d.]+px/g) || []).map(parseFloat)[3] || 0 }))
      .filter(shadow => shadow.width > 0 && shadow.color[3])
      .map(({ color, inset, width }) => ({ color: over(color, inset ? own : outer), against: inset ? own : outer, width }))
      .sort((a, b) => b.width - a.width)[0] ?? null
  }
  window.probe = el => {
    const style = getComputedStyle(el), own = surface(el), outer = surface(el.parentElement)
    const placeholder = el.placeholder ? over(rgba(getComputedStyle(el, '::placeholder').color), own) : null
    return { text: over(rgba(style.color), own), surface: own, outer, placeholder,
      border: over(rgba(style.borderTopColor), outer), ring: ring(style, own, outer),
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


def still(window, element):
    """색 전환이 끝날 때까지 기다린다."""
    settle(window)
    wait_for(lambda: js(window, f"({element}).getAnimations({{ subtree: true }}).every(a => a.playState !== 'running')"))


def painted_still(window, element):
    """요소의 그림에 영향을 주는 애니메이션이 모두 끝날 때까지 기다린다.

    불투명도·변형 애니메이션은 조상에 걸려 있어도 요소의 픽셀을 바꾼다(대화상자를 감싼 오버레이의 fade-in).
    still은 요소와 그 아래만 보므로 픽셀을 재는 검사는 조상까지 본다.
    """
    settle(window)
    wait_for(lambda: js(window, f"""(() => {{ const e = {element}
      return document.getAnimations().every(a => a.playState !== 'running' || !(a.effect?.target?.contains(e) || e.contains(a.effect?.target))) }})()"""))


def hover(window, element):
    # 떠 있는 층 안 목록은 스크롤되므로 요소를 보이는 자리로 옮긴 뒤 마우스를 올린다.
    js(window, f"({element}).scrollIntoView({{ block: 'nearest' }})")
    settle(window)
    # 커서가 이미 그 자리면(같은 작업자의 앞 테스트가 같은 좌표에 올려 둔 경우) 마우스 이동 이벤트가 생기지 않아
    # 새 창의 요소가 호버되지 않는다. 빈 자리를 거쳐 옮긴다.
    QTest.mouseMove(view(window), QPoint(2, 2))
    QTest.mouseMove(view(window), point(window, element))
    wait_for(lambda: probe(window, element)['hovered'])
    still(window, element)
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
    still(window, element)
    return probe(window, element)


def focus_ring(window, element):
    """키보드 초점에 실제로 그려지는 윤곽(outline 또는 ring)이 놓인 면과 3:1이고, 쉬는 상태와 구별된다."""
    js(window, f"(() => {{ const e = {element}; if (document.activeElement === e) e.blur() }})()")
    still(window, element)
    rest = probe(window, element)
    focused = keyboard_focus(window, element)
    shown = focused['ring']
    assert shown is not None and shown['width'] >= 1
    assert ratio(shown['color'], shown['against']) >= UI
    assert rest['ring'] is None or rest['ring']['width'] < shown['width'] or ratio(rest['ring']['color'], shown['color']) >= 1.3
    return focused


def hover_below_selection(selected, hovered):
    """호버 면은 놓인 면보다 한 단계 밝고, 선택 면은 그 호버 면보다 더 밝아 둘이 같은 모양이 아니다."""
    assert luminance(hovered['surface']) > luminance(hovered['outer'])
    assert ratio(hovered['surface'], hovered['outer']) >= 1.1
    assert luminance(selected['surface']) > luminance(hovered['surface'])
    assert ratio(selected['surface'], hovered['surface']) >= 1.15
    assert ratio(selected['text'], selected['surface']) >= TEXT
    assert ratio(hovered['text'], hovered['surface']) >= TEXT


def close_with_escape(window, element):
    """Esc를 눌러 떠 있는 층을 닫는다. 태그 고르기는 활성 후보·검색어를 먼저 지우므로 닫힐 때까지 누른다."""
    def gone():
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        settle(window)
        return not js(window, f"!!{element}")
    wait_for(gone)


def in_dialog(window, entry, check):
    """모달로 도는 업무 대화상자 안에서 check를 실행하고 닫는다."""
    errors = []

    def run():
        try:
            check()
        except BaseException as error:
            errors.append(error)
        finally:
            dialogs = window.web_host.dialogs
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(0, run)
    entry()
    # 닫은 뒤 예약된 초점 되돌리기와 대화상자 루프 정리를 창을 지우기 전에 끝낸다.
    settle(window)
    if errors:
        raise errors[0]


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
    # 다 본 영상을 두 번 더 다 보면 즐겨 보는 영상이 된다. 태그 고르기 후보로 태그 둘을 붙인다.
    for _ in range(2):
        core.playback.start(ids[2], 0)
        core.playback.report(120)
        core.playback.end()
    core.add_video_tag(ids[0], '복습')
    core.add_video_tag(ids[1], '예습')
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
    assert ratio(field['placeholder'], field['surface']) >= TEXT
    focus_ring(window, search)

    # 카드: 영상 제목·길이 글자, 상세 패널의 윤곽선 단추 경계와 초점 경계.
    title = probe(window, text_in(card, '강의 01강'))
    length = probe(window, text_in(card, '2:00'))
    assert ratio(title['text'], title['surface']) >= TEXT
    assert ratio(length['text'], length['surface']) >= TEXT
    outline = button_in(aside, '태그 편집')
    button = probe(window, outline)
    assert ratio(button['border'], button['outer']) >= UI
    assert ratio(button['text'], button['surface']) >= TEXT
    focus_ring(window, outline)
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
    trigger = f"{panel}.querySelector('[data-slot=select-trigger]')"
    select = probe(window, trigger)
    assert ratio(tags['border'], tags['outer']) >= UI
    assert ratio(tags['placeholder'], tags['surface']) >= TEXT
    assert ratio(choice['border'], choice['outer']) >= UI
    assert ratio(select['border'], select['outer']) >= UI
    focus_ring(window, f"{panel}.querySelector('input')")
    focus_ring(window, trigger)
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
    focus_ring(window, close)
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

    # 영상 카드: 쉬는 테두리는 장식 선 그대로이고, 호버에 면이 한 단계 밝아진다. 선택은 강조색 윤곽.
    grid = "document.getElementById('library-grid')"
    other = f"[...{grid}.querySelectorAll('[role=gridcell]')].find(e => e.id !== {grid}.getAttribute('aria-activedescendant'))"
    rest = probe(window, other)
    hovered = hover(window, other)
    assert luminance(hovered['surface']) > luminance(rest['surface'])
    assert ratio(hovered['surface'], rest['surface']) >= 1.15
    assert ratio(hovered['border'], rest['border']) < 1.05
    chosen = probe(window, f"document.getElementById({grid}.getAttribute('aria-activedescendant'))")
    assert ratio(chosen['border'], chosen['outer']) >= UI

    # 상세 패널 탭(카드 위): 호버와 선택이 다른 면이다.
    tabs = "document.querySelector('aside nav')"
    selected = probe(window, f"{tabs}.querySelector('[aria-current=page]')")
    hover_below_selection(selected, hover(window, f"{tabs}.querySelector('button:not([aria-current])')"))

    # 윤곽선 단추: 호버에 면이 한 단계 밝아진다.
    aside = "document.querySelector('aside')"
    outline = button_in(aside, '태그 편집')
    rest = probe(window, outline)
    hovered = hover(window, outline)
    assert ratio(hovered['surface'], rest['surface']) >= 1.3

    # 태그 고르기(떠 있는 층 위): 하나를 고른 뒤 다른 후보에 올린 호버가 고른 후보와 다른 면이다.
    page = "document.querySelector('[data-page=library]')"
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=point(window, button_in(page, '필터')))
    panel = "document.querySelector('[aria-label=\"라이브러리 필터 패널\"]')"
    options = f"{panel}.querySelectorAll('[role=option]')"
    wait_for(lambda: js(window, f"{options}.length") == 2)
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=point(window, f"{options}[0]"))
    wait_for(lambda: js(window, f"{options}[0].getAttribute('aria-selected')") == 'true')
    still(window, f"{options}[0]")
    selected = probe(window, f"{options}[0]")
    hover_below_selection(selected, hover(window, f"{options}[1]"))
    close_with_escape(window, panel)

    # 설정 분류(바탕 위): 고른 분류와 호버한 분류가 다른 면이다.
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=point(window, "document.querySelector('nav [data-tab=settings]')"))
    current = "document.querySelector('#settings-category [aria-current=true]')"
    wait_for(lambda: js(window, f"!!{current}?.getClientRects().length"))
    still(window, current)
    selected = probe(window, current)
    hover_below_selection(selected, hover(window, "document.querySelector('#settings-category button:not([aria-current])')"))


def test_search_result_badge_stays_distinct_on_rest_hover_and_selected_row(window):
    # 검색 결과 행 안 출처 배지(muted)는 쉬는·호버·선택 어느 행 면에서도 면이 사라지지 않는다.
    window.core.prepare_search()
    window.show_search()
    field = "document.querySelector('[data-page=search] input')"
    wait_for(lambda: js(window, f"!!{field}?.getClientRects().length"))
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, pos=point(window, field))
    QTest.keyClicks(view(window), 'mkv')
    rows = "document.querySelectorAll('#search-results [role=option]')"
    wait_for(lambda: js(window, f"{rows}.length") == 3 and not js(window, f"!!document.querySelector('#search-results [aria-disabled]')"))
    selected_row = "document.querySelector('#search-results [aria-selected=true]')"
    rest_row = f"[...{rows}].filter(e => e.getAttribute('aria-selected') !== 'true').at(-1)"
    other_row = f"[...{rows}].find(e => e.getAttribute('aria-selected') !== 'true')"
    still(window, "document.getElementById('search-results')")

    def badge(row):
        return probe(window, text_in(row, '파일 이름'))
    rest, rest_badge = probe(window, rest_row), badge(rest_row)
    selected, selected_badge = probe(window, selected_row), badge(selected_row)
    hovered = hover(window, other_row)
    hovered_badge = badge(other_row)
    assert luminance(hovered['surface']) > luminance(rest['surface'])
    assert ratio(hovered['surface'], rest['surface']) >= 1.15
    for row, chip in ((rest, rest_badge), (hovered, hovered_badge), (selected, selected_badge)):
        assert ratio(chip['surface'], row['surface']) >= 1.1
        assert ratio(chip['text'], chip['surface']) >= TEXT


def test_status_badges_notices_and_highlight_text_meet_text_contrast(window):
    grid = "document.getElementById('library-grid')"
    for label in ('아직 안 봄', '다 봄', '즐겨 보는'):
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


def test_checkbox_boundary_meets_ui_contrast_on_floating_layer(window):
    # 공용 체크박스(구간 하이라이트)의 꺼진 테두리를 대화상자에 실제로 그려진 픽셀로 잰다.
    core = window.core
    video = min(core.videos(), key=lambda video: video.title)
    highlight = core.highlights(video.id)[0]
    box = shown('[role=dialog] [role=checkbox]')

    def check():
        wait_for(lambda: js(window, f"!!{box}"))
        painted_still(window, box)
        assert js(window, f"{box}.getAttribute('aria-checked')") == 'false'
        surface = probe(window, box)['outer']
        rect = json.loads(js(window, f"JSON.stringify(({box}).getBoundingClientRect())"))
        origin = view(window).mapTo(window, QPoint(0, 0))
        frame = {}

        def drawn():
            # 화면 그림은 DOM보다 늦게 온다. 체크박스 옆 빈자리가 대화상자 면으로 칠해지고,
            # 한 프레임 뒤에도 체크박스 둘레가 그대로인(더 바뀌지 않는) 그림을 기다린다.
            # 면 색만 보면 끝나 가는 fade-in 프레임도 허용 오차 안에 들어와 옅은 테두리를 재게 된다.
            previous = frame.get('image')
            settle(window)
            frame['image'] = image = window.grab().toImage()
            scale = image.devicePixelRatio()
            around = QRect(round((origin.x() + rect['x'] - 4) * scale), round((origin.y() + rect['y'] - 4) * scale),
                           round((rect['width'] + 8) * scale), round((rect['height'] + 8) * scale))
            gap = image.pixelColor(round((origin.x() + rect['right'] + 3) * scale), round((origin.y() + rect['y'] + rect['height'] / 2) * scale))
            return (max(abs(a - b) for a, b in zip((gap.red(), gap.green(), gap.blue()), surface)) <= 2
                    and previous is not None and previous.copy(around) == image.copy(around))
        wait_for(drawn)
        image = frame['image']
        scale = image.devicePixelRatio()
        left, top = (origin.x() + rect['x']) * scale, (origin.y() + rect['y']) * scale
        colors = [image.pixelColor(round(left + x), round(top + y))
                  for x in range(round(rect['width'] * scale)) for y in range(round(rect['height'] * scale))]
        assert max(ratio((c.red(), c.green(), c.blue()), surface) for c in colors) >= UI
    in_dialog(window, lambda: HighlightEditor(core, highlight, video.duration, window).exec(), check)
