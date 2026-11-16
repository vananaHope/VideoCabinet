"""번들 글꼴: 웹 셸의 모든 탭·대화상자·키 안내와 Qt 화면(재생·트레이 메뉴·공용 경고)이 앱에 묶은 Pretendard로 뜬다.

첫 렌더용 글꼴(라틴·기호·자주 쓰는 한글 2,780자 부분 집합, font-display: block)은 첫 렌더 전에 읽고,
부분 집합에 없는 글자용 전체 파일(swap)은 그 글자가 화면에 나올 때만 읽는다.
"""
import json
import logging
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QMessageBox, QToolButton

from my_video_manager import theme
from my_video_manager.library_views import default_options
from my_video_manager.theme import FALLBACK_FONT
from my_video_manager.web_contract import TABS
from my_video_manager.web_tokens import type_roles, web_tokens
from qt_wait import wait_for
from test_emergency_hide_dialogs_ui import js, rename_dialog, settle, view
from test_emergency_hide_ui import app, open_window as open_native_window, window
from test_web_dialogs import within
from test_web_key_guide import press_f1, wait_closed, wait_guide
from test_web_library_data import core
from test_web_library_loading import FIRST_ROW, open_window, stop_recording
from test_web_library_page import window_factory

BUNDLED = 'Pretendard'
WEIGHTS = {int(weight): stem for weight, stem in web_tokens()['bundled-font']['weights'].items()}
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


def code_points(unicode_range):
    """CSS unicode-range 값을 글자 번호 집합으로."""
    points = set()
    for part in filter(None, (p.strip() for p in unicode_range.split(','))):
        first, _, last = part[2:].partition('-')
        points.update(range(int(first, 16), int(last or first, 16) + 1))
    return points


def test_every_tab_dialog_and_key_guide_render_with_loaded_bundled_font(window):
    assert web_tokens()['typography']['font-sans'].startswith(f'"{BUNDLED}", "{FALLBACK_FONT}"')
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
    # 글꼴은 설치된 웹 번들 안의 파일에서만 읽는다(외부 URL 없음). 굵기마다 첫 렌더용 하나와 나머지 글자용 하나다.
    assert {s['family'].strip('"') for s in sources} == {BUNDLED}
    assert sorted((s['display'], s['weight']) for s in sources) == sorted((d, str(w)) for d in ('block', 'swap') for w in WEIGHTS)
    for source in sources:
        assert len(source['urls']) == 1 and source['urls'][0].startswith('file:///'), source
        font_file = Path(QUrl(source['urls'][0]).toLocalFile()).resolve()
        assert font_file.is_relative_to(WEB.resolve()) and font_file.stat().st_size > 0
    # 같은 굵기의 두 face는 글자 범위가 겹치지 않는다(어느 글자든 맡는 face가 하나다).
    for weight in WEIGHTS:
        first, rest = (code_points(next(s['range'] for s in sources if s['weight'] == str(weight) and s['display'] == display))
                       for display in ('block', 'swap'))
        assert first and rest and not first & rest, weight
    # 문서 머리에서 미리 읽는 글꼴은 정확히 첫 렌더용 face의 파일들이다.
    preloads = json.loads(js(window, "JSON.stringify([...document.querySelectorAll('link[rel=preload][as=font]')].map(link => link.href))"))
    assert sorted(preloads) == sorted(s['urls'][0] for s in sources if s['display'] == 'block')
    # 부분 집합 안의 글자만 보이는 화면에서는 나머지 글자 파일을 읽지 않는다.
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


# 부분 집합 밖(확장 라틴 ı·ơ, 호환 자모 ㆍ, 기호 №·Ⅻ·↰, 가나 あ, 드문 음절 뷀)과 안(ŝ·똠·뷁·A·한)의 글자.
# 번들 원본에는 한자가 없어 한자는 어느 face도 맡지 않는다(대체 글꼴이 맞다).
GLYPHS = 'ıơㆍ№Ⅻ↰あ뷀ŝ똠뷁A한'

