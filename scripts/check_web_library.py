"""Windows 실제 창에서 Qt/웹 시험판 비교. 원본 영상은 --source에서 복사해 사용한다.

python scripts/check_web_library.py --prepare --count 24 --source <읽기 전용 폴더>
python scripts/check_web_library.py --mode web --count 24 --verify --stay
python scripts/check_web_library.py --prepare --count 5000
python scripts/check_web_library.py --mode qt --count 5000
"""
import time
STARTED = time.perf_counter()
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['qt', 'web'], default='web')
parser.add_argument('--count', type=int, default=24)
parser.add_argument('--prepare', action='store_true')
parser.add_argument('--source', type=Path)
parser.add_argument('--verify', action='store_true')
parser.add_argument('--stay', action='store_true')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'windows'
os.environ['MVM_WEB_UI'] = '1' if args.mode == 'web' else '0'

from PySide6.QtCore import Qt, QEventLoop, QTimer, QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
if args.mode == 'web':
    from my_video_manager.web_thumbnail import register_thumbnail_scheme
    register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow

app = QApplication([])
directory = ROOT / '.local' / 'issue43' / f'demo-{args.count}'
directory.mkdir(parents=True, exist_ok=True)
media_dir = directory / 'videos'
media_dir.mkdir(exist_ok=True)


class DemoMedia:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        # 데모 영상은 도메인 공개 등록 경로를 통과한다. 측정에서 디코딩 비용은 제외한다.
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        index = sum(path.stem.encode())
        image.fill(QColor.fromHsv(index % 360, 100, 85))
        painter = QPainter(image)
        painter.setPen(QColor('#eeeeee'))
        font = painter.font()
        font.setPointSize(22)
        painter.setFont(font)
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, path.stem[:12])
        painter.end()
        image.save(str(destination), 'JPG')


core = AppCore(media=DemoMedia(), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc), database=directory / 'library.sqlite3')
if args.prepare:
    if args.source:
        for path in args.source.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.mkv', '.mp4', '.webm'):
                target = media_dir / path.name
                if not target.exists():
                    shutil.copy2(path, target)
    existing = len(list(media_dir.iterdir()))
    themes = ['한글 여행', 'Python 실습', '도시 산책', '음악 이야기', '자연 다큐', '사진 수업']
    for index in range(existing, args.count):
        (media_dir / f'{themes[index % len(themes)]} {index:04d}.mkv').write_bytes(f'demo video {index}'.encode())
    core.add_watched_folder(media_dir)
    result = core.scan()
    for index in range(args.count - len(core.videos())):
        (media_dir / f'추가 데모 {index:04d}.mkv').write_bytes(f'unique supplement {index}'.encode())
    if len(core.videos()) != args.count:
        core.scan()
    for index, video in enumerate(core.videos()[:12]):
        core.add_video_tag(video.id, ['나중에 보기', '배움', '휴식'][index % 3])
        if index % 3 == 0:
            core.playback.start(video.id, 0)
            core.playback.report(35)
            core.playback.end()
    print(json.dumps({'prepared': len(core.videos()), 'added': result.added}, ensure_ascii=False))
    raise SystemExit()

window = MainWindow(core)
window.setWindowTitle(f'이슈 43 검증 · {args.mode} · {args.count}')
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page = window.library_page


def wait_until(predicate, timeout=20):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    page.engine_page.runJavaScript(code, values.append)
    wait_until(lambda: bool(values))
    return values[0]


def js_json(code):
    return json.loads(js(f'JSON.stringify({code})'))


def settle(milliseconds=250):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


if args.mode == 'web':
    wait_until(lambda: bool(js("document.querySelector('[role=gridcell]')?.textContent")))
    js("window.__firstFrame = false; requestAnimationFrame(() => requestAnimationFrame(() => window.__firstFrame = true)); true")
    wait_until(lambda: js('window.__firstFrame'))
else:
    wait_until(lambda: page.grid.model().rowCount() == args.count)
