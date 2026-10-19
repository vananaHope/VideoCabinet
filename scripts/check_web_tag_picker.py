"""#195: 라이브러리 검색 조건의 태그 고르기 화면 검사.

--offscreen은 태그 0·몇 개·300개, 긴 이름, 칩이 많을 때의 1100×720 배치와 키보드·조합 이벤트를 본다.
--verify는 데스크톱 잠금 안의 실창에서 키보드만으로 검색 → 고르기 → 칩 빼기와 실제 한국어 IME를 확인한다.
DB는 임시 폴더에만 만든다.
"""
import argparse
from contextlib import closing
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter

parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--verify', action='store_true')
parser.add_argument('--videos', type=int, default=300)
parser.add_argument('--output', type=Path, default=Path('.local/screens-195'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library_views import default_options
from my_video_manager.tags import tag_name_key
from my_video_manager.ui import MainWindow

PANEL = '[aria-label="라이브러리 필터 패널"]'
SEARCH = '[aria-label="태그 검색"]'
LONG_NAME = '아주 긴 태그 이름으로 말줄임을 확인하는 LongTagNameWithoutSpaces'[:50]


class FakeMedia:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        destination.write_bytes(b'thumbnail')


app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-195-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
root = directory / '영상'
root.mkdir()
core.add_watched_folder(root)
with closing(sqlite3.connect(core.database)) as db, db:
    for i in range(args.videos):
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', f'영상 {i:04d}', 100 + i, 'mp4', 'thumbnails/none.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / f'{i}.mp4'), vid))
video_ids = [v.id for v in core.videos()]
metrics = {'videos': len(video_ids), 'checks': [], 'screenshots': [], 'panels': {}}

window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page, host = window.library_page, window.web_host


def wait(predicate, seconds=30):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def settle(ms=180):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def key(value, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy(), value, modifier)
    settle()


def view(**changes):
    result = json.loads(page.bridge.view(json.dumps({**default_options(), **changes})))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def capture(name):
    settle()
    path = args.output / f'{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def open_panel():
    if not js(f"!!document.querySelector('{PANEL}')"):
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='필터').click()")
        wait(lambda: js(f"!!document.querySelector('{PANEL}')"))
    js(f"document.querySelector('{PANEL} fieldset').scrollIntoView({{block:'end'}})")
    settle()


def close_panel():
    js(f"document.querySelector('{PANEL} [aria-label=\"필터 닫기\"]')?.click()")
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))


def layout(name):
    """패널과 태그 영역이 창 안에 있고 패널이 최대 높이(28rem)를 넘지 않는지 잰다."""
    state = json.loads(js(f"""JSON.stringify((() => {{
      const p = document.querySelector('{PANEL}').getBoundingClientRect()
      const list = document.querySelector('{PANEL} [role=listbox]')
      const chips = document.querySelector('{PANEL} [aria-label="고른 태그"]')
      return {{ top: p.top, bottom: p.bottom, left: p.left, right: p.right, height: p.height,
        innerWidth, innerHeight, rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
        options: list ? list.querySelectorAll('[role=option]').length : 0,
        listHeight: list?.clientHeight ?? 0, listScroll: list?.scrollHeight ?? 0,
        listOverflowX: list ? list.scrollWidth > list.clientWidth : false,
        panelOverflowX: document.querySelector('{PANEL}').scrollWidth > document.querySelector('{PANEL}').clientWidth,
        clipped: list ? [...list.querySelectorAll('[role=option]')].filter(o => o.lastElementChild.getBoundingClientRect().right > list.getBoundingClientRect().right + 0.5).length : 0,
        chipHeight: chips?.clientHeight ?? 0, chipScroll: chips?.scrollHeight ?? 0,
        names: list ? [...list.querySelectorAll('[role=option]')].slice(0, 15).map(o => o.title) : [] }} }})())"""))
    metrics['panels'][name] = state
    assert state['top'] >= 0 and state['left'] >= 0, state
    assert state['bottom'] <= state['innerHeight'] and state['right'] <= state['innerWidth'], state
    assert state['height'] <= 28 * state['rem'] + 1, state
    assert not state['listOverflowX'] and not state['panelOverflowX'] and not state['clipped'], state
    return state


