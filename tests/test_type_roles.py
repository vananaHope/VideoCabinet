"""글자 역할 토큰: 웹 셸의 모든 탭·키 안내와 Qt 재생 화면의 글자가 web_tokens.json의 역할 값(크기·줄 높이·굵기·자간)으로 그려진다.

같은 역할은 어느 화면이든 같은 값이고, 역할 줄 높이에 묶인 카드 정보 칸·격자 줄 높이가 토큰을 따라간다.
"""
import json

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtTest import QTest

from my_video_manager.library_views import default_options
from my_video_manager.web_contract import TABS
from my_video_manager.web_tokens import type_roles, web_tokens
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, settle, view
from test_emergency_hide_ui import app, window  # noqa: F401 (pytest 픽스처)
from test_web_key_guide import wait_guide

ROLES = type_roles()


def pixels(value):
    return float(value.removesuffix('rem')) * 16


def expected(role):
    """역할 토큰을 getComputedStyle 값(px·굵기 문자열)으로."""
    values = ROLES[role]
    size = pixels(values['size'])
    return {'size': size, 'line': pixels(values['line-height']), 'weight': values['weight'],
            'spacing': round(float(values['letter-spacing'].removesuffix('em')) * size, 2)}


# 보이는 글자 요소의 계산된 글자 값. 역할 클래스(text-<역할>)를 가진 요소는 그 역할 이름을 함께 돌려준다.
# Recharts가 글자 폭을 재려고 body에 붙이는 측정용 span과 SVG 축 글자는 제외한다.
TEXT_STYLES = """JSON.stringify((() => {
  const roles = %s
  const visible = e => e.getClientRects().length > 0
  const own = e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
  return [...document.querySelectorAll('body *')]
    .filter(e => visible(e) && own(e) && e.id !== 'recharts_measurement_span' && !e.closest('svg'))
    .map(e => {
      const s = getComputedStyle(e), dialog = e.closest('[role=dialog]')
      return { tag: e.tagName.toLowerCase(), text: e.textContent.trim().slice(0, 30),
        role: roles.find(role => e.classList.contains('text-' + role)) ?? null,
        dialogTitle: !!dialog && !!e.id && dialog.getAttribute('aria-labelledby') === e.id,
        kbd: e.tagName === 'KBD', badge: e.matches('[data-slot=status-badge]'),
        size: parseFloat(s.fontSize), line: parseFloat(s.lineHeight), weight: s.fontWeight,
        spacing: s.letterSpacing === 'normal' ? 0 : Math.round(parseFloat(s.letterSpacing) * 100) / 100 }
    })
})())""" % json.dumps(list(ROLES))


def text_styles(window):
    return json.loads(js(window, TEXT_STYLES))


def style(element):
    return {key: element[key] for key in ('size', 'line', 'weight', 'spacing')}


def add_viewing(core):
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(40)
    core.playback.end()


def page_ready(window, tab):
    return window.web_host.active_tab == tab and js(window, f"""(() => {{
      const page = document.querySelector('[data-page={tab}]')
      return !!page && page.getClientRects().length > 0 && !page.querySelector('[aria-busy=true], [data-slot=skeleton]') }})()""")


def test_every_tab_and_key_guide_draw_each_role_with_its_token_values(window):
    add_viewing(window.core)
    wait_for(lambda: window.loaded)
    window.activateWindow()
    seen, elements = set(), []
    for index, (tab, _) in enumerate(TABS):
        # 사용자가 Ctrl+순번으로 탭을 옮긴다.
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda: page_ready(window, tab))
        if tab == 'statistics':
            wait_for(lambda: js(window, "!!document.querySelector('[data-page=statistics] .text-display')"))
        settle(window)
        found = text_styles(window)
        assert found, tab
        for element in found:
            element['tab'] = tab
        elements += found

    # 키 안내(F1): 대화상자 제목과 키 표시.
    window.navigate_web_tab('library')
    window.web_host.view.setFocus()
    js(window, "document.getElementById('library-grid').focus()")
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_guide(window)
    settle(window)
    guide = text_styles(window)
    elements += [{**element, 'tab': 'key-guide'} for element in guide]

    for element in elements:
        # 역할 클래스를 가진 글자는 어느 탭에서나 그 역할 토큰 값 그대로다(다른 유틸리티가 덮어쓰지 않는다).
        if element['role']:
            seen.add(element['role'])
            assert style(element) == expected(element['role']), element
        # 페이지 제목·대화상자 제목·상태 배지·키 표시는 정해진 역할로 그린다.
        if element['tag'] == 'h1':
            assert style(element) == expected('page-title'), element
        if element['dialogTitle']:
            assert style(element) == expected('section-title'), element
        if element['badge'] or element['kbd']:
            assert style(element) == expected('label-strong'), element
        # 같은 크기의 글자는 화면마다 다른 줄 높이를 쓰지 않는다.
        for role in ('body', 'label'):
            if element['size'] == expected(role)['size']:
                assert element['line'] == expected(role)['line'], element
        # 번들 글꼴에 있는 굵기만 쓴다(없는 굵기를 흉내 내지 않는다).
        assert element['weight'] in web_tokens()['bundled-font']['weights'], element
    assert seen == set(ROLES), seen
    assert any(e['tag'] == 'h1' for e in elements)
    assert any(e['dialogTitle'] for e in guide) and any(e['kbd'] for e in guide)
    assert any(e['badge'] for e in elements)


