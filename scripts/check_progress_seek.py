"""데스크톱 잠금 안에서 실행하는 Windows 실제 mpv 진행 막대 검사.

--source는 읽기 전용 영상 파일, --data-dir는 worktree 밖의 새 임시 폴더다.
QTest.mouseMove(QWidget)는 Windows 커서 이동에 의존한다. 커서를 옮긴 뒤 QWindow
경유로 Qt 입력을 보내고 수신을 확인해 OS 입력 누락과 제품 실패를 구분한다.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.highlight_ui import progress_time
from my_video_manager.time_display import timestamp
from my_video_manager.ui import MainWindow
from my_video_manager.web_thumbnail import register_thumbnail_scheme


def wait_for(predicate, label, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(label)
        process_for(20)


def process_for(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class MouseProbe(QObject):
    def __init__(self, progress):
        super().__init__(progress)
        self.moves = []
        progress.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            self.moves.append(event.position().toPoint())
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('.local/progress-seek'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.data_dir.resolve().is_relative_to(root) or args.data_dir.exists():
        parser.error('--data-dir는 worktree 밖의 아직 존재하지 않는 임시 폴더여야 합니다')
    if not args.source.is_file():
        parser.error('--source 영상 파일이 없습니다')
    args.output.mkdir(parents=True, exist_ok=True)
    register_thumbnail_scheme()
    app = QApplication([])
    core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                   database=args.data_dir / 'library.sqlite3')
    core.add_file(args.source)
    window = MainWindow(core)
    page, progress = window.playback_page, window.progress
    probe = MouseProbe(progress)
    seeks = []
    progress.seek_requested.connect(seeks.append)
    result = {'passed': [], 'data_dir': str(args.data_dir), 'source': str(args.source)}

    def key(code):
        QTest.keyClick(QApplication.focusWidget() or window.surface, code)

    def point(fraction):
        return QPoint(round(5 + (progress.width() - 10) * fraction), 7)

    def target(pos):
        return progress_time(pos.x(), progress.width(), progress.duration)

    def arrived(pos):
        return abs(core.playback.position - target(pos)) < .6

    def move_cursor(pos):
        previous_count = len(probe.moves)
        QCursor.setPos(progress.mapToGlobal(pos))
        wait_for(lambda: QCursor.pos() == progress.mapToGlobal(pos), 'OS 커서 위치 도착')
        QTest.mouseMove(window.windowHandle(), progress.mapTo(window, pos))
        wait_for(lambda: len(probe.moves) > previous_count and probe.moves[-1] == pos,
                 'QWindow 경유 MouseMove 수신')
        assert QApplication.widgetAt(QCursor.pos()) is progress

    def hover():
        # 기존 커서와 다른 두 좌표를 통과해 실제 이동 이벤트를 보장한다.
        intermediate = point(.1 if progress.mapFromGlobal(QCursor.pos()) != point(.1) else .15)
        move_cursor(intermediate)
        pos = point(.3)
        move_cursor(pos)
        wait_for(lambda: QToolTip.isVisible() and QToolTip.text() == timestamp(target(pos)),
                 '정확한 시각 툴팁 표시')
        return pos

    def capture(name):
        # QWidget.grab은 네이티브 mpv 자식 창을 검게 캡처하므로 화면에서 읽는다.
        origin = window.mapToGlobal(QPoint())
        window.screen().grabWindow(0, origin.x(), origin.y(), window.width(), window.height()).save(
            str(args.output / f'{name}.png'))

    try:
        window.show()
        window.activateWindow()
        wait_for(window.isActiveWindow, 'Windows 창 활성화')
        window.play(core.videos()[0].id)
        wait_for(lambda: core.playback.position > .1, '실제 mpv 재생 시작')
        engine = window.player._player
        engine.mute = True
        assert progress.duration > 3
        result['duration'] = progress.duration
        key(Qt.Key.Key_Return)
        wait_for(lambda: engine.pause, 'Enter 일시정지')

        pos = hover()
        result['passed'].append('일반 창 호버 시각 표시')
        capture('hover-window')

        for fullscreen in (False, True):
            label = '전체 화면' if fullscreen else '일반 창'
            if fullscreen:
                key(Qt.Key.Key_Apostrophe)
                wait_for(window.isFullScreen, '전체 화면 진입')
                page.reveal_bar()
                process_for(100)
                hover()
                result['passed'].append('전체 화면 호버 시각 표시')
            pos = point(.25)
            before = len(seeks)
            QTest.mouseClick(progress, Qt.MouseButton.LeftButton, pos=pos)
            wait_for(lambda: arrived(pos), label + ' 클릭 탐색')
            assert len(seeks) == before + 1
            assert engine.pause and window.surface.hasFocus()
            result['passed'].append(label + ' 클릭 탐색·일시정지·포커스 유지')

            start, end = point(.35), point(.65)
            QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=start)
            wait_for(lambda: arrived(start), label + ' 드래그 시작 탐색')
            before = len(seeks)
            for fraction in (.4, .5, .6, .65):
                QTest.mouseMove(progress, point(fraction))
            assert progress.displayed_position == target(end)
            assert len(seeks) == before
            page.hide_temporary_bar()
            assert page.bottom_bar.isVisible()
            QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=end)
            wait_for(lambda: arrived(end), label + ' 드래그 최종 탐색')
            assert len(seeks) == before + 1
            assert engine.pause and window.surface.hasFocus()
            result['passed'].append(label + ' 드래그 미리보기·최종 탐색·일시정지·바 유지')
            key(Qt.Key.Key_Return)
            wait_for(lambda: not engine.pause, label + ' 클릭 뒤 Enter 재생')
            result['passed'].append(label + ' 클릭 뒤 Enter 키 동작')
            start, end = point(.25), point(.45)
            QTest.mousePress(progress, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(progress, end)
            QTest.mouseRelease(progress, Qt.MouseButton.LeftButton, pos=end)
            wait_for(lambda: arrived(end), label + ' 재생 중 드래그')
            assert not engine.pause
            result['passed'].append(label + ' 드래그 뒤 재생 상태 유지')
            capture('fullscreen' if fullscreen else 'window')
            key(Qt.Key.Key_Return)
            wait_for(lambda: engine.pause, label + ' 다음 검사 준비')
        key(Qt.Key.Key_Escape)
        assert not window.isFullScreen()
        result['success'] = True
    except Exception as error:
        result['success'] = False
        result['error'] = repr(error)
        raise
    finally:
        under = QApplication.widgetAt(QCursor.pos())
        result['pointer'] = {
            'global': QCursor.pos().toTuple(),
            'progress_origin': progress.mapToGlobal(QPoint()).toTuple(),
            'widget_at_cursor': type(under).__name__ if under else None,
            'tooltip_text': QToolTip.text(), 'tooltip_visible': QToolTip.isVisible(),
        }
        result['mouse_moves'] = [pos.toTuple() for pos in probe.moves]
        result['seek_requests'] = seeks
        (args.output / 'result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False), flush=True)
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
