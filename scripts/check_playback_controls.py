"""재생 조작 줄 검사.

python scripts/check_playback_controls.py --offscreen
python ~/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_playback_controls.py --real

--offscreen은 가짜 플레이어로 1100×720 창의 조작 줄이 넘치지 않는지 보고 위젯 grab 이미지를 남긴다.
--real은 데스크톱 잠금 안에서 합성 영상과 실제 mpv, Windows 마우스·키 입력으로 단추 클릭, Tab 이동,
단추 초점에서의 재생 키, 전체 화면 조작 줄의 '목록으로'·'전체 화면 끄기', 키 안내 마우스 닫기를 확인한다.
실창에서는 화면 캡처를 하지 않는다. 데이터는 worktree 밖 임시 폴더에 만들고 지운다.
"""

import argparse
import ctypes
import ctypes.wintypes
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--real', action='store_true')
parser.add_argument('--output', type=Path, default=Path('.local/playback-controls'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QCursor, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    """offscreen 배치 확인용 가짜 플레이어."""

    def __init__(self, surface):
        self.options, self.paused = (1, True), False

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        pass

    def take_positions(self):
        return ()

    def take_eof(self):
        return False

    def playback_options(self):
        return self.options

    def execute(self, command):
        pass


def settle(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, label, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f'대기 시간 초과: {label}')
        settle(20)


def fits(page):
    """조작 줄의 최소 폭이 줄 폭 안이고 보이는 단추가 모두 줄 안에 있다."""
    row = page.controls.layout()
    inside = all(widget.geometry().right() < page.controls.width()
                 for widget in (*page.control_buttons, page.menu_button) if widget.isVisible())
    return row.minimumSize().width() <= page.controls.width() and inside


def offscreen(app, directory, result):
    # Windows offscreen 플러그인은 시스템 글꼴을 자동 열거하지 않는 경우가 있다.
    for name in ('malgun.ttf', 'malgunbd.ttf', 'segoeui.ttf', 'seguisym.ttf', 'seguiemj.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
    for index in (1, 2):
        path = directory / f'아주 긴 제목의 강의 영상 {index:02}강.mkv'
        path.write_bytes(bytes([index]))
        core.add_file(path)
    window = MainWindow(core, player_factory=Player)
    window.resize(1100, 720)
    window.show()
    window.play(core.videos()[0].id)
    window.sync_position()
    page = window.playback_page

    def check(name):
        settle()
        assert fits(page), name
        assert not any(button.compact for button in page.compact_order), name
        image = args.output / f'playback-{name}.png'
        assert window.grab().save(str(image))
        result['passed'].append(name)
        result['images'].append(str(image))

    check('plain')
    # 열린 구간·다듬은 자막·작업 표시가 함께 보이는 가장 넓은 창 모드 줄.
    core.playback.report(10)
    window.core.execute_highlight_command(Command(CommandType.RANGE_HIGHLIGHT))
    window.sync_position()
    page._details = replace(page._details, original_lines=3, spoken_language='ko',
                            subtitle_state='transcribing', translation_state='translating')
    window.player.options = (1.75, False)
    window.player.paused = True
    page.update_controls()
    # 다듬은 자막이 가장 긴 자막 종류 이름표다. 번역 결과 없이 이름표만 그 상태로 둔다.
    page.subtitle_language_button.set_label('다듬은 자막', '다듬은')
    check('widest')
    page.key_guide_button.click()
    settle()
    assert page.help_panel.isVisible()
    assert page.help_panel.grab().save(str(args.output / 'playback-key-guide.png'))
    page.help_panel.close_button.click()
    assert not page.help_panel.isVisible()
    result['passed'].append('key-guide-close-button')
    window.tray.quit()


def real(app, directory, result):
    from my_video_manager.adapters import FFmpegMediaReader
    user32 = ctypes.windll.user32
    source = directory / '실창 조작 줄.mp4'
    subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                    '-t', '120', '-c:v', 'libx264', '-preset', 'ultrafast', '-y', str(source)], check=True)
    core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                   database=directory / 'library.sqlite3')
    core.add_file(source)
    window = MainWindow(core)
    window.move(40, 40)
    window.resize(1100, 720)
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000), '앱 창 활성화 실패'
    # 다른 앱(IDE 등)이 검사 창 위로 올라와 OS 클릭을 가로채지 않게 검사 동안만 z 순서를 맨 위로 둔다.
    # Qt 창 플래그는 바꾸지 않으므로 활성화·초점 동작은 앱과 같다.
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    page = window.playback_page
    window.play(core.videos()[0].id)
    wait(lambda: core.playback.position > 1, '재생 시작')

    def point(widget):
        """Qt 논리 좌표의 위젯 가운데를 Windows 물리 좌표로 바꾼다. 창은 원점에 있는 주 화면에 둔다."""
        assert widget.screen().geometry().topLeft() == QPoint(0, 0), '주 화면 밖의 창'
        ratio = widget.screen().devicePixelRatio()
        center = widget.mapToGlobal(widget.rect().center())
        return round(center.x() * ratio), round(center.y() * ratio)

    def click(widget):
        x, y = point(widget)
        user32.SetCursorPos(x, y)
        settle(80)
        # 커서 아래 위젯을 먼저 확인해 OS 입력 누락(다른 창이 가림 등)과 제품 실패를 구분한다.
        under = QApplication.widgetAt(QCursor.pos())
        if under is not widget:
            hwnd = user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
            title, kind, pid = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256), ctypes.c_ulong()
            user32.GetWindowTextW(hwnd, title, 256)
            user32.GetClassNameW(hwnd, kind, 256)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = ctypes.wintypes.RECT()
            root = user32.GetAncestor(hwnd, 2)
            user32.GetWindowRect(root, ctypes.byref(rect))
            topmost = bool(user32.GetWindowLongW(root, -20) & 0x8)
            print(f'가린 창: {title.value!r} {kind.value!r} pid {pid.value} (이 프로세스 {os.getpid()})'
                  f' 영역 {(rect.left, rect.top, rect.right, rect.bottom)} 항상 위 {topmost}')
        assert under is widget, (f'커서 아래가 {under!r}({QCursor.pos()}), 기대 {widget.accessibleName()}'
                                 f' · 활성 창 {QApplication.activeWindow()!r} · 창 {window.geometry()}'
                                 f' · 화면 {widget.screen().geometry()} ×{widget.screen().devicePixelRatio()}'
                                 f' · 위젯 {widget.mapToGlobal(widget.rect().center())}')
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        settle(250)

    def press(vk, extended=False):
        flag = 0x1 if extended else 0
        user32.keybd_event(vk, 0, flag, 0)
        user32.keybd_event(vk, 0, flag | 0x2, 0)
        settle(250)

    def passed(name):
        assert window.isActiveWindow(), f'{name}: 앱 창이 활성 창이 아님'
        result['passed'].append(name)

    window.surface.setFocus()
    click(page.pause_button)
    wait(lambda: window.player.paused, '⏸ 단추로 일시정지')
    assert page.pause_button.text() == '▶' and page.pause_button.accessibleName() == '재생'
    assert window.surface.hasFocus(), '단추 클릭이 영상 초점을 가져감'
    passed('pause-button-click')
    press(0x0D)  # Enter: 초점이 영상에 남아 재생 키가 그대로 동작한다.
    wait(lambda: not window.player.paused, 'Enter로 재개')
    passed('playback-key-after-click')

    press(0x09)
    press(0x09)
    assert page.pause_button.hasFocus(), 'Tab 두 번 뒤 ⏯ 초점'
    before = core.playback.position
    press(0x27, extended=True)  # →
    wait(lambda: core.playback.position >= before + 4, '단추 초점에서 → 탐색')
    press(0x20)  # Space: 초점 단추 누르기
    wait(lambda: window.player.paused, 'Space로 초점 단추 누르기')
    press(0x0D)  # Enter: 초점 단추 누르기
    wait(lambda: not window.player.paused, 'Enter로 초점 단추 누르기')
    passed('tab-focus-keys')
    window.surface.setFocus()

    click(page.subtitles_button)
    wait(lambda: not window.player.playback_options()[1], '자막 끄기 단추')
    assert not page.subtitles_button.isChecked()
    click(page.subtitles_button)
    wait(lambda: window.player.playback_options()[1], '자막 켜기 단추')
    passed('subtitles-button-click')

    click(page.key_guide_button)
    wait(page.help_panel.isVisible, '⌨ 단추로 키 안내 열기')
    click(page.help_panel.close_button)
    wait(lambda: not page.help_panel.isVisible(), '닫기 단추로 키 안내 닫기')
    assert not page.key_guide_button.isChecked()
    passed('key-guide-mouse-close')

    click(page.fullscreen_button)
    wait(window.isFullScreen, '⛶ 단추로 전체 화면')
    settle(300)
    page.hide_temporary_bar()
    assert not page.bottom_bar.isVisible()
    x, y = point(page.surface)
    user32.SetCursorPos(x + 30, y + 30)
    wait(page.bottom_bar.isVisible, '마우스 움직임으로 조작 줄 표시')
    assert page.list_button.isVisible() and fits(page), '전체 화면 조작 줄 배치'
    result['fullscreen_bar'] = {'width': page.controls.width(),
                                'minimum': page.controls.layout().minimumSize().width(),
                                'fullscreen_label': page.fullscreen_button.text()}
    click(page.fullscreen_button)
    wait(lambda: not window.isFullScreen(), '전체 화면 끄기 단추')
    assert core.playback.session is not None
    passed('fullscreen-off-button')

    press(0xDE)  # ': 전체 화면
    wait(window.isFullScreen, "' 키로 전체 화면")
    x, y = point(page.surface)
    user32.SetCursorPos(x + 60, y + 60)
    wait(page.bottom_bar.isVisible, '조작 줄 다시 표시')
    click(page.list_button)
    wait(lambda: core.playback.session is None, '목록으로 단추')
    assert not window.isFullScreen() and window.pages.currentWidget() is window.web_host
    passed('fullscreen-list-button')
    window.tray.quit()


def main():
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    directory = Path(tempfile.mkdtemp(prefix='playback-controls-'))
    result = {'mode': 'offscreen' if args.offscreen else 'real', 'passed': [], 'images': []}
    try:
        (offscreen if args.offscreen else real)(app, directory, result)
    finally:
        settle()
        shutil.rmtree(directory, ignore_errors=True)
    path = args.output / f'{result["mode"]}-result.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