# 보이고 글자를 직접 가진 요소 중 글자가 정확히 title인 것의 계산된 글자 값. 클래스가 없어 상속으로 정해지는 제목도 잡는다.
TITLE_STYLE = """(() => {
  const title = %s
  const own = e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
  const e = [...document.querySelectorAll(%s)].find(e => e.getClientRects().length > 0 && own(e) && e.textContent.trim() === title)
  if (!e) return null
  const s = getComputedStyle(e)
  return JSON.stringify({ size: parseFloat(s.fontSize), line: parseFloat(s.lineHeight), weight: s.fontWeight,
    spacing: s.letterSpacing === 'normal' ? 0 : Math.round(parseFloat(s.letterSpacing) * 100) / 100 })
})()"""


def title_style(window, selector, title):
    found = js(window, TITLE_STYLE % (json.dumps(title), json.dumps(selector)))
    return json.loads(found) if found else None


def click(window, selector):
    """보이는 selector 요소의 가운데를 실제 마우스로 누른다."""
    center = json.loads(js(window, f"""(() => {{ const e = [...document.querySelectorAll({json.dumps(selector)})]
      .find(e => e.getClientRects().length > 0), r = e.getBoundingClientRect()
      return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) }})()"""))
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*map(round, center)))


def test_excluded_and_dismissed_video_titles_use_the_same_role_as_library_cards(window):
    core = window.core
    excluded, dismissed = core.videos()[:2]
    core.exclude_video(excluded.id)
    core.dismiss_video(dismissed.id)
    wait_for(lambda: window.loaded)
    window.activateWindow()
    # 라이브러리 카드의 영상 제목(관심 없음으로 뺀 영상은 라이브러리에 그대로 보인다).
    wait_for(lambda: title_style(window, '#library-grid [role=gridcell] *', dismissed.title) is not None)
    card = title_style(window, '#library-grid [role=gridcell] *', dismissed.title)
    assert card == expected('body-strong'), card

    # 사용자가 Ctrl+순번으로 폴더 관리에 들어가 제외 목록·관심 없음 되돌리기 구역을 차례로 연다.
    index = [tab for tab, _ in TABS].index('folders')
    QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: page_ready(window, 'folders'))
    for section, video in (('excluded', excluded), ('dismissed', dismissed)):
        click(window, f'[data-page=folders] button[data-tab={section}]')
        wait_for(lambda: js(window, f"!!document.querySelector('[data-page=folders] button[data-tab={section}][aria-current=page]')"))
        wait_for(lambda: title_style(window, '#folders-section li *', video.title) is not None)
        settle(window)
        # 되돌리기 목록의 영상 제목도 카드·목록의 항목 제목과 같은 역할 값이다.
        assert title_style(window, '#folders-section li *', video.title) == card, section


CARD_ROWS = """JSON.stringify((() => {
  const grid = document.getElementById('library-grid'), root = parseFloat(getComputedStyle(document.documentElement).fontSize)
  return { row: parseFloat(getComputedStyle(grid).getPropertyValue('--grid-row-height')) * root,
    cards: [...grid.querySelectorAll('[role=gridcell]')].map(card => { const info = card.lastElementChild
      const box = card.getBoundingClientRect(), own = info.getBoundingClientRect()
      return { height: box.height, info: own.height, below: own.bottom - (box.bottom - parseFloat(getComputedStyle(card).borderBottomWidth)),
        clipped: info.scrollHeight - info.clientHeight,
        sticks: Math.max(...[...info.querySelectorAll('*')].map(e => e.getBoundingClientRect().bottom)) - info.getBoundingClientRect().bottom } }) }
})())"""


