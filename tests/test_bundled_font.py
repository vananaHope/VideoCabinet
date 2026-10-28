"""번들 글꼴: 웹 셸의 모든 탭·대화상자·키 안내가 앱에 묶은 Pretendard로 뜨고, Qt 화면은 맑은 고딕을 유지한다.

첫 렌더용 글꼴(라틴·기호·자주 쓰는 한글 2,780자 부분 집합, font-display: block)은 첫 렌더 전에 읽고,
나머지 한글 음절용 전체 파일(swap)은 그 음절이 화면에 나올 때만 읽는다.
"""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from my_video_manager.library_views import default_options
from my_video_manager.theme import NATIVE_FONT
from my_video_manager.web_contract import TABS
from my_video_manager.web_tokens import web_tokens
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, rename_dialog, settle, view
from test_emergency_hide_ui import app, window
from test_web_dialogs import within
from test_web_key_guide import press_f1, wait_closed, wait_guide
from test_web_library_data import core
from test_web_library_loading import FIRST_ROW, open_window, stop_recording
from test_web_library_page import window_factory

BUNDLED = 'Pretendard'
WEIGHTS = [400, 500, 600]
WEB = Path(__file__).resolve().parents[1] / 'src/my_video_manager/web'

# 보이는 글자를 가진 요소(입력란·단추 포함)의 계산된 첫 글꼴 이름과 번들 글꼴의 로드 상태.
FONT_STATE = """JSON.stringify((() => {
  const visible = e => e.getClientRects().length > 0
  const texts = [...document.querySelectorAll('body *')].filter(e => visible(e)
    && (e.matches('input, textarea, button') || [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())))
  const first = e => getComputedStyle(e).fontFamily.split(',')[0].trim().replace(/^"|"$/g, '')
  const faces = [...document.fonts].filter(f => f.family.replace(/^"|"$/g, '') === %s)
  const status = display => Object.fromEntries(faces.filter(f => f.display === display).map(f => [f.weight, f.status]))
  return { families: [...new Set(texts.map(first))], texts: texts.length, first: status('block'), rest: status('swap') }
})())""" % json.dumps(BUNDLED)


def font_state(window):
    return json.loads(js(window, FONT_STATE))


def assert_bundled(window):
    state = font_state(window)
    assert state['texts'] > 0 and state['families'] == [BUNDLED], state
    assert state['first'] == {str(weight): 'loaded' for weight in WEIGHTS}, state


def test_every_tab_dialog_and_key_guide_render_with_loaded_bundled_font(window):
    assert web_tokens()['typography']['font-sans'].startswith(f'"{BUNDLED}", "{NATIVE_FONT}"')
    wait_for(lambda: window.loaded)
    host = window.web_host
    for tab, _ in TABS:
        window.navigate_web_tab(tab)
        wait_for(lambda: host.active_tab == tab and js(window, f"!!document.querySelector('[data-page={tab}]')?.getClientRects().length"))
        settle(window)
        assert_bundled(window)

    window.navigate_web_tab('library')
    press_f1(window)
    wait_guide(window)
    assert_bundled(window)
    assert js(window, "!!Array.from(document.querySelectorAll('[role=dialog] kbd')).find(e => e.getClientRects().length)")
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_closed(window)

    dialogs = host.dialogs

    def check():
        wait_for(lambda: js(window, "!!document.querySelector('[role=dialog] input[aria-label=\"영상 제목\"]')"))
        settle(window)
        assert_bundled(window)
    within(rename_dialog(window), dialogs, check)


