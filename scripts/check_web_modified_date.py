"""#193: 수정한 날짜의 검색 조건·정렬·조건 칩·상세 정보 화면 검사.

--offscreen은 영상 0개·몇 개·5,000개(--videos)에서 1100×720 배치를 찍는다. 몇 개(50개 이하)는 실제 파일로
만들어 위치 둘의 가장 이른 날짜, 파일 없음, 모르는 수정 시각, 파일 교체 뒤 다시 검사 반영까지 본다.
--verify는 데스크톱 잠금 안의 실창에서 키보드만으로 직접 지정 범위를 넣고 칩으로 푸는 흐름을 확인한다.
DB와 파일은 임시 폴더에만 만든다.
"""
import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
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
parser.add_argument('--videos', type=int, default=6)
parser.add_argument('--output', type=Path, default=Path('.local/screens-193'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library_views import default_options
from my_video_manager.ui import MainWindow

PANEL = '[aria-label="라이브러리 필터 패널"]'
CHIPS = '[aria-label="적용한 검색 조건"]'
REAL_FILES = args.videos <= 50


class FakeMedia:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        destination.write_bytes(b'thumbnail')


def stamp(path, moment):
    os.utime(path, (moment.timestamp(), moment.timestamp()))


app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-193-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
now = datetime.now(timezone.utc)
core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
# 실제 파일이 없는 합성 위치를 시작 검사가 지우지 않도록 자동 감지를 끈다.
core.set_automatic_detection_enabled(False)
root = directory / '영상'
root.mkdir()
core.add_watched_folder(root)
special = {}
if REAL_FILES:
    paths = []
    for i in range(args.videos):
        path = root / f'영상 {i:02d}.mkv'
        path.write_bytes(f'video {i}'.encode())
        stamp(path, now - timedelta(days=3 * i, hours=1))
        paths.append(path)
    if args.videos >= 3:
        # 0: 위치 둘의 날짜가 다르면 가장 이른 날, 1: 수정 시각 모름, 2: 파일 없음
        copy = root / '복사본' / '영상 00 사본.mkv'
        copy.parent.mkdir()
        copy.write_bytes(paths[0].read_bytes())
        stamp(paths[0], now - timedelta(days=2))
        stamp(copy, now - timedelta(days=20))
    for path in paths:
        core.add_file(path)
    if args.videos >= 3:
        core.add_file(copy)
        paths[2].unlink()
        core.scan()
        by_path = {location.path: video for video in core.videos() for location in video.locations}
        special = {'two_locations': by_path[paths[0]].id, 'unknown': by_path[paths[1]].id,
                   'missing': next(v.id for v in core.videos() if v.missing)}
        with closing(sqlite3.connect(core.database)) as db, db:
            db.execute('UPDATE locations SET mtime_ns=NULL WHERE path=?', (str(paths[1]),))
    if args.videos >= 4:
        watched = next(v for v in core.videos() if v.locations and v.locations[0].path == paths[3])
        core.playback.start(watched.id, 0)
        core.playback.report(30)
        core.playback.end()
        special['viewed'] = watched.id
else:
    # 합성 영상은 640px 썸네일을 미리 두어 유휴 썸네일 갱신이 없는 파일을 읽다가 경고를 띄우지 않게 한다.
    thumbnail = QImage(64, 36, QImage.Format.Format_RGB32)
    thumbnail.fill(QColor('#24354a'))
    thumbnail.save(str(directory / 'thumbnails/demo.640.jpg'))
    with closing(sqlite3.connect(core.database)) as db, db:
        for i in range(args.videos):
            vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
                VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', f'영상 {i:04d}', 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                             now.isoformat(), 1920, 1080)).lastrowid
            if i % 50 == 7:
                continue  # 파일 없음
            mtime = None if i % 77 == 5 else int((now - timedelta(hours=7 * i)).timestamp()) * 10**9
            db.execute('INSERT INTO locations(path,video_id,mtime_ns) VALUES (?,?,?)', (str(root / f'{i}.mp4'), vid, mtime))
metrics = {'videos': args.videos, 'real_files': REAL_FILES, 'special': special, 'checks': [], 'screenshots': [], 'layout': {}}

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


def type_digits(text):
    for digit in text:
        QTest.keyClick(host.view.focusProxy(), Qt.Key(Qt.Key.Key_0.value + int(digit)))
    settle()


def view(**changes):
    result = json.loads(page.bridge.view(json.dumps({**default_options(), **changes})))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def select(video_id):
    result = json.loads(page.bridge.select(video_id))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def capture(name):
    settle()
    path = args.output / f'{args.videos}-{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def open_panel():
    if not js(f"!!document.querySelector('{PANEL}')"):
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='필터').click()")
        wait(lambda: js(f"!!document.querySelector('{PANEL}')"))
    settle()


def close_panel():
    js(f"document.querySelector('{PANEL} [aria-label=\"필터 닫기\"]')?.click()")
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))