def search(text):
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(text)});
      e.dispatchEvent(new Event('input', {{bubbles:true}})); e.focus(); }})()""")
    settle()


def option_names():
    return json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} [role=option]')].map(o => o.title))"))


def picker_chips():
    return json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} [aria-label=\"고른 태그\"] button')].map(b => b.title))"))


def applied_tag_chips():
    tag_labels = {t['name'] for t in page.tags}
    return [c['label'] for c in json.loads(page.bridge.view(json.dumps(page.options)))['chips'] if c['label'] in tag_labels]


def add_tags(count):
    """태그 i는 (count - i) // 4 + 1개 영상에 붙인다. 이름 검색용 태그와 긴 이름을 섞는다."""
    special = ['SF액션', '액션', '로맨틱 코미디', 'Straße', '한', LONG_NAME]
    names = special + [f'태그 {i:03d}' for i in range(count - len(special))]
    with closing(sqlite3.connect(core.database)) as db, db:
        for i, name in enumerate(names):
            tag = db.execute('INSERT INTO tags(name, name_key) VALUES (?, ?)', (name, tag_name_key(name))).lastrowid
            for vid in video_ids[:min(len(video_ids), (count - i) // 4 + 1) if name != '한' else 0]:
                db.execute('INSERT INTO video_tags(video_id, tag_id) VALUES (?, ?)', (vid, tag))
    page.refresh()
    settle()


def offscreen():
    open_panel()
    capture('tags-0')
    assert js(f"document.querySelector('{PANEL} fieldset').textContent.includes('등록한 태그가 없습니다.')")
    assert not js(f"[...document.querySelectorAll('{PANEL} button')].some(b => b.textContent.startsWith('모두 보기'))")
    layout('tags-0')
    close_panel()
    metrics['checks'].append('태그 0개: 안내 문구, 모두 보기 없음')

    for name in ('적은 태그', '두 번째'):
        core.add_video_tag(video_ids[0], name)
    page.refresh()
    open_panel()
    capture('tags-few')
    few = layout('tags-few')
    assert few['options'] == 2 and few['names'] == ['두 번째', '적은 태그'], few
    assert not js(f"[...document.querySelectorAll('{PANEL} button')].some(b => b.textContent.startsWith('모두 보기'))")
    close_panel()
    for tag in core.tags():
        core.delete_tag(tag.id)
    metrics['checks'].append('태그 몇 개: 같은 수는 이름순, 모두 보기 없음')

    add_tags(300)
    assert len(page.tags) == 300
    open_panel()
    capture('tags-300-frequent')
    frequent = layout('tags-300-frequent')
    expected = [t['name'] for t in sorted(page.tags, key=lambda t: (-t['videoCount'], tag_name_key(t['name'])))[:12]]
    assert frequent['options'] == 12 and frequent['names'] == expected, (frequent, expected)
    metrics['checks'].append('입력 없음: 영상 수 많은 순 12개(같으면 이름순)')

    js(f"[...document.querySelectorAll('{PANEL} button')].find(b => b.textContent.startsWith('모두 보기')).click()")
    settle()
    js(f"document.querySelector('{PANEL} fieldset').scrollIntoView({{block:'end'}})")
    capture('tags-300-all')
    every = layout('tags-300-all')
    assert every['options'] == 300 and every['listHeight'] <= 12 * every['rem'] + 1, every
    assert every['listScroll'] > every['listHeight'], every
    metrics['checks'].append('모두 보기 300개: 목록 자체 스크롤, 패널 최대 높이 유지')

    search('액션')
    capture('tags-300-search')
    assert option_names() == ['SF액션', '액션'], option_names()
    search('  STRASSE ')
    assert option_names() == ['Straße'], option_names()
    search('없는 이름 xyz')
    assert js(f"document.querySelector('{PANEL} fieldset').textContent.includes('들어간 태그가 없습니다')")
    capture('tags-300-no-match')
    metrics['checks'].append('중간 일치(액션→SF액션)·코어 정규화 key(STRASSE→Straße)·결과 없음 안내')

    # 검색(키보드) → 자주 쓴 태그(클릭) → 모두 보기(클릭)에서 하나씩 고른다.
    search('액션')
    key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Down)
    assert js(f"document.querySelector('{SEARCH}').getAttribute('aria-activedescendant')") == \
        js(f"document.querySelectorAll('{PANEL} [role=option]')[1].id")
    key(Qt.Key.Key_Return)
    by_name = {t['name']: t['id'] for t in page.tags}
    assert page.options['tags'] == [by_name['액션']], page.options
    assert js(f"document.querySelector('{SEARCH}').value") == ''
    js(f"document.querySelector('{PANEL} [role=listbox] [role=option]').click()")
    settle()
    js(f"[...document.querySelectorAll('{PANEL} button')].find(b => b.textContent.startsWith('모두 보기')).click()")
    settle()
    js(f"[...document.querySelectorAll('{PANEL} [role=option]')].find(o => o.title === 'Straße').click()")
    settle()
    # 코어가 저장할 때 태그 ID를 정렬한다.
    chosen = sorted([by_name['액션'], by_name[expected[0]], by_name['Straße']])
    assert page.options['tags'] == chosen, page.options
    assert page.visible_ids == core.library_view_ids({**default_options(), 'tags': chosen}, index=page.index)
    assert picker_chips() == applied_tag_chips() and set(picker_chips()) == {'액션', expected[0], 'Straße'}, (picker_chips(), applied_tag_chips())
    selected = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} [role=option][aria-selected=true]')].map(o => o.title))"))
    assert set(selected) == {'액션', expected[0], 'Straße'}, selected
    capture('tags-300-picked')
    metrics['checks'].append('검색·자주 쓴 태그·모두 보기에서 고른 결과가 같은 AND 필터와 적용 조건 칩에 맞음')

    # Esc는 활성 후보 → 검색어 → 모두 보기 순으로 먼저 지우고, 그다음에 패널을 닫는다.
    search('태그')
    key(Qt.Key.Key_Down)
    assert js(f"document.querySelector('{SEARCH}').getAttribute('aria-activedescendant')")
    key(Qt.Key.Key_Escape)
    state = js(f"JSON.stringify([document.activeElement?.getAttribute('aria-label'), document.querySelector('{SEARCH}')?.getAttribute('aria-activedescendant'), document.querySelector('{SEARCH}')?.value, !!document.querySelector('{PANEL}')])")
    assert json.loads(state)[1] is None and json.loads(state)[2] == '태그', state
    key(Qt.Key.Key_Escape)
    assert js(f"document.querySelector('{SEARCH}').value") == '' and js(f"!!document.querySelector('{PANEL}')")
    assert js(f"document.querySelectorAll('{PANEL} [role=option]').length") == 300
    key(Qt.Key.Key_Escape)
    assert js(f"document.querySelectorAll('{PANEL} [role=option]').length") == 12 and js(f"!!document.querySelector('{PANEL}')")
    key(Qt.Key.Key_Escape)
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))
    metrics['checks'].append('Esc: 활성 후보·검색어·모두 보기를 먼저 지우고 마지막에 패널 닫기')

    open_panel()
    search('SF')
    assert js(f"document.querySelector('{SEARCH}').value") == 'SF'
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      e.dispatchEvent(new CompositionEvent('compositionstart', {{bubbles:true, data:'액'}}));
      e.dispatchEvent(new KeyboardEvent('keydown', {{key:'ArrowDown', bubbles:true, cancelable:true, isComposing:true}}));
      e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', bubbles:true, cancelable:true, isComposing:true}}));
      e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape', bubbles:true, cancelable:true, isComposing:true}})); }})()""")
    settle()
    assert page.options['tags'] == chosen and js(f"!!document.querySelector('{PANEL}')"), (page.options['tags'], chosen, js(f"!!document.querySelector('{PANEL}')"))
    js(f"document.querySelector('{SEARCH}').dispatchEvent(new CompositionEvent('compositionend', {{bubbles:true, data:'SF'}}))")
    key(Qt.Key.Key_Return)
    # Enter는 활성 후보가 없으면 정확히 같은 이름만 고른다. 'SF'와 같은 이름은 없으므로 그대로다.
    assert page.options['tags'] == chosen
    metrics['checks'].append('조합 중 ↓·Enter·Esc 무시, 활성 후보 없는 Enter는 정확히 같은 이름만')

    js(f"document.querySelector('{PANEL} [aria-label=\"액션 빼기\"]').click()")
    settle()
    assert page.options['tags'] == [i for i in chosen if i != by_name['액션']] and picker_chips() == applied_tag_chips()
    metrics['checks'].append('칩 ×로 빼면 조건 칩도 함께 빠짐')
    close_panel()

    many = [t['id'] for t in page.tags if t['name'] == LONG_NAME] + [t['id'] for t in page.tags[:39]]
    view(tags=many)
    open_panel()
    js(f"document.querySelector('{PANEL}').scrollTop = 0")
    capture('tags-300-many-chips-top')
    js(f"document.querySelector('{PANEL} fieldset').scrollIntoView({{block:'end'}})")
    capture('tags-300-many-chips')
    crowded = layout('tags-300-many-chips')
    assert crowded['chipHeight'] <= 4 * crowded['rem'] + 1 and crowded['chipScroll'] > crowded['chipHeight'], crowded
    assert LONG_NAME in picker_chips()
    metrics['checks'].append('고른 태그 40개·긴 이름: 칩 줄은 4rem 안에서 스크롤, 긴 이름 말줄임')
    close_panel()
    capture('tags-300-applied-chips')


