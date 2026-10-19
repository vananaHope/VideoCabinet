"""#205: '태그에서…' 무작위 재생 창과 상세 패널 태그 메뉴의 배치·키보드·후보 수·재생 복귀 검사.

--offscreen은 영상·태그 수(0·적음·많음)별 1100×720 화면, 키보드만으로 고르고 재생하기, IME 조합 Enter,
Esc 순서, 후보 0개, 태그를 여러 번 바꿀 때의 후보 수 갱신 시간을 잰다. 재생은 기록만 하고 복귀 신호를 흉내 낸다.
--verify는 데스크톱 잠금 안에서 ▾ → 태그에서… → 태그 둘 → 재생 → 실제 mpv(이어볼 위치) → Esc 복귀와
상세 패널 태그 우클릭 → 이 태그에서 무작위 재생 → mpv → 복귀를 검사한다.
--source 원본은 읽기만 한다. DB와 합성 위치는 임시 폴더에만 기록한다.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter

parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--count', type=int, default=5000)
parser.add_argument('--tags', type=int, default=300)
parser.add_argument('--source', type=Path)
parser.add_argument('--output', type=Path, default=Path('.local/screens-205'))
args = parser.parse_args()
if args.verify and (args.offscreen or not args.source):
    parser.error('--verify는 실창과 --source 영상이 필요합니다.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QPoint, QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.ui import MainWindow

app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-205-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
# 합성 위치에는 실제 파일이 없다. 시작 검사가 위치를 지우지 않게 자동 감지를 끈다.
core.set_automatic_detection_enabled(False)
label = f'{args.count}v-{args.tags}t'
metrics = {'count': args.count, 'tags': args.tags, 'checks': [], 'screenshots': [], 'app_data': str(directory)}
playable = None
if args.source:
    core.add_file(args.source)
    playable = core.videos()[0]
    core.rename_video(playable.id, '실제 재생 태그 무작위 대상')
    # 보다 만 영상으로 만들어 이어볼 위치부터 재생되는지 본다.
    core.playback.start(playable.id, 0)
    core.playback.report(round(playable.duration * 0.4, 3))
    core.playback.end()
    metrics['resume_point'] = core.resume_start(playable.id)
    for name in ('실제 A', '실제 B'):
        core.add_video_tag(playable.id, name)
root = directory / '라이브러리'
root.mkdir()
image = QImage(640, 360, QImage.Format.Format_RGB32)
image.fill(QColor('#24354a'))
image.save(str(directory / 'thumbnails/demo.640.jpg'))
# 태그 이름은 '태그 000'처럼 숫자로 찾을 수 있게 하고, 하나는 아주 길게 만든다.
LONG = ' 아주 긴 태그 이름과 EnglishTagNameForEllipsisCheck'  # 태그 이름 상한(50자)에 가깝게
tags = [core.create_tag(f'태그 {i:03d}' + (LONG if i == 1 else '')) for i in range(args.tags)]
# QTest.keyClicks로 한글을 보내면 offscreen 프로세스가 끝나므로 키보드로 찾는 이름은 ASCII를 넣는다.
missing_only = core.create_tag('missing 파일 없음만 붙은 태그') if args.count else None
with closing(sqlite3.connect(core.database)) as db, db:
    synthetic = []
    for i in range(args.count):
        title = f'영상 {i:04d} 태그 무작위 검증'
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', title, 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        # 마지막 영상은 위치가 없는 파일 없음 영상이다.
        if i < args.count - 1:
            db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / f'{i}.mp4'), vid))
        synthetic.append(vid)
    # 영상마다 태그 세 개(겹치게). 태그 수가 영상보다 많으면 일부 태그는 비어 있다.
    if tags:
        db.executemany('INSERT OR IGNORE INTO video_tags(video_id, tag_id) VALUES (?,?)', [
            (vid, tags[(j * step) % len(tags)].id) for j, vid in enumerate(synthetic[:-1]) for step in (1, 7, 31)])
    if missing_only:
        db.execute('INSERT INTO video_tags(video_id, tag_id) VALUES (?,?)', (synthetic[-1], missing_only.id))
window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page, host = window.library_page, window.web_host
played = []
if not args.verify:
    # offscreen에서는 mpv 대신 재생 요청만 기록한다. 실제 재생 경로는 --verify가 확인한다.
    window.play = played.append
else:
    switch_to = core.switch_to
    starts = []
    core.switch_to = lambda video_id, **kw: starts.append(switch_to(video_id, **kw)) or starts[-1]


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


def view(**changes):
    result = json.loads(page.bridge.view(json.dumps({**default_options(), **changes})))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def capture(name):
    settle()
    path = args.output / f'{label}-{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def key(value, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy(), value, modifier)
    settle()


def type_text(text):
    QTest.keyClicks(host.view.focusProxy(), text)
    settle()


TRIGGER = "document.querySelector('button[aria-label=\"무작위 재생 범위\"]')"
DIALOG = "document.querySelector('[role=dialog]')"
ACTIVE = "document.activeElement.getAttribute('aria-label') || document.activeElement.textContent"
STATUS = "document.querySelector('[role=dialog] [role=status]')?.textContent"
PLAY = "[...document.querySelectorAll('[role=dialog] button')].find(b => b.textContent === '재생')"
CHIPS = "JSON.stringify([...document.querySelectorAll('[role=dialog] [role=group] button')].map(b => b.title))"


def dialog_open():
    return js(f'!!{DIALOG}')


def chips():
    return json.loads(js(CHIPS))


def status():
    return js(STATUS)


def play_disabled():
    return js(f'{PLAY}.disabled')


def dialog_layout(name):
    """창이 1100×720 안에 들어가고 가로로 넘치지 않으며 재생 단추가 보이는지 잰다."""
    value = json.loads(js(f"""JSON.stringify((() => {{
      const d = {DIALOG}, r = d.getBoundingClientRect(), p = {PLAY}.getBoundingClientRect()
      const list = d.querySelector('[role=listbox]')
      return {{top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height,
        overflowX: d.scrollWidth - d.clientWidth, overflowY: d.scrollHeight - d.clientHeight,
        playVisible: p.bottom <= r.bottom && p.top >= r.top, viewport: [innerWidth, innerHeight],
        list: list ? {{height: list.clientHeight, scroll: list.scrollHeight, options: list.children.length}} : null}}
    }})())"""))
    assert value['top'] >= 0 and value['bottom'] <= value['viewport'][1] and value['right'] <= value['viewport'][0], (name, value)
    assert value['overflowX'] <= 0 and value['playVisible'], (name, value)
    metrics.setdefault('layout', {})[name] = value


def open_dialog_by_keyboard():
    js(TRIGGER + '.focus()')
    key(Qt.Key.Key_Return)
    wait(lambda: js("!!document.querySelector('[role=menu]')"))
    items = json.loads(js("JSON.stringify([...document.querySelectorAll('[role=menuitem]')].map(i => i.textContent))"))
    assert items == ['현재 결과에서', '태그에서…'], items
    # 메뉴는 열릴 때 첫 항목이나 메뉴 자체에 초점을 둔다. ↓로 '태그에서…'까지 간다(마지막 항목에서 멈춤).
    for _ in range(3):
        if js("document.activeElement.textContent") == '태그에서…':
            break
        key(Qt.Key.Key_Down)
    assert js("document.activeElement.textContent") == '태그에서…', js(ACTIVE)
    key(Qt.Key.Key_Return)
    wait(dialog_open)
    settle(300)
    assert js("document.activeElement.getAttribute('role')") == 'combobox', js(ACTIVE)


def expected_count(names):
    ids = [t.id for t in core.tags() if t.name in names]
    return core.random_video_count(tag_ids=ids), ids


def pick_by_typing(query):
    """검색어를 쳐서 ↓·Enter로 첫 후보를 고른다. 고른 태그 이름을 돌려준다."""
    before = chips()
    type_text(query)
    key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Return)
    after = chips()
    assert len(after) == len(before) + 1, (before, after)
    return after[-1]


def check_ime_enter():
    """조합 중 Enter는 태그를 고르지 않고 창도 닫거나 재생하지 않는다."""
    before = chips()
    js("""(() => { const input = document.querySelector('[role=dialog] [role=combobox]'); input.focus()
      input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}))
      input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true})) })()""")
    settle()
    assert dialog_open() and chips() == before and played == [], ('enter', dialog_open(), chips(), before, played)
    js("""document.querySelector('[role=dialog] [role=combobox]').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', isComposing: true, bubbles: true, cancelable: true}))""")
    settle()
    assert dialog_open() and chips() == before and played == [], (dialog_open(), chips(), before, played)
    js("document.querySelector('[role=dialog] [role=combobox]').dispatchEvent(new CompositionEvent('compositionend', {bubbles: true}))")
    settle(100)
    metrics['checks'].append('IME 조합 중 Enter·Esc: 태그를 고르지 않고 창을 닫거나 재생하지 않음')


