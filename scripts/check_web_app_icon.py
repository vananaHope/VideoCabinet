"""#304 앱 아이콘. offscreen은 영상 0·적음과 긴 버전에서 1100×720 설정 버전 정보 구역(아이콘·이름·버전)을 캡처하고
ICO 각 크기를 밝은·어두운 작업 표시줄 색 위에 늘어놓은 확인 판을 만든다.

스크린샷: python scripts/check_web_app_icon.py --offscreen
실창: desktop_lock.py run --owner issue-304 -- python scripts/check_web_app_icon.py --verify
실창은 앱 시작 경로와 같이 app.ico를 창 아이콘으로 정하고 Win32 창의 작은·큰 아이콘이 붙었는지 확인한다.
작업 표시줄·Alt+Tab·창 모서리·배율별 선명도는 사람이 눈으로 확인한다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true', help='실창 Win32 창 아이콘 확인')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-304')
args = parser.parse_args()
if args.offscreen == args.verify:
    parser.error('--offscreen과 --verify 중 하나만 지정하세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
import my_video_manager
from my_video_manager import web_settings_page
from my_video_manager.app_version import DISPLAY_NAME, current_version
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow
sys.path.insert(0, str(ROOT / 'scripts'))
import app_icon

app = QApplication([])
ICON = Path(my_video_manager.__file__).with_name('app.ico')
app.setWindowIcon(QIcon(str(ICON)))
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=args.output))
checks = []
LONG_VERSION = '10.20.300.dev4567+g0123456789abcdef.d20261028'


class Media:
    def read(self, path):
        return MediaInfo(60, 'mp4')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(60, 90, 120))
        image.save(str(destination), 'JPG')


def wait_until(predicate, message='조건 대기', timeout=30):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(f'{message} 시간 초과')


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def read(window, expression):
    result = []
    window.web_host.engine_page.runJavaScript(f'JSON.stringify({expression})', result.append)
    wait_until(lambda: bool(result), expression)
    return json.loads(result[0])


def check(name, ok, detail=''):
    checks.append((name, bool(ok), detail))
    print(('통과' if ok else '실패'), name, detail)


def library(name, count):
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 10, 29, tzinfo=timezone.utc),
                   database=directory / f'{name}.sqlite3')
    folder = directory / name
    folder.mkdir()
    for index in range(count):
        path = folder / f'강의 {index + 1:03}.mp4'
        path.write_bytes(bytes([index % 256]))
        core.add_file(path)
    return core


def make_window(core):
    window = MainWindow(core)
    window.resize(1100, 720)
    window.show()
    if not args.offscreen:
        window.raise_()
        window.activateWindow()
    wait_until(lambda: window.web_host._frontend_ready, 'React 초기화')
    settle()
    return window


def close(window):
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def capture(window, label):
    settle(400)
    picture = window.grab().toImage()
    assert (picture.width(), picture.height()) == (1100, 720), (picture.width(), picture.height())
    picture.save(str(args.output / f'web-{label}.png'))


SETTINGS = """(() => {
  const heading = [...document.querySelectorAll('[data-page="settings"] h3')].find(e => e.textContent.includes(' · '));
  if (!heading) return null;
  const section = heading.closest('section'), image = section.querySelector('img');
  const r = heading.getBoundingClientRect(), s = section.getBoundingClientRect(), i = image?.getBoundingClientRect();
  return {text: heading.textContent, inside: r.left >= s.left && r.right <= s.right + 1,
    overflow: heading.scrollWidth > heading.clientWidth + 1 || section.scrollWidth > section.clientWidth + 1,
    horizontal: document.documentElement.scrollWidth > innerWidth,
    image: image && {complete: image.complete, natural: [image.naturalWidth, image.naturalHeight],
      shown: [Math.round(i.width), Math.round(i.height)], alt: image.alt, local: !/^https?:/.test(image.currentSrc),
      inside: i.left >= s.left && i.right <= s.right && i.top >= s.top && i.bottom <= s.bottom,
      beside: i.right <= r.left && Math.abs((i.top + i.bottom) / 2 - (r.top + r.bottom) / 2) <= 2}};
})()"""


def show_settings_version(window):
    window.navigate_web_tab('settings')
    wait_until(lambda: (read(window, SETTINGS) or {}).get('image', {}).get('complete'), '설정 버전 정보 아이콘')
    settle()


def check_settings(label, window, version):
    settings = read(window, SETTINGS)
    image = settings['image']
    check(f'{label} 버전 정보 글자', settings['text'] == f'{DISPLAY_NAME} · {version}' and settings['inside']
          and not settings['overflow'] and not settings['horizontal'], json.dumps(settings, ensure_ascii=False))
    check(f'{label} 버전 정보 아이콘', image['complete'] and image['natural'] == [app_icon.WEB_IMAGE_SIZE] * 2
          and image['shown'] == [40, 40] and image['alt'] == '' and image['local'] and image['inside'] and image['beside'],
          json.dumps(image, ensure_ascii=False))


def board():
    """ICO의 각 프레임을 실제 크기로 밝은·어두운 작업 표시줄 색 위에 놓고, 픽셀을 보기 쉽게 4배로 늘린 판도 만든다."""
    frames = app_icon.decode_ico(ICON.read_bytes())
    sizes = sorted(frames)
    gap, height = 12, max(sizes) + 24
    width = sum(sizes) + gap * (len(sizes) + 1)
    picture = QImage(width, height * 2, QImage.Format.Format_ARGB32)
    painter = QPainter(picture)
    for row, color in enumerate(app_icon.TASKBAR_BACKGROUNDS.values()):
        painter.fillRect(0, row * height, width, height, QColor(color))
        x = gap
        for size in sizes:
            painter.drawImage(x, row * height + (height - size) // 2, frames[size])
            x += size + gap
    painter.end()
    picture.save(str(args.output / 'icon-sizes.png'))
    small = [size for size in sizes if size <= 64]
    zoomed = picture.copy(0, 0, sum(small) + gap * (len(small) + 1), height * 2)
    zoomed.scaled(zoomed.width() * 4, zoomed.height() * 4, Qt.AspectRatioMode.IgnoreAspectRatio,
                  Qt.TransformationMode.FastTransformation).save(str(args.output / 'icon-sizes-x4.png'))
    check('확인 판', True, str(args.output / 'icon-sizes.png'))


def offscreen():
    for label, count in (('empty', 0), ('few', 3)):
        window = make_window(library(label, count))
        try:
            show_settings_version(window)
            check_settings(label, window, current_version())
            capture(window, f'settings-icon-{label}')
        finally:
            close(window)
    web_settings_page.current_version = lambda: LONG_VERSION
    window = make_window(library('long-version', 3))
    try:
        show_settings_version(window)
        check_settings('긴 버전', window, LONG_VERSION)
        capture(window, 'settings-icon-long-version')
    finally:
        close(window)
    board()


def verify():
    import ctypes
    window = make_window(library('real', 2))
    try:
        assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
        user32 = ctypes.windll.user32
        user32.SendMessageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        WM_GETICON, ICON_SMALL, ICON_BIG = 0x007F, 0, 1
        hwnd = int(window.winId())
        small = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0)
        big = user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0)
        check('Win32 창 작은 아이콘(창 모서리·작업 표시줄)', bool(small), hex(small or 0))
        check('Win32 창 큰 아이콘(Alt+Tab)', bool(big), hex(big or 0))
        check('창 아이콘이 app.ico 크기 모두', {s.width() for s in window.windowIcon().availableSizes()} >= set(app_icon.ICON_SIZES),
              str(sorted({s.width() for s in window.windowIcon().availableSizes()})))
        settle(1500)
    finally:
        close(window)


try:
    offscreen() if args.offscreen else verify()
finally:
    failed = [name for name, ok, _ in checks if not ok]
    print(f'결과: {len(checks) - len(failed)}/{len(checks)} 통과', '' if not failed else f'실패: {failed}')
raise SystemExit(1 if failed else 0)
