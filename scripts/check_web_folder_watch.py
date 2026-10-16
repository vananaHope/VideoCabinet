"""실행 중 폴더 감시(#132)의 자동 반영, 자동 감지 켜기/끄기, 감시 실패 안내 검증.

python scripts/check_web_folder_watch.py --offscreen
실창은 desktop_lock.py run --owner issue-132 -- 아래에서만 실행한다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-132')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska', 1280, 720) if path.suffix == '.mkv' else None

    def capture(self, path, destination, seconds):
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


def wait(predicate, timeout=60):
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


def titles(core):
    return {video.title for video in core.videos()}


def main():
    app = QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mvm-watch-132-') as directory:
        root = Path(directory)
        folder = root / 'videos'
        (folder / 'season-1').mkdir(parents=True)
        (folder / 'season-1' / 'episode-01.mkv').write_bytes(b'episode one')
        # 감시를 설치할 수 없는 루트: 등록 뒤 드라이브 분리처럼 사라진 폴더.
        missing = [root / 'external-drive' / 'recordings',
                   root / 'network-share' / ('아주 긴 폴더 이름으로 줄바꿈을 확인하는 녹화 보관함 ' * 3).strip()]
        core = AppCore(database=root / 'data/library.sqlite3', media=Media(),
                       clock=lambda: datetime.now(timezone.utc))
        for path in (folder, *missing):
            path.mkdir(parents=True, exist_ok=True)
            core.add_watched_folder(path)
        for path in missing:
            path.rmdir()
        window = MainWindow(core, player_factory=Player, folder_watch_options=dict(
            debounce_seconds=0.1, stable_seconds=0.5, poll_seconds=0.1))
        window.resize(1100, 720)
        window.show()
        metrics = {'temporary_data': directory}
        try:
            wait(lambda: 'episode-01' in titles(core) and window.worker is None)
            unwatched = set(map(str, window.folder_watch.unwatched_folders()))
            assert unwatched == {str(f.path) for f in core.watched_folders() if not f.path.exists()}, unwatched

            started = time.monotonic()
            (folder / 'season-1' / 'episode-02.mkv').write_bytes(b'episode two copied while running')
            wait(lambda: 'episode-02' in titles(core) and window.worker is None)
            metrics['running_add_seconds'] = round(time.monotonic() - started, 2)

            window.navigate_web_tab('folders')
            wait(lambda: js(window, 'document.body.innerText.includes("감시하지 못하는 폴더 2개")'))
            capture(window, 'folders-unwatched')

            window.navigate_web_tab('settings')
            toggle = 'document.getElementById("settings-automatic-detection-toggle")'
            wait(lambda: js(window, f'{toggle}?.getAttribute("aria-pressed") === "true"'))
            capture(window, 'settings-detection-on')
            js(window, f'{toggle}.click()')
            wait(lambda: js(window, f'{toggle}.getAttribute("aria-pressed") === "false"'))
            assert not core.automatic_detection_enabled()
            capture(window, 'settings-detection-off')

            (folder / 'season-1' / 'episode-03.mkv').write_bytes(b'episode three while off')
            settle(2000)
            assert 'episode-03' not in titles(core), '자동 감지를 꺼도 반영됨'
            window.navigate_web_tab('folders')
            wait(lambda: js(window, 'document.body.innerText.includes("자동 감지가 꺼져 있습니다")'))
            assert not js(window, 'document.body.innerText.includes("감시하지 못하는 폴더")')
            capture(window, 'folders-detection-off')

            window.navigate_web_tab('settings')
            wait(lambda: js(window, f'{toggle}?.getAttribute("aria-pressed") === "false"'))
            js(window, f'{toggle}.click()')
            started = time.monotonic()
            wait(lambda: 'episode-03' in titles(core) and window.worker is None)
            metrics['enable_full_scan_seconds'] = round(time.monotonic() - started, 2)
            metrics['videos'] = sorted(titles(core))
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
        finally:
            window.tray.quit()
            settle(100)


if __name__ == '__main__':
    main()
