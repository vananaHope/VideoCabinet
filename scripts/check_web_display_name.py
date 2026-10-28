"""#302 표시 이름. offscreen은 영상 0·적음·많음·긴 제목과 긴 버전에서 1100×720 머리글·설정 버전 정보를 캡처하고 배치를 잰다.

스크린샷: python scripts/check_web_display_name.py --offscreen
실창: desktop_lock.py run --owner issue-302 -- python scripts/check_web_display_name.py --verify
실창은 Win32 창 제목(작업 표시줄·Alt+Tab 이름), 트레이 툴팁, 첫 창 닫기 트레이 알림을 확인한다.
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
parser.add_argument('--verify', action='store_true', help='실창 창 제목·트레이 툴팁·트레이 알림 확인')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-302')
args = parser.parse_args()
if args.offscreen == args.verify:
    parser.error('--offscreen과 --verify 중 하나만 지정하세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager import web_settings_page
from my_video_manager.app_version import DISPLAY_NAME, current_version
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow

app = QApplication([])
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=args.output))
checks = []
LONG_TITLE = '아주 긴 제목의 강의 영상 ' * 12
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


def library(name, count, title='강의'):
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 10, 28, tzinfo=timezone.utc),
                   database=directory / f'{name}.sqlite3')
    folder = directory / name
    folder.mkdir()
    for index in range(count):
        path = folder / f'{title} {index + 1:03}.mp4'
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


HEADER = """(() => {
  const header = document.querySelector('header'), name = header.querySelector('span');
  const nav = header.querySelector('nav'), button = header.querySelector(':scope > button');
  const rect = e => e.getBoundingClientRect(), line = parseFloat(getComputedStyle(name).lineHeight);
  const n = rect(name), v = rect(nav), b = rect(button), tabs = [...nav.querySelectorAll('button')].map(rect);
  return {text: name.textContent, title: document.title, nameOneLine: n.height <= line + 1,
    tabsOneRow: tabs.every(t => Math.abs(t.top - tabs[0].top) < 1),
    noOverlap: n.right <= v.left && v.right <= b.left, insideHeader: b.right <= rect(header).right + 1,
    tabsVisible: tabs.every(t => t.right <= v.right + 1), headerHeight: Math.round(rect(header).height)};
})()"""

SETTINGS = """(() => {
  const heading = [...document.querySelectorAll('[data-page="settings"] h3')].find(e => e.textContent.includes(' · '));
  if (!heading) return null;
  const section = heading.closest('section'), r = heading.getBoundingClientRect(), s = section.getBoundingClientRect();
  return {text: heading.textContent, inside: r.left >= s.left && r.right <= s.right + 1,
    overflow: heading.scrollWidth > heading.clientWidth + 1 || section.scrollWidth > section.clientWidth + 1,
    horizontal: document.documentElement.scrollWidth > innerWidth};
})()"""


def show_settings_version(window):
    window.navigate_web_tab('settings')
    wait_until(lambda: read(window, SETTINGS) is not None, '설정 버전 정보')
    read(window, """(() => { const h = [...document.querySelectorAll('[data-page="settings"] h3')].find(e => e.textContent.includes(' · '));
      h.scrollIntoView({block: 'center'}); return true })()""")
    settle()


def offscreen():
    for label, count, title in (('empty', 0, '강의'), ('few', 3, '강의'), ('many', 300, '강의'), ('long', 12, LONG_TITLE)):
        window = make_window(library(label, count, title))
        try:
            wait_until(lambda: read(window, "document.querySelectorAll('[data-page=library] [role=gridcell]').length") >= min(count, 1),
                       f'{label} 목록')
            header = read(window, HEADER)
            check(f'{label} 창 제목', window.windowTitle() == DISPLAY_NAME, window.windowTitle())
            check(f'{label} 머리글 이름·문서 제목', header['text'] == DISPLAY_NAME and header['title'] == DISPLAY_NAME,
                  f"{header['text']} / {header['title']}")
            check(f'{label} 머리글 배치', header['nameOneLine'] and header['tabsOneRow'] and header['noOverlap']
                  and header['insideHeader'] and header['tabsVisible'], json.dumps(header, ensure_ascii=False))
            capture(window, f'header-{label}')
            if label == 'few':
                show_settings_version(window)
                settings = read(window, SETTINGS)
                check('설정 버전 정보', settings['text'] == f'{DISPLAY_NAME} · {current_version()}' and settings['inside']
                      and not settings['overflow'] and not settings['horizontal'], json.dumps(settings, ensure_ascii=False))
                capture(window, 'settings-version')
        finally:
            close(window)
    # 개발 빌드의 긴 버전 문자열도 버전 정보 구역 안에 머문다.
    web_settings_page.current_version = lambda: LONG_VERSION
    window = make_window(library('long-version', 3))
    try:
        show_settings_version(window)
        settings = read(window, SETTINGS)
        check('긴 버전 정보', settings['text'] == f'{DISPLAY_NAME} · {LONG_VERSION}' and settings['inside']
              and not settings['overflow'] and not settings['horizontal'], json.dumps(settings, ensure_ascii=False))
        capture(window, 'settings-version-long')
    finally:
        close(window)


def verify():
    import ctypes
    window = make_window(library('real', 2))
    try:
        assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
        buffer = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(int(window.winId()), buffer, 256)
        check('Win32 창 제목(작업 표시줄·Alt+Tab)', buffer.value == DISPLAY_NAME, buffer.value)
        check('트레이 표시', QSystemTrayIcon.isSystemTrayAvailable() and window.tray.icon.isVisible())
        check('트레이 툴팁', window.tray.icon.toolTip() == f'{DISPLAY_NAME} · 자막 대기열', window.tray.icon.toolTip())
        sent = []
        real = window.tray.icon.showMessage
        window.tray.icon.showMessage = lambda *message: (sent.append(message), real(*message))
        window.close()
        wait_until(lambda: not window.isVisible(), '트레이로 숨김')
        check('첫 창 닫기 트레이 알림', len(sent) == 1 and sent[0][0] == DISPLAY_NAME, repr(sent))
        settle(4000)  # 사람이 알림 풍선을 볼 시간. 단언에는 쓰지 않는다.
        window.tray.open()
        wait_until(window.isVisible, '트레이 열기')
        check('트레이 열기로 복귀', window.isVisible())
    finally:
        close(window)


offscreen() if args.offscreen else verify()
failed = [name for name, ok, _ in checks if not ok]
print(f'{len(checks) - len(failed)}/{len(checks)} 통과', args.output)
raise SystemExit(1 if failed else 0)
