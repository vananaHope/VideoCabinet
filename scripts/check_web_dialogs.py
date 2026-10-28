"""#53 대화상자 화면/입력 검사. 실창 실행은 반드시 desktop_lock.py 안에서 한다.

python scripts/check_web_dialogs.py --offscreen
python desktop_lock.py run --owner issue-53 -- .venv/Scripts/python scripts/check_web_dialogs.py --real
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--real', action='store_true')
parser.add_argument('--windows-ime', action='store_true', help='OS 키 전달이 가능한 데스크톱에서 실제 IME 검증을 추가한다')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-53')
args = parser.parse_args()
if not args.offscreen and not args.real:
    parser.error('--offscreen 또는 잠금 안에서 --real을 지정하세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow
from my_video_manager.web_dialogs_entries import TagEditor, TagManager
from my_video_manager.web_dialogs_entries import SeriesEditor
from my_video_manager.web_dialogs_entries import HighlightList, HighlightEditor
from my_video_manager.web_dialogs_entries import ReviewDialog

app = QApplication([])
if args.offscreen:
    # Windows offscreen 플러그인은 시스템 글꼴을 자동 열거하지 않는 경우가 있다.
    for filename in ('malgun.ttf', 'malgunbd.ttf'):
        assert QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / filename)) >= 0
args.output.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory(prefix='dialogs-', dir=args.output)
directory = Path(temporary.name)


class Media:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor('#27272a'))
        image.save(str(destination))


class Transcriber:
    def transcribe(self, path, language, **kwargs):
        return TranscriberResult('en', tuple(TranscriptSegment(i, i + .75,
            f'{i:03d} 긴 원어 자막과 줄바꿈\n' + 'Long subtitle text 한글 ' * 8) for i in range(80)), model="large-v3")


class Translator:
    def translate(self, lines, language, **kwargs):
        return tuple(TranslatedLine(line.id, '번역 자막 ' + line.text) for line in lines)


core = AppCore(media=Media(), database=directory / 'data/library.sqlite3',
               clock=lambda: datetime.now(timezone.utc),
               transcriber=Transcriber(), translator=Translator())
for i in range(40):
    path = directory / f'검사 영상 {i:03d}.mkv'
    path.write_bytes(f'dialog sample {i}'.encode())
    core.add_file(path)
video, empty = core.videos()[:2]
if args.real:
    from my_video_manager.adapters import FFmpegMediaReader
    # 합성 영상만 생성한다. 사용자 라이브러리는 읽거나 바꾸지 않는다.
    real_path = directory / '실창 테스트.mp4'
    subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                    '-t', '100', '-c:v', 'libx264', '-preset', 'ultrafast', '-y', str(real_path)], check=True)
    core.add_file(real_path)
    video = next(v for v in core.videos() if v.title == '실창 테스트')
for i in range(35):
    core.add_video_tag(video.id, f'{i:02d} 긴 태그 이름 ' + '한글태그' * 8)
core.playback.start(video.id, 0)
for i in range(30):
    core.playback.report(i * 3 + .12345)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
for i, highlight in enumerate(core.highlights(video.id)):
    core.update_highlight(highlight.id, start=highlight.start, end=highlight.start + 1 if i % 2 else None,
                          note='긴 메모와 공백없는문자열 ' + '장면메모' * 40)
core.playback.end()
core.request_subtitles(video.id)
core.process_next_subtitle()
core.process_next_translation()
core.edit_translation_line(video.id, core.review_lines(video.id)[0].original.id, '직접 검수한 번역')

window = MainWindow(core)
window.subtitles.timer.stop()
window.translations.timer.stop()
window.resize(1100, 720)
window.show()
metrics = {'checks': [], 'mode': 'web', 'real': args.real, 'screens': [], 'manual': []}


def settle(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, seconds=15):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('대기 시간 초과')


def js(code):
    result = []
    window.web_host.engine_page.runJavaScript(code, result.append)
    wait(lambda: bool(result))
    return result[0]


def capture(name, widget=window):
    if args.real:
        return  # 실창에서는 데스크톱 캡처를 하지 않는다.
    settle()
    path = args.output / f'web-{name}.png'
    captured = widget.grab()
    if (captured.width(), captured.height()) != (1100, 720):
        canvas = QImage(1100, 720, QImage.Format.Format_RGB32)
        canvas.fill(window.palette().window().color())
        painter = QPainter(canvas)
        painter.drawPixmap((1100 - captured.width()) // 2, (720 - captured.height()) // 2, captured)
        painter.end()
        assert canvas.save(str(path))
    else:
        assert captured.save(str(path))
    metrics['screens'].append(path.name)


def click(text):
    wait(lambda: js(f"(() => {{ const e = Array.from(document.querySelectorAll('[role=dialog] button, [role=alertdialog] button')).find(e => e.textContent === {json.dumps(text)}); if (!e || e.disabled) return false; e.click(); return true; }})()"))
    settle()


def input_value(label, text):
    js(f"""(() => {{ const e = document.querySelector('[aria-label={json.dumps(label)}]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(text)});
      e.dispatchEvent(new Event('input', {{bubbles:true}})); e.focus(); }})()""")
    settle()


def current():
    return json.loads(window.web_host.dialogs.bridge.snapshot())['dialog']


def web_modal(kind, context, scenario, entry=None):
    dialogs = window.web_host.dialogs
    failures = []
    measuring = args.real and window.pages.currentWidget() is not window.web_host
    if measuring:
        js("""(() => {
          const start = performance.now();
          window.dialogTiming = {start};
          const observer = new MutationObserver(() => {
            if (!document.querySelector('[role=dialog]')) return;
            window.dialogTiming.react_dom_commit_ms = performance.now() - start;
            observer.disconnect();
          }); observer.observe(document.body, {childList:true, subtree:true});
          const width = innerWidth, height = innerHeight;
          const resized = new ResizeObserver(() => {
            if (innerWidth === width && innerHeight === height) return;
            const begin = performance.now();
            document.querySelector('[role=dialog]')?.getBoundingClientRect();
            window.dialogTiming.layout_probe_ms = performance.now() - begin;
            window.dialogTiming.viewport_layout_ms = performance.now() - start;
            requestAnimationFrame(() => requestAnimationFrame(() => {
              window.dialogTiming.two_frame_opportunity_ms = performance.now() - start;
            })); resized.disconnect();
          }); resized.observe(document.documentElement);
        })()""")
    started = time.perf_counter()
    def run():
        try:
            wait(lambda: js("!!document.querySelector('[role=dialog], [role=alertdialog]')"))
            if args.real and window.pages.currentWidget() is not window.web_host:
                wait(lambda: dialogs.container is not None)
                js("window.dialogPainted = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.dialogPainted = true }))")
                wait(lambda: js('window.dialogPainted'))
                metrics.setdefault('open_to_two_frames_ms', []).append(round((time.perf_counter() - started) * 1000, 2))
                metrics.setdefault('browser_phase_timeline', []).append(json.loads(js('JSON.stringify(window.dialogTiming)')))
            settle()
            scenario()
        except BaseException as error:
            failures.append(error)
        finally:
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(0, run)
    (entry or (lambda: dialogs.run(kind, **context)))()
    settle()
    if failures:
        raise failures[0]


def memory():
    script = f"$all = Get-CimInstance Win32_Process; $ids = @({os.getpid()}); do {{ $next = @($all | Where-Object {{ $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids }} | ForEach-Object {{ $_.ProcessId }}); $ids += $next }} while ($next.Count); Get-Process -Id $ids -ErrorAction SilentlyContinue | Select-Object ProcessName,WorkingSet64 | ConvertTo-Json -Compress"
    result = json.loads(subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True, check=True).stdout)
    result = result if isinstance(result, list) else [result]
    return round(sum(p['WorkingSet64'] for p in result if p['ProcessName'] in ('python', 'pythonw', 'QtWebEngineProcess')) / 2**20, 2)




def native_save_cancel():
    """QFileDialog가 만든 Windows 기본 창을 확인하고 취소한다. 파일은 쓰지 않는다."""
    found = []
    timer = QTimer()
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def find_window(hwnd, _):
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid() and title.value == 'SRT 저장' and user32.IsWindowVisible(hwnd):
            classname = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, classname, 256)
            found.append(classname.value)
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return True
    callback = callback_type(find_window)
    timer.timeout.connect(lambda: user32.EnumWindows(callback, 0))
    timer.start(100)
    try:
        click('원어 SRT 저장')
        wait(lambda: bool(found))
        assert '#32770' in found, found
        metrics['checks'].append('Windows 기본 SRT 저장 대화상자 열기·취소')
    finally:
        timer.stop()


def windows_ime():
    """실제 한국어 키보드 레이아웃/IME에 키를 보내고 DOM과 저장 결과를 확인한다."""
    user32 = ctypes.windll.user32
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
    user32.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, wintypes.UINT]
    previous = user32.GetKeyboardLayout(0)
    korean = user32.LoadKeyboardLayoutW('00000412', 1)
    def press(key):
        user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(key, 0, 2, 0)
        settle(70)
    try:
        window.raise_(); window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000)
        window.web_host.view.setFocus()
        input_value('태그 검색', '')
        js("window.imeEvents = []; for (const name of ['compositionstart','compositionend']) document.querySelector('[aria-label=\"태그 검색\"]').addEventListener(name, e => window.imeEvents.push([name,e.data]))")
        for attempt in range(2):
            for key in 'GKS': press(ord(key))  # 두벌식: 한
            value = js("document.querySelector('[aria-label=\"태그 검색\"]').value")
            if value == '한':
                break
            input_value('태그 검색', '')
            press(0x15)  # VK_HANGUL. 레이아웃의 영문 상태라면 한글로 전환한다.
        events = js('JSON.stringify(window.imeEvents)')
        metrics['ime'] = {'layout': hex(korean or 0), 'value': value, 'events': json.loads(events)}
        assert value == '한' and 'compositionstart' in events, metrics['ime']
        before = {tag.name for tag in core.video_tags(video.id)}
        press(0x0D)
        assert {tag.name for tag in core.video_tags(video.id)} == before, 'IME 확정 Enter가 태그 추가도 실행함'
        press(0x0D)
        wait(lambda: any(tag.name == '한' for tag in core.video_tags(video.id)))
        metrics['checks'].append('실제 Windows 한국어 IME 조합·첫 Enter 확정·둘째 Enter 추가')
    finally:
        user32.ActivateKeyboardLayout(previous, 0)


try:
    host, dialogs = window.web_host, window.web_host.dialogs
    wait(lambda: host._frontend_ready)
    wait(lambda: js("!!document.getElementById('library-grid')"))
    for name, identifier in (('many-long', video.id), ('empty', empty.id)):
        for kind in ('tags', 'highlights', 'review'):
            context = {'video_id': identifier}
            if kind == 'highlights': context['duration'] = 100
            if kind == 'review': context.update(jump=window.review_jump, changed=window.review_changed)
            web_modal(kind, context, lambda name=name, kind=kind: capture(f'{kind}-{name}'))
    for kind, context in (
        ('tag-manager', {}), ('series', {}), ('highlight', {'highlight': core.highlights(video.id)[0], 'duration': 100}),
        ('subtitles', {'video_id': video.id}), ('translation', {}),
        ('video-rename', {'video_id': video.id}), ('video-exclude', {'video_id': video.id})):
        web_modal(kind, context, lambda kind=kind: capture(kind))

    def rename_keys():
        original = core.video(video.id).title
        input_value('영상 제목', '한글 제목 변경')
        js("""(() => { const e = document.querySelector('[aria-label="영상 제목"]');
          e.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
          e.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true, isComposing:true})); })()""")
        settle()
        assert core.video(video.id).title == original
        js("document.querySelector('[aria-label=\"영상 제목\"]').dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}))")
        settle()
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        wait(lambda: not dialogs.active)
        assert core.video(video.id).title == '한글 제목 변경'
    window.library_page.bridge.select(video.id)
    web_modal('video-rename', {'video_id': video.id}, rename_keys, window.library_page.library_controls.rename)
    def exclude_cancel():
        assert js('document.activeElement.textContent') == '취소'
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Escape)
        wait(lambda: not dialogs.active)
        assert not core.video(video.id).excluded
    web_modal('video-exclude', {'video_id': video.id}, exclude_cancel)
    metrics['checks'].append('제목 변경 조합 중 Enter 억제·확정 저장, 제외 기본 취소·Esc 취소')

    def tag_keys():
        original = len(core.video_tags(video.id))
        input_value('태그 검색', '조합 중')
        js("""(() => { const e = document.querySelector('[aria-label="태그 검색"]');
          e.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true, data:'조합'}));
          e.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true, isComposing:true})); })()""")
        settle()
        assert len(core.video_tags(video.id)) == original
        js("document.querySelector('[aria-label=\"태그 검색\"]').dispatchEvent(new CompositionEvent('compositionend', {bubbles:true, data:'조합 중'}))")
        settle()
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        wait(lambda: len(core.video_tags(video.id)) == original + 1)
        # 붙은 태그만 걸리는 검색어는 목록이 비고, Esc는 대화상자보다 검색어를 먼저 지운다.
        input_value('태그 검색', '00')
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Escape)
        settle()
        assert current()['kind'] == 'tags' and js("document.querySelector('[aria-label=\"태그 검색\"]').value") == ''
        input_value('태그 검색', '00')
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        wait(lambda: any(tag.name == '00' for tag in core.video_tags(video.id)))
        for key in (Qt.Key.Key_2, Qt.Key.Key_8): QTest.keyClick(host.view.focusProxy(), key, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert host.active_tab == 'library' and not window.settings_menu.isVisible()
        js("document.querySelector('[aria-label=\"붙은 태그\"]').focus()")
        for _ in range(3): QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
        selected_tag = js("document.querySelector('[aria-label=\"붙은 태그\"] [role=option][aria-selected=true]').id")
        click('모든 태그 관리')
        click('이름 변경')
        input_value('새 이름', '이름 변경 검증')
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        wait(lambda: any(tag.name == '이름 변경 검증' for tag in core.tags()))
        click('닫기')
        assert js("document.querySelector('[aria-label=\"붙은 태그\"] [role=option][aria-selected=true]').id") == selected_tag
        metrics['checks'].append('태그 IME composition·Esc 검색어 먼저·없는 이름 Enter 새 태그·셸 단축키')
        metrics['checks'].append('이름 변경 Enter 저장·중첩 대화상자 선택 복원')
    web_modal('tags', {'video_id': video.id}, tag_keys, lambda: TagEditor(core, video_id=video.id, parent=window).exec())

    def review_checks():
        click('전체 다시 생성')
        assert js("!!document.querySelector('[role=alertdialog]')")
        capture('warning')
        click('취소')
        click('원어 줄 수정')
        capture('line')
        click('취소')
        click('구간 다시 생성')
        capture('range')
        assert '실제로 받아쓸 범위' in js('document.body.innerText')
        click('취소')
        metrics['checks'].append('검수 경고·줄 수정·구간 범위·취소')
    review_context = dict(video_id=video.id, jump=window.review_jump, changed=window.review_changed)
    web_modal('review', review_context, review_checks, lambda: ReviewDialog(core, **review_context, parent=window).exec())
    core.request_subtitle_range(video.id, 0, .5)
    def locked_check():
        capture('review-locked')
        click('전체 다시 생성')
        assert js("!!document.querySelector('[role=alertdialog]')")
        click('취소')
    web_modal('review', review_context, locked_check)
    core.process_next_subtitle()

    # 제품과 같은 실제 Radix/ConfirmDialog를 별도 검사 번들로 띄운다.
    subprocess.run(['npm.cmd', 'exec', 'vite', 'build', '--', '--config', 'checks/vite.config.ts'], cwd=ROOT / 'frontend', check=True)
    js((ROOT / '.local/dialog-fixture/probe.js').read_text(encoding='utf-8'))
    for kind, expected in (('popover', False), ('nonmodal', False), ('dialog', True), ('confirm', True)):
        js(f'window.dialogProbe({json.dumps(kind)})')
        settle()
        assert dialogs.web_modal == expected, kind
        if kind == 'confirm':
            window.showFullScreen()
            settle()
            assert not window.fullscreen_settings_shortcut.isEnabled()
        if expected:
            js("window.probeKeys = []; document.addEventListener('keydown', e => window.probeKeys.push(e.key), {capture:true})")
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
            settle()
            assert host.active_tab == 'library' and not window.settings_menu.isVisible()
            keys = js('JSON.stringify(window.probeKeys)')
            assert '2' in keys and 's' in keys.lower(), keys
        js("window.dialogProbe('close')")
        wait(lambda: not dialogs.web_modal)
        if kind == 'confirm':
            assert window.fullscreen_settings_shortcut.isEnabled()
            window.showNormal()
            settle()
    metrics['checks'].append('실제 ConfirmDialog·modal Dialog 차단 / nonmodal Dialog·Popover 허용 / 키 이벤트 전달')

    if args.offscreen:
        js("document.getElementById('library-grid').scrollTop = 600")
        settle()
        before = js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])")
        selected_before = host.controllers['library'].selected_id
        window.pages.setCurrentWidget(window.playback_page)
        for kind, context in (('translation', {}), ('review', review_context)):
            def container_check(kind=kind):
                wait(lambda: dialogs.container is not None)
                settle(300)
                container = dialogs.container
                rect = json.loads(js("JSON.stringify([Math.ceil(document.querySelector('[data-dialog-frame]').getBoundingClientRect().width), Math.ceil(document.querySelector('[data-dialog-frame]').getBoundingClientRect().height)])"))
                assert [container.width(), container.height()] == rect, (container.width(), container.height(), rect, dialogs.content_size)
                assert container.width() <= window.width() and container.height() <= window.height()
                assert js("getComputedStyle(document.getElementById('root')).visibility") == 'hidden'
                assert js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])") == before, (before, js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])"))
                metrics.setdefault('container_sizes', {})[kind] = rect
                capture(f'container-{kind}', container)
            web_modal(kind, context, container_check)
        window.pages.setCurrentWidget(host)
        settle(300)
        assert js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])") == before, (before, js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])"))
        assert host.controllers['library'].selected_id == selected_before
        metrics['checks'].append('내용 크기 컨테이너 grab·숨은 페이지 가상화 크기/스크롤/선택 보존')

    if args.real:
        if args.windows_ime:
            web_modal('tags', {'video_id': video.id}, windows_ime)
        window.raise_(); window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000)
        js("document.getElementById('library-grid').scrollTop = 600")
        settle()
        scroll_before = js("document.getElementById('library-grid').scrollTop")
        selected_before = host.controllers['library'].selected_id
        window.play_video(video.id, start=0)
        wait(lambda: window.player is not None and core.playback.position > .1)
        baseline = memory()
        def playback_modal():
            wait(lambda: dialogs.container is not None)
            assert host.view.parent() is dialogs.container
            from PySide6.QtWebEngineWidgets import QWebEngineView
            assert len(window.findChildren(QWebEngineView)) == 1
            if current()['kind'] == 'review':
                session = core.playback.session
                js("document.querySelector('[role=dialog] [role=option]').click()")
                wait(lambda: core.playback.position < 2)
                assert core.playback.session is session
            before = core.playback.position
            settle(300)
            assert core.playback.position > before
            metrics['during_dialog_working_set_mib'] = memory()
            click('닫기')
        for kind, entry in (('highlights', window.show_highlights), ('review', window.show_review), ('subtitles', window.subtitles.request)):
            if kind == 'subtitles':
                def subtitle_modal():
                    wait(lambda: dialogs.container is not None)
                    click('취소')
                scenario = subtitle_modal
            else: scenario = playback_modal
            web_modal(kind, {}, scenario, entry)
            wait(lambda: window.surface.hasFocus() and window.isActiveWindow())
            QTest.keyClick(window.surface, Qt.Key.Key_Return)
            settle(200)
            paused_position = core.playback.position
            settle(250)
            assert abs(core.playback.position - paused_position) < .1
            QTest.keyClick(window.surface, Qt.Key.Key_Return)
            metrics.setdefault('playback_keys', []).append({'kind': kind, 'position': core.playback.position,
                'active': window.isActiveWindow(), 'surface_focus': window.surface.hasFocus(),
                'modal': str(QApplication.activeModalWidget()), 'web_modal': dialogs.web_modal,
                'dialogs_active': dialogs.active})
            wait(lambda: core.playback.position > paused_position + .1)
        web_modal('review', review_context, native_save_cancel, window.show_review)
        window.back_to_list()
        settle(400)
        assert js("document.getElementById('library-grid').scrollTop") == scroll_before
        assert host.controllers['library'].selected_id == selected_before
        metrics.update(before_working_set_mib=baseline, after_working_set_mib=memory(), reparent=dialogs.metrics)
        metrics['checks'].append('단일 웹 뷰·mpv 진행·재생 키 복귀·라이브러리 선택/스크롤')
        metrics['manual'].extend(['실제 Windows 한국어 IME 조합·한자 후보 선택', '재부모화 순간 검은 프레임/깜빡임의 육안 확인', 'Windows SRT 저장 창의 빠른 접근/덮어쓰기'])
    # #49 통합 뒤 실제 검색 입력/결과/선택/스크롤도 왕복한다.
    window.navigate_web_tab('search')
    wait(lambda: js("!!document.getElementById('search-query')"))
    input_value('검색어', 'Long subtitle')
    wait(lambda: js("document.querySelectorAll('#search-results [role=option]').length > 20"))
    js("document.getElementById('search-results').focus()")
    for _ in range(3): QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
    js("document.getElementById('search-results').scrollTop = 400")
    settle()
    search_state = "JSON.stringify([document.getElementById('search-query').value, document.querySelectorAll('#search-results [role=option]').length, document.getElementById('search-results').getAttribute('aria-activedescendant'), document.getElementById('search-results').scrollTop])"
    search_before = js(search_state)
    if args.real:
        window.play_video(video.id, start=0)
        wait(lambda: window.player is not None and core.playback.position > .1)
    else:
        window.pages.setCurrentWidget(window.playback_page)
    web_modal('review', review_context, lambda: click('닫기'))
    if args.real: window.back_to_list()
    else: window.pages.setCurrentWidget(host)
    settle(400)
    assert js(search_state) == search_before, (search_before, js(search_state))
    metrics['checks'].append('검색어·결과·선택·스크롤의 재생 중 검수 왕복 보존')
    metrics['checks'].append('웹 대화상자 전체·0개/많음/긴 텍스트')
finally:
    path = args.output / f'web-{"ime" if args.windows_ime else "real" if args.real else "offscreen"}-metrics.json'
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    temporary.cleanup()
