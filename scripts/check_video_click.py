"""영상 클릭 실창 검사.

python ~/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_video_click.py

데스크톱 잠금 안에서 합성 영상과 실제 mpv, Windows 마우스·키 입력으로 확인한다.
창 모드와 전체 화면에서 한 번 클릭(판정 시간 뒤 재생/일시정지)과 두 번 클릭(전체 화면, 재생 상태 그대로),
클릭 뒤에도 재생 키가 동작하는지, 전체 화면 커서 이동 → 조작 줄 표시,
키 안내·재생 메뉴·속도 목록이 열린 상태의 클릭은 그것만 닫는지, 영상 전환 직후의 클릭이 이전 영상의 누름과
두 번 클릭으로 묶이지 않는지, 클릭 직후 긴급 탈출 → 빠른 복원에서 재생이 다시 시작되지 않는지 본다.
mpv 영상 창이 비활성이라 누름이 Qt 표면으로 오는지도 단언한다. 화면 캡처는 하지 않는다. 데이터는 출력 폴더 아래 임시 폴더에 만들고 지운다.
"""

import argparse
import ctypes
import ctypes.wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--output', type=Path, default=Path('.local/video-click'))
parser.add_argument('--verify', action='store_true', help='실제 mpv와 OS 입력으로 검증한다 (기본 동작).')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.ui import MainWindow

user32 = ctypes.windll.user32
# HWND_TOPMOST(-1)가 64비트 핸들로 넘어가도록 인자 형식을 정한다.
user32.SetWindowPos.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.wintypes.HWND
user32.GetAncestor.restype = ctypes.wintypes.HWND
user32.FindWindowExW.restype = ctypes.wintypes.HWND
user32.FindWindowExW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR,
                                 ctypes.wintypes.LPCWSTR]


class PressCounter(QObject):
    """표면이 받은 왼쪽 단추 누름 수."""

    def __init__(self, widget):
        super().__init__()
        self.count = 0
        self.events = []
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                            QEvent.Type.MouseButtonRelease):
            self.events.append(event.type().name)
        if event.type() == QEvent.Type.MouseButtonPress:
            self.count += 1
        return False


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


def window_class(x, y):
    """커서 아래 창의 클래스. 다른 프로세스 창이면 OS 입력 누락과 제품 실패를 가를 수 있게 함께 적는다."""
    hwnd = user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
    kind, title, pid = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256), ctypes.c_ulong()
    user32.GetClassNameW(hwnd, kind, 256)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return kind.value
    user32.GetWindowTextW(user32.GetAncestor(hwnd, 2), title, 256)
    return f'{kind.value} (다른 프로세스 {pid.value}: {title.value!r})'


