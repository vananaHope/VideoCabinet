"""#49 웹 1100×720 비교와 실제 Chromium 키 입력·mpv 왕복 검사.

스크린샷: python scripts/check_web_reel_search.py --offscreen
실창: desktop_lock.py run --owner issue-49 -- python scripts/check_web_reel_search.py --verify --no-screenshots
"""
import argparse
from datetime import datetime, timezone
import hashlib
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
from my_video_manager.onscreen_subtitles import RegionImage, RegionRect
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow
from my_video_manager.web_tabs import TABS
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


# 영역 이미지 → 보이는 글자. #277 화면 자막·화면 번역 자막 검색 결과 촬영용 가짜 OCR이 읽는다.
SHOWN = {}


class OnScreenMedia(Media):
    captions = ()  # (보이기 시작, 사라짐, 화면 글자)

    def read(self, path):
        return MediaInfo(120, 'mp4')

    def region_frames(self, path, region, *, fps, cancellation, start=None, end=None):
        for index in range(round((start or 0) * fps), round((120 if end is None else end) * fps)):
            seconds = index / fps
            text = next((t for start, end, t in self.captions if start <= seconds < end), '')
            pixels = hashlib.shake_256(text.encode()).digest(64) if text else bytes(64)
            SHOWN[pixels] = text
            yield seconds, RegionImage(16, 4, pixels)


class Ocr:
    def language_available(self, language):
        return language == 'en'

    def missing_language_guidance(self, language):
        return ''

    def read_text(self, image, language):
        return SHOWN[image.pixels]


class Translator:
    def translate(self, lines, language, **kwargs):
        return tuple(TranslatedLine(line.id, '화면 번역 ' + line.text) for line in lines)


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


def tab_key(name):
    """탭 이동 예약 키(Ctrl+순번). 탭 순서는 web_tabs에서 읽는다."""
    return Qt.Key(Qt.Key.Key_1.value + [tab for tab, _ in TABS].index(name))


def mark(core, video, start, end=None, note='기억할 장면'):
    core.playback.start(video.id, start, record_viewing=False)
    core.execute_highlight_command(core.command_for_key('Insert'))
    highlight = next(h for h in core.highlights(video.id) if h.start == start)
    core.playback.end()
    return core.update_highlight(highlight.id, start=start, end=end, note=note)


def make_window(core):
    window = MainWindow(core)
    window.resize(1100, 720)
    windows.append(window)
    window.show()
    if not args.offscreen:
        window.raise_()
        window.activateWindow()
    wait_until(lambda: read(window, "!!document.getElementById('search-query')"))
    wait_until(lambda: window.web_host._frontend_ready)
    settle()
    return window


def show_results(window, core, text):
    expected = len(core.search(text).results)
    wait_until(lambda: read(window, f"document.querySelectorAll('#search-results [role=\"option\"]').length === {expected} && document.getElementById('search-results').getAttribute('aria-busy') === 'false'"))


