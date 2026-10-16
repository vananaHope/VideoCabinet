"""대기열 웹 비교 캡처·변경분 측정·실제 WebEngine 키보드 검사.

python scripts/check_web_queue.py --offscreen
python <desktop_lock.py> run --owner issue-50 -- .venv/Scripts/python scripts/check_web_queue.py --verify
실창 검사는 캡처하지 않는다. 시각 상태는 공개 조회 경계의 명시적 데모 값이다.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import median
import tempfile
import time
import sys

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--quick', action='store_true', help='빈 목록과 선택 행 캡처 2장만 검사')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-50')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEvent, QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.subtitle_queue import SubtitleQueueItem
from my_video_manager.ui import MainWindow

app = QApplication([])
if args.offscreen:
    # Windows offscreen 플러그인은 시스템 글꼴을 자동 열거하지 않는다.
    for font in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / font))
args.output.mkdir(parents=True, exist_ok=True)
temporary_library = tempfile.TemporaryDirectory(prefix='queue-', dir=args.output)
directory = Path(temporary_library.name).resolve()
assert directory.parent == args.output.resolve() and directory.name.startswith('queue-')


class Media:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(32, 18, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


core = AppCore(media=Media(), clock=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc),
               database=directory / 'library.sqlite3')
media_dir = directory / '영상'
media_dir.mkdir()
for index in range(300):
    path = media_dir / f'영상 {index:03}.mkv'
    path.write_bytes(f'queue fixture {index}'.encode())
core.add_watched_folder(media_dir)
core.scan()
videos = core.videos()
window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.subtitles.timer.stop()
window.translations.timer.stop()
window.tray.timer.stop()
window.navigate_web_tab('queue')
host = window.web_host
page = host.controllers['queue']
metrics = {'checks': [], 'condition': '웹 기본 상태; 300개 공개 AppCore 조회 + 첫 행 진행률만 변경, 40회'}


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
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def js_json(code):
    return json.loads(js(f'JSON.stringify({code})'))


def click_text(text):
    assert js(f"(() => {{ const b = [...document.querySelectorAll('button')].find(b => b.textContent === {json.dumps(text)} && b.getClientRects().length); if (!b) return false; b.click(); return true }})()"), text
    settle()


def keys(key, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(host.view.focusProxy() or host.view, key, modifiers)
    settle(80)


def capture(name):
    if not args.offscreen:
        return
    # DOM 반영과 WebEngine 합성 프레임은 다르다. grab이 이전 프레임을 읽지 않게 기다린다.
    marker = f'queue-capture-{time.perf_counter_ns()}'
    loop = QEventLoop()
    completed = []
    def ready(title):
        if title == marker:
            completed.append(True)
            loop.quit()
    host.engine_page.titleChanged.connect(ready)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(10000)
    host.engine_page.runJavaScript('requestAnimationFrame(() => requestAnimationFrame(() => '
                                  f'setTimeout(() => document.title = {json.dumps(marker)}, 100)))')
    loop.exec()
    timeout.stop()
    host.engine_page.titleChanged.disconnect(ready)
    assert completed, '캡처 프레임 대기 시간 초과'
    window.grab().save(str(args.output / f'web-{name}.png'))



try:
    wait(lambda: js("document.getElementById('queue-list') !== null"))
    settle(300)
    page.timer.stop()
    assert js("document.body.innerText.includes('자막 대기열이 비어 있습니다')")
    assert js("document.querySelectorAll('#queue-list [role=columnheader]').length") == 0
    assert js("document.querySelectorAll('#queue-list h2').length") == 1
    assert js("Array.from(document.querySelectorAll('button')).find(b => b.textContent === '실패 항목 모두 재시도').disabled")
    capture('empty')

    if args.verify:
        window.raise_()
        window.activateWindow()
        host.view.setFocus()
        window.tray.show_queue()
        settle()
        assert host.active_tab == 'queue'
        assert js("document.activeElement.id") == 'queue-list'
        metrics['checks'].append('트레이 대기열 열기와 웹 목록 포커스')
        page.timer.stop()
        for video in videos[:3]:
            core.request_subtitles(video.id)
        page.refresh()
        settle()
        keys(Qt.Key.Key_Down)
        assert js("document.querySelector('#queue-list [aria-selected=true]').dataset.queueRow") == str(videos[1].id)
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '앞당기기'
        keys(Qt.Key.Key_Space)
        assert core.subtitle_queue_items()[0].video_id == videos[1].id
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '빼기'
        keys(Qt.Key.Key_Space)
        assert videos[1].id not in {item.video_id for item in core.subtitle_queue_items()}
        keys(Qt.Key.Key_Tab)
        keys(Qt.Key.Key_Space)
        assert js("document.body.innerText.includes('재시도 0개 · 건너뜀 0개')")
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '선택한 번역 보류 재시도'
        keys(Qt.Key.Key_Space)
        metrics['checks'].append('↑↓ 선택, Tab 버튼 이동, Space 앞당기기·빼기·일괄 재시도·보류 재시도')
        # 상태 필터 Select: Enter로 열고 End·Home으로 옮긴 뒤 Enter로 고른다.
        js("document.querySelector('[aria-label=\"대기열 상태 필터\"]').focus()")
        keys(Qt.Key.Key_Return)
        assert js("!!document.querySelector('[data-slot=select-content]')")
        keys(Qt.Key.Key_End)
        keys(Qt.Key.Key_Return)
        assert js("document.body.innerText.includes('이 상태의 항목이 없습니다')")
        assert js('document.activeElement.getAttribute("aria-label")') == '대기열 상태 필터'
        keys(Qt.Key.Key_Return)
        keys(Qt.Key.Key_Home)
        keys(Qt.Key.Key_Return)
        assert not js("document.body.innerText.includes('이 상태의 항목이 없습니다')")
        metrics['checks'].append('상태 필터 Select Enter 열기·End/Home 이동·Enter 선택·포커스 복귀')
        # Tab으로 자동 규칙 버튼에 도달해 키보드로 연다.
        js("document.querySelector('[data-tab=rules]').focus()")
        keys(Qt.Key.Key_Space)
        js("document.getElementById('queue-rules').focus()")
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.id') == 'queue-target'
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.id') == 'queue-language'
        # 합성 composition 이벤트는 조합 중 저장 억제 회귀만 검증한다. 실제 한국어 IME는 수동 확인.
        js("document.activeElement.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true,data:'한'}))")
        click_text('규칙 저장')
        assert not js("!!document.querySelector('[role=alertdialog]')")
        js("document.getElementById('queue-language').dispatchEvent(new CompositionEvent('compositionend', {bubbles:true,data:'한'}))")
        keys(Qt.Key.Key_Tab)
        keys(Qt.Key.Key_Space)
        wait(lambda: js("!!document.querySelector('[role=alertdialog]')"))
        assert js('document.activeElement.textContent') == '아니요'
        draft = js('document.getElementById("queue-language").value')
        # 셸 모달 차단 여부와 독립적으로 외부 페이지 비활성화를 직접 발생시킨다.
        window.navigate_web_tab('library')
        settle()
        assert not js("!!document.querySelector('[role=alertdialog]')")
        assert core.auto_subtitle_rules() == ()
        assert not js("!!document.querySelector('main [role=alert]')")
        window.navigate_web_tab('queue')
        settle()
        assert js('document.getElementById("queue-language").value') == draft
        click_text('규칙 저장')
        keys(Qt.Key.Key_Escape)
        assert len(core.auto_subtitle_rules()) == 1
        assert len(core.subtitle_queue_items()) == 2
        metrics['checks'].append('규칙 저장 확인 기본 아니요·Esc=규칙만 저장, 조합 중 저장 억제')
        metrics['checks'].append('확인 중 페이지 비활성화=저장 없이 닫기, 입력 보존, 오류 없음')
        click_text('규칙 저장')
        keys(Qt.Key.Key_Space)  # 기본 포커스 아니요
        assert len(core.auto_subtitle_rules()) == 1
        assert len(core.subtitle_queue_items()) == 2
        # 다시 저장할 때 예를 선택하면 남은 기존 영상도 들어간다.
        click_text('규칙 저장')
        keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '예'
        keys(Qt.Key.Key_Space)
        assert len(core.subtitle_queue_items()) == 300
        js("document.getElementById('queue-rules').focus()")
        keys(Qt.Key.Key_Home)
        for _ in range(4):
            keys(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '선택 규칙 해제'
        keys(Qt.Key.Key_Space)
        assert core.auto_subtitle_rules() == ()
        # 예약 키는 앱이 실제 활성 창일 때만 처리한다. 긴 300개 등록 뒤 이를 다시 확인한다.
        window.raise_()
        window.activateWindow()
        wait(window.isActiveWindow)
        keys(Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        assert host.active_tab == 'library' and not page.timer.isActive(), (host.active_tab, window.isActiveWindow())
        keys(Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
        assert host.active_tab == 'queue'
        metrics['checks'].append('예=기존 영상 포함, 키보드 규칙 해제, Ctrl+1/4 왕복')
        click_text('처리 상태')

    # 스크린샷·성능용 명시적 반환값: 실제 300개 공개 조회 비용에 UI 상태만 덧씌운다.
    for video in videos:
        core.request_subtitles(video.id)
    original_items = core.subtitle_queue_items
    visual_count = 6
    tick = 0
    visual_states = True
    states = ('queued', 'transcribing', 'translating', 'held', 'completed', 'failed')

    def display_items():
        items = list(original_items())[:visual_count]
        if visual_states:
            items = [SubtitleQueueItem(item.video_id, item.title, states[i % 6], (i % 6) / 5,
                     '로그인을 확인한 뒤 선택한 번역 보류 재시도를 눌러 주세요. ' * 8 if i == 3 else None)
                     for i, item in enumerate(items)]
        if items:
            items[0] = replace(items[0], progress=(tick % 90) / 100,
                               title='아주 긴 한글 영상 제목 ' + 'LongVideoTitle' * 12)
        return tuple(items)

    core.subtitle_queue_items = display_items
    page.refresh()
    settle()
    assert not js("Array.from(document.querySelectorAll('button')).find(b => b.textContent === '실패 항목 모두 재시도').disabled")
    assert js("""(() => {
        const row = document.querySelector('[data-queue-row][aria-selected=true]');
        const badge = row.querySelector('[role=gridcell] span');
        const track = row.querySelector('[role=progressbar]');
        return getComputedStyle(row).backgroundColor !== getComputedStyle(badge).backgroundColor
            && getComputedStyle(row).backgroundColor !== getComputedStyle(track).backgroundColor;
    })()""")
    capture('few-all-states-long')
    if args.quick:
        print('quick: empty disabled, failed enabled, selected badge/track visible; 2 captures', flush=True)
        raise SystemExit(0)
    visual_count = 300
    page.refresh()
    wait(lambda: js('document.querySelectorAll("[data-queue-row]").length') == 300)
    assert js("document.querySelector('[aria-label=\"상태별 개수\"]').textContent.includes('대기 50개')")
    capture('300')
    assert js('document.querySelectorAll("[data-queue-row]").length') == 300
    js("document.getElementById('queue-list').focus()")
    page_size = int(js("""(() => {
      const list = document.getElementById('queue-list');
      const header = list.querySelector('[role=columnheader]').parentElement.getBoundingClientRect().height;
      return Math.max(1, Math.floor((list.clientHeight - header) / list.querySelector('[data-queue-row]').getBoundingClientRect().height));
    })()"""))
    def selected_row():
        return js("document.getElementById('queue-list').getAttribute('aria-activedescendant')")
    keys(Qt.Key.Key_Home)
    keys(Qt.Key.Key_PageDown)
    assert selected_row() == f'queue-row-{videos[page_size].id}'
    keys(Qt.Key.Key_PageUp)
    assert selected_row() == f'queue-row-{videos[0].id}'
    keys(Qt.Key.Key_PageUp)
    assert selected_row() == f'queue-row-{videos[0].id}'
    keys(Qt.Key.Key_End)
    keys(Qt.Key.Key_PageDown)
    assert selected_row() == f'queue-row-{videos[-1].id}'
    keys(Qt.Key.Key_PageUp)
    assert selected_row() == f'queue-row-{videos[-1 - page_size].id}'
    metrics['checks'].append(f'PageUp/PageDown 표시 행 {page_size}개만큼 이동 및 양 끝 경계')
    click_text('자동 자막 규칙')
    capture('rules-empty')
    for index, video in enumerate(videos[:4]):
        tag = core.add_video_tag(video.id, f'태그 {index} 긴 자동 자막 대상 ' + '배움' * 12)
        core.set_auto_subtitle_rule(tag_id=tag.id, spoken_language='en')
    page.refresh_rules()
    settle()
    capture('rules-many')
    # 후보 확인 화면은 대기열을 비운 뒤 만든다.
    for video in videos:
        core.remove_from_subtitle_queue(video.id)
    click_text('규칙 저장')
    wait(lambda: js("!!document.querySelector('[role=alertdialog]')"))
    if args.offscreen:
        settle()
        window.grab().save(str(args.output / 'web-confirm.png'))
    keys(Qt.Key.Key_Escape)
    click_text('처리 상태')
    for video in videos:
        core.request_subtitles(video.id)
    visual_states = False
    page.refresh()
    settle()
    page.timer.stop()
    query_samples = []
    for _ in range(40):
        start = time.perf_counter()
        display_items()
        query_samples.append((time.perf_counter() - start) * 1000)
    metrics['core_query_ms'] = {'median': median(query_samples), 'max': max(query_samples)}
    samples = []
    payloads = []
    page.bridge.queueChanged.connect(payloads.append)
    for _ in range(40):
        tick += 1
        start = time.perf_counter()
        page.refresh()
        samples.append((time.perf_counter() - start) * 1000)
    settle()
    metrics['python_web_ms'] = {'median': median(samples), 'max': max(samples)}
    metrics['delta_bytes'] = len(payloads[-1].encode('utf-8'))
    assert len(json.loads(payloads[-1])['rows']) == 1
    assert json.loads(payloads[-1])['order'] is None
    # DB 비용을 뺀 표시 계층 비교도 같은 300개 DTO, 같은 변경으로 따로 측정한다.
    frozen = display_items()
    core.subtitle_queue_items = lambda: (replace(frozen[0], progress=(tick % 90) / 100), *frozen[1:])
    window.navigate_web_tab('queue')
    page.timer.stop()
    settle()
    samples = []
    for _ in range(40):
        tick += 1
        start = time.perf_counter()
        page.refresh()
        samples.append((time.perf_counter() - start) * 1000)
    metrics['presentation_web_ms'] = {'median': median(samples), 'max': max(samples)}
    settle()

    # 실제 QWebChannel 신호를 JS에서 40회 발행, React/DOM commit 비용만 잰다.
    # 타이밍 동안 Python 폴링 없이 titleChanged로 종료한다. DOM MutationObserver로 행 범위를 검증한다.
    loop = QEventLoop()
    marker = f'queue-profile-{time.perf_counter_ns()}'
    finished = []
    def complete(title):
        if title == marker:
            finished.append(True)
            loop.quit()
    host.engine_page.titleChanged.connect(complete)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)
    payload = json.loads(payloads[-1])
    js_script = """
      const data = PAYLOAD;
      const results = [], frames = [], changed = new Set();
      let start = 0, sample = 0;
      const observer = new MutationObserver(records => {
        for (const record of records) {
          const element = record.target.nodeType === 1 ? record.target : record.target.parentElement;
          const row = element.closest('[data-queue-row]');
          if (row) changed.add(row.dataset.queueRow);
        }
        if (!start) return;
        const began = start;
        results.push(performance.now() - start); start = 0;
        requestAnimationFrame(() => {
          frames.push(performance.now() - began);
          if (++sample === 40) {
            observer.disconnect();
            window.queueProfile = {commitMs: results, nextFrameMs: frames, changedRows: [...changed]};
            document.title = MARKER;
          } else requestAnimationFrame(send);
        });
      });
      observer.observe(document.getElementById('queue-list'), {subtree:true,childList:true,characterData:true,attributes:true});
      const send = () => {
        data.rows[0].progress = sample / 100;
        start = performance.now();
        // QWebChannel transport dispatch는 실제 Python 신호와 같은 객체/구독자를 거친다.
        window.qt.webChannelTransport.onmessage({data: JSON.stringify({type:1,object:'queue',signal:signalIndex,args:[JSON.stringify(data)]})});
      };
      requestAnimationFrame(send);
    """
    # Qt 메타객체의 공개 신호 인덱스로 실제 채널 이벤트를 전달한다.
    signal_index = page.bridge.metaObject().indexOfSignal('queueChanged(QString)')
    js_script = js_script.replace('PAYLOAD', json.dumps(payload)).replace('MARKER', json.dumps(marker))
    host.engine_page.runJavaScript(f'(() => {{ const signalIndex = {signal_index}; {js_script} }})()')
    loop.exec()
    timeout.stop()
    host.engine_page.titleChanged.disconnect(complete)
    assert finished, '웹 갱신 측정 시간 초과'
    web = js_json('window.queueProfile')
    assert web['changedRows'] == [str(videos[0].id)], web
    metrics['web_commit_ms'] = {'median': median(web['commitMs']), 'max': max(web['commitMs'])}
    metrics['web_next_frame_ms'] = {'median': median(web['nextFrameMs']), 'max': max(web['nextFrameMs'])}
    metrics['web_changed_rows'] = web['changedRows']
    metrics['checks'].append('300개 중 진행률 1행 전송·DOM 1행 변경, 무변경 시 신호 없음')
    unchanged = len(payloads)
    page.refresh()
    assert len(payloads) == unchanged
    js("document.getElementById('queue-list').focus()")
    keys(Qt.Key.Key_End)
    scroll = js("document.getElementById('queue-list').scrollTop")
    selection = js("document.getElementById('queue-list').getAttribute('aria-activedescendant')")
    tick += 1
    page.refresh()
    settle()
    assert js("document.getElementById('queue-list').scrollTop") == scroll
    assert js("document.getElementById('queue-list').getAttribute('aria-activedescendant')") == selection
    assert js('document.activeElement.id') == 'queue-list'
    metrics['checks'].append('진행률 갱신 중 선택·스크롤·포커스 유지')
    result_path = args.output / ('live-results.json' if args.verify else 'offscreen-results.json')
    result_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
finally:
    try:
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    finally:
        temporary_library.cleanup()