def real(app, directory, result):
    source = directory / '실창 영상 클릭 01강.mp4'
    other = directory / '실창 영상 클릭 02강.mp4'
    # 내용이 같은 파일은 라이브러리가 하나로 합치므로 두 영상의 길이를 다르게 만든다.
    for path, seconds in ((source, '120'), (other, '121')):
        subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                        '-t', seconds, '-c:v', 'libx264', '-preset', 'ultrafast', '-y', str(path)], check=True)
    core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                   database=directory / 'library.sqlite3')
    for path in (source, other):
        core.add_file(path)
    assert len(core.videos()) == 2, '검사 영상 두 편이 라이브러리에 들어가지 않았다'
    window = MainWindow(core)
    window.move(40, 40)
    window.resize(1100, 720)
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000), '앱 창 활성화 실패'
    # 다른 앱이 검사 창 위로 올라와 OS 클릭을 가로채지 않게 검사 동안만 z 순서를 맨 위로 둔다.
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    topmost = bool(user32.GetWindowLongW(int(window.winId()), -20) & 0x8)
    assert topmost, '검사 창을 맨 위로 두지 못했다'
    page = window.playback_page
    presses = PressCounter(page.surface)
    result['surface_events'] = presses.events
    window.play(next(video.id for video in core.videos() if video.title.endswith('01강')))
    wait(lambda: core.playback.position > 1, '재생 시작')
    # 종료 중인 이전 엔진은 같은 표면 아래 남아 있을 수 있다. 현재 엔진의 wid 아래만 찾는다.
    engine = user32.FindWindowExW(int(window._player_surface.winId()), None, 'mpv', None)
    assert engine, 'mpv 영상 창을 찾지 못했다'
    result['mpv_window_disabled'] = not user32.IsWindowEnabled(engine)
    # 비활성 mpv → 현재 엔진의 QWidget → 기본 ignore 전파 → 부모 surface 순서로 전달된다.
    assert result['mpv_window_disabled'], 'mpv 영상 창이 활성이라 클릭이 Qt 표면으로 오지 않는다'
    interval = page.clicks.interval
    result['double_click_interval'] = interval

    def point(widget, offset=None):
        """Qt 논리 좌표를 Windows 물리 좌표로 바꾼다. 창은 원점에 있는 주 화면에 둔다."""
        assert widget.screen().geometry().topLeft() == QPoint(0, 0), '주 화면 밖의 창'
        ratio = widget.screen().devicePixelRatio()
        local = widget.rect().center() if offset is None else offset
        spot = widget.mapToGlobal(local)
        return round(spot.x() * ratio), round(spot.y() * ratio)

    def video_point(offset=None):
        x, y = point(page.surface, offset)
        user32.SetCursorPos(x, y)
        settle(80)
        kind = window_class(x, y)
        result.setdefault('video_window_class', kind)
        return x, y

    def click_video(offset=None, double=False):
        video_point(offset)
        before = presses.count
        for index in range(2 if double else 1):
            if index:
                settle(60)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        settle(40)
        return before

    def press(vk, extended=False):
        flag = 0x1 if extended else 0  # 확장 키(PgDn 등)는 플래그가 없으면 숫자 패드 키가 된다.
        user32.keybd_event(vk, 0, flag, 0)
        user32.keybd_event(vk, 0, flag | 0x2, 0)
        settle(250)

    def combo(*vks):
        for vk in vks:
            user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            user32.keybd_event(vk, 0, 0x2, 0)
        settle(60)

    def passed(name):
        assert window.isActiveWindow(), f'{name}: 앱 창이 활성 창이 아님'
        result['passed'].append(name)

    def wait_interval():
        settle(round(interval * 1000) + 300)

    # 창 모드 한 번 클릭: 판정 시간 뒤에 일시정지하고, 초점·재생 키는 앱에 남는다.
    page.subtitles_button.setFocus()
    before = click_video()
    assert not window.player.paused, '판정 시간 전에 일시정지했다'
    wait(lambda: window.player.paused, '한 번 클릭으로 일시정지')
    assert presses.count > before, '누름이 표면으로 오지 않았다'
    assert window.surface.hasFocus(), '클릭 뒤 영상에 초점이 없다'
    press(0x0D)  # Enter
    wait(lambda: not window.player.paused, '클릭 뒤 Enter로 재개')
    passed('window-single-click-and-keys')

    # 창 모드 두 번 클릭: 전체 화면만 켜고 재생 상태는 그대로다.
    click_video(double=True)
    wait(window.isFullScreen, '두 번 클릭으로 전체 화면')
    wait_interval()
    assert not window.player.paused, '두 번 클릭이 재생 상태를 바꿨다'
    passed('window-double-click-fullscreen')

    # 전체 화면 커서 이동 → 조작 줄.
    settle(300)
    page.hide_temporary_bar()
    assert not page.bottom_bar.isVisible()
    x, y = point(page.surface)
    user32.SetCursorPos(x + 40, y + 40)
    wait(page.bottom_bar.isVisible, '전체 화면 커서 이동으로 조작 줄 표시')
    passed('fullscreen-pointer-reveals-bar')

    click_video()
    wait(lambda: window.player.paused, '전체 화면 한 번 클릭으로 일시정지')
    assert window.isFullScreen()
    click_video()
    wait(lambda: not window.player.paused, '전체 화면 한 번 클릭으로 재개')
    passed('fullscreen-single-click')
    click_video(double=True)
    wait(lambda: not window.isFullScreen(), '두 번 클릭으로 전체 화면 끄기')
    wait_interval()
    assert not window.player.paused, '전체 화면 끄기 두 번 클릭이 재생 상태를 바꿨다'
    passed('fullscreen-double-click-off')

    # 키 안내가 열려 있으면 영상 클릭은 키 안내만 닫는다. 안내는 영상 가운데에 있으므로 왼쪽 위를 누른다.
    press(0x70)  # F1
    wait(page.help_panel.isVisible, 'F1로 키 안내 열기')
    corner = QPoint(30, 30)
    assert not page.help_panel.geometry().contains(page.surface.mapToGlobal(corner)), '누를 곳이 키 안내에 가림'
    click_video(corner)
    wait(lambda: not page.help_panel.isVisible(), '영상 클릭으로 키 안내 닫기')
    wait_interval()
    assert not window.player.paused and not window.isFullScreen(), '키 안내를 닫은 클릭이 재생을 조작했다'
    passed('click-closes-key-guide')

    # 재생 메뉴가 열려 있으면 영상 클릭은 메뉴만 닫는다. 메뉴 단추를 OS 클릭으로 누르면 QMenu.exec의 중첩 루프에서
    # 이 스크립트의 대기가 돌아오지 않으므로, 메뉴는 같은 자리에 popup으로 열고 영상만 OS 클릭으로 누른다.
    button = page.menu_button
    page.menu.popup(button.mapToGlobal(button.rect().topRight()))
    wait(page.menu.isVisible, '재생 메뉴 열기')
    before = click_video(corner)
    wait(lambda: not page.menu.isVisible(), '영상 클릭으로 메뉴 닫기')
    wait_interval()
    assert not window.player.paused and not window.isFullScreen(), '메뉴를 닫은 클릭이 재생을 조작했다'
    result['menu_close_surface_press'] = presses.count > before
    passed('click-closes-menu')

    click_video()
    wait(lambda: window.player.paused, '메뉴를 닫은 뒤 한 번 클릭')
    passed('click-after-menu')

    # 속도 목록(#238)이 열려 있으면 영상 클릭은 목록만 닫는다. 재생 메뉴와 같은 이유로 popup으로 연다.
    speed = window.player.playback_options()[0]
    page.speed_menu.popup(page.menu_anchor_point(page.speed_menu))
    wait(page.speed_menu.isVisible, '속도 목록 열기')
    click_video(corner)
    wait(lambda: not page.speed_menu.isVisible(), '영상 클릭으로 속도 목록 닫기')
    wait_interval()
    assert window.player.paused and not window.isFullScreen(), '속도 목록을 닫은 클릭이 재생을 조작했다'
    assert window.player.playback_options()[0] == speed, '속도 목록을 닫은 클릭이 속도를 바꿨다'
    click_video()
    wait(lambda: not window.player.paused, '속도 목록을 닫은 뒤 한 번 클릭')
    passed('click-closes-speed-list')

    # 영상 전환 직후의 클릭은 이전 영상의 누름과 두 번 클릭으로 묶이지 않는다.
    first_session = core.playback.session
    click_video()
    press(0x22, extended=True)  # PgDn: 판정 시간 안에 다음 영상
    wait(lambda: core.playback.session is not first_session, 'PgDn으로 다음 영상')
    click_video()
    settle(150)
    assert not window.isFullScreen(), '서로 다른 영상의 누름이 두 번 클릭이 됐다'
    wait(lambda: window.player.paused, '다음 영상의 한 번 클릭')
    assert not window.isFullScreen()
    passed('click-after-video-switch')

    # 클릭 직후 긴급 탈출 → 판정 시간 안에 복원해도 남은 클릭이 재생을 다시 틀지 않는다.
    click_video()  # 일시정지를 푸는 클릭이 판정 대기 중
    combo(0x11, 0x10, 0x48)  # Ctrl+Shift+H
    wait(lambda: not window.isVisible(), '긴급 탈출로 창 숨김')
    assert window.player.paused
    window.tray.open()
    wait(window.isVisible, '트레이 열기로 복원')
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    wait_interval()
    assert window.player.paused, '긴급 탈출 전 클릭이 복원 뒤 재생을 다시 틀었다'
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000), '복원 뒤 앱 창 활성화 실패'
    click_video()
    wait(lambda: not window.player.paused, '복원 뒤 새 클릭으로 재개')
    passed('emergency-hide-drops-pending-click')
    result['surface_presses'] = presses.count
    window.tray.quit()


def main():
    args.output.mkdir(parents=True, exist_ok=True)
    # 검사가 멈춰도 데스크톱 잠금을 오래 잡지 않게 2분 뒤 프로세스를 끝낸다.
    watchdog = threading.Timer(120, lambda: (print('검사 시간 초과: 2분', flush=True), os._exit(3)))
    watchdog.daemon = True
    watchdog.start()
    app = QApplication([])
    directory = Path(tempfile.mkdtemp(prefix='video-click-', dir=args.output.resolve()))
    result = {'mode': 'real', 'passed': []}
    try:
        real(app, directory, result)
    except AssertionError as error:
        result['failed'] = str(error)
        raise
    finally:
        settle()
        shutil.rmtree(directory, ignore_errors=True)
        path = args.output / 'real-result.json'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
