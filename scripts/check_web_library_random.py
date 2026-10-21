"""#198: 라이브러리 검색줄 '무작위 재생' 버튼의 배치·키보드·후보 없음 안내와 재생 복귀 검사.

--offscreen은 영상 0·적음·많음에서 1100×720 화면과 키보드를 검사한다. 재생은 기록만 하고 복귀 신호를 흉내 낸다.
--verify는 데스크톱 잠금 안에서 검색 조건을 건 채 무작위 재생 → 실제 mpv(이어볼 위치) → Esc 복귀를 검사한다.
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
parser.add_argument('--source', type=Path)
parser.add_argument('--output', type=Path, default=Path('.local/screens-198'))
args = parser.parse_args()
if args.verify and (args.offscreen or not args.source):
    parser.error('--verify는 실창과 --source 영상이 필요합니다.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.random_play import NO_CANDIDATE_MESSAGE
from my_video_manager.ui import MainWindow

app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-198-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
media = FFmpegMediaReader()
core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
# 합성 위치에는 실제 파일이 없다. 시작 검사가 위치를 지우지 않게 자동 감지를 끈다.
core.set_automatic_detection_enabled(False)
metrics = {'count': args.count, 'checks': [], 'screenshots': [], 'app_data': str(directory)}
playable = None
if args.source:
    core.add_file(args.source)
    playable = core.videos()[0]
    core.rename_video(playable.id, '실제 재생 무작위 대상')
    # 보다 만 영상으로 만들어 이어볼 위치부터 재생되는지 본다.
    core.playback.start(playable.id, 0)
    core.playback.report(round(playable.duration * 0.4, 3))
    core.playback.end()
    metrics['resume_point'] = core.resume_start(playable.id)
root = directory / '라이브러리'
root.mkdir()
image = QImage(640, 360, QImage.Format.Format_RGB32)
image.fill(QColor('#24354a'))
image.save(str(directory / 'thumbnails/demo.640.jpg'))
with closing(sqlite3.connect(core.database)) as db, db:
    for i in range(args.count):
        title = f'영상 {i:04d} ' + ('아주 긴 한글과 EnglishTitle' * 8 if i == 0 else '무작위 검증')
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', title, 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / f'{i}.mp4'), vid))
if args.count:
    first = next(v for v in core.videos() if v.title.startswith('영상 0000'))
    core.add_video_tag(first.id, '긴 태그 이름 ' * 5)
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
    # 기존 재생 경로가 정한 시작 위치(이어볼 위치)를 기록한다.
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
    path = args.output / f'{args.count}-{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def key(value, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy(), value, modifier)
    settle()


BUTTON = "[...document.querySelectorAll('button')].find(b => b.textContent === '무작위 재생')"
TRIGGER = "document.querySelector('button[aria-label=\"무작위 재생 범위\"]')"
NOTICE = "[...document.querySelectorAll('main[aria-label=라이브러리] [data-slot=notice]')].map(n => [n.dataset.tone, n.textContent])"
ACTIVE = "document.activeElement.getAttribute('aria-label') || document.activeElement.id || document.activeElement.textContent"


def layout(name):
    """검색줄이 1100px 창 폭을 넘지 않고 버튼 묶음이 한 줄로 붙어 있는지 잰다."""
    value = json.loads(js("""JSON.stringify((() => {
      const row = document.querySelector('[aria-label="영상 제목 빠른 검색"]').parentElement.parentElement, bounds = row.getBoundingClientRect()
      const group = document.querySelector('[role=group][aria-label="무작위 재생"]'), [main, more] = group.children
      const a = main.getBoundingClientRect(), b = more.getBoundingClientRect()
      return {rowOverflow: row.scrollWidth - row.clientWidth, outside: [...row.children].filter(c => c.getBoundingClientRect().right > bounds.right + 0.5).length,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        searchWidth: document.querySelector('[aria-label="영상 제목 빠른 검색"]').clientWidth,
        groupWidth: group.offsetWidth, joined: Math.abs(a.right - b.left) < 1 && a.top === b.top, rowHeight: row.offsetHeight}
    })())"""))
    assert value['rowOverflow'] <= 0 and value['outside'] == 0 and value['pageOverflow'] <= 0, (name, value)
    assert value['joined'] and value['searchWidth'] >= 96 and value['rowHeight'] <= 40, (name, value)
    metrics.setdefault('layout', {})[name] = value


def notices():
    # 셸의 상태 안내(자동 감지 꺼짐 등)는 빼고 라이브러리 페이지 안의 안내만 본다.
    return [tuple(n) for n in json.loads(js(f'JSON.stringify({NOTICE})'))]


def check_empty(label):
    """후보가 없으면 오류가 아니라 정보 안내다. 닫을 수 있고 결과가 바뀌면 사라진다."""
    js(BUTTON + '.click()')
    wait(lambda: notices())
    assert notices() == [('info', NO_CANDIDATE_MESSAGE)], notices()
    assert played == [] and not page.bridge.busy
    capture(f'empty-{label}')
    layout(f'empty-{label}')
    js("document.querySelector('[aria-label=\"안내 닫기\"]').click()")
    wait(lambda: not notices())
    metrics['checks'].append(f'후보 없음({label}): 정보 안내 "{NO_CANDIDATE_MESSAGE}"·닫기·재생 안 함')


def check_play(label, *, expect=None):
    """버튼 → 현재 결과에서 고름 → 재생 요청 → 복귀 신호에서 그 카드에 선택·초점·보임."""
    before = set(page.visible_ids)
    js(BUTTON + '.click()')
    wait(lambda: len(played) == 1)
    video_id = played.pop()
    assert video_id in before and (expect is None or video_id == expect), (video_id, expect)
    page.return_from_playback()
    settle(400)
    state = json.loads(js(f"""JSON.stringify((() => {{
      const grid = document.getElementById('library-grid'), card = document.getElementById('video-{video_id}')
      const g = grid.getBoundingClientRect(), c = card && card.getBoundingClientRect()
      return {{active: document.activeElement.id, descendant: grid.getAttribute('aria-activedescendant'),
        visible: !!c && c.top >= g.top - 1 && c.bottom <= g.bottom + 1, top: grid.scrollTop}}
    }})())"""))
    assert page.selected_id == video_id and state['descendant'] == f'video-{video_id}', state
    assert state['active'] == 'library-grid' and state['visible'], state
    metrics.setdefault('returns', {})[label] = {'video': video_id, 'index': page.visible_ids.index(video_id), **state}
    metrics['checks'].append(f'재생({label}): 현재 결과 {len(before)}개에서 고름 → 복귀 시 선택·격자 초점·카드 보임')
    return video_id


def check_keyboard():
    """버튼과 ▾는 Tab으로 차례로 닿고, ▾ 메뉴는 Enter로 열고 Esc로 닫으면 ▾로 초점이 돌아온다."""
    js(BUTTON + '.focus()')
    assert js(ACTIVE) == '무작위 재생'
    key(Qt.Key.Key_Tab)
    assert js(ACTIVE) == '무작위 재생 범위'
    key(Qt.Key.Key_Return)
    wait(lambda: js("!!document.querySelector('[role=menu]')"))
    items = json.loads(js("JSON.stringify([...document.querySelectorAll('[role=menuitem]')].map(i => i.textContent))"))
    assert items == ['현재 결과에서', '영상 전체에서Ctrl+Shift+R', '태그에서…'], items
    capture('menu-open')
    key(Qt.Key.Key_Escape)
    wait(lambda: not js("!!document.querySelector('[role=menu]')"))
    assert js(ACTIVE) == '무작위 재생 범위'
    key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert js(ACTIVE) == '무작위 재생'
    metrics['checks'].append('Tab 버튼→▾, ▾ Enter 메뉴(현재 결과에서·영상 전체에서·태그에서…)·Esc 닫기 후 ▾ 초점 복원, Shift+Tab 버튼')
    if args.count and not args.verify:
        js(TRIGGER + '.focus()')
        key(Qt.Key.Key_Return)
        wait(lambda: js("!!document.querySelector('[role=menu]')"))
        metrics['menu_open_focus'] = js("document.activeElement.getAttribute('role')")
        key(Qt.Key.Key_Down)
        wait(lambda: js("document.activeElement.getAttribute('role') === 'menuitem'"))
        key(Qt.Key.Key_Return)
        wait(lambda: len(played) == 1)
        assert played.pop() in page.visible_ids
        page.return_from_playback()
        settle(400)
        metrics['checks'].append('▾ Enter → ↓ → 현재 결과에서 Enter로 재생 요청')


try:
    wait(lambda: js("!!document.getElementById('library-grid')"))
    settle()
    capture('initial')
    layout('initial')
    # 버튼 한 번은 메인 스레드에서 후보를 한 번 계산한다(검사 잠금 없음).
    samples = []
    for _ in range(5):
        started = perf_counter()
        core.random_video_count(video_ids=page.visible_video_ids())
        samples.append((perf_counter() - started) * 1000)
    metrics['candidates_ms'] = {'median': round(sorted(samples)[2], 3), 'max': round(max(samples), 3)}
    check_keyboard()
    if not args.count and not args.verify:
        check_empty('no-videos')
    elif not args.verify:
        view(query='없는 제목 abcdef')
        assert page.visible_ids == []
        check_empty('no-results')
        # 결과가 바뀌면 안내가 함께 사라진다.
        js(BUTTON + '.click()')
        wait(lambda: notices())
        view(query='')
        assert not notices(), notices()
        metrics['checks'].append('후보 없음 안내는 검색 조건이 바뀌면 사라짐')
        view(query='영상 0000')
        assert len(page.visible_ids) == 1
        capture('one-result')
        layout('one-result')
        check_play('one-result', expect=page.visible_ids[0])
        view()
        capture('all')
        if args.count > 200:
            js("document.getElementById('library-grid').scrollTop = 0")
            for i in range(3):
                check_play(f'all-{i}')
            capture('all-after-return')
        view(query='긴 한글과 EnglishTitle', viewing='unwatched', tags=[t.id for t in core.tags()])
        capture('long-chips')
        layout('long-chips')
        # 걸러진 결과가 모두 제외되면 후보가 없다(코어 규칙). 검사 중에도 막지 않는다.
        if args.count:
            view()
            page.worker = object()
            check_play('scanning')
            page.worker = None
            metrics['checks'].append('검사 중(worker 있음)에도 무작위 재생 요청이 바로 처리됨')
    if args.verify:
        assert QTest.qWaitForWindowActive(window, 5000)
        view(query='실제 재생')
        assert page.visible_ids == [playable.id], page.visible_ids
        js(BUTTON + '.click()')
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(1500)
        session = core.playback.session
        assert session.video_id == playable.id, session
        metrics['playback_start'] = starts
        mpv = getattr(window.player, '_player', None)
        metrics['mpv_time_pos'] = getattr(mpv, 'time_pos', None)
        assert len(starts) == 1 and abs(starts[0] - metrics['resume_point']) < 0.01, metrics
        assert metrics['mpv_time_pos'] is not None and metrics['mpv_time_pos'] >= metrics['resume_point'] - 1, metrics
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host)
        settle(600)
        assert page.selected_id == playable.id and page.options['query'] == '실제 재생'
        assert js('document.activeElement.id') == 'library-grid'
        assert js("document.getElementById('library-grid').getAttribute('aria-activedescendant')") == f'video-{playable.id}'
        capture('real-playback-return')
        metrics['checks'].append('실창: 검색 조건 → 무작위 재생 → mpv 이어볼 위치 시작 → Esc 복귀 → 그 영상 선택·격자 초점')
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    try:
        (args.output / f'metrics-{args.count}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
        # 콘솔 인코딩(cp949 등)에서 '▾' 같은 글자를 못 써 UnicodeEncodeError로 끝나지 않게 ASCII로 escape한다.
        print(json.dumps(metrics, ensure_ascii=True, indent=2))
    finally:
        # 결과 출력이 실패해도 트레이 정리는 건너뛰지 않는다.
        wait(lambda: not window.tray.quit_blocker(), 120)
        window.tray.quit()
