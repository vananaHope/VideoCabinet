"""#199 앱 수준 무작위 재생. offscreen은 위젯만 캡처하고 실창은 mpv·포커스·트레이 왕복을 검사한다.

실창은 MVM_REAL_WINDOW_TESTS=1과 desktop_lock.py run --owner issue-199 안에서만 실행한다.
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
parser.add_argument('--count', type=int, default=2)
parser.add_argument('--output', type=Path, default=Path('.local/issue-199-check'))
args = parser.parse_args()
if not args.offscreen and os.environ.get('MVM_REAL_WINDOW_TESTS') != '1':
    parser.error('실창은 MVM_REAL_WINDOW_TESTS=1과 desktop_lock 안에서 실행하세요.')
if args.count < 0 or (not args.offscreen and args.count != 2):
    parser.error('count는 0 이상이며 실창은 합성 영상 2개로 검사합니다.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.adapters import FFmpegMediaReader, MpvPlayer, executable
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.random_play import NO_CANDIDATE_MESSAGE
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        pass

    def play(self, path, start, *, subtitle):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def close(self):
        pass


app = QApplication([])
if args.offscreen:
    # offscreen에는 OS 트레이가 없다. 메뉴 QAction과 창 숨김·복원은 그대로 검사한다.
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
args.output.mkdir(parents=True, exist_ok=True)
metrics = {'count': args.count, 'offscreen': args.offscreen, 'checks': [], 'screenshots': []}


def wait(predicate, seconds=30):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


with tempfile.TemporaryDirectory(prefix='mvm-199-') as temporary:
    root = Path(temporary)
    core = AppCore(media=Media() if args.offscreen else FFmpegMediaReader(),
                   database=root / 'data/library.sqlite3', clock=lambda: datetime.now(timezone.utc))
    core.set_automatic_detection_enabled(False)
    core.set_automatic_update_check_enabled(False)
    core.set_minimum_duration(0)
    if args.offscreen:
        # 대량 합성 자료 준비는 이 검증 전용 DB에만 기록한다. 동작은 공개 코어·UI 경계를 쓴다.
        with closing(sqlite3.connect(core.database)) as db, db:
            for index in range(args.count):
                path = root / f'{index}.mkv'
                path.write_bytes(str(index).encode())
                title = ('아주 긴 제목 ' * 30) if index == 0 else f'합성 영상 {index:04}'
                vid = db.execute('INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked) VALUES (?,?,?,?,?,?,?,?,1)',
                                 (f'synthetic-{index}', title, 120, 'matroska', '', '2026-10-20T00:00:00+00:00', 640, 360)).lastrowid
                db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(path), vid))
    else:
        for index, color in enumerate(('darkblue', 'darkred')):
            path = root / f'{index}.mkv'
            subprocess.run([executable('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                            f'color=c={color}:s=640x360:r=24', '-t', '60', '-c:v', 'mpeg4', str(path)], check=True)
            core.add_file(path)
    start = perf_counter()
    window = MainWindow(core, player_factory=Player if args.offscreen else MpvPlayer)
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    window.show()
    window.activateWindow()
    wait(lambda: loaded)
    metrics['startup_ms'] = round((perf_counter() - start) * 1000, 2)
    host = window.web_host

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait(lambda: bool(result))
        return result[0]

    def capture(name):
        if not args.offscreen:
            return
        QTest.qWait(250)
        path = args.output / f'{args.count}-{name}.png'
        assert window.grab().save(str(path))
        assert (QImage(str(path)).width(), QImage(str(path)).height()) == (1100, 720)
        metrics['screenshots'].append(str(path.resolve()))

    def key(value, modifiers=Qt.KeyboardModifier.NoModifier):
        window.activateWindow()
        app.processEvents()
        if not args.offscreen:
            wait(window.isActiveWindow)
        target = QApplication.focusWidget()
        assert target is not None and (target is window or window.isAncestorOf(target))
        QTest.keyClick(target, value, modifiers)
        app.processEvents()

    def random_key():
        key(Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)

    try:
        capture('library')
        window.navigate_web_tab('settings')
        wait(lambda: js('!!document.querySelector("#settings-category")'))
        js('document.querySelector("#settings-category [data-category=keys]").click()')
        selector = '[data-command="random_play:0"]'
        wait(lambda: js(f'!!document.querySelector({json.dumps(selector)})'))
        js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"center"}})')
        row = js(f'document.querySelector({json.dumps(selector)}).closest("tr").textContent')
        assert 'Ctrl+Shift+R' in row and 'IME' in row
        capture('settings-random')
        metrics['checks'].append('자동 명령 목록·현재/기본 키·앱 수준/IME 안내')
        window.navigate_web_tab('search')
        host.view.setFocus()
        start = perf_counter()
        random_key()
        metrics['random_ms'] = round((perf_counter() - start) * 1000, 2)
        if args.count == 0:
            assert core.playback.session is None
            wait(lambda: js(f'document.body.innerText.includes({json.dumps(NO_CANDIDATE_MESSAGE)})'))
            capture('empty-info')
            metrics['checks'].append('빈 후보 정보 안내')
        else:
            assert window.pages.currentWidget() is window.playback_page
            first = core.playback.session.video_id
            if not args.offscreen:
                wait(lambda: core.playback.position > 0.2)
            random_key()
            second = core.playback.session.video_id
            if args.count > 1:
                assert second != first
            assert core.viewings(first)[-1].ended_at is not None
            if not args.offscreen:
                wait(lambda: core.playback.position > 0.2)
            start = perf_counter()
            key(Qt.Key.Key_Escape)
            assert core.playback.session is None and host.active_tab == 'search'
            assert window.pages.currentWidget() is host
            metrics['return_ms'] = round((perf_counter() - start) * 1000, 2)
            metrics['checks'].append('검색 탭 키 → 재생 → 다른 영상 전환·시청 마감 → Esc 원래 탭 복귀')
            assert QSystemTrayIcon.isSystemTrayAvailable()
            window.close()
            assert not window.isVisible()
            action = next(a for a in window.tray.icon.contextMenu().actions() if a.text() == '무작위 재생')
            action.trigger()
            assert window.isVisible() and window.pages.currentWidget() is window.playback_page
            if not args.offscreen:
                wait(window.isActiveWindow)
                wait(lambda: core.playback.position > 0.2)
            key(Qt.Key.Key_Escape)
            assert core.playback.session is None
            metrics['checks'].append('트레이 숨김 → 무작위 재생 QAction → 재생 → Esc 복귀')
    finally:
        window.tray.quit()
    (args.output / f'{args.count}-metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