def active_label():
    return js("document.activeElement?.getAttribute('aria-label') ?? document.activeElement?.textContent")


def page_overflow():
    return js('document.documentElement.scrollWidth - document.documentElement.clientWidth')


def panel_layout(name):
    """패널이 창 안(가장자리 1rem)에 있고, 머리 줄·"조건 모두 지우기" 줄은 고정, 그 사이 조건 영역만 스크롤하는지 잰다(#381)."""
    state = json.loads(js(f"""JSON.stringify((() => {{
      const e = document.querySelector('{PANEL}'), p = e.getBoundingClientRect()
      const area = e.querySelector('.definition-list'), a = area.getBoundingClientRect()
      const head = e.querySelector('h2').getBoundingClientRect()
      const clear = [...e.querySelectorAll('button')].find(b => b.textContent === '조건 모두 지우기').getBoundingClientRect()
      const inside = r => r.top >= p.top - 0.5 && r.bottom <= p.bottom + 0.5
      return {{ top: p.top, bottom: p.bottom, left: p.left, right: p.right, height: p.height, innerWidth, innerHeight,
        rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
        scrollHeight: area.scrollHeight, clientHeight: area.clientHeight, scrollTop: area.scrollTop,
        panelScroll: e.scrollHeight > e.clientHeight + 1,
        overflowX: e.scrollWidth > e.clientWidth || area.scrollWidth > area.clientWidth,
        headVisible: inside(head) && head.bottom <= a.top + 0.5, clearVisible: inside(clear) && clear.top >= a.bottom - 0.5,
        dateInputs: [...e.querySelectorAll('input[type=date]')].map(i => i.getAttribute('aria-label')) }} }})())"""))
    metrics['layout'][name] = state
    edge = state['rem'] - 1
    assert state['top'] >= edge and state['left'] >= edge, state
    assert state['bottom'] <= state['innerHeight'] - edge and state['right'] <= state['innerWidth'] - edge, state
    assert not state['overflowX'] and not state['panelScroll'], state
    assert state['headVisible'] and state['clearVisible'], state
    return state


def detail_line():
    """상세 정보 `dt`·`dd` 짝(#406)을 '수정한 날짜: 값' 한 줄로 읽는다."""
    return js("(dt => dt ? `${dt.textContent}: ${dt.nextElementSibling?.textContent ?? ''}` : null)([...document.querySelectorAll('#detail-scroll dt')].find(d => d.textContent === '수정한 날짜'))")


def local_day(value):
    return datetime.fromisoformat(value).astimezone().date()


def shown(value):
    """화면의 날짜 모양(#232)."""
    return f'{value.year}. {value.month:02d}. {value.day:02d}.'


def cards():
    return {card['id']: card for card in page.cards}


