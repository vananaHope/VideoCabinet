"""시작 검사 응답성(기본) 또는 --count 5000 무변경 성능 검증.

python scripts/check_web_startup_scan.py --offscreen
python scripts/check_web_startup_scan.py --offscreen --count 5000
실창은 desktop_lock.py run --owner issue-131 -- 아래에서만 실행한다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--count', type=int, default=0)
parser.add_argument('--output', type=Path, default=ROOT / '.local/issue-131')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def __init__(self):
        self.reads = 0
        self.captures = 0
        self.slow_path = None
        self.started = threading.Event()
        self.release = threading.Event()

    def read(self, path):
        self.reads += 1
        if path.suffix != '.mkv':
            return None
        if path == self.slow_path:
            self.started.set()
            assert self.release.wait(60), '첫 조작 제한 시간 초과'
        return MediaInfo(120, 'matroska', 1280, 720)

    def capture(self, path, destination, seconds):
        self.captures += 1
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


class Player:
    def __init__(self, surface):
        pass

    def play(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False


def settle(ms=20):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, '조건 대기 시간 초과'
        settle()


def js(window, source):
    values = []
    window.web_host.engine_page.runJavaScript(source, values.append)
    wait(lambda: bool(values))
    return values[0]


def capture(window, name):
    if not args.offscreen:
        return
    js(window, 'window.captureReady = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.captureReady = true }));')
    wait(lambda: js(window, 'window.captureReady'))
    settle(250)
    assert window.grab().save(str(args.output / f'{name}.png'))


def main():
    app = QApplication([])
    args.output.mkdir(parents=True, exist_ok=True)
    # #119와 같은 공개 등록/합성 미디어 방식. 데이터는 worktree 밖 임시 폴더.
    with tempfile.TemporaryDirectory(prefix='mvm-startup-131-') as directory:
        root = Path(directory)
        folder = root / 'videos'
        folder.mkdir()
        media = Media()
        database = root / 'data/library.sqlite3'
        core = AppCore(database=database, media=media, clock=lambda: datetime.now(timezone.utc))
        for index in range(args.count or 1):
            sub = folder / f'folder-{index % 60:02d}'
            sub.mkdir(exist_ok=True)
            path = sub / f'video-{index:05d}.mkv'
            if not args.offscreen and not args.count:
                subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi',
                                '-i', 'color=c=navy:s=640x360:r=25', '-t', '10',
                                '-c:v', 'mpeg4', str(path)], check=True)
            else:
                path.write_bytes(f'unique video {index}'.encode())
            if args.count and index % 5 == 0:
                path.with_suffix('.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nSample\n', encoding='utf-8')
        core.add_watched_folder(folder)
        initial = core.scan()
        assert initial.added == (args.count or 1), initial
        print(f'초기 등록 완료: {initial.added}개', flush=True)
        # 앱 재시작처럼 코어를 다시 만들고 캐시된 DB와 파일을 읽는다.
        core = AppCore(database=database, media=media, clock=lambda: datetime.now(timezone.utc))
        if not args.count:
            media.slow_path = folder / 'new-video.mkv'
            media.slow_path.write_bytes(b'added while app was closed')
        media.reads = media.captures = 0
        metrics = {'count': args.count or 1, 'subtitles': args.count // 5,
                   'mode': 'offscreen' if args.offscreen else 'real', 'temporary_data': directory}
        scan = core.scan
        scan_calls = []

        def measured_scan():
            scan_calls.append(time.perf_counter())
            result = scan()
            metrics['scan_seconds'] = time.perf_counter() - scan_calls[-1]
            metrics['added'] = result.added
            metrics['issues'] = len(result.issues)
            return result

        core.scan = measured_scan
        started = time.perf_counter()
        window = MainWindow(core, **({'player_factory': Player} if args.offscreen else {}))
        window.resize(1100, 720)
        window.web_host.frontend_loaded.connect(
            lambda: metrics.update(frontend_ready_seconds=time.perf_counter() - started))
        window.library_page.scan_state_changed.connect(
            lambda busy: metrics.update(**{('worker_started_seconds' if busy else 'finished_with_refresh_seconds'):
                                           time.perf_counter() - started}))
        window.show()
        try:
            if args.count:
                wait(lambda: bool(scan_calls) and window.worker is None)
                assert metrics['added'] == metrics['issues'] == media.reads == media.captures == 0
                assert len(window.library_page.cards) == args.count
                assert window.web_host.controllers['folders'].report == ''
                capture(window, f'unchanged-{args.count}')
            else:
                wait(media.started.is_set)
                assert window.worker is not None
                assert js(window, 'document.querySelectorAll("header nav button").length') == 7
                capture(window, 'scanning-library')
                window.raise_()
                window.activateWindow()
                wait(window.isActiveWindow)
                first_input = time.perf_counter()
                QTest.keyClick(window, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
                wait(lambda: window.web_host.active_tab == 'folders')
                wait(lambda: js(window, 'document.querySelector("header nav [aria-current=page]") === document.querySelectorAll("header nav button")[5]'))
                metrics['tab_input_seconds'] = time.perf_counter() - first_input
                bridge = window.web_host.controllers['folders'].bridge
                assert 'error' in json.loads(bridge.action('scan', ''))
                window.scan()
                assert len(scan_calls) == 1
                capture(window, 'scanning-folders')
                QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
                wait(lambda: js(window, 'document.activeElement?.getAttribute("role") === "grid"'))
                QTest.keyClick(app.focusWidget(), Qt.Key.Key_Return)
                wait(lambda: window.pages.currentWidget() is window.playback_page)
                if not args.offscreen:
                    wait(lambda: core.playback.position > 0)
                QTest.keyClick(app.focusWidget(), Qt.Key.Key_Escape)
                wait(lambda: window.pages.currentWidget() is window.web_host)
                assert window.worker is not None and window.worker.isRunning()
                metrics['navigation_playback_return_while_scanning'] = True
                media.release.set()
                wait(lambda: window.worker is None)
                assert len(core.videos()) == 2 and len(scan_calls) == 1
                capture(window, 'scan-completed')
            metrics.update(scan_calls=len(scan_calls), media_reads=media.reads, media_captures=media.captures)
            name = f'benchmark-{args.count}' if args.count else f'responsive-{metrics["mode"]}'
            (args.output / f'{name}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
        finally:
            media.release.set()
            wait(lambda: window.worker is None)
            window.tray.quit()
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