def tab_to_play():
    for _ in range(40):
        if js("document.activeElement.textContent") == '재생':
            return
        key(Qt.Key.Key_Tab)
    raise AssertionError('Tab으로 재생 단추에 닿지 않음')


def measure_toggles():
    """태그를 여러 번 바꿀 때 클릭부터 후보 수 갱신까지 걸린 시간(브라우저 안). 코어에 다시 묻지 않아야 한다."""
    calls = []
    original = core.random_tag_candidates
    core.random_tag_candidates = lambda *a, **kw: calls.append(1) or original(*a, **kw)
    core_count = core.random_video_count
    core.random_video_count = lambda *a, **kw: calls.append(1) or core_count(*a, **kw)
    try:
        js("""window.__toggle = null; new Promise(resolve => {
          const options = [...document.querySelectorAll('[role=dialog] [role=option]')].slice(0, 6), samples = []
          let step = 0
          const next = () => {
            if (step >= 20) return resolve(JSON.stringify(samples))
            const status = () => document.querySelector('[role=dialog] [role=status]').textContent
            const before = status(), started = performance.now()
            options[step % options.length].click()
            requestAnimationFrame(() => { samples.push({ms: performance.now() - started, changed: before !== status()}); step++; setTimeout(next, 30) })
          }
          next()
        }).then(value => { window.__toggle = value }); true""")
        wait(lambda: js('!!window.__toggle'))
        samples = json.loads(js('window.__toggle'))
    finally:
        core.random_tag_candidates, core.random_video_count = original, core_count
    times = sorted(s['ms'] for s in samples)
    assert not calls, len(calls)
    metrics['toggle_to_status_ms'] = {'samples': len(times), 'median': round(times[len(times) // 2], 2), 'max': round(times[-1], 2),
                                      'status_changed': sum(s['changed'] for s in samples), 'core_calls': len(calls)}


try:
    wait(lambda: js("!!document.getElementById('library-grid')"))
    # 첫 표시의 격자 초점 요청이 메뉴 초점을 가로채지 않게 시작 초점이 자리 잡을 때까지 기다린다.
    wait(lambda: js('document.activeElement.id') == 'library-grid')
    settle(500)
    # 창을 열 때 한 번 받는 태그별 후보(스냅숏으로 계산)와 예전 경로(호출마다 DB)의 비용 비교.
    samples = []
    for _ in range(5):
        started = perf_counter()
        page.bridge.randomTagCandidates()
        samples.append((perf_counter() - started) * 1000)
    metrics['open_candidates_ms'] = {'median': round(sorted(samples)[2], 2), 'max': round(max(samples), 2)}
    if tags:
        samples = []
        for _ in range(5):
            started = perf_counter()
            core.random_video_count(tag_ids=[t.id for t in tags[:3]])
            samples.append((perf_counter() - started) * 1000)
        metrics['core_count_per_call_ms'] = {'median': round(sorted(samples)[2], 2), 'max': round(max(samples), 2)}

    if not args.verify:
        open_dialog_by_keyboard()
        assert status() == ('태그를 하나 이상 고르세요.' if tags else '') and play_disabled(), status()
        capture('dialog-open')
        dialog_layout('dialog-open')
        # 창은 실제 모달이다. 열린 동안 예약 키(Ctrl+2)가 탭을 바꾸지 않는다.
        key(Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        settle(300)
        assert host.active_tab == 'library' and dialog_open(), host.active_tab
        # 모달은 키를 입력으로 넘긴다. QTest가 Ctrl+2에 실은 글자 '2'가 검색어로 들어가면 Esc로 지운다(창은 남음).
        if js("document.querySelector('[role=dialog] [role=combobox]').value"):
            key(Qt.Key.Key_Escape)
        assert dialog_open() and not js("document.querySelector('[role=dialog] [role=combobox]').value")
        metrics['checks'].append('창이 열린 동안 Ctrl+2는 탭을 바꾸지 않음(셸 모달 차단)')
        metrics['checks'].append('▾ Enter → ↓↓ → 태그에서… Enter로 창 열기, 시작 초점은 태그 검색, 태그 없으면 재생 막힘')
        if not tags:
            assert js("document.querySelector('[role=dialog]').textContent.includes('등록한 태그가 없습니다.')")
            metrics['checks'].append('태그 0개: "등록한 태그가 없습니다." 안내, 재생 막힘')
        else:
            first = pick_by_typing('000')
            check_ime_enter()
            second = pick_by_typing('002')
            count, ids = expected_count([first, second])
            wait(lambda: status() == f'후보 {count}개')
            assert not play_disabled()
            capture('dialog-two-tags')
            dialog_layout('dialog-two-tags')
            metrics['checks'].append(f'숫자로 검색해 ↓·Enter로 두 태그 고름 → 칩 2개, 후보 {count}개(코어 OR 후보 수와 같음)')
            # Esc는 검색어 → 창 순서. 검색어가 있으면 창을 닫지 않는다.
            type_text('00')
            key(Qt.Key.Key_Escape)
            assert dialog_open() and js("document.querySelector('[role=dialog] [role=combobox]').value") == ''
            if args.count:
                # 많이 쓴 태그와 긴 이름: 모두 보기 목록과 칩 말줄임.
                js("[...document.querySelectorAll('[role=dialog] button')].find(b => b.textContent.startsWith('모두 보기')).click()")
                settle()
                capture('dialog-show-all')
                dialog_layout('dialog-show-all')
                js("[...document.querySelectorAll('[role=dialog] button')].find(b => b.textContent.startsWith('자주 쓴')).click()")
                settle()
            if len(tags) > 1:
                pick_by_typing('001')
                capture('dialog-long-chip')
                dialog_layout('dialog-long-chip')
                metrics['checks'].append('긴 태그 이름: 칩 말줄임, 창 가로 넘침 없음')
            if args.count > 100:
                measure_toggles()
                metrics['checks'].append('태그 20번 바꾸기: 브리지 재호출 없이 화면에서 합집합 크기만 셈(시간은 toggle_to_status_ms)')
            # 키보드만으로 Tab → 재생 Enter. 고른 태그 중 하나라도 붙은 영상이 재생된다.
            chosen_names = chips()
            count, ids = expected_count(chosen_names)
            wait(lambda: status() == f'후보 {count}개')
            tab_to_play()
            key(Qt.Key.Key_Return)
            wait(lambda: len(played) == 1)
            video_id = played.pop()
            assert not dialog_open()
            assert {t.id for t in core.video_tags(video_id)} & set(ids), video_id
            page.return_from_playback()
            settle(400)
            state = json.loads(js("""JSON.stringify({active: document.activeElement.id, descendant: document.getElementById('library-grid').getAttribute('aria-activedescendant')})"""))
            assert page.selected_id == video_id and state == {'active': 'library-grid', 'descendant': f'video-{video_id}'}, state
            metrics['checks'].append('Tab으로 재생 단추 → Enter: 고른 태그 영상 재생 요청 → 복귀 시 그 영상 선택·격자 초점')
            if missing_only:
                open_dialog_by_keyboard()
                # 이전에 고른 태그는 남아 있다. 모두 빼고 파일 없음만 붙은 태그를 고른다.
                while chips():
                    js("document.querySelector('[role=dialog] [role=group] button').click()")
                    settle(60)
                type_text('missing')
                key(Qt.Key.Key_Down)
                key(Qt.Key.Key_Return)
                wait(lambda: status() == '후보 0개 · 고른 태그에 재생할 수 있는 영상이 없습니다.')
                assert play_disabled()
                capture('dialog-zero-candidates')
                dialog_layout('dialog-zero-candidates')
                metrics['checks'].append('파일 없음 영상에만 붙은 태그: 후보 0개 안내·재생 막힘')
                key(Qt.Key.Key_Escape)
                assert not dialog_open() and js(ACTIVE) == '무작위 재생 범위', js(ACTIVE)
                metrics['checks'].append('Esc로 창 닫으면 ▾로 초점 복원')
            else:
                key(Qt.Key.Key_Escape)
        if dialog_open():
            key(Qt.Key.Key_Escape)
            assert not dialog_open() and js(ACTIVE) == '무작위 재생 범위', js(ACTIVE)
        # 상세 패널 태그 칩: 우클릭과 키보드(Enter)로 메뉴, '이 태그에서 무작위 재생'.
        if tags and args.count:
            view(query='영상 0002')
            assert page.selected_id is not None
            settle(300)
            chip = "document.querySelector('aside [role=group][aria-label=\"태그\"] button')"
            tag_name = js(chip + '.title')
            js(f"(() => {{ const c = {chip}, r = c.getBoundingClientRect(); c.dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, cancelable: true, clientX: r.left + 4, clientY: r.top + 4}})) }})()")
            wait(lambda: js("!!document.querySelector('[role=menu]')"))
            assert json.loads(js("JSON.stringify([...document.querySelectorAll('[role=menuitem]')].map(i => i.textContent))")) == ['이 태그에서 무작위 재생']
            capture('detail-tag-menu')
            js("document.querySelector('[role=menuitem]').click()")
            wait(lambda: len(played) == 1)
            video_id = played.pop()
            tag_id = next(t.id for t in core.tags() if t.name == tag_name)
            assert tag_id in {t.id for t in core.video_tags(video_id)}
            page.return_from_playback()
            settle(400)
            metrics['checks'].append(f'상세 패널 태그 우클릭 → 이 태그에서 무작위 재생: 그 태그 영상 재생 요청(필터 밖 영상이면 기존 선택 정책)')
            view(query='영상 0002')
            settle(300)
            js(chip + '.focus()')
            key(Qt.Key.Key_Return)
            wait(lambda: js("!!document.querySelector('[role=menu]')"))
            key(Qt.Key.Key_Escape)
            assert not js("!!document.querySelector('[role=menu]')") and js("document.activeElement.title") == tag_name
            metrics['checks'].append('상세 패널 태그 칩 Enter로 메뉴 열기·Esc 닫으면 칩으로 초점 복원')
            key(Qt.Key.Key_Menu)
            wait(lambda: js("!!document.querySelector('[role=menu]')"))
            key(Qt.Key.Key_Escape)
            metrics['checks'].append('상세 패널 태그 칩에서 메뉴 키로도 메뉴 열림')
            # 태그가 많은 영상과 긴 태그 이름의 상세 패널 배치.
            view(query='영상 0001')
            capture('detail-tags')
        else:
            capture('detail-no-tags')
    else:
        assert QTest.qWaitForWindowActive(window, 5000)
        view(query='실제 재생')
        assert page.visible_ids == [playable.id], page.visible_ids
        # 1) ▾ → 태그에서… → 태그 둘 → 재생 → mpv → Esc 복귀
        open_dialog_by_keyboard()
        type_text('A')  # '실제 A'
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Return)
        type_text('B')
        key(Qt.Key.Key_Down)
        key(Qt.Key.Key_Return)
        assert sorted(chips()) == ['실제 A', '실제 B'], chips()
        wait(lambda: status() == '후보 1개')
        capture('real-dialog')
        tab_to_play()
        key(Qt.Key.Key_Return)
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(1500)
        assert core.playback.session.video_id == playable.id
        mpv = getattr(window.player, '_player', None)
        metrics['mpv_time_pos_dialog'] = getattr(mpv, 'time_pos', None)
        assert abs(starts[-1] - metrics['resume_point']) < 0.01, starts
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host)
        settle(600)
        assert page.selected_id == playable.id
        assert js('document.activeElement.id') == 'library-grid'
        capture('real-dialog-return')
        metrics['checks'].append('실창: ▾ → 태그에서… → 태그 둘 → 재생 → mpv 이어볼 위치 → Esc 복귀 → 그 영상 선택·격자 초점')
        # 2) 상세 패널 태그 우클릭(실제 마우스 이벤트) → 이 태그에서 무작위 재생 → mpv → 복귀
        rect = json.loads(js("JSON.stringify((() => { const r = document.querySelector('aside [role=group][aria-label=\"태그\"] button').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2] })())"))
        point = QPoint(round(rect[0]), round(rect[1]))
        QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
        wait(lambda: js("!!document.querySelector('[role=menu]')"))
        capture('real-detail-menu')
        key(Qt.Key.Key_Down) if js("document.activeElement.getAttribute('role')") != 'menuitem' else None
        key(Qt.Key.Key_Return)
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(1500)
        assert core.playback.session.video_id == playable.id
        metrics['mpv_time_pos_detail'] = getattr(getattr(window.player, '_player', None), 'time_pos', None)
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host)
        settle(600)
        assert page.selected_id == playable.id and js('document.activeElement.id') == 'library-grid'
        capture('real-detail-return')
        metrics['playback_starts'] = starts
        metrics['checks'].append('실창: 상세 패널 태그 우클릭 → 이 태그에서 무작위 재생 → mpv → Esc 복귀 → 선택·격자 초점')
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    try:
        (args.output / f'metrics-{label}{"-verify" if args.verify else ""}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(metrics, ensure_ascii=True, indent=2))
    finally:
        wait(lambda: not window.tray.quit_blocker(), 120)
        window.tray.quit()
