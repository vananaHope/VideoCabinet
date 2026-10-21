"""#235: offscreen 위젯 캡처 또는 desktop_lock 안에서 실제 mpv EOF·키·목록 왕복."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from time import monotonic


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--library', type=Path)
parser.add_argument('--output', type=Path, default=Path('.local/issue-235'))
args = parser.parse_args()
if not args.offscreen and (os.environ.get('MVM_REAL_WINDOW_TESTS') != '1' or args.library is None):
    parser.error('실창은 desktop_lock 안에서 MVM_REAL_WINDOW_TESTS=1, --library로 실행하세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.adapters import FFmpegMediaReader, MpvPlayer
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        self.positions, self.eof = [], False
        self.paused, self.position = False, 0

    def play(self, path, start, *, subtitle):
        self.position = start

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        eof, self.eof = self.eof, False
        return eof

    def close(self):
        pass


args.output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
if args.offscreen:
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    # offscreen 플랫폼은 Windows 기본 한글 글꼴을 자동으로 찾지 못한다.
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/malgun.ttf'
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))


def wait(predicate, seconds=30):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


evidence = {'offscreen': args.offscreen, 'checks': [], 'screenshots': []}
with tempfile.TemporaryDirectory(prefix='check-', dir=args.output) as temporary:
    root = Path(temporary)
    media = Media() if args.offscreen else FFmpegMediaReader()
    core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc),
                   database=root / 'data/library.sqlite3', random_choice=min)
    core.set_automatic_detection_enabled(False)
    core.set_automatic_update_check_enabled(False)
    core.set_minimum_duration(0)
    if args.offscreen:
        for name in ('a', 'b'):
            path = root / f'{name}.mkv'
            path.write_bytes(name.encode())
            core.add_file(path)
    else:
        paths = [p for p in args.library.rglob('*') if p.suffix.lower() in ('.mkv', '.mp4', '.webm')]
        durations = sorted((media.read(p).duration, str(p)) for p in paths)
        for duration, name in durations:
            core.add_file(Path(name))
            if len(core.videos()) == 2:
                break
        assert len(core.videos()) == 2
        evidence['media'] = [{'path': str(v.locations[0].path), 'duration': v.duration} for v in core.videos()]
    window = MainWindow(core, player_factory=Player if args.offscreen else MpvPlayer)
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    try:
        window.show()
        window.activateWindow()
        wait(lambda: loaded)
        if not args.offscreen:
            wait(window.isActiveWindow)
        QTest.keyClick(window.web_host.view, Qt.Key.Key_R,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        wait(lambda: core.playback.session is not None)
        first = core.playback.session.video_id
        assert core.random_continuous_enabled
        if args.offscreen:
            window.player.positions = [(120, False)]
            window.player.eof = True
        else:
            wait(lambda: core.playback.position > 0)
            window.playback_page.seek(core.video(first).duration - 1)
        wait(lambda: core.playback.session.video_id != first)
        second = core.playback.session.video_id
        assert core.viewings(first)[0].ended_at is not None
        evidence['checks'].append('EOF -> next random video, previous viewing closed')
        QTest.keyClick(window.surface, Qt.Key.Key_PageUp)
        wait(lambda: core.playback.session.video_id == first)
        QTest.keyClick(window.surface, Qt.Key.Key_PageDown)
        wait(lambda: core.playback.session.video_id == second)
        evidence['checks'].append('PgUp/PgDn -> backward/forward history')
        if args.offscreen:
            image_path = args.output / 'random-playback.png'
            assert window.grab().save(str(image_path))
            evidence['screenshots'].append(str(image_path.resolve()))
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: core.playback.session is None)
        assert not core.random_continuous_enabled
        assert window.library_page.selected_video_id() == second
        assert window.pages.currentWidget() is window.web_host
        evidence['checks'].append('Esc -> library, last video selected, continuous state discarded')
        if args.offscreen:
            QTest.qWait(300)
            image_path = args.output / 'random-return.png'
            assert window.grab().save(str(image_path))
            evidence['screenshots'].append(str(image_path.resolve()))
        evidence['viewings'] = {str(v.id): len(core.viewings(v.id)) for v in core.videos()}
    finally:
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
result = args.output / ('offscreen.json' if args.offscreen else 'real.json')
result.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False))
