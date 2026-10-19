"""#195: 라이브러리 검색 조건의 태그 고르기 화면 검사.

--offscreen은 태그 0·몇 개·300개, 긴 이름·검색어, 칩이 많을 때의 1100×720 배치와 키보드·조합 이벤트,
combobox 속성, Unicode 이름의 자기 이름 검색, 검사 번들로 띄운 즉시 실행·뺄 태그를 본다.
또 화면의 검색 key(tagNameKey, 생성 표)가 코어 tag_name_key와 모든 코드 포인트와 몇 가지 문맥에서 같은지,
고른 직후·검색어를 바꾼 직후·칩을 뺀 직후의 입력이 이전 결과를 고르거나 뺀 칩을 되살리지 않는지 본다.
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
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
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
PROBE = '[data-tag-picker-probe]'
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


def combobox(scope=PANEL):
    """검색 입력의 combobox 속성이 실제로 보이는 목록·안내와 맞는지 잰다."""
    state = json.loads(js(f"""JSON.stringify((() => {{
      const e = document.querySelector('{scope} input[role=combobox]'), list = document.querySelector('{scope} [role=listbox]')
      const controls = e.getAttribute('aria-controls'), described = e.getAttribute('aria-describedby')
      return {{ expanded: e.getAttribute('aria-expanded'), controls, described, list: !!list,
        controlsList: !!list && !!controls && document.getElementById(controls) === list,
        status: described ? document.getElementById(described)?.textContent ?? null : null }} }})())"""))
    if state['list']:
        assert state['expanded'] == 'true' and state['controlsList'] and state['described'] is None, state
    else:
        assert state['expanded'] == 'false' and state['controls'] is None and state['status'], state
    return state


def keeps_escape(scope=PANEL):
    return js(f"document.querySelector('{scope} [data-keeps-escape]').dataset.keepsEscape")


def active_label():
    return js("document.activeElement?.getAttribute('aria-label') ?? document.activeElement?.textContent")


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
    assert combobox()['status'] == '등록한 태그가 없습니다.'
    close_panel()
    metrics['checks'].append('태그 0개: 안내 문구, 모두 보기 없음, combobox 닫힘·안내 연결')

    for name in ('적은 태그', '두 번째'):
        core.add_video_tag(video_ids[0], name)
    page.refresh()
    open_panel()
    capture('tags-few')
    few = layout('tags-few')
    assert few['options'] == 2 and few['names'] == ['두 번째', '적은 태그'], few
    combobox()
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
    assert '들어간 태그가 없습니다' in combobox()['status']
    capture('tags-300-no-match')
    metrics['checks'].append('중간 일치(액션→SF액션)·코어 정규화 key(STRASSE→Straße)·결과 없음 안내와 combobox 연결')
    for text in ('W' * 50, 'Ｗ' * 50, 'W' * 100, 'Ｗ' * 100):
        search(text)
        assert not option_names() and text in combobox()['status']
        state = layout(f'tags-300-long-query-{len(text)}-{ord(text[0]):x}')
        status = json.loads(js(f"JSON.stringify((p => [p.scrollWidth, p.clientWidth])(document.getElementById(document.querySelector('{SEARCH}').getAttribute('aria-describedby'))))"))
        assert status[0] <= status[1], (text[:3], status, state)
        if text == 'Ｗ' * 100:
            capture('tags-300-long-query')
    metrics['checks'].append('긴 검색어(W·전각 Ｗ 50·100자) 결과 없음 안내: 패널 폭 안에서 줄바꿈, 가로 넘침 없음')

    # 검색(키보드) → 자주 쓴 태그(클릭) → 모두 보기(클릭)에서 하나씩 고른다.
    search('액션')
    descendant = lambda: js(f"document.querySelector('{SEARCH}').getAttribute('aria-activedescendant')")
    option_id = lambda index: js(f"document.querySelectorAll('{PANEL} [role=option]')[{index}].id")
    key(Qt.Key.Key_Up)
    assert descendant() == option_id(1)
    key(Qt.Key.Key_Down)
    assert descendant() == option_id(0)
    key(Qt.Key.Key_Down)
    assert descendant() == option_id(1)
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

    # 포커스가 모두 보기 버튼에 있어도 Esc는 목록을 먼저 접는다.
    open_panel()
    js(f"[...document.querySelectorAll('{PANEL} button')].find(b => b.textContent.startsWith('모두 보기')).click()")
    settle()
    js(f"[...document.querySelectorAll('{PANEL} button')].find(b => b.textContent === '자주 쓴 태그만 보기').focus()")
    assert keeps_escape() == 'true'
    key(Qt.Key.Key_Escape)
    assert js(f"!!document.querySelector('{PANEL}')") and js(f"document.querySelectorAll('{PANEL} [role=option]').length") == 12
    assert active_label() == '모두 보기 (300개)' and keeps_escape() == 'false', active_label()
    key(Qt.Key.Key_Escape)
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))
    metrics['checks'].append('모두 보기 버튼 포커스의 Esc: 목록 접기 → 패널 닫기')

    # 검색어도 활성 후보도 없을 때의 조합 중 Esc는 isComposing만으로 패널을 지킨다.
    open_panel()
    search('')
    assert keeps_escape() == 'false'
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      e.dispatchEvent(new CompositionEvent('compositionstart', {{bubbles:true, data:''}}));
      e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape', bubbles:true, cancelable:true, isComposing:true}})); }})()""")
    settle()
    assert js(f"!!document.querySelector('{PANEL}')"), '빈 질의의 조합 중 Esc가 패널을 닫음'
    js(f"document.querySelector('{SEARCH}').dispatchEvent(new CompositionEvent('compositionend', {{bubbles:true, data:''}}))")
    settle()
    metrics['checks'].append('빈 질의의 조합 중 Esc: 패널 유지(isComposing 판정)')
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

    # Windows IME처럼 compositionend와 확정 Enter가 같은 작업에 오면 정확히 같은 이름('한')이어도 고르지 않는다.
    search('')
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      e.dispatchEvent(new CompositionEvent('compositionstart', {{bubbles:true, data:''}}));
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, '한');
      e.dispatchEvent(new InputEvent('input', {{bubbles:true, data:'한', inputType:'insertCompositionText', isComposing:true}})); }})()""")
    settle()
    assert option_names() == ['한'], option_names()
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      e.dispatchEvent(new CompositionEvent('compositionend', {{bubbles:true, data:'한'}}));
      e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', bubbles:true, cancelable:true}})); }})()""")
    settle()
    assert page.options['tags'] == chosen, '조합을 확정한 Enter가 같은 이름 태그를 고름'
    key(Qt.Key.Key_Return)
    chosen = sorted([*chosen, by_name['한']])
    assert page.options['tags'] == chosen and js(f"document.querySelector('{SEARCH}').value") == '', page.options
    metrics['checks'].append('compositionend와 같은 작업의 확정 Enter는 같은 이름도 무시, 다음 Enter로 고름')

    # 칩 ×는 검색어를 두고 포커스를 다음 칩으로, 마지막 칩이면 검색 입력으로 옮긴다. 칩 포커스의 Esc는 검색어부터 지운다.
    search('태그')
    names = picker_chips()
    js(f"document.querySelector('{PANEL} [aria-label=\"액션 빼기\"]').focus()")
    key(Qt.Key.Key_Return)
    chosen.remove(by_name['액션'])
    assert page.options['tags'] == chosen and picker_chips() == applied_tag_chips()
    assert active_label() == f"{names[names.index('액션') + 1]} 빼기", active_label()
    assert js(f"document.querySelector('{SEARCH}').value") == '태그' and '태그 000' in option_names()
    assert keeps_escape() == 'true'
    key(Qt.Key.Key_Escape)
    assert js(f"document.querySelector('{SEARCH}').value") == '' and js(f"!!document.querySelector('{PANEL}')")
    assert active_label().endswith(' 빼기'), active_label()
    last = picker_chips()[-1]
    js(f"document.querySelector('{PANEL} [aria-label=\"{last} 빼기\"]').focus()")
    key(Qt.Key.Key_Return)
    chosen.remove(by_name[last])
    assert page.options['tags'] == chosen and active_label() == '태그 검색', (page.options, active_label())
    assert js(f"document.querySelector('{PANEL} [aria-label=\"고른 태그\"]').getAttribute('role')") == 'group'
    metrics['checks'].append('칩 ×: 조건 칩도 빠짐, 검색어 유지, 포커스는 다음 칩 → 검색 입력, 칩 포커스 Esc는 검색어부터')
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
    immediate_and_exclude()
    key_equivalence()
    unicode_names()
    no_stale_picks()