# 굵기마다 앱 글꼴 스택과, 같은 전체 파일만 담은 별도 계열, 대체 글꼴 스택으로 각 글자를 그린 픽셀의 해시.
GLYPH_PIXELS = """window.glyphPixels = null;
(async () => {
  const stack = getComputedStyle(document.body).fontFamily, fallback = stack.split(',').slice(1).join(',')
  const canvas = document.createElement('canvas')
  canvas.width = 80
  canvas.height = 60
  const g = canvas.getContext('2d', { willReadFrequently: true })
  const draw = (font, ch) => { g.clearRect(0, 0, 80, 60); g.font = font; g.fillText(ch, 10, 45)
    return g.getImageData(0, 0, 80, 60).data.reduce((h, v) => (h * 31 + v) | 0, 0) }
  const result = {}
  for (const [weight, url] of Object.entries(%s)) {
    const reference = new FontFace('BundledReference' + weight, `url("${url}")`, { weight })
    document.fonts.add(await reference.load())
    await document.fonts.load(`${weight} 40px ${stack}`, %s)
    result[weight] = Object.fromEntries([...%s].map(ch => [ch, { app: draw(`${weight} 40px ${stack}`, ch),
      bundled: draw(`${weight} 40px BundledReference${weight}`, ch), fallback: draw(`${weight} 40px ${fallback}`, ch) }]))
  }
  return result
})().then(result => { window.glyphPixels = JSON.stringify(result) }, error => { window.glyphPixels = JSON.stringify({ error: String(error) }) })
true"""


def test_every_glyph_of_the_bundled_font_is_drawn_with_it(window):
    """계산된 글꼴 이름이 아니라 실제로 그린 글리프를 본다: 번들 원본이 가진 글자는 부분 집합 밖이어도 대체 글꼴로 그리지 않는다."""
    wait_for(lambda: window.loaded)
    full = {weight: next(p for p in (WEB / 'assets').glob(f'{BUNDLED}-{stem}-*.woff2')) for weight, stem in WEIGHTS.items()}
    references = json.dumps({weight: QUrl.fromLocalFile(str(path)).toString() for weight, path in full.items()})
    js(window, GLYPH_PIXELS % (references, json.dumps(GLYPHS), json.dumps(GLYPHS)))
    wait_for(lambda: js(window, 'window.glyphPixels'))
    pixels = json.loads(js(window, 'window.glyphPixels'))
    assert 'error' not in pixels, pixels
    assert sorted(pixels) == sorted(map(str, WEIGHTS)) and all(''.join(glyphs) == GLYPHS for glyphs in pixels.values())

    def glyphs_where(differs):
        return {weight: ''.join(ch for ch, hashes in glyphs.items() if differs(hashes)) for weight, glyphs in pixels.items()}
    # 대체 글꼴과 번들 글꼴의 글리프가 달라야 이 비교가 대체를 잡는다.
    assert glyphs_where(lambda h: h['fallback'] == h['bundled']) == dict.fromkeys(pixels, '')
    assert glyphs_where(lambda h: h['app'] != h['bundled']) == dict.fromkeys(pixels, '')