def test_bundled_font_is_read_from_the_web_bundle_and_has_tabular_digits(window):
    wait_for(lambda: window.loaded)
    sources = json.loads(js(window, """JSON.stringify([...document.styleSheets].flatMap(sheet => [...sheet.cssRules]
      .filter(rule => rule instanceof CSSFontFaceRule)
      .map(rule => ({ family: rule.style.getPropertyValue('font-family'), display: rule.style.getPropertyValue('font-display'),
        weight: rule.style.getPropertyValue('font-weight'), range: rule.style.getPropertyValue('unicode-range'),
        urls: [...rule.style.getPropertyValue('src').matchAll(/url\\("?([^")]+)"?\\)/g)].map(m => new URL(m[1], sheet.href).href) }))))"""))
    # 글꼴은 설치된 웹 번들 안의 파일에서만 읽는다(외부 URL 없음). 굵기마다 첫 렌더용 하나와 나머지 음절용 하나다.
    assert {s['family'].strip('"') for s in sources} == {BUNDLED}
    assert sorted((s['display'], s['weight']) for s in sources) == sorted((d, str(w)) for d in ('block', 'swap') for w in WEIGHTS)
    for source in sources:
        assert len(source['urls']) == 1 and source['urls'][0].startswith('file:///'), source
        font_file = Path(QUrl(source['urls'][0]).toLocalFile()).resolve()
        assert font_file.is_relative_to(WEB.resolve()) and font_file.stat().st_size > 0
        assert source['range'] == ('U+AC00-D7A3' if source['display'] == 'swap' else ''), source
    # KS X 1001 안의 글자만 보이는 화면에서는 나머지 음절 파일을 읽지 않는다.
    state = font_state(window)
    assert state['first'] == {str(weight): 'loaded' for weight in WEIGHTS}, state
    assert state['rest'] == {str(weight): 'unloaded' for weight in WEIGHTS}, state

    # 고정폭 표시(font-mono)와 tabular-nums는 숫자마다 같은 폭이다. 기본 숫자는 비례폭이라 대조가 된다.
    widths = json.loads(js(window, """JSON.stringify(Object.fromEntries(['font-mono', 'tabular-nums', ''].map(cls => {
      const measure = text => { const s = document.createElement('span'); s.className = cls; s.textContent = text
        document.body.append(s); const w = s.getBoundingClientRect().width; s.remove(); return w }
      return [cls || 'default', [measure('1111111111'), measure('0000000000')]]
    })))"""))
    for name in ('font-mono', 'tabular-nums'):
        narrow, wide = widths[name]
        assert abs(narrow - wide) < 0.5, widths
    assert widths['default'][1] - widths['default'][0] > 1, widths


CARD_FIT = """JSON.stringify((() => {
  const grid = document.getElementById('library-grid')
  const row = parseFloat(getComputedStyle(grid).getPropertyValue('--grid-row-height')) * parseFloat(getComputedStyle(document.documentElement).fontSize)
  const cards = [...grid.querySelectorAll('[role=gridcell]')]
  return { row, cards: cards.map(card => { const info = card.lastElementChild
    return { height: card.getBoundingClientRect().height, clipped: info.scrollHeight - info.clientHeight,
      sticks: info.lastElementChild.getBoundingClientRect().bottom - info.getBoundingClientRect().bottom } }) }
})())"""