def check_panel_and_range():
    open_panel()
    labels = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} button[role=combobox]')].map(b => b.getAttribute('aria-label')))"))
    assert '수정한 날짜' in labels and labels.index('추가일') < labels.index('수정한 날짜') < labels.index('마지막 시청'), labels
    panel_layout('default')
    capture('panel-default')
    close_panel()
    today = date.today()
    start, end = (today - timedelta(days=10)).isoformat(), today.isoformat()
    view(modified_preset='custom', modified_from=start, modified_to=end)
    open_panel()
    values = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} input[type=date]')].map(i => [i.getAttribute('aria-label'), i.value]))"))
    assert values == [['수정한 날짜 시작', start], ['수정한 날짜 끝', end]], values
    panel_layout('modified-custom')
    capture('panel-modified-custom')
    visible = [cards()[vid] for vid in page.visible_ids]
    assert all(card['modifiedAt'] and start <= local_day(card['modifiedAt']).isoformat() <= end for card in visible), visible[:3]
    assert not any(card['missing'] for card in visible)
    if args.videos:
        assert visible, '직접 지정 범위에 맞는 영상이 없음'
    metrics['custom_range'] = {'from': start, 'to': end, 'visible': len(visible)}
    close_panel()
    # 세 날짜를 모두 직접 지정하면 패널이 가장 길어진다. 조건 영역만 스크롤해 끝까지 닿는지 본다.
    view(added_preset='custom', modified_preset='custom', viewed_preset='custom')
    open_panel()
    state = panel_layout('all-custom-top')
    assert state['scrollHeight'] > state['clientHeight'] and state['scrollTop'] == 0, state
    capture('panel-scroll-top')
    js(f"document.querySelector('{PANEL} .definition-list').scrollTop = 1e6")
    settle()
    state = panel_layout('all-custom-bottom')
    assert state['scrollTop'] > 0 and state['scrollTop'] + state['clientHeight'] >= state['scrollHeight'] - 1, state
    assert len(state['dateInputs']) == 6, state
    capture('panel-scroll-bottom')
    close_panel()
    metrics['checks'].append(f"검색 조건 패널: 추가일·수정한 날짜·마지막 시청 순서, 직접 지정 입력 2칸, 범위 결과 {len(visible)}개(파일 없음 제외), 조건 영역만 스크롤하고 머리 줄·'조건 모두 지우기' 고정")


def check_sort():
    for descending in (False, True):
        view(sort='modified', descending=descending)
        state = json.loads(js("JSON.stringify({sort: document.querySelector('button[role=combobox][aria-label=\"정렬\"]').textContent, direction: document.querySelector('[aria-label=\"정렬 방향\"]').textContent})"))
        assert state['sort'] == '수정한 날짜', state
        values = [cards()[vid]['modifiedAt'] for vid in page.visible_ids]
        known = [datetime.fromisoformat(v) for v in values if v]
        assert values[:len(known)] == [v for v in values if v], '날짜 없는 영상이 끝에 있지 않음'
        assert known == sorted(known, reverse=descending), descending
        if args.videos:
            first = page.visible_ids[0]
            assert js(f"!!document.getElementById('video-{first}')"), first
        capture('sort-desc' if descending else 'sort-asc')
        metrics.setdefault('sort', {})['desc' if descending else 'asc'] = {'direction': state['direction'], 'known': len(known), 'without': len(values) - len(known)}
    metrics['checks'].append('정렬 선택지 수정한 날짜·오름/내림차순 순서와 날짜 없는 영상(파일 없음·모름) 끝 배치')


