"""통계 페이지의 1100×720 화면, 키보드, 실제 mpv 왕복 검사.

스크린샷: python scripts/check_web_statistics.py --offscreen --count 50000
실창: desktop_lock.py run --owner issue-52 -- python scripts/check_web_statistics.py --verify
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import tempfile
import sys
import time
from threading import Event

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--count', type=int, choices=(0, 8, 50000), default=8)
parser.add_argument('--verify', action='store_true')
parser.add_argument('--empty-library', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-52')
args = parser.parse_args()
if args.empty_library and (args.count != 0 or args.verify):
    parser.error('--empty-library는 --count 0의 스크린샷 검사에만 사용합니다')
sample = 'empty' if args.empty_library else str(args.count)
os.environ['MVM_WEB_UI'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QThreadPool, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow

app = QApplication([])
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='statistics-', dir=args.output.parent))
now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


class Media:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor('#18181b'))
        image.save(str(destination), 'JPG')


core = AppCore(media=Media(), clock=lambda: now, database=directory / 'library.sqlite3')
source = directory / '실제 재생 확인.mkv'
if args.verify:
    from my_video_manager.adapters import FFmpegMediaReader
    subprocess.run([str(FFmpegMediaReader().ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=indigo:s=320x180:r=24:d=100', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-y', str(source)], check=True)
else:
    source.write_bytes(b'statistics demo')
if not args.empty_library:
    core.add_file(source)
    first = core.videos()[0]
    core.rename_video(first.id, '긴 제목도 목록 너비를 넘지 않습니다 ' + 'LongVideoTitle' * 16)
    with sqlite3.connect(core.database) as db:
        video_count = 5000 if args.count == 50000 else 6
        db.executemany('INSERT INTO videos (id,fingerprint,title,duration,format,thumbnail,registered_at) VALUES (?,?,?,?,?,?,?)',
                       [(i, f'demo-{i}', f'시청 기록 영상 {i:04}', (300, 900, 2700, 5400, 10800)[i % 5], ('matroska,webm', 'mov,mp4,m4a,3gp,3g2,mj2', 'avi')[i % 3], first.thumbnail.name,
                         (now - timedelta(days=i % 365)).isoformat()) for i in range(2, video_count + 1)])
        db.executemany('INSERT INTO locations (path,video_id,size) VALUES (?,?,?)',
                       [(str(directory / f'video-{i}.mkv'), i, i * 10000000 if i % 10 else None) for i in range(2, video_count + 1)])
        rows = []
        for i in range(args.count):
            # 730일에 분/초/마이크로초를 퍼뜨려 분 단위 메모에 유리하지 않게 한다.
            when = now - timedelta(seconds=(i * 123457) % (730 * 86400), microseconds=i * 17)
            seconds = (1, 95, 45, 25)[i % 4]
            vid = i % video_count + 1
            if vid == 1:
                seconds = 95
            rows.append((vid, 100, when.isoformat(), when.isoformat(), when.isoformat(), json.dumps([[0, seconds]]), seconds))
        if args.count:
            # 항상 긴 제목의 영상이 상위 목록에 들어가게 한다.
            rows[-1] = (1, 100, now.isoformat(), now.isoformat(), now.isoformat(), '[[0,95]]', 95)
        db.executemany('INSERT INTO viewings (video_id,duration,started_at,updated_at,ended_at,intervals,last_position) VALUES (?,?,?,?,?,?,?)', rows)
    db.close()

window = MainWindow(core)
window.resize(1100, 720)
window.show()
if not args.offscreen:
    window.raise_()
    window.activateWindow()
host = window.web_host
page = host.controllers['statistics']
checks = []


def settle(milliseconds=100):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def wait(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        settle(25)
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def key(value, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy(), value, modifiers)
    settle(100)


def content_ready(days):
    wait(lambda: page.result is not None and page.result['period']['days'] == days and not page.loading)
    wait(lambda: bool(js(f"document.querySelector('main[aria-label=통계]')?.textContent.includes('{page.result['period']['start_date']}')")))
    settle(150)


def check_chart(index, values, *, count=False, labels=None):
    chart = json.loads(js(f"""JSON.stringify((() => {{
      const chart = document.querySelectorAll('[data-slot=chart]')[{index}];
      return {{
        role: chart.getAttribute('role'), name: chart.getAttribute('aria-label'),
        ticks: [...chart.querySelectorAll('.recharts-yAxis-tick-labels text')].map(e => Number(e.textContent.replaceAll(',', ''))),
        labels: [...chart.querySelectorAll('.recharts-xAxis-tick-labels text')].map(e => e.textContent),
        grid: [...chart.querySelectorAll('.recharts-cartesian-grid-horizontal line')].map(e => Number(e.getAttribute('y1'))),
        bars: [...chart.querySelectorAll('.recharts-bar-rectangle path')].map(e => Number(e.getAttribute('height')))
      }};
    }})())"""))
    maximum = max(values)
    divisor = 1 if count else 3600 if maximum >= 3600 else 60 if maximum >= 60 else 1
    axis_max = max(chart['ticks']) * divisor
    assert chart['role'] == 'figure' and chart['name']
    assert min(chart['ticks']) == 0 and axis_max >= maximum, (index, chart)
    # 시간도 표시 단위(초/분/시간)에서 정수 눈금이어야 한다.
    assert all(value.is_integer() for value in map(float, chart['ticks'])), (index, chart)
    if labels is not None:
        assert chart['labels'] == labels, (index, chart['labels'])
    if maximum:
        height = max(chart['grid']) - min(chart['grid'])
        assert abs(max(chart['bars']) / height - maximum / axis_max) < 0.01, (index, chart)


def check_refresh_keeps_content():
    original = core.statistics_dashboard
    started, release = Event(), Event()
    def slow(days):
        started.set()
        assert release.wait(10)
        return original(days)
    core.statistics_dashboard = slow
    js("document.querySelector('main[aria-label=통계]').scrollTop=200; globalThis.previousStatisticsChart=document.querySelector('[data-slot=chart]')")
    scroll = js("document.querySelector('main[aria-label=통계]').scrollTop")
    page.bridge.setPeriod(365)
    try:
        wait(started.is_set)
        wait(lambda: js("document.querySelector('main[aria-label=통계]').getAttribute('aria-busy')") == 'true')
        assert page.result['period']['days'] == 30
        assert js("document.querySelector('[data-slot=chart]') === globalThis.previousStatisticsChart")
        assert js("document.querySelector('main[aria-label=통계]').scrollTop") == scroll
    finally:
        release.set()
        core.statistics_dashboard = original
    content_ready(365)
    assert js("document.querySelector('main[aria-label=통계]').getAttribute('aria-busy')") == 'false'
    assert js("document.querySelector('[data-slot=chart]') === globalThis.previousStatisticsChart")
    assert js("document.querySelector('main[aria-label=통계]').scrollTop") == scroll
    checks.append('재계산 중 이전 본문·스크롤 보존, aria-busy true → false')


try:
    wait(lambda: bool(js("!!document.querySelector('[data-tab=statistics]')")))
    window.navigate_web_tab('statistics')
    content_ready(30)
    check_refresh_keeps_content()
    for days in (7, 30, 90, 365):
        js(f"document.querySelector('nav[aria-label=\"통계 기간\"] [data-tab=\"{days}\"]').click()")
        content_ready(days)
        expected = json.loads(json.dumps(asdict(core.statistics_dashboard(days))))
        assert json.loads(json.dumps(page.result)) == expected
        for metric in ('watched_seconds', 'viewing_count'):
            js(f"document.querySelector('nav[aria-label=\"통계 지표\"] [data-tab=\"{metric}\"]').click()")
            settle(200)
            assert js("document.querySelector('main[aria-label=통계]').scrollWidth <= document.querySelector('main[aria-label=통계]').clientWidth")
            assert js("document.querySelectorAll('main[aria-label=통계] .recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value').length > 0")
            check_chart(0, [day[metric] for day in expected['period']['daily']], count=metric == 'viewing_count')
            if args.offscreen:
                js("document.querySelector('main[aria-label=통계]').scrollTop=0")
                settle()
                window.grab().save(str(args.output / f'{sample}-{days}-{metric}.png'))
                js("document.querySelector('main[aria-label=통계]').scrollTop=99999")
                settle()
                window.grab().save(str(args.output / f'{sample}-{days}-{metric}-lower.png'))
            checks.append(f'{days}일/{metric}: 데이터 일치, 표시 단위 정수 눈금·막대 비율, 접근성 이름, 가로 넘침 없음')
        check_chart(1, expected['weekday_seconds'], labels=list('일월화수목금토'))
        check_chart(2, expected['hourly_seconds'], labels=[f'{hour}시' for hour in range(0, 24, 3)])
        checks.append(f'{days}일/요일·시간대: 정수 시간 눈금·막대 비율, 요일 7개·3시간 간격 축')
        if args.offscreen:
            js("document.querySelectorAll('[data-slot=chart]')[1].scrollIntoView({block:'center'})")
            settle()
            window.grab().save(str(args.output / f'{sample}-{days}-activity.png'))
            js("document.querySelector('nav[aria-label=\"통계 구역\"] [data-tab=inventory]').click()")
            settle()
            js("document.querySelector('main[aria-label=통계]').scrollTop=0")
            settle()
            window.grab().save(str(args.output / f'{sample}-{days}-inventory.png'))
            js("document.querySelector('main[aria-label=통계]').scrollTop=99999")
            settle()
            window.grab().save(str(args.output / f'{sample}-{days}-inventory-lower.png'))
            js("document.querySelector('nav[aria-label=\"통계 구역\"] [data-tab=activity]').click()")
            settle()
    if args.verify:
        # 실제 WebEngine 포커스에서 Tab/Space만으로 기간과 지표를 선택한다.
        host.focus_content()
        wait(lambda: js("document.activeElement?.getAttribute('data-tab')") == '365')
        key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        key(Qt.Key.Key_Space)
        content_ready(90)
        assert page.days == 90
        key(Qt.Key.Key_Tab)
        key(Qt.Key.Key_Tab)
        key(Qt.Key.Key_Tab)
        key(Qt.Key.Key_Tab)
        key(Qt.Key.Key_Space)
        assert js("document.querySelector('nav[aria-label=\"통계 지표\"] [aria-current=page]').getAttribute('data-tab')") == 'watched_seconds'
        key(Qt.Key.Key_Tab)
        key(Qt.Key.Key_Space)
        assert js("document.querySelector('nav[aria-label=\"통계 지표\"] [aria-current=page]').getAttribute('data-tab')") == 'viewing_count'
        checks.append('실제 Qt 키 입력: Shift+Tab/Tab/Space 기간·지표 선택')
        # 차트의 접근성 포커스를 거쳐 목록까지 Tab으로 이동한다.
        for _ in range(16):
            key(Qt.Key.Key_Tab)
            if js("document.activeElement?.hasAttribute('data-statistics-video')"):
                break
        assert js("document.activeElement?.hasAttribute('data-statistics-video')")
        selected = int(js("document.activeElement.getAttribute('data-statistics-video')"))
        # 데모에서 실제 파일이 있는 첫 영상이 첫 항목이다.
        assert selected == first.id
        key(Qt.Key.Key_Return)
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        wait(lambda: core.playback.position > 0)
        core.playback.report(50)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        content_ready(90)
        assert host.active_tab == 'statistics'
        checks.append('목록 Enter → 실제 mpv 재생 → Esc → 통계 갱신 및 기간 보존')
    report = {'count': args.count, 'offscreen': args.offscreen, 'checks': checks,
              'size': [window.width(), window.height()]}
    (args.output / f'checks-{sample}-{"offscreen" if args.offscreen else "window"}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
finally:
    window.tray.quit()
    window.deleteLater()
    assert QThreadPool.globalInstance().waitForDone(10000)
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    shutil.rmtree(directory)