settle()
startup = (time.perf_counter() - STARTED) * 1000
screens = ROOT / '.local/screens-43'
screens.mkdir(exist_ok=True)
window.grab().save(str(screens / f'{args.mode}-{args.count}.png'))
metrics = {'mode': args.mode, 'count': args.count, 'startup_ms': round(startup, 2), 'checks': []}

if args.verify and args.mode == 'web':
    assert js("document.querySelector('img')?.naturalWidth") > 0, '썸네일 스킴'
    page.focus_content()
    wait_until(lambda: js('document.activeElement.id') == 'library-grid')
    initial_id = page.selected_video_id()
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Right)
    wait_until(lambda: page.selected_video_id() != initial_id)
    metrics['checks'].append('Chromium 방향키 선택')
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: bool(js("!!document.querySelector('[role=menu]')")))
    metrics['checks'].append('Shift+F10 메뉴')
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Escape)
    QTest.qWait(100)
    page.focus_content()
    QTest.qWait(100)
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Menu)
    wait_until(lambda: bool(js("!!document.querySelector('[role=menu]')")))
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Escape)
    metrics['checks'].append('메뉴 키')
    # 실제 DOM의 composition 이벤트를 사용한다. Windows IME 자체 검증과 구분한다.
    original_ids = page.visible_video_ids()
    js("""(() => {
      const input = document.querySelector('input'); input.focus();
      input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true, data:''}));
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'ㅎ');
      input.dispatchEvent(new InputEvent('input', {bubbles:true, data:'ㅎ', inputType:'insertCompositionText', isComposing:true}));
      input.dispatchEvent(new CompositionEvent('compositionupdate', {bubbles:true, data:'ㅎ'}));
      input.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, key:'Enter', code:'Enter', isComposing:true}));
      return true;
    })()""")
    QTest.qWait(150)
    assert page.query == '' and page.visible_video_ids() == original_ids
    assert js("document.querySelector('input').value") == 'ㅎ'
    assert window.pages.currentWidget() is page and core.playback.session is None
    js("""(() => {
      const input = document.querySelector('input');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '한글');
      input.dispatchEvent(new InputEvent('input', {bubbles:true, data:'한글', inputType:'insertCompositionText', isComposing:true}));
      input.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true, data:'한글'}));
      return true;
    })()""")
    wait_until(lambda: page.query == '한글')
    assert page.visible_video_ids() and len(page.visible_video_ids()) < len(original_ids)
    assert js("document.querySelector('input').value") == '한글'
    js("""(() => {
      const input = document.querySelector('input');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '');
      input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
      return true;
    })()""")
    wait_until(lambda: page.query == '')
    metrics['checks'].append('composition 중 미완성 입력·목록 보존, Enter 재생 방지, 완료 후 한글 필터')
    point = js_json("(() => {const r = document.querySelector('input').getBoundingClientRect(); return [r.x + 10, r.y + 10]})()")
    QTest.mouseClick(page.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    wait_until(lambda: js('document.activeElement.tagName') == 'INPUT')
    QTest.qWait(100)
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.tagName') == 'SELECT')
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.id') == 'hidden-gems')
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.id') == 'library-grid')
    metrics['checks'].append('Tab 검색 → 태그 → 숨겨진 보석 → 격자')
    for index in range(1, 6):
        page.focus_content()
        window.pages.setCurrentWidget(page)
        QTest.qWait(80)
        QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: window.pages.currentWidget() is window.navigation_pages[index])
    window.navigate(0)
    page.focus_content()
    QTest.qWait(100)
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: window.pages.currentWidget() is page)
    QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    wait_until(window.settings_menu.isVisible)
    window.settings_menu.hide()
    metrics['checks'].append('웹 포커스 Ctrl+1~6, Alt+S')
    # 실제 mpv로 열 수 있는 복사본만 골라 Enter 재생·Esc 복귀를 확인한다.
    playable = next((v for v in reversed(core.videos()) if any(loc.path.stat().st_size > 1000 for loc in v.locations)), None)
    if playable:
        index = next(i for i, v in enumerate(core.videos()) if v.id == playable.id)
        columns = int(js("Number(document.getElementById('library-grid').getAttribute('aria-colcount'))"))
        js(f"document.getElementById('library-grid').scrollTop = {index // columns * 256}")
        wait_until(lambda: bool(js(f"!!document.getElementById('video-{playable.id}')")))
        js(f"document.getElementById('video-{playable.id}')?.click()")
        wait_until(lambda: page.selected_video_id() == playable.id)
        page.focus_content()
        QTest.qWait(100)
        before = js_json("({id: document.getElementById('library-grid').getAttribute('aria-activedescendant'), top: document.getElementById('library-grid').scrollTop, cols: document.getElementById('library-grid').getAttribute('aria-colcount'), width: document.getElementById('library-grid').clientWidth, height: document.getElementById('library-grid').scrollHeight})")
        QTest.keyClick(page.view.focusProxy(), Qt.Key.Key_Return)
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(500)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait_until(lambda: window.pages.currentWidget() is page)
        QTest.qWait(250)
        after = js_json("({id: document.getElementById('library-grid').getAttribute('aria-activedescendant'), top: document.getElementById('library-grid').scrollTop, cols: document.getElementById('library-grid').getAttribute('aria-colcount'), width: document.getElementById('library-grid').clientWidth, height: document.getElementById('library-grid').scrollHeight})")
        assert before == after, (before, after)
        assert js('document.activeElement.id') == 'library-grid'
        metrics['checks'].append('실제 mpv Enter 재생 / Esc 선택·스크롤·포커스 복귀')
        # 더블클릭도 브리지를 거쳐 같은 네이티브 플레이어를 연다.
        js(f"document.getElementById('video-{playable.id}').dispatchEvent(new MouseEvent('dblclick', {{bubbles:true}}))")
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait_until(lambda: window.pages.currentWidget() is page)
        metrics['checks'].append('카드 더블클릭 mpv 전환')
    # 기존 Qt 대화상자를 실제 웹 작업 버튼으로 열고 취소한다.
    for index, expected in ((1, 'TagEditor'), (2, 'QInputDialog'), (3, 'ReviewDialog'), (4, 'SeriesEditor'), (5, 'QInputDialog')):
        observed = []
        def close_dialog():
            modal = QApplication.activeModalWidget()
            if modal:
                observed.append(type(modal).__name__)
                modal.reject()
        closer = QTimer()
        closer.setInterval(20)
        closer.timeout.connect(close_dialog)
        closer.start()
        js(f"document.querySelector('aside').querySelectorAll('button')[{index}].click()")
        wait_until(lambda: bool(observed) and not page.bridge.busy)
        closer.stop()
        assert expected in observed, (expected, observed)
    metrics['checks'].append('태그·자막·검수·시리즈·제목 변경 Qt 대화상자 연결')
    if page.gem_ids:
        dismissed = page.gem_ids[0]
        previous_selection = page.selected_id
        page.bridge.action('dismiss', dismissed)
        wait_until(lambda: dismissed not in page.gem_ids)
        assert dismissed in {v.id for v in core.videos()}
        assert page.selected_id == previous_selection
        core.restore_dismissed_video(dismissed)
        page.refresh()
        metrics['checks'].append('관심 없음·되돌리기, 라이브러리 선택 보존')