def card_rows(window):
    return json.loads(js(window, CARD_ROWS))


def test_card_info_height_and_grid_rows_follow_the_token(window):
    core = window.core
    first = core.videos()[0]
    core.rename_video(first.id, '아주 긴 한글 제목과 공백 없는 영문 제목 ' + 'LongVideoTitle' * 12)
    for index in range(4):
        core.add_video_tag(first.id, f'{index} 긴 태그 ' + '태그' * 12)
    add_viewing(core)
    wait_for(lambda: window.loaded)
    page = window.library_page
    page.selection_changed()
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 2)
    info = pixels(web_tokens()['layout']['library-card-info-height'])
    for size in ('small', 'medium', 'large'):
        page.bridge.view(json.dumps({**default_options(), 'card_size': size}))
        page.selection_changed()
        wait_for(lambda: js(window, "document.querySelector('[aria-label=\"카드 크기\"]').dataset.value") == size)
        settle(window)
        rows = card_rows(window)
        for card in rows['cards']:
            # 정보 칸은 토큰 높이이고, 카드(테두리+16:9 썸네일+정보 칸)와 줄 간격 12px이 줄 높이와 같다. 글자는 잘리지 않는다.
            assert abs(card['info'] - info) < 0.5, (size, rows)
            assert abs(card['height'] + 12 - rows['row']) < 1, (size, rows)
            # 카드는 줄 높이를 채우므로(h-full) 정보 칸 아래 끝이 카드 테두리 안쪽 끝과 맞는지로 줄 높이 계산을 확인한다.
            assert abs(card['below']) < 0.5, (size, rows)
            assert card['clipped'] <= 0 and card['sticks'] <= 0.5, (size, rows)

    # 토큰 값을 바꾸면 카드 정보 칸과 격자 줄 높이 계산이 함께 따라간다(둘 다 같은 토큰을 읽는다).
    before = card_rows(window)
    js(window, "document.documentElement.style.setProperty('--library-card-info-height', '12rem')")
    window.resize(window.width() - 40, window.height())
    wait_for(lambda: abs(card_rows(window)['row'] - before['row']) > 1)
    settle(window)
    after = card_rows(window)
    for card in after['cards']:
        assert abs(card['info'] - pixels('12rem')) < 0.5, after
        assert abs(card['height'] + 12 - after['row']) < 1, after
        assert abs(card['below']) < 0.5, after


def test_playback_title_and_secondary_text_read_role_tokens(window):
    wait_for(lambda: window.loaded)
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 2)
    # 사용자가 격자에서 선택한 영상을 Enter로 재생한다.
    window.activateWindow()
    window.web_host.view.setFocus()
    js(window, "document.getElementById('library-grid').focus()")
    wait_for(lambda: window.library_page.selected_id is not None)
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    playback = window.playback_page
    wait_for(lambda: window.pages.currentWidget() is playback and playback.title_label.text())

    def check(widget, role):
        widget.ensurePolished()
        actual = QFontInfo(widget.font())
        token = expected(role)
        assert (actual.pixelSize(), actual.weight()) == (token['size'], int(token['weight'])), (role, widget.text())
        assert widget.font().letterSpacingType() == QFont.SpacingType.AbsoluteSpacing
        # Qt는 자간을 1/64px 단위로 저장한다.
        assert abs(widget.font().letterSpacing() - token['spacing']) <= 1 / 64, (role, widget.font().letterSpacing())
        # 글자가 위젯 안에 다 들어간다(머리글·패널 높이가 역할 크기를 받아 준다).
        assert widget.height() >= widget.sizeHint().height(), (role, widget.height(), widget.sizeHint())

    panel = playback.highlights_panel
    wait_for(lambda: playback.header.isVisible() and panel.isVisible())
    check(playback.title_label, 'section-title')
    check(panel.heading, 'section-title')
    for widget in (panel.empty, panel.hint):
        check(widget, 'body')
    for widget in (playback.reel_label, playback.subtitle_work_label, playback.message_label):
        widget.ensurePolished()
        assert QFontInfo(widget.font()).pixelSize() == expected('body')['size']
        assert QFontInfo(widget.font()).weight() == int(expected('body')['weight'])
    assert playback.header.height() >= playback.header.sizeHint().height()
