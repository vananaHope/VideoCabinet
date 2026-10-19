"""#191: 태그 편집 대화상자의 등록 태그 목록 화면 검사.

--offscreen은 등록 태그 0개·모두 붙음·몇 개·300개·긴 이름의 1100×720 배치와,
검색(중간 일치)·↓/↑·Enter·클릭으로 붙이기, 없는 이름 Enter와 '새 태그로 붙이기', 조합 중 Enter 무시,
Esc가 활성 후보 → 검색어를 먼저 지우고 대화상자는 그다음에 닫히는지를 본다.
--verify는 데스크톱 잠금 안의 실창에서 키보드만으로 고르기·새 태그 만들기, Esc 순서, 실제 한국어 IME 조합 중 Enter 무시를 본다.
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
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--verify', action='store_true')
parser.add_argument('--output', type=Path, default=Path('.local/screens-191'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.tags import tag_name_key
from my_video_manager.ui import MainWindow
from my_video_manager.web_dialogs_entries import TagEditor

FRAME = '[data-dialog-frame]'
SEARCH = f'{FRAME} [aria-label="태그 검색"]'
PICKER = f'{FRAME} [data-keeps-escape]'
ATTACHED = f'{FRAME} [aria-label="붙은 태그"]'
LONG_NAME = ('아주 긴 태그 이름으로 말줄임을 확인하는 LongTagNameWithoutSpaces' * 2)[:50]


class FakeMedia:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        destination.write_bytes(b'thumbnail')


app = QApplication([])
if args.offscreen:
    for filename in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / filename))
temporary = tempfile.TemporaryDirectory(prefix='mvm-191-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
root = directory / '영상'
root.mkdir()
core.add_watched_folder(root)
with closing(sqlite3.connect(core.database)) as db, db:
    for i in range(120):
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', f'영상 {i:04d}', 100 + i, 'mp4', 'thumbnails/none.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / f'{i}.mp4'), vid))
video_ids = [v.id for v in core.videos()]
target = video_ids[-1]  # 다른 태그가 붙지 않는 영상
metrics = {'checks': [], 'screenshots': [], 'layouts': {}}

window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
host, dialogs = window.web_host, window.web_host.dialogs


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


def capture(name):
    settle()
    path = args.output / f'{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def reset_tags():
    for tag in core.tags():
        core.delete_tag(tag.id)


def add_tags(names, counts):
    """names[i]를 counts[i]개 영상(대상 영상 제외)에 붙여 등록한다."""
    with closing(sqlite3.connect(core.database)) as db, db:
        for name, count in zip(names, counts):
            tag = db.execute('INSERT INTO tags(name, name_key) VALUES (?, ?)', (name, tag_name_key(name))).lastrowid
            for vid in video_ids[:count]:
                db.execute('INSERT INTO video_tags(video_id, tag_id) VALUES (?, ?)', (vid, tag))


def attached():
    return [tag.name for tag in core.video_tags(target)]


def option_names():
    return json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PICKER} [role=option]')].map(o => o.title))"))


def search(text):
    js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(text)});
      e.dispatchEvent(new Event('input', {{bubbles:true}})); e.focus(); }})()""")
    settle()


def query():
    return js(f"document.querySelector('{SEARCH}').value")


def picker_text():
    return js(f"document.querySelector('{PICKER}').textContent")


def create_button():
    return f"[...document.querySelectorAll('{PICKER} button')].find(b => b.textContent === '새 태그로 붙이기')"


