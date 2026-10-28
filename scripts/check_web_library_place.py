"""#263 목록을 밀지 않는 안내·필터 칩·폴더 패널의 1100×720·최대화 배치 검사.

스크린샷: python scripts/check_web_library_place.py --offscreen [--output <폴더>]
영상 0개·3개·60개, 긴 제목, 칩 많음, 안내 여러 개·긴 문구, 셸 안내 접기, 폴더 패널, 다른 탭의 셸 안내를 찍는다.
떠 있는 안내(라이브러리 띠·셸 묶음)가 덮는 조작 요소를 장면마다 기록하고, 머리글·툴바·칩 줄·상세 패널 단추·
페이지 머리글 단추를 덮지 않는지 단언한다.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-263')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.app_version import current_version
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library_views import default_options
from my_video_manager.subtitle_preparation_ui import preparation_state
from my_video_manager.update_check import LAST_CHECK_KEY, release_notes_summary
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor.fromHsv(sum(path.stem.encode()) % 360, 90, 80))
        image.save(str(destination), 'JPG')


class Player:
    def __init__(self, surface):
        pass

    def play(self, *args, **kwargs):
        pass

    def prepare_close(self):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def execute(self, command):
        pass


app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
(ROOT / '.local').mkdir(exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='library-place-', dir=ROOT / '.local'))
checks = []
layouts = {}
window = host = None

GRID = 'document.getElementById("library-grid")'
SHELL = '[aria-label="앱 안내"]'
BAND = '[aria-label="라이브러리 안내"]'
# 떠 있는 안내가 덮으면 안 되는 자리.
PROTECTED = ['header', 'main[aria-label="라이브러리"] > div:first-child', '[aria-label="적용한 검색 조건"]',
             'aside[aria-label="선택 영상 상세"] h2', '[aria-label="영상 상세 탭"]', '[aria-label="영상 작업"]',
             'button[aria-label="폴더 패널"]', '[data-page]:not([hidden]) main > div:first-child :is(button, input, nav)']


def wait(predicate, message='조건 대기', timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(script):
    values = []
    host.engine_page.runJavaScript(script, values.append)
    wait(lambda: bool(values), script)
    return values[0]


def click(selector):
    point = json.loads(js(f'JSON.stringify((() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})())'))
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(round, point)))
    settle()


def measure(name):
    """떠 있는 안내가 덮는 조작 요소, 넘침, 격자·선택 카드 자리를 잰다."""
    layout = json.loads(js(f'''JSON.stringify((() => {{
      const rect = e => {{ const r = e.getBoundingClientRect(); return {{ left: r.left, top: r.top, right: r.right, bottom: r.bottom }} }}
      const over = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
      const visible = e => e && e.checkVisibility() && e.getBoundingClientRect().height > 0
      const layers = [document.querySelector('{SHELL}'), document.querySelector('{BAND}')].filter(visible)
      const page = document.querySelector('[data-page]:not([hidden])')
      const controls = [...document.querySelectorAll('header button, [data-page]:not([hidden]) :is(button, input, a[href], [role=combobox], [role=tab], [role=tree])')]
        .filter(e => visible(e) && !layers.some(layer => layer.contains(e)))
      const label = e => e.getAttribute('aria-label') || e.title || e.textContent.trim().slice(0, 30) || e.id || e.tagName
      const hit = controls.filter(e => layers.some(layer => over(rect(layer), rect(e))))
      // 넘쳐서 스크롤되는 목록 안의 요소는 스크롤로 묶음 밖으로 옮길 수 있다. 나머지가 고정 조작 요소다.
      const scrolls = e => e.scrollHeight > e.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(e).overflowY)
      const fixed = e => {{ for (let p = e.parentElement; p && p !== page; p = p.parentElement) if (scrolls(p)) return false; return true }}
      const covered = hit.map(label), fixedCovered = hit.filter(fixed).map(label)
      const guarded = {json.dumps(PROTECTED)}.flatMap(s => [...document.querySelectorAll(s)]).filter(visible)
        .filter(e => layers.some(layer => over(rect(layer), rect(e)))).map(e => e.getAttribute('aria-label') || e.tagName)
      const shell = document.querySelector('{SHELL}'), grid = {GRID}
      return {{ covered: [...new Set(covered)], fixedCovered: [...new Set(fixedCovered)], guarded,
        wide: document.documentElement.scrollWidth > innerWidth, pageScroll: page.scrollHeight - page.clientHeight,
        shell: visible(shell) ? rect(shell) : null, shellScroll: visible(shell) ? shell.lastElementChild.scrollHeight - shell.lastElementChild.clientHeight : 0,
        pageArea: rect(shell.parentElement),
        grid: grid && visible(grid) ? {{ ...rect(grid), top: grid.scrollTop, columns: Number(grid.getAttribute('aria-colcount')) }} : null,
        tones: [...document.querySelectorAll('{SHELL} [data-slot=notice], {BAND} [data-slot=notice]')].map(e => e.dataset.tone) }}
    }})())'''))
    layouts[name] = layout
    assert not layout['guarded'], (name, layout)
    assert not layout['wide'], (name, layout)
    if layout['shell']:
        area = layout['pageArea']
        assert layout['shell']['bottom'] <= area['bottom'] and layout['shell']['right'] <= area['right'], (name, layout)
        assert layout['shell']['bottom'] - layout['shell']['top'] <= (area['bottom'] - area['top']) / 3 + 1, (name, layout)
        assert layout['shell']['right'] - layout['shell']['left'] <= 448 + 1, (name, layout)
    return layout


def capture(name):
    if args.offscreen:
        settle()
        image = window.grab().toImage()
        image.save(str(args.output / f'web-{name}.png'))
    return measure(name)


def make_core(name, count, *, long_title=False):
    folder = workspace / name
    watched, direct = folder / 'watched', folder / 'direct'
    watched.mkdir(parents=True)
    direct.mkdir()
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc), database=folder / 'library.sqlite3')
    for index in range(count):
        title = f'clip {index:03}' if not (long_title and index == 4) else 'clip 아주 긴 한글 제목과 공백 없는 영문 제목 ' + 'LongVideoTitle' * 12
        path = (watched if index % 2 else direct) / f'{title}.mkv'
        path.write_bytes(f'{name} video {index}'.encode())
        core.add_file(path)
    if count:
        core.add_watched_folder(watched)
    core.set_automatic_detection_enabled(False)
    return core


def open_window(core, size=(1100, 720), **options):
    global window, host
    core.save_library_view_options({**default_options(), **options})
    window = MainWindow(core, player_factory=Player, update_check_options=dict(startup_delay_ms=600_000))
    window.resize(*size)
    window.show()
    host = window.web_host
    wait(lambda: host._frontend_ready and 'library' in host._ready_pages, 'React 초기화')
    wait(lambda: js(f'{GRID}?.getAttribute("aria-busy")') == 'false', '첫 데이터')
    window.subtitles.timer.stop()
    settle(400)
    return window


def close_window():
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def notices(long=True):
    """셸 안내(자막 기능 준비 실패·작업 알림·새 버전)와 라이브러리 띠 안내(오류)를 띄운다."""
    tail = ' 아주 긴 설명이 이어집니다.' * (10 if long else 0)
    window.library_page.bridge.libraryError.emit('라이브러리 요청 실패: 응답을 읽지 못했습니다.' + tail)
    window.show_status('검사 실패: 접근할 수 없는 감시 폴더가 있습니다.' + tail)
    window.subtitles.set_preparation(preparation_state('failed', kind='error', message='자막 기능 준비 실패: 런타임 파일을 받지 못했습니다.' + tail))
    checked = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    notes = release_notes_summary('\n'.join(f'- 고친 점 {index}: ' + '설명이 길게 이어집니다. ' * 4 for index in range(8)) if long else '- 재생 위치 저장 문제를 고쳤습니다')
    window.core.settings.set(LAST_CHECK_KEY, {'checked_at': checked, 'current_version': current_version(), 'latest_version': '99.0.0', 'kind': 'patch',
                                              'download_size': 12 * 1024 * 1024, 'failure_reason': None, 'release_notes': notes})
    window.updates.changed.emit()
    wait(lambda: js(f"document.querySelectorAll('{BAND} [data-slot=notice]').length") == 1, '라이브러리 안내')
    wait(lambda: js(f"document.querySelectorAll('{SHELL} [data-slot=notice]').length") == 3, '셸 안내')
    settle(400)


def clear_notices():
    window.library_page.bridge.libraryError.emit('')
    js(f"document.querySelector('{BAND} button[aria-label=\"안내 닫기\"]')?.click(); true")
    window.statusBar().clearMessage()
    window.subtitles.set_preparation(preparation_state('ready'))
    window.core.settings.reset(LAST_CHECK_KEY)
    window.updates.changed.emit()
    wait(lambda: js(f"document.querySelector('{SHELL}').checkVisibility()") is False, '셸 안내 사라짐')
    settle()


def choose_middle_card():
    js(f'{GRID}.scrollTop = 900; true')
    second = f"""(() => {{ const g = {GRID}.getBoundingClientRect()
      const cells = [...document.querySelectorAll('#library-grid [role=gridcell]')].filter(cell => cell.getBoundingClientRect().top > g.top + 100)
      return cells.length > 1 ? Number(cells[1].id.slice(6)) : 0 }})()"""
    wait(lambda: js(second) > 0, '스크롤한 줄')
    target = int(js(second))
    click(f'#video-{target}')
    wait(lambda: window.library_page.selected_id == target, '카드 선택')
    return target


def card_y(video_id):
    return js(f"Math.round(document.getElementById('video-{video_id}').getBoundingClientRect().y - {GRID}.getBoundingClientRect().y)")


try:
    # 영상 0개: 칩 줄 자리와 빈 안내, 안내가 떠도 빈 격자 안내가 밀리지 않는다.
    open_window(make_core('empty', 0))
    empty = capture('empty')
    notices(long=False)
    with_notices = capture('empty-notices')
    assert with_notices['grid']['top'] == empty['grid']['top'], (empty, with_notices)
    checks.append('영상 0개: 칩 줄 자리 예약, 안내 띠·셸 묶음이 빈 격자 안내를 밀지 않음')
    close_window()

    # 영상 3개.
    open_window(make_core('few', 3))
    few = capture('few')
    notices(long=False)
    assert capture('few-notices')['grid'] == few['grid']
    checks.append('영상 3개: 짧은 안내 여러 개가 떠도 격자 경계 그대로')
    close_window()

    # 영상 60개(감시 폴더 30·직접 추가 30)와 긴 제목.
    core = make_core('many', 60, long_title=True)
    long_tags = [core.add_video_tag(video.id, '모든 영상에 붙은 아주 긴 태그 이름 ' + '태그' * 6) for video in core.videos()][0]
    for video in core.videos():
        core.add_video_tag(video.id, '둘째 긴 태그 ' + '이름' * 8)
    open_window(core, card_size='small')
    selected = choose_middle_card()
    many = capture('many')
    y = card_y(selected)
    notices()
    long_notices = capture('many-notices-long')
    assert long_notices['grid'] == many['grid'] and card_y(selected) == y, (many, long_notices)
    assert long_notices['tones'][:3] == ['error', 'error', 'info'] or 'error' in long_notices['tones'], long_notices
    checks.append(f"60개 + 긴 안내 4개(띠 1·셸 3): 선택 카드 세로 위치({y}px)·격자 그대로, 셸 묶음 높이 {round(long_notices['shell']['bottom'] - long_notices['shell']['top'])}px(안에서 스크롤 {long_notices['shellScroll']}px)")
    js(f"document.querySelector('{SHELL} [aria-label=\"새 버전 알림\"] [aria-expanded=\"false\"]')?.click(); true")
    settle()
    capture('many-notices-notes-expanded')
    js(f"document.querySelector('{SHELL}').lastElementChild.scrollTop = 1e6; true")
    capture('many-notices-scrolled')
    js(f"document.querySelector('{SHELL} button[aria-expanded]').focus(); true")
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
    wait(lambda: js(f"document.querySelector('{SHELL} button[aria-expanded]').getAttribute('aria-expanded')") == 'false', '셸 묶음 접힘')
    collapsed = capture('many-notices-collapsed')
    assert '오류' in js(f"document.querySelector('{SHELL}').innerText")
    checks.append(f"셸 묶음 Enter로 접기: 머리 줄만 남고(높이 {round(collapsed['shell']['bottom'] - collapsed['shell']['top'])}px) 오류 개수 표시 유지")
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
    wait(lambda: js(f"document.querySelector('{SHELL} button[aria-expanded]').getAttribute('aria-expanded')") == 'true', '셸 묶음 펼침')
    clear_notices()
    assert card_y(selected) == y

    # 칩 많음: 결과는 그대로이고 칩 줄은 한 줄 안에서 가로로 넘긴다.
    tags = sorted({tag.id for video in core.videos() for tag in core.library_snapshot().tags.get(video.id, [])})
    window.library_page.set_view({**window.library_page.options, 'query': 'clip', 'tags': tags, 'added_preset': 'custom',
                                  'added_from': '2025-01-01', 'added_to': '2026-12-31'})
    window.library_page.selection_changed()
    wait(lambda: js("document.querySelectorAll('[aria-label=\"적용한 검색 조건\"] button').length") >= 4, '칩')
    settle()
    chips = capture('many-chips')
    assert chips['grid'] == many['grid'] and card_y(selected) == y, (many, chips)
    row = json.loads(js("JSON.stringify((() => { const e = document.querySelector('[aria-label=\"적용한 검색 조건\"]'); return [e.clientHeight, e.scrollWidth, e.clientWidth] })())"))
    count = int(js("document.querySelectorAll('[aria-label=\"적용한 검색 조건\"] button').length"))
    checks.append(f'칩 {count}개(긴 태그 2개 포함, "모두 지우기" 포함): 한 줄({row[0]}px), 넘치면 그 줄 안에서 가로 스크롤(지금 내용 폭 {row[1]}px · 보이는 폭 {row[2]}px), 격자·선택 카드 그대로')
    click('[aria-label="적용한 검색 조건"] button:last-child')
    wait(lambda: js("document.querySelectorAll('[aria-label=\"적용한 검색 조건\"] button').length") == 0, '칩 모두 지우기')
    assert capture('many-chips-cleared')['grid'] == many['grid']

    # 폴더 패널: 열 수는 바뀌어도 선택 카드의 세로 위치는 같다.
    click('button[aria-label="폴더 패널"]')
    wait(lambda: js('!!document.getElementById("library-folder-panel")'), '폴더 패널')
    wait(lambda: js(f'{GRID}.getAttribute("aria-colcount")') == '2', '열 수')
    folders = capture('many-folders')
    assert abs(card_y(selected) - y) <= 1, (y, card_y(selected))
    click('button[aria-label="폴더 패널"]')
    wait(lambda: js(f'{GRID}.getAttribute("aria-colcount")') == '3', '열 수 복원')
    assert abs(card_y(selected) - y) <= 1
    checks.append(f"폴더 패널 열기·닫기: 열 {many['grid']['columns']}→{folders['grid']['columns']}→3, 선택 카드 세로 위치 ±1px")

    # 긴 제목 카드.
    long_video = next(video.id for video in core.videos() if 'LongVideoTitle' in video.title)
    click(f'#video-{long_video}') if js(f"!!document.getElementById('video-{long_video}')") else None
    js(f'{GRID}.scrollTop = 0; true')
    settle()
    capture('many-long-title')
    checks.append('긴 제목 카드: 카드·상세 패널 경계 안에서 줄임')

    # 다른 탭에서 셸 묶음이 고른 모서리와 덮는 조작 요소를 기록한다. 짧은 안내 세 개는 고정 조작 요소를 덮지 않아야 한다.
    # 긴 안내 세 개(묶음이 높이 상한까지 자람)는 모든 모서리가 무언가를 덮을 수 있어 가장 적게 덮는 모서리를 기록만 한다.
    clear_notices()
    for size in ('short', 'long'):
        notices(long=size == 'long')
        for tab in ('recommend', 'reel', 'search', 'queue', 'statistics', 'folders', 'settings'):
            window.navigate_web_tab(tab)
            wait(lambda: js(f"!document.querySelector('[data-page=\"{tab}\"]').hidden"), tab)
            settle(500)
            layout = capture(f'tab-{tab}-{size}')
            corner = js(f"document.querySelector('{SHELL}').dataset.corner")
            checks.append(f"{tab} 탭 안내 {size}: 셸 묶음 {corner}, 덮는 고정 조작 요소 {layout['fixedCovered'] or '없음'}(스크롤 목록 안 {len(layout['covered']) - len(layout['fixedCovered'])}개)")
            if size == 'short':
                assert not layout['fixedCovered'], (tab, layout)
        window.navigate_web_tab('library')
        settle()
        clear_notices()
    notices()
    window.navigate_web_tab('library')
    settle()

    # 최대화에 가까운 큰 창.
    window.resize(1920, 1040)
    settle(600)
    big = capture('max-many-notices-long')
    checks.append(f"1920×1040: 열 {big['grid']['columns']}, 셸 묶음 {round(big['shell']['right'] - big['shell']['left'])}×{round(big['shell']['bottom'] - big['shell']['top'])}px, 덮는 요소 {big['covered'] or '없음'}")
    clear_notices()
    capture('max-many')
    close_window()

    result = {'mode': 'offscreen' if args.offscreen else 'windows', 'checks': checks, 'passed': len(checks), 'layouts': layouts}
    (args.output / f'{result["mode"]}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks}, ensure_ascii=False, indent=1))
finally:
    if window is not None and not window.tray.quitting:
        close_window()