def windows_ime():
    """실창에서 키보드만으로 검색 → 고르기 → 칩 빼기, 실제 한국어 IME 조합 중 Enter 무시를 확인한다."""
    assert QTest.qWaitForWindowActive(window, 5000)
    add_tags(300)
    by_name = {t['name']: t['id'] for t in page.tags}
    host.view.setFocus()
    js("[...document.querySelectorAll('button')].find(b=>b.textContent==='필터').focus()")
    key(Qt.Key.Key_Return)
    wait(lambda: js(f"!!document.querySelector('{PANEL}')"))
    for _ in range(30):
        if js(f"document.activeElement === document.querySelector('{SEARCH}')"):
            break
        key(Qt.Key.Key_Tab)
    assert js(f"document.activeElement === document.querySelector('{SEARCH}')"), '태그 검색까지 Tab으로 가지 못함'
    QTest.keyClicks(host.view.focusProxy(), 'SF')
    settle()
    assert option_names() == ['SF액션'], option_names()
    key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Return)
    assert page.options['tags'] == [by_name['SF액션']], page.options
    key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert js("document.activeElement.getAttribute('aria-label')") == 'SF액션 빼기'
    key(Qt.Key.Key_Return)
    assert page.options['tags'] == []
    metrics['checks'].append('실창 키보드만: 필터 Enter → Tab 검색 → SF ↓ Enter 고르기 → Shift+Tab 칩 Enter 빼기')

    js(f"document.querySelector('{SEARCH}').focus()")
    user32 = ctypes.windll.user32
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
    user32.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    previous = user32.GetKeyboardLayout(0)
    korean = user32.LoadKeyboardLayoutW('00000412', 1)

    def press(code):
        user32.keybd_event(code, 0, 0, 0)
        user32.keybd_event(code, 0, 2, 0)
        settle(70)
    try:
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000)
        js(f"window.imeEvents = []; for (const n of ['compositionstart','compositionend']) document.querySelector('{SEARCH}').addEventListener(n, e => window.imeEvents.push(n))")
        for _ in range(2):
            for letter in 'GKS':  # 두벌식: 한
                press(ord(letter))
            value = js(f"document.querySelector('{SEARCH}').value")
            if value == '한':
                break
            search('')
            js(f"document.querySelector('{SEARCH}').focus()")
            press(0x15)  # VK_HANGUL
        metrics['ime'] = {'layout': hex(korean or 0), 'value': value, 'events': json.loads(js('JSON.stringify(window.imeEvents)'))}
        assert value == '한' and 'compositionstart' in metrics['ime']['events'], metrics['ime']
        press(0x0D)
        settle()
        assert page.options['tags'] == [], '조합 중 Enter가 태그를 고름'
        assert js(f"!!document.querySelector('{PANEL}')")
        press(0x0D)
        wait(lambda: page.options['tags'] == [by_name['한']])
        metrics['checks'].append('실제 Windows 한국어 IME: 조합 확정 Enter는 무시, 둘째 Enter로 같은 이름 태그 고름')
    finally:
        user32.ActivateKeyboardLayout(previous, 0)
    capture('verify-ime')


try:
    wait(lambda: js("!!document.getElementById('library-grid')"))
    settle()
    if args.offscreen:
        offscreen()
    else:
        windows_ime()
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    (args.output / ('metrics-verify.json' if args.verify else 'metrics.json')).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in metrics.items() if k != 'panels'}, ensure_ascii=False, indent=2))
    # 시작 검사가 돌고 있으면 완전 종료가 경고 창으로 막힌다.
    wait(lambda: not (window.worker and window.worker.isRunning()), 60)
    window.tray.quit()