def layout(name):
    """대화상자가 창 안에 있고 목록이 자체 스크롤되며 가로로 넘치거나 잘리지 않는지 잰다."""
    state = json.loads(js(f"""JSON.stringify((() => {{
      const frame = document.querySelector('{FRAME}'), f = frame.getBoundingClientRect()
      const list = document.querySelector('{PICKER} [role=listbox]'), mine = document.querySelector('{ATTACHED}')
      const footer = frame.querySelector('footer').getBoundingClientRect()
      return {{ top: f.top, bottom: f.bottom, left: f.left, right: f.right, innerWidth, innerHeight,
        rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
        frameScroll: frame.scrollHeight > frame.clientHeight + 1, frameOverflowX: frame.scrollWidth > frame.clientWidth,
        footerBottom: footer.bottom,
        options: list ? list.querySelectorAll('[role=option]').length : 0,
        listHeight: list?.clientHeight ?? 0, listScroll: list?.scrollHeight ?? 0,
        listOverflowX: list ? list.scrollWidth > list.clientWidth : false,
        clipped: list ? [...list.querySelectorAll('[role=option]')].filter(o => o.lastElementChild.getBoundingClientRect().right > list.getBoundingClientRect().right + 0.5).length : 0,
        attachedHeight: mine.clientHeight, attachedScroll: mine.scrollHeight, attachedOverflowX: mine.scrollWidth > mine.clientWidth,
        names: list ? [...list.querySelectorAll('[role=option]')].slice(0, 15).map(o => o.title) : [] }} }})())"""))
    metrics['layouts'][name] = state
    assert state['top'] >= 0 and state['left'] >= 0, state
    assert state['bottom'] <= state['innerHeight'] and state['right'] <= state['innerWidth'], state
    assert state['footerBottom'] <= state['bottom'] + 0.5, state
    assert not state['frameScroll'] and not state['frameOverflowX'], state
    assert not state['listOverflowX'] and not state['clipped'] and not state['attachedOverflowX'], state
    assert state['listHeight'] <= 12 * state['rem'] + 1, state
    return state


def tag_dialog(scenario):
    """태그 편집 대화상자를 열고 scenario를 실행한다. 대화상자는 끝에서 닫는다."""
    failures = []

    def run():
        try:
            wait(lambda: js(f"!!document.querySelector('{SEARCH}')"))
            settle()
            scenario()
        except BaseException as error:
            failures.append(error)
        finally:
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(0, run)
    TagEditor(core, video_id=target, parent=window).exec()
    settle()
    if failures:
        raise failures[0]


