"""#49 Qt/웹 1100×720 비교와 실제 Chromium 키 입력·mpv 왕복 검사.

스크린샷: python scripts/check_web_reel_search.py --offscreen
실창: desktop_lock.py run --owner issue-49 -- python scripts/check_web_reel_search.py --verify --no-screenshots
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--no-screenshots', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-49')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import executable
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow
from my_video_manager.web_tokens import web_tokens

app = QApplication([])
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=args.output))
checks = []
windows = []


class Media:
    def read(self, path):
        return MediaInfo(60, 'mp4')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(web_tokens()['colors']['card']))
        painter = QPainter(image)
        painter.setPen(QColor(web_tokens()['colors']['primary-text']))
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, '하이라이트 모아보기 · 장면')
        painter.end()
        image.save(str(destination), 'JPG')


def wait_until(predicate, timeout=20):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(window, code):
    result = []
    window.web_host.engine_page.runJavaScript(code, result.append)
    wait_until(lambda: bool(result))
    return result[0]


def read(window, expression):
    return json.loads(js(window, f'JSON.stringify({expression})'))


def query(window, text):
    js(window, "(() => { const input = document.getElementById('search-query'); "
       f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,{json.dumps(text)}); "
       "input.dispatchEvent(new Event('input',{bubbles:true})); })()")


def key(window, value, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(window.focusWidget() or window, value, modifiers)
    settle(100)


def mark(core, video, start, end=None, note='기억할 장면'):
    core.playback.start(video.id, start, record_viewing=False)
    core.execute_highlight_command(core.command_for_key('Insert'))
    highlight = next(h for h in core.highlights(video.id) if h.start == start)
    core.playback.end()
    return core.update_highlight(highlight.id, start=start, end=end, note=note)


def make_window(mode, core):
    os.environ['MVM_WEB_UI'] = '1' if mode == 'web' else '0'
    window = MainWindow(core)
    window.resize(1100, 720)
    windows.append(window)
    window.show()
    if not args.offscreen:
        window.raise_()
        window.activateWindow()
    if mode == 'web':
        wait_until(lambda: read(window, "!!document.getElementById('search-query')"))
        wait_until(lambda: window.web_host._frontend_ready)
    settle()
    return window


def capture_pair(core, label, tab, text='', preparing=False):
    if args.no_screenshots:
        return
    pictures = []
    for mode in ('qt', 'web'):
        window = make_window(mode, core)
        if mode == 'web':
            window.navigate_web_tab(tab)
            if tab == 'search':
                page = window.web_host.controllers['search']
                if preparing:
                    page.preparation = SimpleNamespace(ready=lambda: False)
                page.bridge.find(text)
                query(window, text)
                if preparing:
                    wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"검색\"] [role=\"status\"]').textContent.includes('색인 준비 중')"))
                else:
                    expected = len(core.search(text).results)
                    wait_until(lambda: read(window, f"document.querySelectorAll('#search-results [role=\"option\"]').length === {expected} && document.getElementById('search-results').getAttribute('aria-busy') === 'false'"))
                    if core.search(text).truncated:
                        assert read(window, "document.querySelector('main[aria-label=\"검색\"] [role=\"status\"]').textContent.includes('500개')")
            wait_until(lambda: read(window, f"!document.querySelector('main[aria-label=\"{'검색' if tab == 'search' else '하이라이트 모아보기'}\"]').parentElement.hidden"))
        else:
            window.navigate(2 if tab == 'search' else 1)
            if tab == 'search':
                page = window.navigation_pages[2]
                if preparing:
                    page.preparation = SimpleNamespace(ready=lambda: False)
                page.query.setText(text)
                page.refresh()
        settle(500)
        picture = window.grab().toImage()
        assert picture.width() == 1100 and picture.height() == 720
        picture.save(str(args.output / f'{mode}-{label}.png'))
        pictures.append(picture)
        if mode == 'web':
            assert read(window, 'document.documentElement.scrollWidth <= innerWidth'), label
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        windows.remove(window)
    pair = QImage(2200, 720, QImage.Format.Format_RGB32)
    painter = QPainter(pair)
    for index, picture in enumerate(pictures):
        painter.drawImage(index * 1100, 0, picture)
    painter.end()
    pair.save(str(args.output / f'pair-{label}.png'))
    checks.append(f'1100×720 Qt/웹: {label}')


def screenshots():
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'screens.sqlite3')
    path = directory / '검증 영상.mp4'
    path.write_bytes(b'screenshot fixture')
    core.add_file(path)
    video = core.videos()[0]
    core.prepare_search()
    capture_pair(core, 'reel-empty', 'reel')
    capture_pair(core, 'search-empty', 'search')
    capture_pair(core, 'search-none', 'search', '없는검색어')
    capture_pair(core, 'search-preparing', 'search', '장면', preparing=True)
    first = mark(core, video, 2, 4)
    mark(core, video, 6, 8, '다시 볼 장면')
    tag = core.add_highlight_tag(first.id, '복습')
    core.start_reel(tag.id)
    core.playback.report(4)
    core.advance_reel_if_due()
    core.playback.end()
    capture_pair(core, 'reel-few', 'reel')
    capture_pair(core, 'search-few', 'search', '장면')
    core.update_highlight(first.id, start=2, end=4, note=('긴 메모와 줄바꿈\n' + '공백없는아주긴메모' * 30))
    core.rename_video(video.id, '긴 영상 제목 ' + 'LongTitle' * 20)
    long_tag = core.add_highlight_tag(first.id, '공백없는태그' * 8)
    capture_pair(core, 'reel-long', 'reel')
    core.update_highlight(first.id, start=2, end=4, note='기억할 장면')
    core.delete_tag(long_tag.id)
    core.rename_video(video.id, '검증 영상')
    for index in range(501):
        mark(core, video, 10 + index / 100, note=f'검색할 장면 {index:03d}')
    capture_pair(core, 'reel-many', 'reel')
    capture_pair(core, 'search-cap', 'search', '장면')


def verify():
    path = directory / '재생 검증.mp4'
    subprocess.run([executable('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=160x90:rate=8', '-t', '60', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-y', str(path)], check=True, timeout=60)
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'verify.sqlite3')
    core.add_file(path)
    video = core.videos()[0]
    first, second = mark(core, video, 2, 4), mark(core, video, 6, 8)
    core.add_highlight_tag(first.id, '복습')
    core.prepare_search()
    window = make_window('web', core)
    try:
        # 예약 탭 키는 Qt가, 입력·목록 키는 Chromium이 처리한다.
        key(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: read(window, "document.activeElement.id === 'search-query'"))
        page = window.web_host.controllers['search']
        calls = []
        search = core.search
        core.search = lambda text: (calls.append(text), search(text))[1]
        query(window, '조합 전')
        js(window, "document.getElementById('search-query').dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}))")
        query(window, '장')
        settle(350)
        assert calls == [], calls
        js(window, "document.getElementById('search-query').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'장'}))")
        wait_until(lambda: bool(calls))
        assert calls == ['장']
        checks.append('한글 조합 이벤트 중 검색 억제·이전 debounce 취소')
        query(window, '장면')
        # debounce 완료 전 Enter도 한 번은 결과로 이동하고 재생은 하지 않는다.
        key(window, Qt.Key.Key_Return)
        wait_until(lambda: read(window, "document.activeElement.id === 'search-results'"))
        assert core.playback.session is None
        key(window, Qt.Key.Key_Down)
        selected = read(window, "document.getElementById('search-results').getAttribute('aria-activedescendant')")
        assert selected == 'search-result-1'
        js(window, "window.searchResultBefore = document.getElementById('search-result-1')")
        key(window, Qt.Key.Key_Return)
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        assert core.playback.position >= second.start
        key(window, Qt.Key.Key_Escape)
        wait_until(lambda: read(window, "document.activeElement.id === 'search-results'"))
        assert read(window, "document.getElementById('search-query').value") == '장면'
        assert read(window, "document.getElementById('search-results').getAttribute('aria-activedescendant')") == selected
        assert read(window, "window.searchResultBefore === document.getElementById('search-result-1')")
        checks.append('검색 Enter/↓ 목록 이동·Enter 실제 mpv 장면 재생·Esc 검색어/선택/DOM 유지')
        key(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: read(window, "document.activeElement.id === 'reel-list'"))
        key(window, Qt.Key.Key_End)
        assert read(window, "document.getElementById('reel-list').getAttribute('aria-activedescendant')") == f'reel-{second.id}'
        key(window, Qt.Key.Key_Home)
        key(window, Qt.Key.Key_Tab)
        assert read(window, "document.activeElement.textContent") == '처음부터 차례 재생'
        key(window, Qt.Key.Key_Return)
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        assert core.reel_playback.entry.highlight.id == first.id
        before = core.viewings(video.id)
        key(window, Qt.Key.Key_Backslash)
        assert core.reel_repeat
        wait_until(lambda: core.last_highlight_revisited_at(first.id) is not None)
        assert core.reel_playback.entry.highlight.id == first.id
        key(window, Qt.Key.Key_Backslash)
        assert not core.reel_repeat
        wait_until(lambda: core.reel_playback is not None and core.reel_playback.entry.highlight.id == second.id)
        wait_until(lambda: window.pages.currentWidget() is window.web_host)
        assert window.web_host.active_tab == 'reel'
        assert core.last_highlight_revisited_at(second.id) is not None
        assert core.viewings(video.id) == before
        checks.append('모아보기 키보드 버튼 접근·실제 mpv 반복·자동 전환·복습 기록·시청 비간섭·웹 복귀')
        key(window, Qt.Key.Key_Escape)
        wait_until(lambda: window.web_host.active_tab == 'library')
        checks.append('모아보기 Esc 라이브러리 복귀')
    finally:
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        windows.remove(window)


try:
    if not args.no_screenshots:
        screenshots()
    if args.verify:
        verify()
    result = {'checks': checks, 'offscreen': args.offscreen,
              'human_checks': ['실제 한국어 IME 자판 조합·확정', '다중 모니터·배율별 재생 왕복 포커스']}
    (args.output / ('verify.json' if args.verify else 'screens.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
finally:
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