# 목록 갱신: Python 조회부터 다음 웹 프레임/Qt paint까지.
refresh = []
for _ in range(5):
    start = time.perf_counter()
    window.refresh()
    if args.mode == 'web':
        js("window.__painted = false; requestAnimationFrame(() => requestAnimationFrame(() => window.__painted = true)); true")
        wait_until(lambda: js('window.__painted'))
    else:
        app.processEvents()
        page.grid.repaint()
    refresh.append(round((time.perf_counter() - start) * 1000, 2))
metrics['refresh_ms'] = refresh

scroll_times = []
for index in range(60):
    start = time.perf_counter()
    if args.mode == 'web':
        js(f"document.getElementById('library-grid').scrollTop = {index * 180}; window.__scrolled = false; requestAnimationFrame(() => window.__scrolled = true); true")
        wait_until(lambda: js('window.__scrolled'))
    else:
        page.grid.verticalScrollBar().setValue(index * 180)
        app.processEvents()
        page.grid.repaint()
    scroll_times.append(round((time.perf_counter() - start) * 1000, 2))
metrics['scroll_step_ms'] = scroll_times
if args.mode == 'web':
    metrics['rendered_cards'] = js("document.querySelectorAll('[role=gridcell]').length")
    js("""(() => {
      window.__scrollFrames = []; window.__scrollDone = false;
      const grid = document.getElementById('library-grid'); let previous; let index = 0;
      function step(now) {
        if (previous !== undefined) window.__scrollFrames.push(now - previous);
        previous = now; grid.scrollTop = (index * 180) % Math.max(1, grid.scrollHeight - grid.clientHeight);
        if (++index < 121) requestAnimationFrame(step); else window.__scrollDone = true;
      }
      requestAnimationFrame(step); return true;
    })()""")
    wait_until(lambda: js('window.__scrollDone'))
    metrics['scroll_frame_ms'] = js_json('window.__scrollFrames')