CARD_FIT ="""JSON.stringify((() => {
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
    """부분 집합 밖 음절(뷀·궯·갂)은 전체 파일이 도착하면 같은 글꼴로 바뀌고, 그 전후로 카드·툴바 경계가 같다."""
    video = next(v for v in core.videos() if v.title == 'PYTHON 응용')
    core.rename_video(video.id, RARE_TITLE)
    window = open_window()
    wait_for(lambda: js(window, FIRST_ROW) > 0)
    # 카드 제목(본문 강조 역할 굵기)의 드문 음절 때문에 그 굵기의 전체 파일만 읽는다.
    wait_for(lambda: font_state(window)['rest'].get(type_roles()['body-strong']['weight']) == 'loaded')
    settle(window)
    frames = stop_recording(window)['frames']
    final = frames[-1]
    assert RARE_TITLE in final['text'] and not final['busy']
    for frame in frames:
        # 첫 프레임부터 글꼴이 바뀐 뒤까지 툴바·첫 줄 카드(드문 음절 제목 카드 포함)의 경계가 같다.
        assert frame['controls'] == final['controls'] and frame['cells'] == final['cells'], frame
    assert_bundled(window)


def native_fonts(window):
    """앱 글꼴, 트레이 메뉴, 공용 경고, 재생 화면(제목·조작 줄·하이라이트 패널) 글자의 실제 글꼴 이름."""
    def actual(widget):
        widget.ensurePolished()
        return QFontInfo(widget.font()).family()

    fonts = {'app': {QFontInfo(QApplication.instance().font()).family()}, 'tray': {actual(window.tray.icon.contextMenu())}}
    alert = QMessageBox(QMessageBox.Icon.Warning, '재생 실패', '파일을 열 수 없습니다.', parent=window)
    alert.show()
    fonts['alert'] = {actual(label) for label in alert.findChildren(QLabel) if label.text()}
    alert.close()

    window.play(window.core.videos()[0].id)
    playback = window.pages.currentWidget()
    assert playback is window.playback_page
    wait_for(lambda: playback.title_label.text())
    for name, part in (('title', playback.header), ('bar', playback.bottom_bar), ('highlights', playback.highlights_panel)):
        widgets = part.findChildren(QLabel) + part.findChildren(QAbstractButton)
        fonts[name] = {actual(widget) for widget in widgets if widget.text() and widget.property('playbackRole') != 'symbol'}
    return fonts


def register_system_font(*names):
    """offscreen에는 시스템 글꼴이 없어, 실제 글꼴 확인에 필요한 Windows 글꼴을 등록한다."""
    for name in names:
        assert QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name)) >= 0, name


def test_native_playback_tray_and_alerts_use_bundled_font(window):
    register_system_font('seguisym.ttf')
    fonts = native_fonts(window)
    assert all(fonts.values()) and fonts == dict.fromkeys(fonts, {BUNDLED}), fonts
    # 제목 굵기(구역 제목 역할)도 번들 글꼴의 해당 굵기 파일로 그린다.
    title = window.playback_page.title_label
    weight = int(type_roles()['section-title']['weight'])
    assert (QFontInfo(title.font()).family(), QFontInfo(title.font()).weight()) == (BUNDLED, weight)
    # 재생 기호는 컬러 이모지가 아닌 단색 기호 글꼴로 그린다.
    symbols = [button for button in window.playback_page.findChildren(QToolButton) if button.property('playbackRole') == 'symbol']
    for button in symbols:
        button.ensurePolished()
    assert symbols and {QFontInfo(button.font()).family() for button in symbols} == {'Segoe UI Symbol'}


@pytest.fixture
def unregistered_font(app, monkeypatch):
    """번들 글꼴을 아직 등록하지 않은 시작 상태(apply_theme만 적용). 끝나면 앱 글꼴과 스타일시트를 되돌린다."""
    font, sheet = app.font(), app.styleSheet()
    monkeypatch.setattr(theme, '_font_families', [FALLBACK_FONT])
    app.setFont(theme.playback_font())
    app.setStyleSheet(theme.playback_stylesheet())
    yield
    app.setFont(font)
    app.setStyleSheet(sheet)


@pytest.mark.skipif(sys.platform != 'win32', reason='대체 글꼴 맑은 고딕을 Windows 글꼴 폴더(%WINDIR%\\Fonts)에서 읽는다')
@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_failed_bundled_font_registration_falls_back_to_malgun_gothic_and_is_logged(
        unregistered_font, damage, tmp_path, app, monkeypatch, caplog):
    register_system_font('malgun.ttf', 'malgunbd.ttf')
    fonts = tmp_path / 'qt-fonts'
    fonts.mkdir()
    for name in theme.QT_FONT_FILES:
        (fonts / name).write_bytes((WEB / 'qt-fonts' / name).read_bytes())
    broken = fonts / theme.QT_FONT_FILES[-1]
    if damage == 'missing':
        broken.unlink()
    else:
        broken.write_bytes(b'not a font' * 100)
    monkeypatch.setattr(theme, 'QT_FONT_DIRECTORY', fonts)
    caplog.set_level(logging.WARNING, logger='my_video_manager.theme')

    for window in open_native_window(tmp_path, app, monkeypatch):
        # 앱 창이 정상으로 뜨고 웹 셸도 읽힌다.
        wait_for(lambda: window.loaded)
        assert window.isVisible()
        records = [r for r in caplog.records if r.name == 'my_video_manager.theme']
        assert len(records) == 1 and records[0].levelno == logging.WARNING and str(broken) in records[0].getMessage()
        fonts_used = native_fonts(window)
        assert all(fonts_used.values()) and fonts_used == dict.fromkeys(fonts_used, {FALLBACK_FONT}), fonts_used