def check_chips():
    today = date.today()
    start, end = today - timedelta(days=30), today
    tags = [t.id for t in core.tags()]
    view(added_preset='30', modified_preset='custom', modified_from=start.isoformat(), modified_to=end.isoformat(), viewed_preset='7', viewing='unwatched' if args.videos > 50 else '', tags=tags)
    chips = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{CHIPS} button')].map(b => b.title || b.textContent))"))
    label = f'수정한 날짜: {shown(start)} ~ {shown(end)}'
    assert {'추가일: 최근 30일', label, '마지막 시청: 최근 7일'} <= set(chips), chips
    assert page_overflow() <= 0
    truncated = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{CHIPS} button span')].filter(e => e.scrollWidth > e.clientWidth).map(e => e.textContent))"))
    metrics['truncated_chips'] = truncated
    assert label not in truncated, truncated
    capture('chips-many')
    if 'viewed' in special:
        assert special['viewed'] in page.visible_ids, page.visible_ids
    js(f"document.querySelector('{CHIPS} button[aria-label=\"{label} 지우기\"]').click()")
    wait(lambda: page.options['modified_preset'] == '')
    assert page.options['modified_from'] == page.options['modified_to'] == ''
    assert page.options['added_preset'] == '30' and page.options['viewed_preset'] == '7'
    view(added_preset='30', modified_preset='7', viewed_preset='7')
    js(f"[...document.querySelectorAll('{CHIPS} button')].find(b => b.textContent === '모두 지우기').click()")
    wait(lambda: page.options['modified_preset'] == '' and page.options['added_preset'] == '' and page.options['viewed_preset'] == '')
    view(modified_preset='7')
    open_panel()
    js(f"[...document.querySelectorAll('{PANEL} button')].find(b => b.textContent === '조건 모두 지우기').click()")
    wait(lambda: page.options['modified_preset'] == '')
    close_panel()
    metrics['checks'].append('조건 칩: 추가일·수정한 날짜·마지막 시청 동시 표시, 수정한 날짜 칩만 풀기, 칩 모두 지우기·패널 조건 모두 지우기에 포함')


def check_details():
    view()
    if not args.videos:
        assert not detail_line()
        capture('details-empty')
        return
    items = {}
    targets = {'known': next(card['id'] for card in page.cards if card['modifiedAt']),
               **{name: special[name] for name in ('two_locations', 'unknown', 'missing') if name in special}}
    if not REAL_FILES:
        targets['missing'] = next(card['id'] for card in page.cards if card['missing'])
        targets['unknown'] = next(card['id'] for card in page.cards if not card['missing'] and not card['modifiedAt'])
    for name, video_id in targets.items():
        select(video_id)
        wait(lambda: bool(detail_line()))
        items[name] = detail_line()
        capture(f'details-{name}')
    assert items['missing'] == '수정한 날짜: 파일 없음', items
    assert items['unknown'] == '수정한 날짜: 알 수 없음', items
    assert any(ch.isdigit() for ch in items['known']), items
    if 'two_locations' in items:
        expected = core.video(special['two_locations']).modified_at.astimezone().date()
        assert items['two_locations'] == f'수정한 날짜: {shown(expected)}', (items, expected)
    metrics['details'] = items
    metrics['checks'].append('상세 정보 수정한 날짜: 날짜 표시(위치 둘이면 가장 이른 날)·파일 없음·알 수 없음')


def check_rescan():
    """파일을 바꾸고 다시 검사하면 상세 정보와 거르기가 새 수정 시각을 따른다."""
    video_id = special['two_locations']
    video = core.video(video_id)
    newer = now - timedelta(hours=2)
    for location in video.locations:
        stamp(location.path, newer)
    today = date.today().isoformat()
    view(modified_preset='custom', modified_from=today, modified_to=today)
    assert video_id not in page.visible_ids
    page.scan()
    wait(lambda: page.worker is None, 60)
    settle()
    assert video_id in page.visible_ids, page.visible_ids
    select(video_id)
    expected = newer.astimezone().date()
    wait(lambda: detail_line() == f'수정한 날짜: {shown(expected)}')
    capture('rescan-refreshed')
    # 모르던 수정 시각도 검사로 채워진다.
    assert cards()[special['unknown']]['modifiedAt'] is not None
    view()
    metrics['checks'].append('파일 수정 시각 변경 → 다시 검사 → 오늘 범위 결과와 상세 정보 새 날짜 반영, 모르던 시각 채움')