def option_names_in(scope):
    return json.loads(js(f"JSON.stringify([...document.querySelectorAll('{scope} [role=option]')].map(o => o.title))"))


def immediate_and_exclude():
    """쓰는 화면이 아직 없는 즉시 실행·뺄 태그 경로를 검사 번들의 실제 TagPicker와 tagChoices로 확인한다."""
    subprocess.run(['npm.cmd', 'exec', 'vite', 'build', '--', '--config', 'checks/tag-picker.vite.config.ts'], cwd=ROOT / 'frontend', check=True)
    js((ROOT / '.local/tag-picker-fixture/probe.js').read_text(encoding='utf-8'))
    tags, ids = json.dumps(page.tags), [t['id'] for t in page.tags]
    by_name = {t['name']: t['id'] for t in page.tags}
    picks = lambda: json.loads(js('JSON.stringify(window.tagPickerPicks)'))

    def choices(key, show_all, exclude):
        return [t['id'] for t in json.loads(js(
            f"JSON.stringify(window.tagChoicesProbe({tags}, {json.dumps(key)}, {json.dumps(show_all)}, {json.dumps(exclude)}))"))]
    assert choices('', False, ids[:2]) == ids[2:14]
    assert choices('', True, ids[:2]) == ids[2:]
    assert choices('', False, ids) == [] and choices('', True, ids) == [] and choices(tag_name_key('태그'), False, ids) == []
    assert choices(tag_name_key('액션'), False, [by_name['SF액션']]) == [by_name['액션']]
    metrics['checks'].append('tagChoices: 뺄 태그를 먼저 빼고 12개·전체·검색, 전부 빼면 빈 목록')

    js(f"window.tagPickerProbe({json.dumps(page.tags[:13])})")
    settle()
    assert len(option_names_in(PROBE)) == 12 and not js(f"document.querySelector('{PROBE} [role=listbox]').hasAttribute('aria-multiselectable')")
    combobox(PROBE)
    js(f"document.querySelector('{PROBE} input[role=combobox]').focus()")
    key(Qt.Key.Key_Down)
    assert js(f"document.querySelector('{PROBE} [role=option][aria-selected=true]')?.title") == page.tags[0]['name']
    key(Qt.Key.Key_Return)
    assert picks() == ids[:1]
    assert option_names_in(PROBE) == [t['name'] for t in page.tags[1:13]]
    js(f"document.querySelector('{PROBE} [role=option]').click()")
    settle()
    assert picks() == ids[:2] and len(option_names_in(PROBE)) == 11, (picks(), option_names_in(PROBE))
    js(f"window.tagPickerProbe({json.dumps(page.tags[:2])}, {json.dumps(ids[:2])})")
    settle()
    assert js(f"document.querySelector('{PROBE}').textContent.includes('붙일 태그가 없습니다.')")
    assert combobox(PROBE)['status'] == '붙일 태그가 없습니다.'
    js("window.tagPickerProbe(null)")
    metrics['checks'].append('즉시 실행: ↓ Enter·클릭마다 onPick, 고른 태그는 뺄 태그로 빠짐, 전부 빼면 안내와 combobox 닫힘')