else:
    frames = []
    frame_loop = QEventLoop()
    last_frame = [time.perf_counter()]
    def frame():
        now = time.perf_counter()
        frames.append((now - last_frame[0]) * 1000)
        last_frame[0] = now
        page.grid.verticalScrollBar().setValue((len(frames) * 180) % max(1, page.grid.verticalScrollBar().maximum()))
        page.grid.repaint()
        if len(frames) >= 120:
            frame_loop.quit()
    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(frame)
    timer.start()
    frame_loop.exec()
    timer.stop()
    metrics['scroll_frame_ms'] = frames[:120]

# 작업 관리자 세부 정보의 작업 집합(메모리)와 같은 WorkingSet64를 프로세스 트리에서 합산한다.
memory_script = f"$all = Get-CimInstance Win32_Process; $ids = @({os.getpid()}); do {{ $next = @($all | Where-Object {{ $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids }} | ForEach-Object {{ $_.ProcessId }}); $ids += $next }} while ($next.Count); Get-Process -Id $ids -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress"
result = subprocess.run(['powershell', '-NoProfile', '-Command', memory_script], capture_output=True, text=True)
processes = json.loads(result.stdout)
if isinstance(processes, dict):
    processes = [processes]
# 측정 도구인 powershell과 그 자식은 앱 메모리에서 제외한다.
processes = [p for p in processes if p['ProcessName'] in ('python', 'pythonw', 'QtWebEngineProcess')]
metrics['processes'] = processes
metrics['working_set_mib'] = round(sum(p['WorkingSet64'] for p in processes) / 2**20, 2)
metrics['private_commit_mib'] = round(sum(p['PrivateMemorySize64'] for p in processes) / 2**20, 2)
out = screens / f'{args.mode}-{args.count}{"-verify" if args.verify else ""}.json'
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({
    'mode': args.mode, 'count': args.count, 'startup_ms': metrics['startup_ms'],
    'refresh_median_ms': median(metrics['refresh_ms']),
    'scroll_frame_median_ms': median(metrics['scroll_frame_ms']),
    'working_set_mib': metrics['working_set_mib'], 'checks': metrics['checks'],
    'report': str(out),
}, ensure_ascii=False), flush=True)
if args.stay:
    if args.mode == 'web':
        js("document.getElementById('library-grid').scrollTop = 0")
    else:
        page.grid.verticalScrollBar().setValue(0)
    app.exec()
else:
    window.tray.quit()
    window.deleteLater()
    app.processEvents()