def capture_page(core, label, tab, text='', preparing=False, failed=False, completed=False, previous=None, sources=()):
    if args.no_screenshots:
        return
    window = make_window(core)
    window.navigate_web_tab(tab)
    if tab == 'search':
        page = window.web_host.controllers['search']
        if preparing:
            page.preparation = SimpleNamespace(ready=lambda: False)
        if failed:
            def fail():
                raise RuntimeError('검증용 색인 오류')
            page.preparation = SimpleNamespace(ready=fail)
        if previous is not None:
            # 이전 검색어의 결과를 받은 뒤, 새 결과를 보내지 않아 기다리는 화면(흐린 이전 결과·기다림 표시)을 남긴다.
            query(window, previous)
            show_results(window, core, previous)
            page.refresh = lambda: None
        else:
            page.bridge.find(text)
        query(window, text)
        if previous is not None:
            wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"검색\"] [data-slot=pending-status]').textContent === '검색 중…'"))
            assert read(window, "document.getElementById('search-results').getAttribute('aria-busy')") == 'true'
            assert read(window, "document.querySelectorAll('#search-results [role=\"option\"]:not([aria-disabled=true])').length") == 0
            assert '검색 결과가 없습니다' not in read(window, "document.querySelector('main[aria-label=\"검색\"]').innerText")
        elif failed:
            wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"검색\"] [role=\"alert\"]')?.textContent === '검색 실패: 검증용 색인 오류'"))
        elif preparing:
            wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"검색\"] [role=\"status\"]').textContent.includes('색인 준비 중')"))
        else:
            show_results(window, core, text)
            # 출처 표시는 용어집 이름 그대로다. 보이는 결과 행의 첫 표시를 모은다.
            shown = set(read(window, "Array.from(document.querySelectorAll('#search-results [role=\"option\"] [data-slot=status-badge]')).map(e => e.textContent)"))
            assert set(sources) <= shown, (label, sources, shown)
            if core.search(text).truncated:
                assert read(window, "document.querySelector('main[aria-label=\"검색\"] [role=\"status\"]').textContent.includes('500개')")
    wait_until(lambda: read(window, f"!document.querySelector('main[aria-label=\"{'검색' if tab == 'search' else '하이라이트 모아보기'}\"]').parentElement.hidden"))
    if completed:
        last = core.reel_entries()[-1].highlight
        core.start_reel(highlight_id=last.id)
        window.reel.shown = core.reel_playback
        core.playback.report(core.reel_playback.end)
        core.advance_reel_if_due()
        window.reel.sync()
        wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"하이라이트 모아보기\"] [role=\"status\"]').textContent.includes('모아보기를 마쳤습니다')"))
    settle(500)
    picture = window.grab().toImage()
    assert picture.width() == 1100 and picture.height() == 720
    picture.save(str(args.output / f'web-{label}.png'))
    assert read(window, 'document.documentElement.scrollWidth <= innerWidth'), label
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    windows.remove(window)
    # 한 core로 창을 여러 번 연다. core는 폴더 감시 컨트롤러를 하나만 만들므로 닫은 창의 자리를 비운다.
    core._folder_watch = None
    checks.append(f'1100×720 웹: {label}')



def screenshots():
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'screens.sqlite3')
    path = directory / '검증 영상.mp4'
    path.write_bytes(b'screenshot fixture')
    core.add_file(path)
    video = core.videos()[0]
    core.prepare_search()
    capture_page(core, 'reel-empty', 'reel')
    capture_page(core, 'search-empty', 'search')
    capture_page(core, 'search-none', 'search', '없는검색어')
    capture_page(core, 'search-none-pending', 'search', '없는검색어 더', previous='없는검색어')
    capture_page(core, 'search-preparing', 'search', '장면', preparing=True)
    capture_page(core, 'search-error', 'search', '장면', failed=True)
    first = mark(core, video, 2, 4)
    mark(core, video, 6, 8, '다시 볼 장면')
    tag = core.add_highlight_tag(first.id, '복습')
    core.start_reel(tag.id)
    core.playback.report(4)
    core.advance_reel_if_due()
    core.playback.end()
    capture_page(core, 'reel-few', 'reel')
    capture_page(core, 'search-few', 'search', '장면')
    capture_page(core, 'search-few-pending', 'search', '장면 다시', previous='장면')
    capture_page(core, 'reel-completed', 'reel', completed=True)
    core.update_highlight(first.id, start=2, end=4, note=('긴 메모와 줄바꿈\n' + '공백없는아주긴메모' * 30))
    core.rename_video(video.id, '긴 영상 제목 ' + 'LongTitle' * 20)
    long_tag = core.add_highlight_tag(first.id, '공백없는태그' * 8)
    capture_page(core, 'reel-long', 'reel')
    capture_page(core, 'search-long', 'search', '메모')
    core.update_highlight(first.id, start=2, end=4, note='기억할 장면')
    core.delete_tag(long_tag.id)
    core.rename_video(video.id, '검증 영상')
    for index in range(501):
        mark(core, video, 10 + index / 100, note=f'검색할 장면 {index:03d}')
    capture_page(core, 'reel-many', 'reel')
    capture_page(core, 'search-cap', 'search', '장면')
    capture_page(core, 'search-cap-pending', 'search', '장면 4', previous='장면')
    onscreen_screenshots()