def enter_date(value):
    """날짜 입력의 칸을 연·월·일 순서로 채운다. 화면 언어는 Windows 로캘과 상관없이 한국어다(#232).

    월·일은 두 자리를 치면 다음 칸으로 넘어가고, 연도는 더 긴 값을 받으므로 오른쪽 화살표로 넘어간다.
    """
    assert js('navigator.language') == 'ko'
    order = ['year', 'month', 'day']
    metrics['date_input_order'] = order
    texts = {'year': f'{value.year}', 'month': f'{value.month:02d}', 'day': f'{value.day:02d}'}
    for i, part in enumerate(order):
        type_digits(texts[part])
        if part == 'year' and i < len(order) - 1:
            key(Qt.Key.Key_Right)


def check_keyboard():
    """키보드만으로 수정한 날짜 직접 지정 범위를 넣고 칩으로 푼다."""
    view()
    js("document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]').focus()")
    for _ in range(12):
        if active_label() == '필터':
            break
        key(Qt.Key.Key_Tab)
    assert active_label() == '필터', active_label()
    key(Qt.Key.Key_Return)
    wait(lambda: js(f"!!document.querySelector('{PANEL}')"))
    for _ in range(20):
        if active_label() == '수정한 날짜':
            break
        key(Qt.Key.Key_Tab)
    assert active_label() == '수정한 날짜', active_label()
    key(Qt.Key.Key_Space)
    wait(lambda: js("!!document.querySelector('[role=listbox]')"))
    key(Qt.Key.Key_End)
    key(Qt.Key.Key_Return)
    wait(lambda: page.options['modified_preset'] == 'custom')
    key(Qt.Key.Key_Tab)
    assert active_label() == '수정한 날짜 시작', active_label()
    today = date.today()
    start = today - timedelta(days=10)
    if args.verify:
        enter_date(start)
        for _ in range(3):
            if active_label() != '수정한 날짜 시작':
                break
            key(Qt.Key.Key_Tab)
        assert active_label() == '수정한 날짜 끝', active_label()
        enter_date(today)
    else:
        # offscreen 창은 활성 창이 아니어서 날짜 입력의 연·월·일 칸이 키를 받지 않는다(일반 입력은 받는다).
        # 날짜 타자는 --verify 실창에서 보고, 여기서는 같은 값을 브리지로 채운 뒤 나머지 키보드 흐름을 본다.
        view(modified_preset='custom', modified_from=start.isoformat(), modified_to=today.isoformat())
        js(f"document.querySelector('{PANEL} [aria-label=\"수정한 날짜 끝\"]').focus()")
    wait(lambda: page.options['modified_from'] == start.isoformat() and page.options['modified_to'] == today.isoformat())
    capture('keyboard-range')
    key(Qt.Key.Key_Escape)
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))
    assert active_label() == '필터', active_label()
    label = f'수정한 날짜: {shown(start)} ~ {shown(today)} 지우기'
    for _ in range(6):
        if active_label() == label:
            break
        key(Qt.Key.Key_Tab)
    assert active_label() == label, active_label()
    key(Qt.Key.Key_Return)
    wait(lambda: page.options['modified_preset'] == '' and page.options['modified_from'] == '')
    capture('keyboard-chip-cleared')
    typed = '시작/끝 날짜 타자' if args.verify else '(날짜 값은 브리지로 채움)'
    metrics['checks'].append(f'키보드: Tab→필터 Enter→수정한 날짜 Space·End·Enter→{typed}→Esc→칩 Tab·Enter로 풀기')


try:
    wait(lambda: js("!!document.getElementById('library-grid') || !!document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]')"))
    settle(400)
    if args.offscreen:
        capture('library')
        check_panel_and_range()
        check_sort()
        check_chips()
        check_details()
        if REAL_FILES and 'two_locations' in special:
            check_rescan()
        if args.videos:
            check_keyboard()
    else:
        assert QTest.qWaitForWindowActive(window, 5000)
        check_keyboard()
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    (args.output / f'metrics-{args.videos}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    wait(lambda: not window.tray.quit_blocker(), 120)
    window.tray.quit()