def test_library_and_recommendation_cards_fit_their_rows_at_every_card_size(window_factory, core):
    first, second, _ = core.videos()
    core.rename_video(first.id, '아주 긴 한글 제목과 공백 없는 영문 제목의 카드 경계 확인 ' + 'LongVideoTitle' * 14)
    for index in range(4):
        core.add_video_tag(first.id, f'{index} 긴 태그 이름 ' + '태그' * 20)
    for video in (first, second):
        core.playback.start(video.id, 0)
        core.playback.report(40)
        core.playback.end()
    window = window_factory()
    host, page = window.web_host, window.library_page
    wait_for(lambda: js(window, "document.querySelectorAll('#library-grid [role=gridcell]').length") == 3)
    for size in ('small', 'medium', 'large'):
        page.bridge.view(json.dumps({**default_options(), 'card_size': size}))
        page.selection_changed()
        wait_for(lambda: js(window, "document.querySelector('[aria-label=\"카드 크기\"]').dataset.value") == size)
        settle(window)
        fit = json.loads(js(window, CARD_FIT))
        for card in fit['cards']:
            # 카드(테두리+16:9 썸네일+정보 칸)와 줄 간격 12px이 줄 높이와 맞고, 정보 칸 글자가 잘리지 않는다.
            assert abs(card['height'] + 12 - fit['row']) < 1, (size, fit)
            assert card['clipped'] <= 0 and card['sticks'] <= 0.5, (size, fit)
        assert_bundled(window)

    window.navigate_web_tab('recommend')
    wait_for(lambda: 'recommend' in host._ready_pages)
    wait_for(lambda: js(window, "document.querySelectorAll('#recommendations [role=gridcell]').length") > 0)
    settle(window)
    # 추천 카드도 정보 칸 글자가 카드 밖으로 넘치지 않는다.
    cards = json.loads(js(window, """JSON.stringify(Array.from(document.querySelectorAll('#recommendations [role=gridcell]')).map(card => {
      const box = card.getBoundingClientRect(), info = card.lastElementChild
      return { clipped: info.scrollHeight - info.clientHeight, overflow: card.scrollHeight - card.clientHeight,
        sticks: Math.max(...[...card.querySelectorAll('*')].map(e => e.getBoundingClientRect().bottom)) - box.bottom } }))"""))
    assert cards and all(c['clipped'] <= 0 and c['overflow'] <= 0 and c['sticks'] <= 0.5 for c in cards), cards
    assert_bundled(window)


# 부분 집합(한글 2,780자)에 없는 음절.
RARE_TITLE = 'A 뷀궯 갂 강의'


def test_rare_syllable_title_swaps_to_bundled_font_without_moving_cards(open_window, core):
    """부분 집합 밖 음절(뷀·궯·갂)은 나머지 음절 파일이 도착하면 같은 글꼴로 바뀌고, 그 전후로 카드·툴바 경계가 같다."""
    video = next(v for v in core.videos() if v.title == 'PYTHON 응용')
    core.rename_video(video.id, RARE_TITLE)
    window = open_window()
    wait_for(lambda: js(window, FIRST_ROW) > 0)
    # 카드 제목(500)의 드문 음절 때문에 그 굵기의 나머지 음절 파일만 읽는다.
    wait_for(lambda: font_state(window)['rest'].get('500') == 'loaded')
    settle(window)
    frames = stop_recording(window)['frames']
    final = frames[-1]
    assert RARE_TITLE in final['text'] and not final['busy']
    for frame in frames:
        # 첫 프레임부터 글꼴이 바뀐 뒤까지 툴바·첫 줄 카드(드문 음절 제목 카드 포함)의 경계가 같다.
        assert frame['controls'] == final['controls'] and frame['cells'] == final['cells'], frame
    assert_bundled(window)


def test_native_playback_tray_and_alerts_keep_malgun_gothic(window):
    # 토큰의 첫 글꼴(번들 글꼴)은 Qt에 등록되지 않았으므로, Qt가 요청하는 글꼴이 맑은 고딕인지 본다.
    def family(widget):
        widget.ensurePolished()
        return widget.font().family()

    assert QApplication.instance().font().family() == NATIVE_FONT
    assert family(window.tray.icon.contextMenu()) == NATIVE_FONT
    alert = QMessageBox(QMessageBox.Icon.Warning, '재생 실패', '파일을 열 수 없습니다.', parent=window)
    alert.show()
    assert {family(label) for label in alert.findChildren(QLabel) if label.text()} == {NATIVE_FONT}
    alert.close()

    window.play(window.core.videos()[0].id)
    playback = window.pages.currentWidget()
    assert playback is not window.web_host
    labels = [label for label in playback.findChildren(QLabel) if label.text()]
    assert labels and {family(label) for label in labels} == {NATIVE_FONT}
