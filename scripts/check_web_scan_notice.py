"""#201 폴더 관리 검사 안내의 1100×720 배치와 외부 자막 경고 목록의 키보드 열고 닫기 검사.

스크린샷: python scripts/check_web_scan_notice.py --offscreen
실창: desktop_lock.py run --owner issue-201 -- python scripts/check_web_scan_notice.py
실창은 캡처하지 않는다. 실제 검사로 생긴 외부 자막 경고를 실제 포커스 위젯의 키로 펼치고 닫는다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-201')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo, ScanIssue, ScanResult
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


class Player:
    def __init__(self, surface):
        pass

    def play(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def execute(self, command):
        pass


app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='scan-notice-', dir=ROOT / '.local'))
core = AppCore(database=workspace / 'data.sqlite3', media=Media(), clock=lambda: datetime.now(timezone.utc))
window = MainWindow(core, player_factory=Player)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
host = window.web_host
checks = []
layouts = {}


def wait(predicate, message='조건 대기', timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(script):
    values = []
    host.engine_page.runJavaScript(script, values.append)
    wait(lambda: bool(values), script)
    return values[0]


def key(code, modifiers=Qt.KeyboardModifier.NoModifier):
    target = QApplication.focusWidget()
    assert target is not None, '실제 키보드 포커스가 없습니다'
    if not args.offscreen:
        assert window.isActiveWindow(), '검사 창이 활성 창이 아닙니다'
    QTest.keyClick(target, code, modifiers)
    settle()


SHOWN = 'document.querySelector(\'[aria-label="검사 안내"]\').textContent'


def run_scan(result):
    if callable(result):
        window.scan(operation=result)
    else:
        window.scan(operation=lambda: result)
    wait(lambda: window.worker is None, '검사 완료')
    # 실창은 브리지 갱신이 늦을 수 있으므로 화면이 이번 결과를 그릴 때까지 기다린다.
    report = host.controllers['folders'].payload()['report']
    marks = [report['message'], *(f'{title} {len(report[key])}개' for key, title in (
        ('failures', '영상 검사 오류'), ('subtitleWarnings', '외부 자막 경고')) if report[key])]
    wait(lambda: all(mark in js(SHOWN) for mark in marks), f'검사 안내 표시: {marks}')
    settle(300)


def hold_next_reply():
    """WebChannel의 다음 응답(type 10) 하나를 잡아 둔다. 신호(type 1)는 그대로 전달한다."""
    js('''window.heldReplies = []; window.receiveReply = qt.webChannelTransport.onmessage; window.holdReply = true;
        qt.webChannelTransport.onmessage = function (event) {
            const message = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
            ;(window.seen ??= []).push([Math.round(performance.now()), message.type, message.id ?? message.signal ?? ''])
            if (window.holdReply && message.type === 10) { window.heldReplies.push(event); window.holdReply = false; return }
            window.receiveReply.call(this, event)
        }; true''')


def release_reply():
    js('window.receiveReply.call(qt.webChannelTransport, window.heldReplies.shift()); '
       'qt.webChannelTransport.onmessage = window.receiveReply; true')


def toggle():
    return '[aria-label="검사 안내"] button[aria-expanded]'


def measure(name):
    """폴더 목록과 검사 안내의 높이, 페이지·안내의 넘침을 잰다."""
    layout = json.loads(js('''JSON.stringify((() => {
        const box = selector => document.querySelector(selector)?.getBoundingClientRect()
        const main = document.querySelector('main[aria-label="폴더 관리"]')
        const report = box('[aria-label="검사 안내"]'), list = box('#folders-section')
        return {list: Math.round(list.height), report: Math.round(report.height), reportBottom: Math.round(report.bottom),
                pageScroll: main.scrollHeight - main.clientHeight, wide: document.documentElement.scrollWidth > innerWidth,
                tones: [...document.querySelectorAll('[aria-label="검사 안내"] [data-slot=notice]')].map(e => e.dataset.tone)}
    })())'''))
    layouts[name] = layout
    # 폴더 목록은 최소 높이(min-h-32, 128px)를 지키고, 페이지 자체는 가로·세로로 넘치지 않는다.
    assert layout['list'] >= 128, (name, layout)
    assert layout['pageScroll'] <= 0 and not layout['wide'], (name, layout)
    assert layout['reportBottom'] <= 720, (name, layout)
    return layout


def capture(name):
    if args.offscreen:
        settle()
        web = window.grab().toImage()
        assert (web.width(), web.height()) == (1100, 720)
        web.save(str(args.output / f'web-{name}.png'))
    return measure(name)


def issues(prefix, count, message, **kind):
    suffix = '.srt' if kind.get('subtitle') else '.mkv'
    return tuple(ScanIssue(workspace / f'{prefix} {index:03}' / f'파일 {index:03}{suffix}', message, **kind) for index in range(count))


try:
    wait(lambda: host._frontend_ready and 'folders' in host._ready_pages, 'React 초기화')
    window.navigate_web_tab('folders')
    settle()
    assert capture('initial')['tones'] == ['info']
    for index in range(30):
        folder = workspace / f'감시 폴더 {index:02}'
        folder.mkdir()
        core.add_watched_folder(folder)
    # 실제 검사: 영상 하나와 블록 하나가 깨진 외부 자막.
    video = workspace / '감시 폴더 00' / '강의.mkv'
    video.write_bytes(b'video')
    video.with_suffix('.ko.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\n정상 줄\n\n끝 잔여 블록\n', encoding='utf-8')
    # 자동 감지의 조용한 검사가 끝난 뒤에 검사 결과를 넣는다.
    settle(1500)
    wait(lambda: window.worker is None, '자동 감지 검사 완료')
    window.refresh()

    run_scan(lambda: ScanResult(0, ()))
    assert measure('none')['tones'] == ['info']
    capture('none')
    checks.append('안내 없음: 요약 정보 한 줄')

    finish = threading.Event()

    def slow():
        finish.wait(10)
        return ScanResult(0, ())

    window.scan(operation=slow)
    try:
        settle(300)
        assert js('!!document.querySelector("[role=progressbar]")')
        capture('scanning')
    finally:
        finish.set()
        wait(lambda: window.worker is None)

    def fail():
        raise RuntimeError('감시 폴더 목록을 읽지 못했습니다')

    run_scan(fail)
    assert measure('failed')['tones'] == ['error']
    assert '검사 실패: 감시 폴더 목록을 읽지 못했습니다' in js('document.querySelector(\'[aria-label="검사 안내"]\').textContent')
    capture('failed')
    # 같은 실패는 셸 상태 안내 한 곳에서만 live region으로 알린다.
    live = js('''[...document.querySelectorAll('[role=alert],[role=status]')]
        .filter(e => e.textContent.includes('검사 실패: 감시 폴더 목록을 읽지 못했습니다')).length''')
    assert live == 1, live
    checks.append('검사 중 진행 막대, 검사 실패는 오류 한 줄(live region 하나)')

    run_scan(lambda: core.scan())
    report = window.web_host.controllers['folders'].payload()['report']
    assert [w['message'] for w in report['subtitleWarnings']] == ['1개 블록을 건너뜀'] and not report['failures'], report
    assert measure('subtitle-one')['tones'] == ['warning', 'info']
    assert js(f'document.querySelector({json.dumps(toggle())}).getAttribute("aria-expanded")') == 'false'
    capture('subtitle-one')
    checks.append('실제 검사의 외부 자막 경고 1개: 경고 요약과 등록 요약 정보로 분리')

    run_scan(ScanResult(0, issues('자막 폴더', 300, '외부 자막: 3개 블록을 건너뜀', subtitle=True)))
    assert '외부 자막 경고 300개' in js('document.querySelector(\'[aria-label="검사 안내"]\').textContent')
    collapsed = measure('subtitle-300')
    capture('subtitle-300')
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    wait(lambda: js('document.querySelectorAll(\'[aria-label="외부 자막 경고 목록"] li\').length') == 300, '목록 펼침')
    expanded = measure('subtitle-300-open')
    list_box = json.loads(js('JSON.stringify((() => { const e = document.querySelector(\'[aria-label="외부 자막 경고 목록"]\'); return [e.clientHeight, e.scrollHeight] })())'))
    assert list_box[0] < list_box[1] and list_box[0] <= 128, list_box
    capture('subtitle-300-open')
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    checks.append(f'외부 자막 경고 300개: 요약 한 줄(안내 높이 {collapsed["report"]}px), 펼친 목록은 자체 스크롤(안내 {expanded["report"]}px)')

    run_scan(ScanResult(0, issues('접근 거부 폴더', 1, '액세스가 거부되었습니다.')))
    assert measure('error-one')['tones'] == ['error', 'info']
    capture('error-one')
    run_scan(ScanResult(0, issues('접근 거부 폴더', 150, '액세스가 거부되었습니다.')))
    many = measure('error-150')
    assert js('document.querySelectorAll(\'[aria-label="영상 검사 오류 목록"] li\').length') == 150
    capture('error-150')
    checks.append(f'영상 검사 오류 1·150개: 경로와 함께 오류 위계, 150개도 자체 스크롤(폴더 목록 {many["list"]}px)')

    deep = workspace / ('아주 긴 하위 폴더 이름 ' * 12).strip() / ('긴파일이름' * 30 + '.mkv')
    run_scan(ScanResult(0, (ScanIssue(deep, '다른 프로세스가 파일을 사용 중입니다.'),
                            ScanIssue(deep.with_suffix('.ko.srt'), '외부 자막: 1개 블록을 건너뜀', subtitle=True),
                            ScanIssue(deep.parent, '건너뜀: 다른 폴더나 파일을 가리키는 연결(정션·심볼릭 링크)', failed=False))))
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    settle()
    assert capture('long-path')['tones'] == ['error', 'warning', 'info']
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    mixed = (*issues('접근 거부 폴더', 120, '액세스가 거부되었습니다.'), ScanIssue(deep, '다른 프로세스가 파일을 사용 중입니다.'),
             *issues('자막 폴더', 278, '외부 자막: 자막 파일을 읽지 못했습니다. 파일과 저장 장치 상태를 확인해 주세요.', subtitle=True),
             ScanIssue(deep.parent, '건너뜀: 다른 폴더나 파일을 가리키는 연결(정션·심볼릭 링크)', failed=False),
             ScanIssue(deep, '파일 없음이던 영상을 다시 찾았습니다.', failed=False))
    run_scan(ScanResult(2, mixed))
    assert measure('mixed')['tones'] == ['error', 'warning', 'info']
    capture('mixed')
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    settle()
    measure('mixed-open')
    capture('mixed-open')
    js(f'document.querySelector({json.dumps(toggle())}).click()')
    for tab in ('excluded', 'dismissed'):
        js(f'document.querySelector(\'[data-tab="{tab}"]\').click()')
        settle()
        capture(f'mixed-{tab}')
    js('document.querySelector(\'[data-tab="folders"]\').click()')
    checks.append('오류·경고·정보 섞임과 아주 긴 경로: 오류→경고→정보 순서, 폴더·제외·관심 없음 구역 유지')

    # 실제 검사 → 요약 줄의 목록 단추를 실제 포커스 위젯의 키로 펼치고 닫는다.
    run_scan(lambda: core.scan())
    window.activateWindow()
    host.view.setFocus()
    settle()
    js(f'document.querySelector({json.dumps(toggle())}).focus()')
    settle()
    assert js('document.activeElement.textContent') == '목록 보기'
    key(Qt.Key.Key_Return)
    assert js('document.activeElement.getAttribute("aria-expanded")') == 'true'
    assert js('document.querySelector(\'[aria-label="외부 자막 경고 목록"]\').textContent').endswith('1개 블록을 건너뜀')
    key(Qt.Key.Key_Tab)
    assert js('document.activeElement.getAttribute("aria-label")') == '외부 자막 경고 목록', js('document.activeElement.outerHTML.slice(0, 300)')
    key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    key(Qt.Key.Key_Space)
    assert js('document.activeElement.getAttribute("aria-expanded")') == 'false'
    assert not js('!!document.querySelector(\'[aria-label="외부 자막 경고 목록"]\')')
    checks.append('실제 검사 뒤 외부 자막 경고 목록: Enter로 펼침, Tab으로 목록 진입, Space로 닫음')

    # 끝난 검사 결과는 키보드로 닫고, 초점은 다음 안내의 닫기 단추 → 검사 안내 구역으로 간다.
    dismiss = '[aria-label="검사 안내"] button[aria-label="안내 닫기"]'
    js(f'document.querySelector({json.dumps(dismiss)}).focus()')
    settle()
    assert js('document.activeElement.closest("[data-slot=notice]").dataset.tone') == 'warning'
    key(Qt.Key.Key_Return)
    wait(lambda: '외부 자막 경고' not in js(SHOWN), '경고 닫힘')
    wait(lambda: js('document.activeElement.closest("[data-slot=notice]")?.dataset.tone ?? ""') == 'info', '다음 안내로 초점')
    key(Qt.Key.Key_Space)
    wait(lambda: not js(f'!!document.querySelector({json.dumps(dismiss)})'), '요약 닫힘')
    wait(lambda: js('document.activeElement.id') == 'folders-report', '검사 안내 구역으로 초점')
    capture('dismissed')
    run_scan(lambda: core.scan())
    assert '외부 자막 경고 1개' in js(SHOWN)
    checks.append('결과 닫기: Enter·Space로 닫고 초점은 다음 안내 → 구역, 새 검사 결과는 다시 보임')

    # 늦은 닫기 응답: WebChannel의 다음 응답(type 10) 하나를 잡아 두고, 그사이 새 검사 결과가 보인 뒤 응답을 푼다.
    run_scan(ScanResult(0, ()))
    hold_next_reply()
    # 초점 이동 여부를 보려고 닫기와 무관한 곳에 초점을 둔다(click()은 초점을 옮기지 않는다).
    js('document.querySelector(`[data-tab="folders"]`).focus(); true')
    js(f'document.querySelector({json.dumps(dismiss)}).click()')
    wait(lambda: js('window.heldReplies.length') == 1, '닫기 응답 잡아 둠')
    wait(lambda: '영상 0개 등록' not in js(SHOWN), '닫은 상태는 foldersChanged로 반영')

    def late():
        raise RuntimeError('닫기 뒤 새 결과')

    run_scan(late)
    release_reply()
    settle(1000)
    assert '검사 실패: 닫기 뒤 새 결과' in js(SHOWN), js(SHOWN)
    focused = js('document.activeElement.dataset.tab ?? document.activeElement.id')
    assert focused == 'folders', f'늦은 응답으로 초점을 옮겼습니다: {focused}'
    checks.append('늦은 닫기 응답이 그사이 온 새 검사 결과를 덮지 않고 초점도 옮기지 않음')

    # 연속 닫기: 첫 닫기 응답을 잡아 둔 채 두 번째를 닫고 입력란에 입력한 뒤 첫 응답을 풀어도 초점은 입력란에 남는다.
    run_scan(ScanResult(0, (ScanIssue(workspace / '연속 닫기.mkv', '액세스가 거부되었습니다.'),
                            ScanIssue(workspace / '연속 닫기.srt', '외부 자막: 1개 블록을 건너뜀', subtitle=True))))
    hold_next_reply()
    window.activateWindow()
    host.view.setFocus()
    js(f'document.querySelector({json.dumps(dismiss)}).focus(); true')
    assert js('document.activeElement.closest("[data-slot=notice]").dataset.tone') == 'error'
    key(Qt.Key.Key_Return)
    wait(lambda: js('window.heldReplies.length') == 1 and '영상 검사 오류' not in js(SHOWN), '첫 닫기 응답 잡아 둠')
    js(f'document.querySelector({json.dumps(dismiss)}).focus(); true')
    assert js('document.activeElement.closest("[data-slot=notice]").dataset.tone') == 'warning'
    key(Qt.Key.Key_Return)
    try:
        wait(lambda: js('document.activeElement.closest("[data-slot=notice]")?.dataset.tone ?? ""') == 'info', '두 번째 닫기 초점')
    except AssertionError:
        print('DIAG', js('''JSON.stringify({seen: window.seen, held: window.heldReplies.length, now: Math.round(performance.now()),
            tones: [...document.querySelectorAll('[aria-label="검사 안내"] [data-slot=notice]')].map(e => e.dataset.tone),
            active: document.activeElement?.outerHTML.slice(0, 200), focused: document.hasFocus()})'''),
              QApplication.focusWidget(), window.isActiveWindow(), flush=True)
        raise
    js('document.getElementById("folders-minimum").focus(); document.getElementById("folders-minimum").select(); true')
    QTest.keyClicks(QApplication.focusWidget(), '123')
    settle()
    assert (js('document.activeElement.id'), js('document.activeElement.value')) == ('folders-minimum', '123')
    release_reply()
    settle(800)
    focused = js('document.activeElement.id || document.activeElement.getAttribute("aria-label")')
    assert focused == 'folders-minimum', f'오래된 첫 닫기 응답이 초점을 가져갔습니다: {focused}'
    assert js('document.getElementById("folders-minimum").value') == '123'
    checks.append('연속 닫기에서 오래된 첫 응답이 사용자가 옮긴 입력란 초점을 가져가지 않음')
    result = {'mode': 'offscreen' if args.offscreen else 'windows', 'checks': checks, 'passed': len(checks), 'layouts': layouts}
    (args.output / f'{result["mode"]}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
finally:
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