def onscreen_screenshots():
    """#277 화면 자막·화면 번역 자막 검색 결과: 적음, 긴 텍스트, 상한(영역 셋 × 많은 줄)."""
    media = OnScreenMedia()
    core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), database=directory / 'onscreen.sqlite3',
                   ocr_engine=Ocr(), translator=Translator())
    path = directory / '화면 자막 영상.mp4'
    path.write_bytes(b'onscreen fixture')
    core.add_file(path)
    video = core.videos()[0]

    def read_screen(captions, regions):
        core.resume_subtitle_processing()  # 촬영 창을 닫으면 자막 작업이 멈춘다.
        media.captions = captions
        core.set_onscreen_subtitle_regions(video.id, [(region, 'en') for region in regions])
        assert core.process_next_onscreen_subtitle().state == 'completed'
        while core.translation_ready():
            core.process_next_translation()

    band = RegionRect(0.08, 0.78, 0.84, 0.17)
    read_screen(((5, 8, 'Corner title'), (20, 24, 'Next corner')), (band,))
    core.prepare_search()
    sources = ('화면 자막', '화면 번역 자막')
    capture_page(core, 'search-onscreen-few', 'search', 'corner', sources=sources)
    read_screen(((5, 9, 'Long burned-in caption ' + 'NoSpaceOnScreenText' * 12 + ' and more words ' * 8),), (band,))
    capture_page(core, 'search-onscreen-long', 'search', 'caption', sources=sources)
    # 줄마다 1초씩 보이고 글자가 크게 달라야 서로 다른 줄로 남는다. 120줄 × 영역 셋 × (화면 자막, 화면 번역) > 500.
    read_screen(tuple((i, i + 1, f'Caption {i:03d} ' + hashlib.md5(str(i).encode()).hexdigest()) for i in range(120)),
                (band, RegionRect(0.05, 0.02, 0.4, 0.12), RegionRect(0.55, 0.02, 0.4, 0.12)))
    assert core.search('caption').truncated
    capture_page(core, 'search-onscreen-cap', 'search', 'caption', sources=sources)


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
    window = make_window(core)
    try:
        # 예약 탭 키는 Qt가, 입력·목록 키는 Chromium이 처리한다.
        key(window, tab_key('search'), Qt.KeyboardModifier.ControlModifier)
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
        key(window, tab_key('reel'), Qt.KeyboardModifier.ControlModifier)
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
        wait_until(lambda: read(window, "document.querySelector('main[aria-label=\"하이라이트 모아보기\"] [role=\"status\"]').textContent.includes('모아보기를 마쳤습니다')"))
        assert window.pages.count() == 2
        checks.append('모아보기 키보드 버튼 접근·실제 mpv 반복·자동 전환·복습 기록·시청 비간섭·웹 복귀')
        # 태그 필터 목록의 Esc는 목록만 닫고 페이지 Esc(라이브러리 복귀)로 새지 않는다.
        js(window, "document.querySelector('[aria-label=\"하이라이트 모아보기 태그 필터\"]').focus()")
        key(window, Qt.Key.Key_Down)
        wait_until(lambda: read(window, "!!document.querySelector('[data-slot=select-content]')"))
        key(window, Qt.Key.Key_Escape)
        wait_until(lambda: read(window, "!document.querySelector('[data-slot=select-content]')"))
        settle(200)
        assert window.web_host.active_tab == 'reel'
        assert read(window, 'document.activeElement.getAttribute("aria-label")') == '하이라이트 모아보기 태그 필터'
        checks.append('태그 필터 목록 Esc는 목록만 닫고 탭 유지')
        js(window, "document.getElementById('reel-list').focus()")
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
