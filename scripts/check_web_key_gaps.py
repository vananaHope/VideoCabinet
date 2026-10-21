"""#237 키로만 되던 웹 화면 작은 항목: 라이브러리 ▾ '영상 전체에서', 추천 기간 '되돌리기', 상세 하이라이트 빈 화면 문구.

--offscreen은 1100×720 위젯을 grab()으로 찍는다. 영상 0·적음·많음(--count)에서 ▾ 메뉴와 툴팁, 상세 하이라이트 빈 화면이
기본 키·여러 키·키 없음에 따라 바뀌는지, 추천 기간 초안의 되돌리기가 브리지 응답 지연 중에도 입력을 엉뚱하게 지우지 않는지 본다.
재생은 기록만 한다. 실제 mpv 왕복은 --verify(실창, 데스크톱 잠금 안)가 ▾ '영상 전체에서'로 한 번 확인한다.
DB와 합성 위치는 임시 폴더에만 기록한다.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from time import perf_counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true', help='실창: 검색 조건을 건 채 ▾ 영상 전체에서 → mpv 재생 → Esc 복귀')
parser.add_argument('--count', type=int, default=3)
parser.add_argument('--output', type=Path, default=Path('.local/screens-237'))
args = parser.parse_args()
if args.offscreen == args.verify:
    parser.error('--offscreen이나 --verify 중 하나를 고르세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import FFmpegMediaReader, executable
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.random_play import NO_CANDIDATE_MESSAGE
from my_video_manager.ui import MainWindow

app = QApplication([])
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
temporary = tempfile.TemporaryDirectory(prefix='mvm-237-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
# 합성 위치에는 실제 파일이 없다. 시작 검사가 위치를 지우지 않게 자동 감지를 끈다.
core.set_automatic_detection_enabled(False)
core.set_automatic_update_check_enabled(False)
metrics = {'count': args.count, 'checks': [], 'screenshots': []}
if args.verify:
    for index, color in enumerate(('darkblue', 'darkred')):
        path = directory / f'{index}.mkv'
        subprocess.run([executable('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=c={color}:s=640x360:r=24', '-t', '60', '-c:v', 'mpeg4', str(path)], check=True)
        core.add_file(path)
else:
    image = QImage(640, 360, QImage.Format.Format_RGB32)
    image.fill(QColor('#24354a'))
    image.save(str(directory / 'thumbnails/demo.640.jpg'))
    with closing(sqlite3.connect(core.database)) as db, db:
        for i in range(args.count):
            title = f'영상 {i:04d} ' + ('아주 긴 한글과 EnglishTitle' * 8 if i == 0 else '키 표시 검증')
            vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
                VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', title, 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                             '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
            db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(directory / f'{i}.mp4'), vid))
window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page, host = window.library_page, window.web_host
settings = host.controllers['settings']
played = []
if args.offscreen:
    # mpv 대신 재생 요청만 기록한다. '영상 전체에서'는 무작위 재생 키와 같은 재생 경로(play_random_video)로 간다.
    window.play = lambda video_id: played.append(('results', video_id))
    window.play_random_video = lambda video_id: played.append(('all', video_id))


def wait(predicate, seconds=30):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def settle(ms=180):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def read(expression):
    return json.loads(js(f'JSON.stringify({expression})'))


def capture(name):
    settle(300)
    if not args.offscreen:
        return
    path = args.output / f'{args.count}-{name}.png'
    picture = window.grab().toImage()
    assert (picture.width(), picture.height()) == (1100, 720), (picture.width(), picture.height())
    assert picture.save(str(path))
    metrics['screenshots'].append(str(path.resolve()))


def key(value, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy(), value, modifier)
    settle(120)


def type_text(text):
    for char in text:
        QTest.keyClick(host.view.focusProxy(), char)
    settle(120)


def click(selector):
    """선택자의 가운데를 실제 마우스로 누른다. 단추를 누르면 입력 칸의 초점이 빠지는 경로까지 재현한다."""
    point = read(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.scrollIntoView({{block: 'nearest'}}); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})()")
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle(150)


def save_keys(**changes):
    """설정 화면의 적용과 같은 슬롯으로 키 배치를 저장한다."""
    rows = json.loads(settings.bridge.snapshot())['bindings']
    draft = {row['id']: changes.get(row['id'].split(':')[0], row['keys']) for row in rows}
    assert 'error' not in json.loads(settings.bridge.saveKeys(json.dumps(draft)))
    settle(250)


def view(**changes):
    result = json.loads(page.bridge.view(json.dumps({**default_options(), **changes})))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


TRIGGER = 'button[aria-label="무작위 재생 범위"]'
BUTTON = "[...document.querySelectorAll('button')].find(b => b.textContent === '무작위 재생')"


def menu_state():
    """▾ 메뉴 항목 글자·접근 이름과, 메뉴·단추 묶음이 창 안에 들어오는지 잰다."""
    return read("""(() => {
      const menu = document.querySelector('[role=menu]'), m = menu.getBoundingClientRect()
      const items = [...menu.querySelectorAll('[role=menuitem]')].map(i => {
        const shortcut = i.querySelector('[data-slot=dropdown-menu-shortcut]'), r = i.getBoundingClientRect()
        return {text: i.textContent, label: i.getAttribute('aria-label'), shortcut: shortcut?.textContent ?? null,
          oneLine: r.height <= 40, shortcutInside: !shortcut || shortcut.getBoundingClientRect().right <= r.right + 0.5}
      })
      return {items, title: """ + BUTTON + """.title, inside: m.left >= 0 && m.right <= innerWidth && m.bottom <= innerHeight,
        width: Math.round(m.width), menuOverflow: menu.scrollWidth > menu.clientWidth,
        pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth}
    })()""")


def open_menu():
    js(f"document.querySelector({json.dumps(TRIGGER)}).focus()")
    key(Qt.Key.Key_Return)
    wait(lambda: js("!!document.querySelector('[role=menu]')"))
    settle(200)


def close_menu():
    key(Qt.Key.Key_Escape)
    wait(lambda: not js("!!document.querySelector('[role=menu]')"))


def check_menu(label, shortcut):
    open_menu()
    state = menu_state()
    capture(f'menu-{label}')
    texts = [item['text'] for item in state['items']]
    assert texts == ['현재 결과에서', f'영상 전체에서{shortcut}', '태그에서…'], state
    whole = state['items'][1]
    assert whole['shortcut'] == (shortcut or None) and whole['label'] == (f'영상 전체에서 · {shortcut}' if shortcut else None), state
    expected_title = '무작위 재생 (현재 결과에서)' + (f' · 영상 전체에서 {shortcut}' if shortcut else '')
    assert state['title'] == expected_title, state
    assert state['inside'] and not state['menuOverflow'] and not state['pageOverflow'], state
    assert all(item['oneLine'] and item['shortcutInside'] for item in state['items']), state
    close_menu()
    assert js("document.activeElement.getAttribute('aria-label')") == '무작위 재생 범위'
    metrics.setdefault('menus', {})[label] = state
    metrics['checks'].append(f"▾ 메뉴({label}): 영상 전체에서 · {shortcut or '키 없음'}, 툴팁 '{state['title']}', 메뉴 폭 {state['width']}px 창 안")


def highlight_guidance():
    return read("document.querySelector('aside[aria-label=\"선택 영상 상세\"] [role=listbox]')?.textContent ?? null")


def check_highlight_empty(label, expected):
    """상세 패널 하이라이트 탭의 빈 화면 문구가 현재 키 배치를 따르고 패널 안에서 줄바꿈되는지 본다."""
    wait(lambda: highlight_guidance() is not None and expected in highlight_guidance())
    state = read("""(() => {
      const box = document.querySelector('aside[aria-label="선택 영상 상세"] [role=listbox]'), b = box.getBoundingClientRect()
      const texts = [...box.querySelectorAll('p, h2, h3')].map(e => e.getBoundingClientRect())
      return {text: box.textContent, horizontal: box.scrollWidth > box.clientWidth + 1, inside: texts.every(r => r.left >= b.left - 1 && r.right <= b.right + 1)}
    })()""")
    capture(f'highlight-empty-{label}')
    assert not state['horizontal'] and state['inside'], state
    metrics.setdefault('highlight_empty', {})[label] = state['text']
    metrics['checks'].append(f'상세 하이라이트 빈 화면({label}): "{expected}"')


def check_library():
    wait(lambda: js("!!document.getElementById('library-grid')"))
    settle()
    capture('library')
    check_menu('default', 'Ctrl+Shift+R')
    if args.count:
        js("document.querySelector('aside[aria-label=\"선택 영상 상세\"] [data-tab=highlights]').click()")
        check_highlight_empty('default', '재생 중 Insert 또는 Delete로 기억할 장면을 남기세요.')
    # 여러 키가 묶이거나 긴 키도 메뉴·툴팁·빈 화면 문구가 무너지지 않는다. 다시 열지 않아도 바로 바뀐다.
    save_keys(random_play=['Ctrl+Alt+R', 'Ctrl+Alt+Shift+F12'], point_highlight=['Ctrl+Alt+Shift+F11', 'N'], range_highlight=['Shift+N'])
    check_menu('multiple', 'Ctrl+Alt+R / Ctrl+Alt+Shift+F12')
    if args.count:
        check_highlight_empty('multiple', '재생 중 Ctrl+Alt+Shift+F11 / N 또는 Shift+N로 기억할 장면을 남기세요.')
    save_keys(random_play=[], point_highlight=[], range_highlight=[])
    check_menu('unassigned', '')
    if args.count:
        check_highlight_empty('unassigned', '키 배치에서 하이라이트 키를 정하면 재생 중 기억할 장면을 남길 수 있습니다.')
    save_keys(random_play=['Ctrl+Shift+R'], point_highlight=['Insert'], range_highlight=['Delete'])

    # 검색 조건과 상관없이 영상 전체에서 고른다. 후보가 없으면 정보 안내다.
    view(query='없는 제목 abcdef')
    assert page.visible_ids == []
    open_menu()
    for _ in range(3):
        if js("document.activeElement.textContent").startswith('영상 전체에서'):
            break
        key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Return)
    if args.count:
        wait(lambda: len(played) == 1)
        scope, video_id = played.pop()
        assert scope == 'all' and video_id in page.video_ids, (scope, video_id)
        page.return_from_playback()
        settle(400)
        metrics['checks'].append('검색 결과 0개에서 ▾ → ↓ → 영상 전체에서 Enter: 영상 전체에서 골라 무작위 재생 키와 같은 재생 경로로 재생 요청')
    else:
        wait(lambda: js(f"document.querySelector('main[aria-label=라이브러리]').textContent.includes({json.dumps(NO_CANDIDATE_MESSAGE)})"))
        assert played == []
        capture('whole-empty')
        metrics['checks'].append(f'영상 0개에서 영상 전체에서: 정보 안내 "{NO_CANDIDATE_MESSAGE}"·재생 안 함')
    view()


def open_recommend():
    window.navigate_web_tab('settings')
    wait(lambda: js("!!document.querySelector('[data-category=recommend]')"))
    js("document.querySelector('[data-category=recommend]').click()")
    wait(lambda: js("!document.querySelector('[aria-labelledby=settings-recommend-heading]').parentElement.hidden"))
    settle()


def period(criterion='rewatch'):
    return read(f"""(() => {{
      const input = document.getElementById('settings-recommend-{criterion}'), form = input.closest('form'), f = form.getBoundingClientRect()
      const revert = form.querySelector('button[aria-label$=" 되돌리기"]'), badge = [...form.querySelectorAll('span')].find(s => s.textContent === '저장 안 됨')
      return {{value: input.value, unsaved: !!badge, revert: !!revert, error: form.querySelector('[data-slot=notice]')?.textContent ?? null,
        status: form.querySelector('[role=status]').textContent, focused: document.activeElement === input,
        revertInside: !revert || (revert.getBoundingClientRect().right <= f.right + 1 && Math.abs(revert.getBoundingClientRect().top - badge.getBoundingClientRect().top) < 12),
        height: Math.round(f.height)}}
    }})()""")


def focus_period(criterion='rewatch'):
    js(f"(() => {{ const e = document.getElementById('settings-recommend-{criterion}'); e.scrollIntoView({{block: 'nearest'}}); e.focus() }})()")
    key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)


def delay_responses(delay):
    """WebChannel 응답(type 10)만 늦춰 저장 요청이 끝나기 전의 조작을 재현한다. 0이면 원래대로 돌린다."""
    js(f"""(() => {{
      const t = window.qt.webChannelTransport;
      window.checkOriginal = window.checkOriginal || t.onmessage;
      t.onmessage = {delay} ? function(e) {{
        if (JSON.parse(e.data).type === 10) setTimeout(() => window.checkOriginal.call(t, e), {delay});
        else window.checkOriginal.call(t, e);
      }} : window.checkOriginal;
    }})()""")


REVERT = 'form button[aria-label="다시 보기 되돌리기"]'


def check_recommend():
    open_recommend()
    before = period()
    assert not before['unsaved'] and not before['revert'], before
    focus_period()
    type_text('42')
    draft = period()
    assert draft['value'] == '42' and draft['unsaved'] and draft['revert'] and draft['revertInside'], draft
    row = read("""(() => { const label = document.querySelector('label[for=settings-recommend-rewatch]'), line = label.parentElement
      const revert = line.querySelector('button'), badge = revert.previousElementSibling, sizes = e => Math.round(e.getBoundingClientRect().height)
      const withButton = sizes(line); revert.style.display = 'none'; const withBadge = sizes(line); revert.style.display = ''
      return {label: sizes(label), badge: sizes(badge), button: sizes(revert), line: withButton, lineWithoutButton: withBadge} })()""")
    metrics['period_row'] = {**row, 'before': before['height'], 'draft': draft['height']}
    assert draft['height'] == before['height'], metrics['period_row']
    capture('recommend-draft')
    click(REVERT)
    after = period()
    assert after['value'] == '60' and not after['unsaved'] and not after['revert'] and after['focused'], after
    assert core.recommendation_period_days()['rewatch'] == 60
    metrics['checks'].append(f"추천 기간 초안: 저장 안 됨 옆 되돌리기(행 높이 {draft['height']}px 그대로) → 저장된 값 60·입력 칸 초점, 초안 없으면 단추 없음")

    # Esc와 같은 동작이다. 오류 안내도 함께 지운다.
    focus_period()
    type_text('abc')
    key(Qt.Key.Key_Return)
    wait(lambda: period()['error'] is not None)
    capture('recommend-error')
    click(REVERT)
    after = period()
    assert after['value'] == '60' and after['error'] is None and not after['revert'], after
    metrics['checks'].append('잘못된 값 저장 실패 뒤 되돌리기: 오류 안내와 초안을 함께 버림')

    delay_responses(1500)
    try:
        # 42를 Enter로 보내고 응답 전에 77을 입력한 뒤 되돌리기를 누른다. 늦은 응답이 초안을 되살리거나 오류를 띄우면 안 된다.
        focus_period()
        type_text('42')
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        focus_period()
        type_text('77')
        assert period()['value'] == '77' and period()['revert'], period()
        click(REVERT)
        assert period()['value'] != '77' and not period()['revert'] and period()['focused'], period()
        wait(lambda: core.recommendation_period_days()['rewatch'] == 42)
        settle(2000)
        after = period()
        assert after['value'] == '42' and not after['unsaved'] and '저장된 값 42일' in after['status'] and after['error'] is None, after
        metrics['checks'].append('응답 지연 1.5초: 42 Enter → 응답 전 77 입력 → 되돌리기 → 응답 뒤 저장값 42 표시, 초안·오류 없음')

        # 잘못된 값을 보내고 응답 전에 되돌리기를 누른 뒤 새로 입력한다. 늦은 오류가 뜨거나 새 초안이 지워지면 안 된다.
        focus_period()
        type_text('abc')
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        click(REVERT)
        assert period()['value'] == '42', period()
        focus_period()
        type_text('77')
        settle(2000)
        after = period()
        assert after['value'] == '77' and after['unsaved'] and after['revert'] and after['error'] is None, after
        assert core.recommendation_period_days()['rewatch'] == 42
        capture('recommend-late-draft')
        metrics['checks'].append('응답 지연 1.5초: abc Enter → 응답 전 되돌리기 → 77 입력 → 늦은 오류 없음, 77·저장 안 됨 유지, 저장값 42')
    finally:
        delay_responses(0)
    core.reset_recommendation_period_days('rewatch')


def verify():
    assert QTest.qWaitForWindowActive(window, 5000)
    wait(lambda: js("!!document.getElementById('library-grid')"))
    view(query='없는 제목 abcdef')
    assert page.visible_ids == []
    open_menu()
    for _ in range(3):
        if js("document.activeElement.textContent").startswith('영상 전체에서'):
            break
        key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Return)
    wait(lambda: window.pages.currentWidget() is window.playback_page)
    wait(lambda: core.playback.position > 0.2)
    all_ids = tuple(video.id for video in core.videos())
    assert core.playback.session.video_id in all_ids and window.playback_list == all_ids
    metrics['mpv_time_pos'] = getattr(getattr(window.player, '_player', None), 'time_pos', None)
    window.playback_page.focus_content()
    QTest.keyClick(window.surface, Qt.Key.Key_Escape)
    wait(lambda: window.pages.currentWidget() is host)
    assert core.playback.session is None and page.options['query'] == '없는 제목 abcdef'
    metrics['checks'].append('실창: 검색 결과 0개 → ▾ 영상 전체에서 Enter → mpv 재생(위치 진행) → Esc 라이브러리 복귀')


try:
    if args.offscreen:
        check_library()
        check_recommend()
    else:
        verify()
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    try:
        (args.output / f"metrics-{'verify' if args.verify else args.count}.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
        # 콘솔 인코딩(cp949 등)에서 '▾' 같은 글자를 못 써 끝나지 않게 ASCII로 escape한다.
        print(json.dumps(metrics, ensure_ascii=True, indent=2))
    finally:
        wait(lambda: not window.tray.quit_blocker(), 120)
        window.tray.quit()