def offscreen():
    def none():
        capture('dialog-tags-0')
        layout('tags-0')
        assert '등록한 태그가 없습니다.' in picker_text()
        assert js(f"{create_button()}.disabled")
        # 셸이 시작 때 예약한 페이지 초점 요청이 늦게 올 수 있어 잠시 기다린다.
        wait(lambda: js(f"document.activeElement === document.querySelector('{SEARCH}')"), 5)
    tag_dialog(none)
    metrics['checks'].append('등록 태그 0개: 안내, 새 태그 버튼 비활성, 처음 초점은 검색 입력')

    add_tags(['적은 태그', '두 번째', '세 번째'], [3, 3, 1])
    def few():
        capture('dialog-tags-few')
        state = layout('tags-few')
        assert state['names'] == ['두 번째', '적은 태그', '세 번째'], state
        assert not js(f"[...document.querySelectorAll('{PICKER} button')].some(b => b.textContent.startsWith('모두 보기'))")
    tag_dialog(few)
    metrics['checks'].append('몇 개: 붙은 영상 수 많은 순(같으면 이름순), 입력 없이 전체 행 목록, 모두 보기 없음')

    for tag in core.tags():
        core.add_video_tag(target, tag.name)
    def all_attached():
        capture('dialog-tags-all-attached')
        layout('tags-all-attached')
        assert '모두 붙어 있습니다' in picker_text() and not option_names()
    tag_dialog(all_attached)
    metrics['checks'].append('모두 붙음: 목록 대신 안내')

    reset_tags()
    special = ['SF액션', '액션', '로맨틱 코미디', '한', LONG_NAME]
    names = special + [f'태그 {i:03d}' for i in range(300 - len(special))]
    add_tags(names, [(300 - i) // 4 + 1 if name != '한' else 0 for i, name in enumerate(names)])
    for name in [LONG_NAME, *names[20:60]]:
        core.add_video_tag(target, name)
    def many():
        capture('dialog-tags-300')
        state = layout('tags-300')
        assert state['options'] == 300 - 41 and state['listScroll'] > state['listHeight'], state
        assert state['attachedScroll'] > state['attachedHeight'] >= 3 * state['rem'], state
        assert LONG_NAME not in option_names() and names[20] not in option_names()
        search('액션')
        capture('dialog-tags-300-search')
        assert option_names() == ['SF액션', '액션'], option_names()
        search('없는 이름')
        capture('dialog-tags-300-no-match')
        assert '들어간 태그가 없습니다' in picker_text() and not js(f"{create_button()}.disabled")
        search('')
        assert len(option_names()) == 300 - 41
        js(f"document.querySelector('{PICKER} [role=listbox]').scrollTop = 99999")
        capture('dialog-tags-300-scrolled')
    tag_dialog(many)
    metrics['checks'].append('300개·붙은 41개·긴 이름: 대화상자 1100×720 안, 고를 목록·붙은 목록 각각 자체 스크롤, 붙은 태그는 목록에 없음, 중간 일치 검색과 지우면 전체 복귀')

    def keyboard():
        # ↓ 두 번 → Enter: 검색 결과 두 번째를 붙이고 검색어를 지운다.
        search('액션')
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Down)
        assert js(f"document.querySelector('{PICKER} [data-active]').title") == '액션'
        key(Qt.Key.Key_Return)
        wait(lambda: '액션' in attached())
        wait(lambda: '액션' not in option_names())
        assert query() == '' and 'SF액션' not in attached()
        # 클릭으로 붙인다.
        js(f"[...document.querySelectorAll('{PICKER} [role=option]')].find(o => o.title === '로맨틱 코미디').click()")
        wait(lambda: '로맨틱 코미디' in attached())
        wait(lambda: '로맨틱 코미디' not in option_names())
        # 이름이 정확히 같으면(대소문자 무시) 새로 만들지 않고 그 태그를 붙인다.
        count = len(core.tags())
        search('sf액션')
        assert js(f"{create_button()}.disabled")
        key(Qt.Key.Key_Return)
        wait(lambda: 'SF액션' in attached())
        assert len(core.tags()) == count
        # 목록에 없는 이름은 Enter로 새 태그를 만든다.
        search('새로 만든 태그')
        key(Qt.Key.Key_Return)
        wait(lambda: '새로 만든 태그' in attached())
        assert len(core.tags()) == count + 1 and query() == ''
        # 버튼으로도 만든다. 끝나면 초점이 검색 입력으로 돌아온다.
        search('버튼으로 만든 태그')
        js(f"{create_button()}.click()")
        wait(lambda: '버튼으로 만든 태그' in attached())
        wait(lambda: query() == '')
        assert js(f"document.activeElement === document.querySelector('{SEARCH}')")
        metrics['checks'].append('↓↓ Enter·클릭·같은 이름 Enter로 붙임, 없는 이름 Enter·버튼으로 새 태그, 붙인 태그는 목록에서 사라짐')

        # 조합 중 Enter와 조합을 확정한 직후 같은 틱의 Enter는 무시한다.
        before = attached()
        search('조합 태그')
        js(f"""(() => {{ const e = document.querySelector('{SEARCH}');
          e.dispatchEvent(new CompositionEvent('compositionstart', {{bubbles:true, data:'조'}}));
          e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', keyCode:229, bubbles:true, cancelable:true, isComposing:true}}));
          e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape', bubbles:true, cancelable:true, isComposing:true}}));
          e.dispatchEvent(new CompositionEvent('compositionend', {{bubbles:true, data:'조합 태그'}}));
          e.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', keyCode:13, bubbles:true, cancelable:true}})); }})()""")
        settle(400)
        assert attached() == before and query() == '조합 태그' and dialogs.active
        key(Qt.Key.Key_Return)
        wait(lambda: '조합 태그' in attached())
        metrics['checks'].append('조합 중 Enter·Esc와 확정 직후 Enter 무시, 다음 Enter로 새 태그')

        # Esc는 활성 후보 → 검색어 순으로 지우고, 지울 것이 없을 때만 대화상자를 닫는다.
        search('태그 0')
        key(Qt.Key.Key_Down)
        assert js(f"!!document.querySelector('{PICKER} [data-active]')")
        key(Qt.Key.Key_Escape)
        assert dialogs.active and query() == '태그 0' and not js(f"!!document.querySelector('{PICKER} [data-active]')")
        key(Qt.Key.Key_Escape)
        assert dialogs.active and query() == ''
        capture('dialog-tags-after-keyboard')
        key(Qt.Key.Key_Escape)
        wait(lambda: not dialogs.active)
        metrics['checks'].append('Esc: 활성 후보 → 검색어 → 대화상자 닫기')
    tag_dialog(keyboard)

    # 붙은 태그 목록과 떼기는 그대로다.
    def detach():
        js(f"document.querySelector('{ATTACHED}').focus()")
        key(Qt.Key.Key_Down)
        selected = js(f"document.querySelector('{ATTACHED} [role=option][aria-selected=true]').textContent")
        js("[...document.querySelectorAll('[role=dialog] button')].find(b => b.textContent === '선택한 태그 떼기').click()")
        wait(lambda: selected not in attached())
        wait(lambda: selected in option_names())
    tag_dialog(detach)
    metrics['checks'].append('붙은 태그 떼기: 떼면 고를 목록에 다시 나타남')

    # 저장이 실패하면 검색어·좁힌 후보·붙은 목록이 그대로이고, 다시 시도하면 붙는다.
    add_tags(['재시도 태그', '느린 저장 태그'], [2, 1])
    add_video_tag = core.add_video_tag
    failing = []

    def flaky_add(video_id, name):
        if failing:
            raise sqlite3.OperationalError('저장 실패 주입')
        return add_video_tag(video_id, name)
    core.add_video_tag = flaky_add

    def save_failure():
        failing.append(True)
        search('재시도')
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Return)
        wait(lambda: js("document.body.innerText.includes('저장 실패 주입')"))
        settle()
        assert query() == '재시도' and option_names() == ['재시도 태그'] and '재시도 태그' not in attached(), (query(), option_names())
        js(f"[...document.querySelectorAll('{PICKER} [role=option]')].find(o => o.title === '재시도 태그').click()")
        settle(400)
        assert query() == '재시도' and option_names() == ['재시도 태그'] and '재시도 태그' not in attached()
        search('실패할 새 태그')
        key(Qt.Key.Key_Return)
        settle(400)
        assert query() == '실패할 새 태그' and '실패할 새 태그' not in [t.name for t in core.tags()]
        capture('dialog-tags-save-failure')
        failing.clear()
        search('재시도')
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Return)
        wait(lambda: '재시도 태그' in attached())
        wait(lambda: query() == '')
        # 저장 응답을 기다리는 동안 더 입력한 검색어는 성공 응답이 지우지 않는다.
        search('느린')
        js(f"""(() => {{ [...document.querySelectorAll('{PICKER} [role=option]')].find(o => o.title === '느린 저장 태그').click()
          const e = document.querySelector('{SEARCH}')
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, '저장 중 입력')
          e.dispatchEvent(new Event('input', {{bubbles:true}})) }})()""")
        wait(lambda: '느린 저장 태그' in attached())
        settle(400)
        assert query() == '저장 중 입력', query()
    try:
        tag_dialog(save_failure)
    finally:
        core.add_video_tag = add_video_tag
    metrics['checks'].append('저장 실패: 기존 태그 Enter·클릭과 새 태그 Enter 모두 검색어·후보·붙은 목록 유지, 재시도 성공, 저장 중 입력한 검색어는 성공 응답이 지우지 않음')