# 검토에서 웹 정규화가 코어와 달랐던 입력과 일반 공백·호환 문자. (질의, 그 질의로 찾아야 하는 태그 이름)
UNICODE_NAMES = ['ＳＦＡｃｔｉｏｎ', 'ﬃ', 'Straße', 'ΟΣ', 'ışık', 'IŞIK', 'İ', 'Ꭰ', 'A\u3000B', 'A-Ｂ!', '한\u200b글']
UNICODE_QUERIES = [('ＳＦＡｃｔｉｏｎ', 'ＳＦＡｃｔｉｏｎ'), ('SFAction', 'ＳＦＡｃｔｉｏｎ'), ('ﬃ', 'ﬃ'), ('ffi', 'ﬃ'),
                   ('Straße', 'Straße'), ('STRAẞE', 'Straße'), ('STRASSE', 'Straße'), ('ΟΣ', 'ΟΣ'), ('ος', 'ΟΣ'), ('οσ', 'ΟΣ'),
                   ('ışık', 'ışık'), ('IŞIK', 'IŞIK'), ('İ', 'İ'), ('Ꭰ', 'Ꭰ'), ('ꭰ', 'Ꭰ'),
                   ('  A\u3000B  ', 'A\u3000B'), ('a\t b', 'A\u3000B'), ('A-Ｂ!', 'A-Ｂ!'), ('한\u200b글', '한\u200b글')]


