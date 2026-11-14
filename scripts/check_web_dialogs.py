"""#53 대화상자 화면/입력 검사. 실창 실행은 반드시 desktop_lock.py 안에서 한다.

python scripts/check_web_dialogs.py --offscreen
python desktop_lock.py run --owner issue-53 -- .venv/Scripts/python scripts/check_web_dialogs.py --real
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
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
from my_video_manager.random_continuous_play import RandomPlayScope
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow
from my_video_manager.web_dialogs_entries import TagEditor, TagManager
from my_video_manager.web_dialogs_entries import SeriesEditor
from my_video_manager.web_dialogs_entries import HighlightList, HighlightEditor
from my_video_manager.web_dialogs_entries import ReviewDialog
from my_video_manager.onscreen_subtitles import RegionImage, RegionRect
from my_video_manager.windows_ocr import WindowsOcrEngine

app = QApplication([])
if args.offscreen:
    # Windows offscreen 플러그인은 시스템 글꼴을 자동 열거하지 않는 경우가 있다.
    for filename in ('malgun.ttf', 'malgunbd.ttf'):
        assert QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / filename)) >= 0
args.output.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory(prefix='dialogs-', dir=args.output)
directory = Path(temporary.name)


# 영역 이미지 → 그 이미지에 보이는 글자. 가짜 OCR이 이 대응으로 읽는다(#277 화면 자막 내보내기 촬영).
SHOWN = {}


def region_image(text):
    pixels = hashlib.shake_256(text.encode()).digest(64) if text else bytes(64)
    SHOWN[pixels] = text
    return RegionImage(16, 4, pixels)


class Media:
    captions = ()  # (보이기 시작, 사라짐, 화면 글자)

    def read(self, path):
        return MediaInfo(100, 'matroska')

    def region_frames(self, path, region, *, fps, cancellation, start=None, end=None):
        for index in range(round((start or 0) * fps), round((100 if end is None else end) * fps)):
            seconds = index / fps
            yield seconds, region_image(next((t for start, end, t in self.captions if start <= seconds < end), ''))

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor('#27272a'))
        image.save(str(destination))


class Transcriber:
    language = 'en'

    def transcribe(self, path, language, **kwargs):
        return TranscriberResult(self.language, tuple(TranscriptSegment(i, i + .75,
            f'{i:03d} 긴 원어 자막과 줄바꿈\n' + 'Long subtitle text 한글 ' * 8) for i in range(80)), model="large-v3")


class Translator:
    def translate(self, lines, language, **kwargs):
        return tuple(TranslatedLine(line.id, '번역 자막 ' + line.text) for line in lines)


class Ocr(WindowsOcrEngine):
    """영어만 언어 팩이 있는 PC. 설치 안내 문구는 실제 Windows OCR 어댑터의 것이다.
    긴 언어 이름 촬영은 available에 그 언어를 잠깐 더한다."""
    available = {'en'}

    def language_available(self, language):
        return language in self.available

    def read_text(self, image, language):
        return SHOWN[image.pixels]


media, transcriber = Media(), Transcriber()
core = AppCore(media=media, database=directory / 'data/library.sqlite3',
               clock=lambda: datetime.now(timezone.utc),
               transcriber=transcriber, translator=Translator(), ocr_engine=Ocr())
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
# #277 검수 화면의 화면 자막 SRT 저장 단추. 적음: 원어 자막 없이 화면 자막만 있는 영상(화면 자막 저장 하나).
# 최대: 한국어 원어(다듬기 단추까지)에 영역 둘의 화면 자막과 화면 번역 자막이 모두 있는 영상(끝 단추가 가장 많다).
onscreen_few, onscreen_max = core.videos()[2:4]
media.captions = ((5, 8, 'Corner title'), (20, 24, 'Next scene'))
core.set_onscreen_subtitle_regions(onscreen_few.id, [(RegionRect(0.08, 0.78, 0.84, 0.17), 'en')])
assert core.process_next_onscreen_subtitle().state == 'completed'
transcriber.language = 'ko'
core.request_subtitles(onscreen_max.id)
core.process_next_subtitle()
transcriber.language = 'en'
media.captions = tuple((i * 3, i * 3 + 2, f'{i:02d} Long on-screen caption ' + 'burned in text ' * 6) for i in range(30))
core.set_onscreen_subtitle_regions(onscreen_max.id, [(RegionRect(0.08, 0.78, 0.84, 0.17), 'en'),
                                                     (RegionRect(0.05, 0.02, 0.4, 0.12), 'en')])
assert core.process_next_onscreen_subtitle().state == 'completed'
for subtitle in core.onscreen_subtitles(onscreen_max.id):
    for line in subtitle.lines:
        core.edit_onscreen_translation_line(line.id, '화면 번역 ' + line.text)

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
    # 바뀐 DOM이 실제로 그려진 뒤 찍는다. offscreen grab은 마지막으로 그린 프레임을 돌려준다.
    js("window.capturePainted = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.capturePainted = true }))")
    wait(lambda: js('window.capturePainted'))
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


def footer_layout(name):
    """맨 위 대화상자의 끝 단추 차례·모양과 틀 안쪽 오른쪽·아래 끝까지의 거리(px)를 기록한다. 전·후를 같은 방식으로 잰다."""
    layout = js("""(() => {
      const content = Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog]')).filter(e => e.getClientRects().length).at(-1)
      const style = getComputedStyle(content), frame = content.getBoundingClientRect(), box = e => e.getBoundingClientRect()
      const right = frame.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight)
      const bottom = frame.bottom - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingBottom)
      const buttons = Array.from(content.querySelectorAll('button')).filter(b => b.getClientRects().length).slice(-3)
      return JSON.stringify({frame: [Math.round(frame.width), Math.round(frame.height)], radius: style.borderTopLeftRadius,
        buttons: buttons.map(b => [b.textContent, b.dataset.variant ?? '', Math.round(right - box(b).right), Math.round(bottom - box(b).bottom)])})
    })()""")
    metrics.setdefault('footers', {})[name] = json.loads(layout)


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




def onscreen_region_edits():
    """#283 이미 화면 자막이 있는 영역 고치기(읽을 언어 대화상자)·지우기(확인 창). 검수로 고친 줄 수
    0 / 적음(3) / 최대(9,999) / 긴 텍스트(긴 영상 제목·가장 긴 언어 이름)를 재생 중 컨테이너로 찍는다."""
    dialogs = window.web_host.dialogs
    media.captions = ((5, 8, 'Corner title'), (20, 24, 'Next scene'), (30, 33, 'Third caption'))
    targets = core.videos()[4:8]
    core.rename_video(targets[3].id, '아주 긴 영상 제목이 이어지는 예능 특집 ' * 4 + '공백없는긴제목' * 6)
    Ocr.available.add('zh-Hant')
    scenarios = []
    for name, target, reviewed, language in (('zero', targets[0], 0, 'en'), ('few', targets[1], 3, 'en'),
                                             ('max', targets[2], 3, 'en'), ('long', targets[3], 3, 'zh-Hant')):
        core.add_onscreen_subtitle_region(target.id, RegionRect(0.05, 0.02, 0.4, 0.12), 'en')
        core.add_onscreen_subtitle_region(target.id, RegionRect(0.08, 0.78, 0.84, 0.17), language)
        assert core.process_next_onscreen_subtitle().state == 'completed'
        _, subtitle = core.onscreen_subtitles(target.id)
        for line in subtitle.lines[:reviewed]:
            core.edit_onscreen_translation_line(line.id, '화면 번역 ' + line.text)
        scenarios.append((name, target, subtitle.region))
    count = core.onscreen_subtitle_region_reviewed_line_count
    for name, target, region in scenarios:
        expected = {'zero': 0, 'few': 3, 'max': 9999, 'long': 3}[name]
        if name == 'max':
            # 줄 9,999개를 실제로 검수하지 않고 자릿수가 큰 수의 배치만 본다. 수 세기 자체는 pytest가 본다.
            core.onscreen_subtitle_region_reviewed_line_count = lambda region_id: 9999
        else:
            assert count(region.id) == expected
        core.playback.start(target.id, 0)
        try:
            def edit_check(name=name, expected=expected):
                wait(lambda: dialogs.container is not None)
                settle(300)
                container = dialogs.container
                assert container.width() <= window.width() and container.height() <= window.height()
                data = current()
                assert data['values']['choice'] == region.language
                assert f'검수로 고친 줄 {expected:,}개의 수정이 사라집니다' in data['information'], data['information']
                footer_layout(f'onscreen-region-edit-{name}')
                capture(f'container-onscreen-region-edit-{name}', container)
            web_modal('onscreen-region', {'video_id': target.id, 'region': region.rect, 'region_id': region.id}, edit_check)
            def delete_check(name=name, expected=expected):
                wait(lambda: dialogs.container is not None)
                settle(300)
                container = dialogs.container
                assert container.width() <= window.width() and container.height() <= window.height()
                assert f'검수로 고친 줄 {expected:,}개의 수정이 사라집니다' in current()['confirmation']
                footer_layout(f'onscreen-region-delete-{name}')
                capture(f'container-onscreen-region-delete-{name}', container)
                click('취소')
                assert not dialogs.active and core.onscreen_subtitle_regions(target.id)[1] == region
            web_modal('onscreen-region-delete', {'video_id': target.id, 'region_id': region.id}, delete_check)
        finally:
            core.playback.end()
            if name == 'max':
                del core.onscreen_subtitle_region_reviewed_line_count
    Ocr.available.discard('zh-Hant')
    metrics['checks'].append('화면 자막 영역 고치기·지우기(검수로 고친 줄 0·3·9,999·긴 제목/언어) 컨테이너 촬영, 지우기 취소 무변경')


def onscreen_review():
    """#285 검수 화면의 화면 자막. 자막 종류·영역 고르기, 화면 자막 줄 목록, 원문·화면 번역 줄 수정, 덮어쓰기 확인 창,
    화면 자막 구간 다시 생성을 화면 자막 없음(none)·적음(few: 영역 하나 두 줄, 원어 자막 없음)·
    최대와 긴 텍스트(max: 영역 둘, 긴 줄 30개씩, 모두 직접 고친 화면 번역)로 찍는다. 끝 단추가 틀 밖으로 넘치지 않는다."""
    proxy = window.web_host.view.focusProxy()
    # 읽기 대기 중 잠금을 찍는 동안 화면 자막 작업자가 먼저 처리하지 않게 멈추고, 처리는 직접 부른다.
    window.onscreen_subtitles.timer.stop()

    def frame_overflow():
        return json.loads(js("""(() => {
          const content = Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog]')).filter(e => e.getClientRects().length).at(-1)
          const frame = content.getBoundingClientRect()
          const outside = Array.from(content.querySelectorAll('button, [role=combobox]')).filter(e => e.getClientRects().length).some(e => {
            const box = e.getBoundingClientRect(); return box.left < frame.left || box.right > frame.right || box.bottom > frame.bottom })
          return JSON.stringify(content.scrollWidth > content.clientWidth || outside)
        })()"""))

    def dialog_text():
        return js("Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog]')).filter(e => e.getClientRects().length).at(-1).innerText")

    def confirm_cancel():
        js("Array.from(document.querySelectorAll('[role=alertdialog] button')).find(b => b.textContent === '취소').click()")
        wait(lambda: not current()['confirmation'] and not js("!!document.querySelector('[role=alertdialog]')"))
        settle()

    def choose(steps, name):
        """검수할 자막 고르기를 키보드로 열어 찍고, 지금 항목에서 steps칸 아래 항목을 Enter로 고른다."""
        js("document.querySelector('[aria-label=\"검수할 자막\"]').focus()")
        QTest.keyClick(proxy, Qt.Key.Key_Down)
        wait(lambda: js("document.querySelectorAll('[data-slot=select-item]').length") == len(current()['choices']))
        settle(200)
        capture(f'review-onscreen-choices-{name}')
        before = current()['values']['choice']
        # offscreen 문서는 창 포커스가 없어 :focus가 맞지 않는다. 키를 받는 activeElement로 커서를 본다.
        focused = "document.activeElement?.closest('[data-slot=select-item]')?.dataset.value ?? null"
        # Radix Select는 ↓로 열면 지금 값에 커서를 둔다. 키마다 커서가 옮겨진 뒤 다음 키를 보낸다.
        wait(lambda: js(focused) == before)
        choices = [c['id'] for c in current()['choices']]
        for step in range(1, steps + 1):
            QTest.keyClick(proxy, Qt.Key.Key_Down)
            wait(lambda: js(focused) == choices[choices.index(before) + step])
        QTest.keyClick(proxy, Qt.Key.Key_Return)
        wait(lambda: not js("!!document.querySelector('[data-slot=select-content]')") and current()['values']['choice'] != before)
        settle()

    def none_check():
        assert current()['choices'] == [] and not js("!!document.querySelector('[aria-label=\"검수할 자막\"]')")
        assert '원어 SRT 저장' in dialog_text()
        capture('review-onscreen-choices-none')
    web_modal('review', dict(video_id=video.id, jump=window.review_jump, changed=window.review_changed), none_check)

    def few_check():
        data = current()
        assert [c['title'] for c in data['choices']] == ['받아쓰기 자막 · 원어 · 번역 자막', '화면 자막 영역 1 · 영어(en) · 2줄']
        assert data['rows'] == []
        choose(1, 'few')
        data = current()
        assert data['task_kind'] == 'onscreen_translation' and [r['title'] for r in data['rows']] == ['Corner title', 'Next scene']
        text = dialog_text()
        assert '원문 · 화면 번역 자막 · 2' in text and '전체 다시 생성' not in text and '원어 SRT 저장' not in text
        assert not frame_overflow()
        footer_layout('review-onscreen-lines-few')
        capture('review-onscreen-lines-few')
        click('원문 줄 수정')
        assert current()['title'] == '원문 줄 수정' and current()['values']['text'] == 'Corner title'
        capture('onscreen-line-original-few')
        click('취소')
        click('화면 번역 줄 수정')
        assert current()['title'] == '화면 번역 줄 수정'
        capture('onscreen-line-translation-few')
        click('취소')
        click('구간 다시 생성')
        assert current()['title'] == '구간 화면 자막 다시 생성'
        assert '실제로 다시 읽을 범위: 5.000–8.000초' in dialog_text()
        capture('onscreen-range-few')
        click('다시 생성')
        wait(lambda: current()['kind'] == 'review' and current()['locked'])
        assert '화면 자막 읽기 대기·진행 중' in dialog_text()
        assert js("Array.from(document.querySelectorAll('[role=dialog] button')).filter(b => ['원문 줄 수정', '화면 번역 줄 수정', '구간 다시 생성'].includes(b.textContent)).every(b => b.disabled)")
        capture('review-onscreen-locked-few')
        assert core.process_next_onscreen_subtitle().state == 'completed'
        wait(lambda: not current()['locked'])
    web_modal('review', dict(video_id=onscreen_few.id, jump=window.review_jump, changed=window.review_changed), few_check)

    def max_check():
        data = current()
        assert [c['title'] for c in data['choices']] == [
            f'받아쓰기 자막 · 원어 · 다듬은 자막', '화면 자막 영역 1 · 영어(en) · 30줄', '화면 자막 영역 2 · 영어(en) · 30줄']
        choose(2, 'max')
        data = current()
        assert data['values']['choice'] == data['choices'][2]['id'] and len(data['rows']) == 30
        assert all(r['status'] == '직접 수정' for r in data['rows'])
        assert not frame_overflow()
        footer_layout('review-onscreen-lines-max')
        capture('review-onscreen-lines-max')
        js("document.querySelector('[data-dialog-list]').scrollTop = 100000")
        capture('review-onscreen-lines-max-end')
        click('원문 줄 수정')
        assert current()['values']['text'].startswith('00 Long on-screen caption')
        capture('onscreen-line-original-max')
        js("""(() => { const e = document.querySelector('[role=dialog] textarea');
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(e, '고친 원문 ' + e.value);
          e.dispatchEvent(new Event('input', {bubbles: true})); })()""")
        settle()
        click('저장')
        wait(lambda: bool(current()['confirmation']))
        assert '직접 고친 번역이 덮어써집니다' in current()['confirmation'] and not current()['keep_reviewed']
        assert js("!!document.querySelector('[role=alertdialog]')")
        capture('onscreen-overwrite-confirm-max')
        confirm_cancel()
        click('취소')
        click('화면 번역 줄 수정')
        assert current()['values']['text'].startswith('화면 번역 00 Long')
        capture('onscreen-line-translation-max')
        click('취소')
        click('구간 다시 생성')
        capture('onscreen-range-max')
        click('취소')
        assert not current()['locked'] and current()['kind'] == 'review'
    before = core.onscreen_subtitles(onscreen_max.id)
    web_modal('review', dict(video_id=onscreen_max.id, jump=window.review_jump, changed=window.review_changed), max_check)
    assert core.onscreen_subtitles(onscreen_max.id) == before  # 취소는 아무것도 바꾸지 않는다
    window.onscreen_subtitles.timer.start(500)
    metrics['checks'].append('검수 화면 자막: 자막 고르기·영역 줄 목록·원문/화면 번역 줄 수정·덮어쓰기 확인·구간 다시 생성·'
                             '읽기 중 잠금(없음·적음·최대/긴 텍스트) 촬영, 끝 단추 넘침 검사, 취소 무변경')


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
        capture('tag-rename')
        footer_layout('tag-rename')
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

    # #277 화면 자막 SRT 저장 단추: 0개(review-many-long·review-empty), 적음, 최대. 끝 단추가 틀 밖으로 넘치지 않는다.
    for name, target, expected in (('none', video, []), ('few', onscreen_few, ['화면 자막 SRT 저장']),
                                   ('max', onscreen_max, ['화면 자막 SRT 저장', '화면 번역 SRT 저장'])):
        def onscreen_exports(name=name, expected=expected):
            assert [row['title'] for row in current()['exports']] == expected, current()['exports']
            footer = json.loads(js("""(() => {
              const content = Array.from(document.querySelectorAll('[role=dialog]')).filter(e => e.getClientRects().length).at(-1)
              const frame = content.getBoundingClientRect()
              const buttons = Array.from(content.querySelectorAll('button')).filter(b => b.getClientRects().length && b.textContent.endsWith('SRT 저장'))
              return JSON.stringify({overflow: content.scrollWidth > content.clientWidth || buttons.some(b => {
                const box = b.getBoundingClientRect(); return box.left < frame.left || box.right > frame.right || box.bottom > frame.bottom }),
                enabled: buttons.filter(b => !b.disabled).map(b => b.textContent)})
            })()"""))
            assert not footer['overflow'], footer
            assert footer['enabled'][-len(expected):] == expected if expected else '화면 자막 SRT 저장' not in footer['enabled'], footer
            footer_layout(f'review-onscreen-{name}')
            capture(f'review-onscreen-{name}')
        context = dict(video_id=target.id, jump=window.review_jump, changed=window.review_changed)
        web_modal('review', context, onscreen_exports)
    metrics['checks'].append('검수 화면 자막·화면 번역 SRT 저장 단추(0개·적음·최대) 촬영과 끝 단추 넘침 검사')
    onscreen_review()
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
        # #296 무작위 이어 재생 범위는 재생 화면에서만 열린다(컨테이너). 플레이어 없이 재생 세션만 만들어 켜고,
        # 긴 이름 태그 35개 중 3개를 고른 태그 범위로 연다.
        core.playback.start(video.id, 0)
        core.set_random_continuous_enabled(True)
        core.set_random_continuous_scope(RandomPlayScope('tags', tag_ids=tuple(tag.id for tag in core.video_tags(video.id)[:3])))
        def random_scope_check():
            wait(lambda: dialogs.container is not None)
            settle(300)
            container = dialogs.container
            assert container.width() <= window.width() and container.height() <= window.height()
            metrics.setdefault('container_sizes', {})['random-scope'] = [container.width(), container.height()]
            footer_layout('random-scope')
            capture('container-random-scope', container)
        web_modal('random-scope', {}, random_scope_check)
        core.set_random_continuous_enabled(False)
        core.playback.end()
        # #274 화면 자막 영역의 읽을 언어(재생 중 컨테이너): 원어를 몰라 직접 고르기 / 원어 기본값(이미 정한 영역이
        # 있어도 새 영역만 더한다) / 언어 팩 없음 경고까지 겹친 가장 긴 상태.
        band = RegionRect(0.08, 0.78, 0.84, 0.17)
        for name, target in (('choose', empty), ('replace', video)):
            if name == 'replace':
                core.set_onscreen_subtitle_regions(video.id, [(band, 'en')])
            core.playback.start(target.id, 0)
            def onscreen_region_check(name=name):
                wait(lambda: dialogs.container is not None)
                settle(300)
                container = dialogs.container
                assert container.width() <= window.width() and container.height() <= window.height()
                assert current()['values']['choice'] == ('' if name == 'choose' else 'en')
                footer_layout(f'onscreen-region-{name}')
                capture(f'container-onscreen-region-{name}', container)
                if name == 'replace':
                    result = json.loads(dialogs.bridge.act(current()['id'], 'save', json.dumps({'choice': 'ja'})))
                    assert '언어 팩이 없어' in result['dialog']['warning'], result
                    settle(300)
                    capture('container-onscreen-region-missing-pack', dialogs.container)
            web_modal('onscreen-region', {'video_id': target.id, 'region': band}, onscreen_region_check)
            core.playback.end()
        metrics['checks'].append('화면 자막 읽을 언어(직접 고르기·원어 기본값·언어 팩 없음 경고) 컨테이너 촬영')
        onscreen_region_edits()
        metrics['checks'].append('무작위 이어 재생 범위(재생 중 컨테이너)·태그 이름 변경 촬영과 끝 단추 배치 기록')
        window.pages.setCurrentWidget(host)
        settle(300)
        assert js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])") == before, (before, js("JSON.stringify([document.getElementById('library-grid').scrollTop, document.getElementById('library-grid').clientWidth, document.getElementById('library-grid').clientHeight])"))
        assert host.controllers['library'].selected_id == selected_before
        metrics['checks'].append('내용 크기 컨테이너 grab·숨은 페이지 가상화 크기/스크롤/선택 보존')

        # #296 대화상자 층 밖의 웹 대화상자(키 안내·무작위 태그·페이지 확인·새 키 입력)도 같은 틀인지 찍는다.
        focus_proxy = host.view.focusProxy()
        def painted():
            js("window.shellDialogPainted = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.shellDialogPainted = true }))")
            wait(lambda: js('window.shellDialogPainted'))
            settle(300)
        def shell_dialog(name, start):
            start()
            wait(lambda: js("!!document.querySelector('[role=dialog], [role=alertdialog]')?.getClientRects().length") and dialogs.web_modal)
            painted()
            capture(name)
            QTest.keyClick(focus_proxy, Qt.Key.Key_Escape)
            wait(lambda: js("!document.querySelector('[role=dialog], [role=alertdialog]')") and not dialogs.web_modal)
        def random_tag():
            js("document.querySelector('[data-page=library] [aria-label=\"무작위 재생 범위\"]').focus()")
            QTest.keyClick(focus_proxy, Qt.Key.Key_Down)
            wait(lambda: js("document.activeElement?.dataset.slot") == 'dropdown-menu-item')
            QTest.keyClick(focus_proxy, Qt.Key.Key_End)
            wait(lambda: js("document.activeElement?.textContent.startsWith('태그에서')") is True)
            QTest.keyClick(focus_proxy, Qt.Key.Key_Return)
        host.view.setFocus()
        js("document.getElementById('library-grid').focus()")
        shell_dialog('key-guide', lambda: QTest.keyClick(focus_proxy, Qt.Key.Key_F1))
        shell_dialog('random-tag', random_tag)
        window.navigate_web_tab('settings')
        wait(lambda: host.active_tab == 'settings' and js("!!document.querySelector('#settings-category [data-category=keys]')?.getClientRects().length"))
        painted()
        shell_dialog('confirm-quit', lambda: js("Array.from(document.querySelectorAll('[aria-label=\"일반 설정\"] button')).find(b => b.textContent === '완전 종료').click()"))
        js("document.querySelector('#settings-category [data-category=keys]').click()")
        wait(lambda: js("!!document.querySelector('button[data-command]')?.getClientRects().length"))
        painted()
        shell_dialog('key-capture', lambda: js("document.querySelector('button[data-command]').click()"))
        window.navigate_web_tab('library')
        metrics['checks'].append('키 안내·무작위 태그·페이지 확인·새 키 입력 대화상자 열기·Esc 닫기')

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