def windows_ime():
    """실창에서 키보드만으로 고르기·새 태그 만들기, Esc 순서, 실제 한국어 IME 조합을 확정한 Enter 무시를 확인한다."""
    assert QTest.qWaitForWindowActive(window, 5000)
    add_tags(['SF액션', '액션', '한'], [5, 3, 0])

    def scenario():
        host.view.setFocus()
        wait(lambda: js(f"document.activeElement === document.querySelector('{SEARCH}')"))
        QTest.keyClicks(host.view.focusProxy(), 'SF')
        settle()
        assert option_names() == ['SF액션'], option_names()
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Return)
        wait(lambda: 'SF액션' in attached())
        assert query() == ''
        QTest.keyClicks(host.view.focusProxy(), 'newtag')
        key(Qt.Key.Key_Return)
        wait(lambda: 'newtag' in attached())
        QTest.keyClicks(host.view.focusProxy(), 'abc')
        settle()
        key(Qt.Key.Key_Escape)
        assert dialogs.active and query() == ''
        metrics['checks'].append('실창 키보드만: SF ↓ Enter로 붙임, 없는 이름 Enter로 새 태그, Esc는 검색어만 지움')

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
            js(f"document.querySelector('{SEARCH}').focus()")
            js(f"""window.imeEvents = []; for (const n of ['compositionstart','compositionend','keydown']) document
              .addEventListener(n, e => window.imeEvents.push(`${{n}}:${{e.key ?? e.data ?? ''}}:${{e.keyCode ?? ''}}:${{e.isComposing}}`), true)""")
            imm32 = ctypes.windll.imm32
            imm32.ImmGetContext.restype = ctypes.c_void_p
            imm32.ImmGetContext.argtypes = [ctypes.c_void_p]
            imm32.ImmSetConversionStatus.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
            imm32.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            for handle in {hwnd, user32.GetFocus()}:
                context = imm32.ImmGetContext(handle)
                if context:
                    imm32.ImmSetConversionStatus(context, 1, 0)  # IME_CMODE_HANGUL
                    imm32.ImmReleaseContext(handle, context)
            settle()
            for letter in 'GKS':  # 두벌식: 한
                press(ord(letter))
            value = query()
            metrics['ime'] = {'layout': hex(korean or 0), 'value': value, 'events': json.loads(js('JSON.stringify(window.imeEvents)'))}
            assert value == '한' and any(e.startswith('compositionstart') for e in metrics['ime']['events']), metrics['ime']
            press(0x0D)
            settle()
            # 조합한 '한'은 같은 이름의 등록 태그가 있으므로 확정 Enter를 무시하지 않으면 여기서 붙는다.
            assert '한' not in attached(), '조합을 확정한 Enter가 태그를 붙임'
            assert option_names() == ['한'], option_names()
            press(0x0D)
            wait(lambda: '한' in attached(), 5)
            metrics['checks'].append('실제 Windows 한국어 IME: 조합 확정 Enter는 무시, 둘째 Enter로 같은 이름 태그를 붙임')
        finally:
            user32.ActivateKeyboardLayout(previous, 0)
        key(Qt.Key.Key_Escape)
        wait(lambda: not dialogs.active)
        metrics['checks'].append('실창 Esc: 지울 검색어가 없으면 대화상자를 닫음')
    tag_dialog(scenario)


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
    print(json.dumps({k: v for k, v in metrics.items() if k != 'layouts'}, ensure_ascii=False, indent=2))
    # 시작 검사가 돌고 있으면 완전 종료가 경고 창으로 막힌다.
    wait(lambda: not (window.worker and window.worker.isRunning()), 60)
    window.tray.quit()