def unicode_names():
    """자기 이름(또는 코어가 같은 key로 보는 표기)을 치면 그 태그가 후보에 나오고 Enter로 골라진다."""
    for tag in core.tags():
        core.delete_tag(tag.id)
    created = {name: core.create_tag(name) for name in UNICODE_NAMES}
    view(tags=[])
    page.refresh()
    open_panel()
    usage = core.tag_usage()
    picked, results = set(), []
    for text, own in UNICODE_QUERIES:
        search(text)
        names = option_names()
        expected = [u.tag.name for u in usage if tag_name_key(text) in u.key]
        results.append({'query': text, 'options': names})
        assert created[own].name in names and names == expected, (text, names, expected)
        key(Qt.Key.Key_Return)
        picked ^= {created[own].id}
        assert page.options['tags'] == sorted(picked), (text, page.options['tags'], sorted(picked))
    metrics['unicode'] = results
    close_panel()
    metrics['checks'].append('Unicode 이름(전각·합자·독일어 에스체트·그리스어 시그마·터키어 i·체로키·공백·서식 문자): 코어 key로 자기 이름 검색·Enter')


# 문맥: 단독, 앞 글자, 뒤 결합 문자(정규화 재배열·조합), 그리스어 단어 끝, 한글 음절 뒤, 공백 사이
KEY_CONTEXTS = [('', ''), ('A', ''), ('', '\u0301'), ('ΑΣ', ''), ('Σ', ' '), ('가', ''), (' ', ' x')]


def key_equivalence():
    """검사 번들의 tagNameKey와 코어 tag_name_key를 전체 코드 포인트(서로게이트 포함)와 문맥에서 비교한다."""
    started = perf_counter()
    samples = [text for pair in UNICODE_QUERIES for text in pair] + [name for name in UNICODE_NAMES]
    mismatches, count = [], 0

    def compare(texts):
        nonlocal count
        got = json.loads(js(f"JSON.stringify({json.dumps(texts)}.map(window.tagNameKeyProbe))"))
        count += len(texts)
        mismatches.extend({'input': text, 'core': tag_name_key(text), 'web': web}
                          for text, web in zip(texts, got) if web != tag_name_key(text))
    compare(samples)
    for prefix, suffix in KEY_CONTEXTS:
        for start in range(0, 0x110000, 0x8000):
            # 코드 포인트는 번들 안에서 만들고 key만 돌려받는다. JSON.stringify는 홀로 선 서로게이트도 이스케이프한다.
            got = json.loads(js(f"""JSON.stringify(Array.from({{length: {min(0x8000, 0x110000 - start)}}},
              (_, i) => window.tagNameKeyProbe({json.dumps(prefix)} + String.fromCodePoint({start} + i) + {json.dumps(suffix)})))"""))
            for offset, web in enumerate(got):
                text = prefix + chr(start + offset) + suffix
                if web != tag_name_key(text):
                    mismatches.append({'input': text, 'core': tag_name_key(text), 'web': web})
            count += len(got)
    metrics['key_equivalence'] = {'strings': count, 'contexts': KEY_CONTEXTS, 'mismatches': mismatches[:50],
                                  'mismatch_count': len(mismatches), 'seconds': round(perf_counter() - started, 1)}
    assert not mismatches, mismatches[:10]
    metrics['checks'].append(f'검색 key 동등성: 코어 tag_name_key와 화면 tagNameKey가 {count}개 문자열(전체 코드 포인트 × 문맥 {len(KEY_CONTEXTS)}가지와 검토 입력)에서 같음')


