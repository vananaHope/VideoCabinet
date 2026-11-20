"""#66 외부 자막의 1100×720 화면, 갱신, 검색 재생 왕복 검사.

python scripts/check_web_external_subtitles.py --offscreen
desktop_lock.py run --owner issue-66 -- python scripts/check_web_external_subtitles.py --verify
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true', help='데스크톱 잠금 아래 실제 mpv 왕복, 캡처 없음')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-66')
args = parser.parse_args()
if not args.offscreen and not args.verify:
    parser.error('--offscreen 또는 데스크톱 잠금 아래 --verify를 사용하세요')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import executable
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow
from my_video_manager.web_contract import TABS
from my_video_manager.web_tokens import web_tokens

app = QApplication([])
if args.offscreen and os.name == 'nt':
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=None if args.verify else args.output))
checks = []


class Media:
    def read(self, path):
        return MediaInfo(60, 'mp4')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(web_tokens()['colors']['card']))
        image.save(str(destination), 'JPG')


class Player:
    """offscreen에서는 공개 재생 수명주기만 검사한다. --verify는 실제 mpv를 쓴다."""
    def __init__(self, surface):
        pass

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False


def wait(predicate, timeout=20):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    window.web_host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def press_detail_action(title):
    """상세 패널의 작업을 누른다. 재생·태그 편집은 단추, 나머지는 "다른 작업" 메뉴 항목이다(#381)."""
    name = json.dumps(title)
    if js(f"[...document.querySelectorAll('aside button')].some(e => e.textContent === {name})"):
        js(f"[...document.querySelectorAll('aside button')].find(e => e.textContent === {name}).click()")
        return
    js("document.querySelector('aside button[aria-label=\"다른 작업\"]').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, button: 0, pointerType: 'mouse'}))")
    wait(lambda: js(f"[...document.querySelectorAll('[role=menuitem]')].some(e => e.textContent === {name})"))
    js(f"[...document.querySelectorAll('[role=menuitem]')].find(e => e.textContent === {name}).click()")


def read(expression):
    return json.loads(js(f'JSON.stringify({expression})'))


def key(value, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(window.focusWidget() or window, value, modifiers)
    QTest.qWait(100)


def capture(name):
    QTest.qWait(350)
    assert read('document.documentElement.scrollWidth <= innerWidth')
    assert read("[...document.querySelectorAll('#detail-scroll, #search-results')].every(e => e.scrollWidth <= e.clientWidth)")
    if not args.verify:
        image = window.grab().toImage()
        assert (image.width(), image.height()) == (1100, 720)
        assert image.save(str(args.output / f'{name}.png'))
    checks.append(name)


def cue(text='찾을 장면', start='00:00:12,125'):
    return f'1\n{start} --> 00:00:15,000\n{text}\n'


class Transcriber:
    def transcribe(self, path, spoken_language, **kwargs):
        return TranscriberResult('en', (TranscriptSegment(7, 9, '찾을 장면 원어'),), model="large-v3")


class Translator:
    def translate(self, lines, language, **kwargs):
        return tuple(TranslatedLine(line.id, '찾을 장면 번역') for line in lines)


core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3',
               transcriber=Transcriber(), translator=Translator())
path = directory / '원본' / '영화' / '영상.mp4'
path.parent.mkdir(parents=True)
if args.verify:
    subprocess.run([executable('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=160x90:rate=8', '-t', '60', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-y', str(path)], check=True, timeout=60)
else:
    path.write_bytes(b'external subtitle demo')
core.add_file(path)
video = core.videos()[0]
window = MainWindow(core)
if not args.verify:
    window.player_factory = Player
window.resize(1100, 720)
window.show()
if args.verify:
    window.raise_()
    window.activateWindow()
section = "document.querySelector('section[aria-label=\"외부 자막\"]')"
try:
    wait(lambda: window.web_host._frontend_ready)
    wait(lambda: read(f'!!{section}'))
    assert read(f"{section}.textContent.includes('가져온 외부 자막이 없습니다.')")
    js("document.getElementById('detail-scroll').scrollTop = 10000")
    capture('detail-empty')

    path.with_suffix('.smi').write_text(
        '<SYNC Start=12125><P Class=KRCC>찾을 장면<P Class=ENCC>찾을 장면 English'
        '<SYNC Start=15000><P Class=KRCC>&nbsp;<P Class=ENCC>&nbsp;', encoding='cp949')
    path.with_suffix('.srt').write_text(cue(), encoding='utf-16')
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 2"))
    assert read(f"['한국어', '영어', '언어 모름', '1줄'].every(t => {section}.textContent.includes(t))")
    js(f'{section}.scrollIntoView({{block: "start"}})')
    capture('detail-languages')

    smi = path.with_suffix('.smi')
    original_smi = smi.read_bytes()
    smi.write_text('<STYLE>.KRCC {lang:ko;} .COMMENT {lang:ko;} .ENCC {lang:en;}</STYLE>'
                   '<SYNC Start=12125><P Class=KRCC>대사<P Class=COMMENT>해설<P Class=ENCC>English',
                   encoding='utf-8')
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.textContent.includes('COMMENT')"))
    assert not read(f"{section}.textContent.includes('ENCC')")
    capture('detail-smi-multiple-tracks')
    smi.write_bytes(original_smi)

    copy = directory / '복사본' / '영화' / path.name
    copy.parent.mkdir(parents=True)
    copy.write_bytes(path.read_bytes())
    copy.with_suffix('.smi').write_bytes(original_smi)
    core.add_file(copy)
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 3"))
    titles = read(f"[...{section}.querySelectorAll('p[title]')].map(e => e.title)")
    assert str(Path('복사본/영화')) in titles and str(Path('원본/영화')) in titles
    js(f"[...{section}.querySelectorAll('li')].find(e => e.querySelectorAll('p[title]').length === 2).scrollIntoView({{block: 'start'}})")
    capture('detail-mirror-copies')
    copy.with_suffix('.smi').unlink()
    core.scan()

    if os.name == 'nt':
        with sqlite3.connect(core.database) as db:
            for root in ('D:/', 'E:/', '//server/share/'):
                db.execute("INSERT INTO external_subtitle_files(video_id,path,size,mtime_ns) VALUES(?,?,0,0)",
                           (video.id, str(Path(root) / 'root.srt')))
        window.refresh()
        wait(lambda: read(f"{section}.textContent.includes('root.srt')"))
        titles = read(f"[...{section}.querySelectorAll('p[title]')].map(e => e.title)")
        assert all(str(Path(root)) in titles for root in ('D:/', 'E:/', '//server/share/'))
        js(f'{section}.scrollIntoView({{block: "start"}})')
        js(f"[...{section}.querySelectorAll('li')].find(e => e.textContent.includes('root.srt')).scrollIntoView({{block: 'start'}})")
        capture('detail-root-copies')
        with sqlite3.connect(core.database) as db:
            db.execute("DELETE FROM external_subtitle_files WHERE video_id=? AND path LIKE '%root.srt'", (video.id,))

    path.with_suffix('.broken.vtt').write_bytes(b'\xff\xfeX')
    partial = path.with_suffix('.ja.srt')
    partial.write_text(cue('부분 성공 장면') + '\n깨진 블록\n\n다른 깨진 블록', encoding='utf-8')
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 4"))
    assert read(f"{section}.textContent.includes('읽기 실패') && {section}.textContent.includes('2개 블록을 건너뜀')")
    assert read(f"[...{section}.querySelectorAll('li')].some(e => e.textContent.includes('2개 블록') && e.textContent.includes('1줄'))")
    js(f'{section}.scrollIntoView({{block: "start"}})')
    capture('detail-warning-partial')

    failed = path.with_suffix('.cause.srt')
    failed.write_text(cue(), encoding='utf-8')
    cause = ctypes.FormatError(1117).strip() if os.name == 'nt' else 'Input/output error'
    read_bytes = Path.read_bytes
    def fail_read(file):
        if file == failed:
            raise OSError(5, cause, str(failed))
        return read_bytes(file)
    with patch.object(Path, 'read_bytes', fail_read):
        result = core.scan()
    assert any(f'(원인: {cause})' in issue.message for issue in result.issues)
    window.refresh()
    wait(lambda: read(f"{section}.textContent.includes({json.dumps(cause)})"))
    assert not read(f"{section}.textContent.includes('외부 자막:')")
    js(f"[...{section}.querySelectorAll('li')].find(e => e.textContent.includes('(원인:')).scrollIntoView({{block: 'start'}})")
    capture('detail-warning-io-cause')
    failed.unlink()
    core.scan()

    long_file = path.with_name(path.stem + '.' + 'LongFileName' * 9 + '.ko.srt')
    long_file.write_text(cue('긴 이름 장면'), encoding='utf-8')
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 5"))
    js(f"[...{section}.querySelectorAll('li')].find(e => e.textContent.includes('LongFileName')).scrollIntoView({{block: 'start'}})")
    long_title = read(f"[...{section}.querySelectorAll('p[title]')].find(e => e.title.includes('LongFileName')).title")
    assert long_title == long_file.name
    capture('detail-long-name')
    long_copy = copy.with_name(long_file.name)
    long_copy.write_bytes(long_file.read_bytes())
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 6"))
    js(f"[...{section}.querySelectorAll('li')].find(e => e.textContent.includes('LongFileName')).scrollIntoView({{block: 'start'}})")
    folders = read(f"[...{section}.querySelectorAll('li')].filter(e => e.textContent.includes('LongFileName')).map(e => e.querySelectorAll('p[title]')[1].title)")
    assert set(folders) == {str(Path('원본/영화')), str(Path('복사본/영화'))}
    assert read(f"[...{section}.querySelectorAll('li')].filter(e => e.textContent.includes('LongFileName')).every(e => {{const [name, folder] = e.querySelectorAll('p[title]'); return folder.getBoundingClientRect().top >= name.getBoundingClientRect().bottom && folder.scrollWidth <= folder.clientWidth;}})")
    capture('detail-long-name-copies')
    long_copy.unlink()
    core.scan()

    for index in range(25):
        path.with_suffix(f'.extra{index:02d}.en.srt').write_text(cue('추가 자막'), encoding='utf-8')
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 30"))
    js(f'{section}.scrollIntoView({{block: "start"}})')
    capture('detail-many-start')
    js("document.getElementById('detail-scroll').scrollTop = 100000")
    capture('detail-many-end')
    partial.unlink()
    core.scan()
    window.refresh()
    wait(lambda: read(f"{section}.querySelectorAll('li').length === 29"))
    assert not read(f"{section}.textContent.includes('2개 블록을 건너뜀')")
    checks.append('재검사 후 같은 영상의 자막 삭제·경고 제거 반영')

    other_path = directory / '자막 없는 영상.mp4'
    other_path.write_bytes(b'other video')
    core.add_file(other_path)
    other = next(v for v in core.videos() if v.id != video.id)
    window.refresh()
    wait(lambda: read(f"!!document.getElementById('video-{other.id}')"))
    js(f"document.getElementById('video-{other.id}').click()")
    wait(lambda: read(f"{section}?.textContent.includes('가져온 외부 자막이 없습니다.')"))
    assert read(f"{section}.querySelectorAll('li').length === 0")
    js(f"document.getElementById('video-{video.id}').click()")
    wait(lambda: read(f"{section}?.querySelectorAll('li').length === 29"))
    checks.append('다른 영상 선택 시 이전 자막·경고 제거와 재선택 복원')

    core.prepare_search()
    window.navigate_web_tab('search')
    wait(lambda: read("document.activeElement.id === 'search-query'"))
    js("(() => { const e = document.getElementById('search-query'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, '찾을장면'); e.dispatchEvent(new Event('input', {bubbles:true})); })()")
    wait(lambda: read("document.querySelectorAll('#search-results [role=option]').length === 3"))
    assert read("['외부 자막', '한국어', '영어', '언어 모름', '00:00:12.125'].every(t => document.getElementById('search-results').textContent.includes(t))")
    assert read("document.querySelectorAll('#search-results mark').length === 3")
    key(Qt.Key.Key_Down)
    wait(lambda: read("document.activeElement.id === 'search-results'"))
    key(Qt.Key.Key_Down)
    capture('search-languages-selected-focus')
    assert read("(() => { const chips = [...document.querySelectorAll('#search-result-1 span.rounded-md')]; return chips.length === 2 && chips.every(e => getComputedStyle(e).boxShadow !== 'none'); })()")
    if args.offscreen:
        # 캡처의 hover는 실제 가상 화면 포인터로 확인한다. 실창은 재생/포커스 검사에 쓴다.
        rect = read("(() => { const r = document.getElementById('search-result-2').getBoundingClientRect(); return [r.x + 10, r.y + 10]; })()")
        QTest.mouseMove(window.web_host.view.focusProxy(), QPoint(round(rect[0]), round(rect[1])))
        QTest.qWait(250)
        assert read("document.getElementById('search-result-2').matches(':hover')")
        capture('search-hover')
    before = read("document.getElementById('search-results').getAttribute('aria-activedescendant')")
    expected = json.loads(window.web_host.controllers['search'].bridge.snapshot())
    key(Qt.Key.Key_Return)
    wait(lambda: window.pages.currentWidget() is window.playback_page)
    assert core.playback.position >= 12.125
    key(Qt.Key.Key_Escape)
    wait(lambda: window.pages.currentWidget() is window.web_host)
    wait(lambda: read("document.activeElement.id === 'search-results'"))
    assert read("document.getElementById('search-query').value") == '찾을장면'
    assert read("document.getElementById('search-results').getAttribute('aria-activedescendant')") == before
    assert json.loads(window.web_host.controllers['search'].bridge.snapshot()) == expected
    capture('search-return')
    checks.append('외부 자막 검색 ↓ 선택·Enter 장면 재생·Esc 검색어/결과/선택/포커스 보존')
    js("document.getElementById('search-result-0').click()")
    wait(lambda: window.pages.currentWidget() is window.playback_page)
    assert core.playback.position >= 12.125
    key(Qt.Key.Key_Escape)
    wait(lambda: window.pages.currentWidget() is window.web_host)
    wait(lambda: read("document.activeElement.id === 'search-results'"))
    assert read("document.getElementById('search-results').getAttribute('aria-activedescendant')") == 'search-result-0'
    checks.append('외부 자막 결과 클릭 재생·Esc 선택 복귀')
    core.request_subtitles(video.id)
    assert core.process_next_subtitle().state == 'completed'
    assert core.process_next_translation().state == 'completed'
    js("(() => { const e = document.getElementById('search-query'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, '찾을 장면'); e.dispatchEvent(new Event('input', {bubbles:true})); })()")
    wait(lambda: read("document.querySelectorAll('#search-results [role=option]').length === 5"))
    mixed = json.loads(window.web_host.controllers['search'].bridge.snapshot())['results']
    assert {row['source'] for row in mixed} == {'원어 자막', '번역 자막', '외부 자막'}
    assert all(row['languageLabel'] is None for row in mixed if row['source'] != '외부 자막')
    capture('search-mixed-sources')
    if args.verify:
        for index, (tab, _) in enumerate(TABS):
            key(Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
            wait(lambda: window.web_host.active_tab == tab)
        key(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert window.web_host.active_tab == 'settings'
        for tab, _ in TABS:
            js(f"document.querySelector('nav [data-tab=\"{tab}\"]').click()")
            wait(lambda: window.web_host.active_tab == tab)
        key(Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        wait(lambda: window.web_host.active_tab == 'library')
        checks.append('실창 여덟 탭 클릭·Ctrl+1~8·Alt+S')

        observed = []
        closer = QTimer()
        def close_dialog():
            if window.web_host.dialogs.active and read("!!document.querySelector('[role=dialog]')"):
                observed.append(window.web_host.dialogs.stack[-1].kind)
                closer.stop()
                key(Qt.Key.Key_Escape)
        closer.timeout.connect(close_dialog)
        closer.start(100)
        try:
            press_detail_action('제목 변경')
            wait(lambda: bool(observed) and not window.library_page.bridge.busy)
        finally:
            closer.stop()
        assert observed == ['video-rename']
        assert core.video(video.id).title == video.title
        wait(lambda: read(f"{section}?.querySelectorAll('li').length === 29"))
        checks.append('정보 탭 제목 변경 대화상자 열기·Esc 취소·외부 자막 보존')

        assert QSystemTrayIcon.isSystemTrayAvailable()
        window.close()
        wait(lambda: not window.isVisible())
        window.tray.icon.contextMenu().actions()[0].trigger()
        wait(lambda: window.isVisible() and window.web_host.active_tab == 'library')
        wait(lambda: read(f"{section}?.querySelectorAll('li').length === 29"))
        checks.append('실창 닫기·트레이 열기 QAction·외부 자막 상세 복원 (OS 아이콘 클릭 제외)')
    report = dict(checks=checks, offscreen=args.offscreen, actual_mpv=args.verify,
                  human_checks=['실제 한국어 IME 입력', '다중 모니터·배율별 포커스'])
    (args.output / ('verify.json' if args.verify else 'screens.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
finally:
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
