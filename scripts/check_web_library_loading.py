"""#260: 라이브러리 첫 진입 자리 표시와 실제 목록의 1100×720 offscreen 스크린샷과 경계 비교.

첫 라이브러리 데이터 응답을 웹 쪽에서 붙잡아 자리 표시 상태를 찍고, 놓아준 뒤 실제 목록을 찍는다.
제품 코드에는 시험용 지연이 없다. 합성 영상과 DB는 임시 폴더에만 기록한다.

python scripts/check_web_library_loading.py --offscreen --count 24
python scripts/check_web_library_loading.py --offscreen --count 5000
python scripts/check_web_library_loading.py --offscreen --count 24 --long-content
python scripts/check_web_library_loading.py --offscreen --count 24 --fail-first

기본 카드 크기(보통)에서 툴바나 첫 줄 카드가 움직이면 0이 아닌 종료 코드로 끝난다.
--fail-first는 첫 스냅숏을 실패 응답으로 바꿔 실패 상태(안내를 보일 때와 닫은 뒤)를 찍는다.
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
parser.add_argument('--count', type=int, default=24)
parser.add_argument('--long-content', action='store_true', help='긴 제목·태그·시리즈 이름')
parser.add_argument('--card-size', choices=('small', 'medium', 'large'), default='medium', help='저장된 카드 크기')
parser.add_argument('--fail-first', action='store_true', help='첫 라이브러리 스냅숏이 실패한 상태')
parser.add_argument('--output', type=Path, default=Path('.local/screens-260'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library_views import default_options
from my_video_manager.ui import MainWindow
from my_video_manager.web_shell import WebShellHost


class DemoMedia:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        raise OSError('합성 영상은 썸네일을 미리 넣는다')


app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-260-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
core = AppCore(media=DemoMedia(), clock=lambda: datetime(2026, 10, 28, tzinfo=timezone.utc), database=directory / 'library.sqlite3')
core.set_automatic_detection_enabled(False)
core.save_library_view_options({**default_options(), 'card_size': args.card_size})
image = QImage(640, 360, QImage.Format.Format_RGB32)
image.fill(QColor('#24354a'))
painter = QPainter(image)
painter.setPen(QColor('#ffffff'))
painter.setFont(QFont('Malgun Gothic', 24))
painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, '640 × 360 · Library')
painter.end()
(directory / 'thumbnails').mkdir(exist_ok=True)
assert image.save(str(directory / 'thumbnails/demo.640.jpg'))
root = directory / 'videos'
with closing(sqlite3.connect(core.database)) as db, db:
    for i in range(args.count):
        title = f'영상 {i:04d} ' + ('아주 긴 한글 제목과 공백 없는 EnglishTitle' * 6 if args.long_content else '라이브러리 검증')
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', title, 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / f'{i}.mp4'), vid))
if args.long_content:
    for video in core.videos()[:6]:
        for index in range(3):
            core.add_video_tag(video.id, f'{index} 긴 태그 이름 ' + '태그' * 12)

# 문서가 만들어질 때 웹 채널의 첫 라이브러리 스냅숏 응답을 붙잡는다. 놓아주는 것은 window.__releaseLibrary().
# --fail-first면 붙잡지 않고 실패 응답으로 바꾼다.
HOLD = """(() => {
  let held = %(hold)s, release = null, channelClass
  const failed = %(fail)s
  window.__releaseLibrary = () => { held = false; release?.() }
  Object.defineProperty(window, 'QWebChannel', { configurable: true, get: () => channelClass, set(Original) {
    channelClass = function (transport, ready) {
      return new Original(transport, channel => {
        const library = channel.objects.library, snapshot = library.snapshot
        library.snapshot = reply => snapshot.call(library, json => {
          if (failed) json = JSON.stringify({ error: '라이브러리를 읽지 못했습니다.' })
          if (held) release = () => reply(json); else reply(json)
        })
        ready(channel)
      })
    }
  } })
})()"""
start = WebShellHost.start


def hold_first_snapshot(host):
    script = QWebEngineScript()
    script.setName('hold-library')
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setSourceCode(HOLD % {'hold': json.dumps(not args.fail_first), 'fail': json.dumps(args.fail_first)})
    host.engine_page.scripts().insert(script)
    start(host)


WebShellHost.start = hold_first_snapshot
window = MainWindow(core)
window.resize(1100, 720)
window.show()
host = window.web_host


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


def frames(count=2):
    js(f"window.__frames = 0; (function step() {{ if (++window.__frames < {count + 1}) requestAnimationFrame(step) }})()")
    wait(lambda: js('window.__frames') > count)
    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()


LAYOUT = """JSON.stringify((() => {
  const box = selector => { const e = document.querySelector(selector); if (!e) return null; const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(v => Math.round(v * 10) / 10) }
  const grid = document.getElementById('library-grid'), columns = Number(grid.getAttribute('aria-colcount'))
  const cells = [...grid.querySelectorAll('[role=gridcell], [data-slot=video-card-placeholder]')].slice(0, columns).map(cell => { const r = cell.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(v => Math.round(v * 10) / 10) })
  return { busy: grid.getAttribute('aria-busy'), columns, cells,
    toolbar: Object.fromEntries(['[aria-label="영상 제목 빠른 검색"]', 'button[aria-label="카드 크기"]', 'button[aria-label="정렬"]', 'button[aria-label="정렬 방향"]',
      '[aria-label="무작위 재생"]', 'button[aria-label="폴더 패널"]', '#library-grid', 'aside[aria-label="선택 영상 상세"]'].map(selector => [selector, box(selector)])),
    status: document.querySelector('[data-slot=pending-status]')?.textContent ?? null,
    count: document.querySelector('[aria-label="라이브러리 등록·표시 개수"]')?.textContent ?? null,
    text: document.querySelector('main[aria-label="라이브러리"]').innerText }
})())"""
name = f'library-{args.count}{"-long" if args.long_content else ""}{"" if args.card_size == "medium" else "-" + args.card_size}'
if args.fail_first:
    # 실패는 끝난 상태다. 기다림 표시·aria-busy·자리 표시 없이 격자 자리에 읽지 못했다는 안내가 남는다.
    wait(lambda: '라이브러리를 읽지 못했습니다.' in js("document.querySelector('main').innerText"))
    frames()
    failed = json.loads(js(LAYOUT))
    assert window.grab().save(str(args.output / f'{name}-failed.png'))
    js("document.querySelector('button[aria-label=\"안내 닫기\"]').click()")
    wait(lambda: '라이브러리를 읽지 못했습니다.' not in js("document.querySelector('main').innerText"))
    deadline = js('performance.now()') + 600
    wait(lambda: js('performance.now()') > deadline)
    frames()
    dismissed = json.loads(js(LAYOUT))
    assert window.grab().save(str(args.output / f'{name}-failed-dismissed.png'))
    # 숨은 다른 탭(통계·추천)의 첫 데이터 전 자리 표시는 세지 않는다.
    busy = js("document.querySelector('main[aria-label=\"라이브러리\"]').querySelectorAll('[aria-busy=true], [data-slot=video-card-placeholder], [data-slot=skeleton]').length")
    print(json.dumps({
        'case': f'{name}-failed', 'busy': [failed['busy'], dismissed['busy']], 'status': [failed['status'], dismissed['status']],
        'busy_or_placeholder_elements': busy, 'moved_after_dismiss': sorted(key for key in failed['toolbar'] if failed['toolbar'][key] != dismissed['toolbar'][key]),
        'screenshots': [str((args.output / f'{name}-{state}.png').resolve()) for state in ('failed', 'failed-dismissed')],
    }, ensure_ascii=False), flush=True)
    assert failed['busy'] == dismissed['busy'] == 'false' and failed['status'] == dismissed['status'] == '' and busy == 0
    assert all('영상 목록을 읽지 못했습니다' in state['text'] and '불러오는 중' not in state['text'] for state in (failed, dismissed))
    window.tray.quit()
    raise SystemExit(0)
wait(lambda: js("document.querySelector('[data-slot=pending-status]')?.textContent") == '불러오는 중…')
frames()
loading = json.loads(js(LAYOUT))
assert window.grab().save(str(args.output / f'{name}-loading.png'))
js('window.__releaseLibrary()')
wait(lambda: js("document.getElementById('library-grid').getAttribute('aria-busy')") == 'false')
frames()
loaded = json.loads(js(LAYOUT))
assert window.grab().save(str(args.output / f'{name}-loaded.png'))
moved = sorted(selector for selector in loaded['toolbar'] if loaded['toolbar'][selector] != loading['toolbar'][selector])
cells_same = loaded['cells'] == loading['cells'] if loaded['cells'] else None
assert '라이브러리가 비어 있습니다' not in loading['text'] and '선택한 영상 없음' not in loading['text'] and '0개' not in loading['text']
print(json.dumps({
    'case': name, 'columns': [loading['columns'], loaded['columns']], 'toolbar_moved': moved, 'first_row_same': cells_same,
    'loading_status': loading['status'], 'loaded_count': loaded['count'],
    'empty_message': '라이브러리가 비어 있습니다' in loaded['text'],
    'screenshots': [str((args.output / f'{name}-{state}.png').resolve()) for state in ('loading', 'loaded')],
}, ensure_ascii=False), flush=True)
# 저장된 카드 크기가 보통이 아니면 데이터 전에 알 수 없어 달라진다(#267). 기본 크기에서만 경계가 같아야 한다.
if args.card_size == 'medium':
    assert not moved, f'데이터 전후 툴바가 움직였다: {moved}'
    assert cells_same is not False, '데이터 전후 첫 줄 카드 경계가 다르다'
window.tray.quit()