def no_stale_picks():
    """고른 직후·검색어를 바꾼 직후·칩을 뺀 직후의 입력이 지금 화면의 결과에만 적용되는지 본다."""
    tags = {t['name']: t['id'] for t in page.tags}
    open_panel()

    def now(code):
        js(f"(() => {{ const e = document.querySelector('{SEARCH}'); {code} }})()")

    def typed(text):
        return f"""e.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(text)});
          e.dispatchEvent(new Event('input', {{bubbles:true}}));"""
    enter = "e.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true, cancelable:true}));"

    def expect(changed, label):
        settle()
        assert set(page.options['tags']) == changed, (label, page.options['tags'], sorted(changed))
        return changed

    chosen = set(page.options['tags'])
    search('')
    # 첫 글자 직후 기다리지 않고 ↓·Enter: 그 글자의 검색 결과 첫 후보를 고른다.
    now(typed('ı'))
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
    chosen = expect(chosen ^ {tags['ışık']}, '첫 글자 직후 ↓ Enter')
    # 첫 글자 입력과 같은 작업에서 첫 후보 클릭.
    now(typed('İ') + f" document.querySelector('{PANEL} [role=option]').click();")
    chosen = expect(chosen ^ {tags['İ']}, '첫 글자 직후 클릭')
    # 다른 검색어로 바꾼 같은 작업의 Enter는 새 검색어와 같은 이름만 고른다.
    search('Straße')
    now(typed('ΟΣ') + enter)
    chosen = expect(chosen ^ {tags['ΟΣ']}, '검색어를 바꾼 직후 Enter')
    # 칩을 뺀 같은 작업의 Enter가 뺀 칩을 되살리지 않는다.
    search('IŞIK')
    removed = next(name for name in ('Straße', 'A-Ｂ!', '한글') if tags[name] in chosen)
    now(f"document.querySelector('{PANEL} [aria-label={json.dumps(removed + ' 빼기')}]').click(); " + enter)
    chosen = expect(chosen ^ {tags[removed], tags['IŞIK']}, '칩을 뺀 직후 Enter')
    # 칩을 뺀 같은 작업에서 패널을 닫아도 그 뒤에 선택이 바뀌지 않는다.
    removed = next(name for name in ('A-Ｂ!', '한글', 'Straße') if tags[name] in chosen)
    now(f"document.querySelector('{PANEL} [aria-label={json.dumps(removed + ' 빼기')}]').click(); "
        f"document.querySelector('{PANEL} [aria-label=\"필터 닫기\"]').click();")
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))
    settle(400)
    expect(chosen ^ {tags[removed]}, '칩을 뺀 직후 패널 닫기')
    metrics['checks'].append('직후 입력: 첫 글자 ↓·Enter·클릭, 검색어 바꾼 직후 Enter, 칩 뺀 직후 Enter·패널 닫기에서 이전 결과·뺀 칩이 되살아나지 않음')


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
    assert page.options['tags'] == [] and js(f"document.activeElement === document.querySelector('{SEARCH}')")
    metrics['checks'].append('실창 키보드만: 필터 Enter → Tab 검색 → SF ↓ Enter 고르기 → Shift+Tab 칩 Enter 빼기 → 포커스 검색 입력')

    user32 = ctypes.windll.user32
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
    user32.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    previous = user32.GetKeyboardLayout(0)
    korean = user32.LoadKeyboardLayoutW('00000412', 1)

    def press(code):
        user32.keybd_event(code, 0, 0, 0)
        settle(30)
        user32.keybd_event(code, 0, 2, 0)
        settle(120)
    try:
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000)
        # 다른 프로세스가 전경이면 Windows가 전경 전환을 막으므로 그 입력 큐에 잠시 붙는다.
        hwnd = int(window.winId())
        if user32.GetForegroundWindow() != hwnd:
            other = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            mine = ctypes.windll.kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(other, mine, True)
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                user32.AttachThreadInput(other, mine, False)
        wait(lambda: user32.GetForegroundWindow() == hwnd, 5)
        host.view.setFocus()
        search('')
        metrics['ime_focus'] = {'foreground': user32.GetForegroundWindow() == int(window.winId()),
                                'active': js("document.activeElement?.getAttribute('aria-label')")}
        js(f"""window.imeEvents = []; for (const n of ['compositionstart','compositionupdate','compositionend','keydown','keyup','beforeinput','input']) document
          .addEventListener(n, e => window.imeEvents.push(`${{n}}:${{e.key ?? e.data ?? ''}}:${{e.keyCode ?? ''}}:${{e.isComposing}}:${{e.target?.getAttribute?.('aria-label')}}`), true)""")
        imm32 = ctypes.windll.imm32
        imm32.ImmGetContext.restype = ctypes.c_void_p
        imm32.ImmGetContext.argtypes = [ctypes.c_void_p]
        imm32.ImmSetConversionStatus.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        imm32.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        focused = user32.GetFocus() if hasattr(user32, 'GetFocus') else hwnd
        for target in {hwnd, focused}:
            context = imm32.ImmGetContext(target)
            if context:
                imm32.ImmSetConversionStatus(context, 1, 0)  # IME_CMODE_HANGUL: 이전 실행의 한/영 상태와 무관하게
                imm32.ImmReleaseContext(target, context)
        settle()
        for letter in 'GKS':  # 두벌식: 한
            press(ord(letter))
        value = js(f"document.querySelector('{SEARCH}').value")
        metrics['ime'] = {'layout': hex(korean or 0), 'value': value, 'events': json.loads(js('JSON.stringify(window.imeEvents)'))}
        assert value == '한' and any(e.startswith('compositionstart') for e in metrics['ime']['events']), metrics['ime']
        press(0x0D)
        settle()
        # 조합한 '한'은 정확히 같은 이름의 태그가 있으므로 확정 Enter를 무시하지 않으면 여기서 골라진다.
        assert page.options['tags'] == [], '조합을 확정한 Enter가 같은 이름 태그를 고름'
        assert option_names() == ['한'], option_names()
        assert js(f"!!document.querySelector('{PANEL}')")
        press(0x0D)
        try:
            wait(lambda: page.options['tags'] == [by_name['한']], 5)
        finally:
            metrics['ime']['after'] = {'events': json.loads(js('JSON.stringify(window.imeEvents)')), 'tags': page.options['tags'],
                                       'value': js(f"document.querySelector('{SEARCH}').value"),
                                       'options': option_names()}
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
    sys.stdout.reconfigure(errors='backslashreplace')
    print(json.dumps({k: v for k, v in metrics.items() if k not in ('panels', 'unicode')}, ensure_ascii=False, indent=2))
    # 시작 검사가 돌고 있으면 완전 종료가 경고 창으로 막힌다.
    wait(lambda: not (window.worker and window.worker.isRunning()), 60)
    window.tray.quit()
