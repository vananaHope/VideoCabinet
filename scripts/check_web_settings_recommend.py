"""#204 설정의 '추천' 절 1100×720 배치와 키보드 기간 변경 → 추천 탭 반영 검사.

스크린샷: python scripts/check_web_settings_recommend.py --offscreen
실창: desktop_lock.py run --owner issue-204 -- python scripts/check_web_settings_recommend.py --verify
"""
import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true', help='실창 Ctrl+8 → 키보드로 기간 변경 → Ctrl+2 반영')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-204')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow

app = QApplication([])
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=args.output))
checks, layouts, windows = [], {}, []
CRITERIA = ('continue_watching', 'revisit', 'new_arrivals', 'rewatch', 'unwatched')


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Media:
    def read(self, path):
        return MediaInfo(60, 'mp4')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(60, 90, 120))
        image.save(str(destination), 'JPG')


def wait_until(predicate, message='조건 대기', timeout=20):
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


def key(window, value, modifiers=Qt.KeyboardModifier.NoModifier):
    if not args.offscreen and not window.isActiveWindow():
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
    QTest.keyClick(window.web_host.view.focusProxy() or window.focusWidget() or window, value, modifiers)
    settle(120)


def type_text(window, text):
    for char in text:
        QTest.keyClick(window.web_host.view.focusProxy(), char)
    settle(120)


def library(name, clock):
    core = AppCore(media=Media(), clock=clock, database=directory / f'{name}.sqlite3')
    folder = directory / name
    folder.mkdir()
    path = folder / '바다 산책.mp4'
    path.write_bytes(b'new')
    core.add_file(path)
    return core


def make_window(core):
    window = MainWindow(core)
    window.resize(1100, 720)
    windows.append(window)
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
    windows.remove(window)


def capture(window, label):
    settle(400)
    if not args.offscreen:
        return
    picture = window.grab().toImage()
    assert (picture.width(), picture.height()) == (1100, 720), (picture.width(), picture.height())
    picture.save(str(args.output / f'web-{label}.png'))


def open_section(window):
    window.navigate_web_tab('settings')
    wait_until(lambda: read(window, "!!document.querySelector('[data-category=recommend]')"), '설정 분류')
    point = read(window, """(() => { const r = document.querySelector('[data-category=recommend]').getBoundingClientRect();
      return [r.x + r.width / 2, r.y + r.height / 2] })()""")
    QTest.mouseClick(window.web_host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    wait_until(lambda: read(window, "!document.querySelector('[aria-labelledby=settings-recommend-heading]').parentElement.hidden"), '추천 절')
    settle()


def scroll(window, where):
    read(window, f"(() => {{ const box = document.getElementById('settings-recommend-heading').closest('.overflow-y-auto'); box.scrollTop = {where}; return box.scrollTop }})()")
    settle()


def layout(window):
    return read(window, """(() => {
      const box = document.getElementById('settings-recommend-heading').closest('.overflow-y-auto');
      const outer = box.getBoundingClientRect();
      const rows = [...document.querySelectorAll('[aria-labelledby=settings-recommend-heading] form')].map(form => {
        const input = form.querySelector('input'), r = form.getBoundingClientRect();
        const controls = [...form.querySelectorAll('input, button')].map(e => e.getBoundingClientRect());
        return {label: form.querySelector('label').textContent, value: input.value, invalid: input.getAttribute('aria-invalid') === 'true',
          height: Math.round(r.height), formOverflow: form.scrollWidth > form.clientWidth + 1,
          controlsInside: controls.every(c => c.left >= r.left - 1 && c.right <= r.right + 1),
          error: form.querySelector('[data-slot=notice]')?.textContent ?? null,
          status: form.querySelector('[role=status]').textContent, unsaved: form.textContent.includes('저장 안 됨')};
      });
      return {rows, scrollHeight: box.scrollHeight, clientHeight: box.clientHeight, top: Math.round(outer.top), bottom: Math.round(outer.bottom),
        horizontal: document.documentElement.scrollWidth > innerWidth || box.scrollWidth > box.clientWidth};
    })()""")


def edit(window, criterion, text):
    """입력 칸에 초점을 두고 키보드로 지운 뒤 입력하고 Enter로 저장한다."""
    read(window, f"(() => {{ const e = document.getElementById('settings-recommend-{criterion}'); e.scrollIntoView({{block: 'nearest'}}); e.focus(); return true }})()")
    key(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    key(window, Qt.Key.Key_Backspace)
    type_text(window, text)
    key(window, Qt.Key.Key_Return)
    settle(300)


def saved(window, criterion):
    return read(window, f"document.getElementById('settings-recommend-{criterion}-range').textContent")


def delay_responses(window, delay):
    """WebChannel 응답(type 10)만 늦춰 저장 요청이 끝나기 전의 입력을 재현한다. 0이면 원래대로 돌린다."""
    read(window, f"""(() => {{
      const t = window.qt.webChannelTransport;
      window.checkOriginal = window.checkOriginal || t.onmessage;
      t.onmessage = {delay} ? function(e) {{
        if (JSON.parse(e.data).type === 10) setTimeout(() => window.checkOriginal.call(t, e), {delay});
        else window.checkOriginal.call(t, e);
      }} : window.checkOriginal;
      return true }})()""")


def late_responses(window, core):
    rows = lambda: {row['label']: row for row in layout(window)['rows']}
    delay_responses(window, 1500)
    try:
        # 42를 Enter로 보내고 응답 전에 99를 입력한다. 늦은 응답이 새 초안을 지우면 안 된다.
        read(window, "(() => { const e = document.getElementById('settings-recommend-rewatch'); e.scrollIntoView({block: 'nearest'}); e.focus(); return true })()")
        key(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text(window, '42')
        QTest.keyClick(window.web_host.view.focusProxy(), Qt.Key.Key_Return)
        key(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text(window, '99')
        before = rows()['다시 보기']
        assert before['value'] == '99' and before['unsaved'], before
        wait_until(lambda: core.recommendation_period_days()['rewatch'] == 42, '늦은 저장')
        settle(2000)
        after = rows()['다시 보기']
        assert after['value'] == '99' and after['unsaved'] and '저장된 값 42일' in after['status'] and not after['error'], after
        checks.append('응답 지연 1.5초: 42 Enter 저장 → 응답 전 99 입력 → 응답 뒤에도 99·저장 안 됨 유지, 저장값 42')

        # 잘못된 값을 보내고 응답 전에 Esc로 버리면 늦게 온 오류를 띄우지 않는다.
        key(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text(window, 'abc')
        QTest.keyClick(window.web_host.view.focusProxy(), Qt.Key.Key_Return)
        key(window, Qt.Key.Key_Escape)
        settle(2000)
        after = rows()['다시 보기']
        assert after['value'] == '42' and not after['unsaved'] and not after['error'], after
        assert core.recommendation_period_days()['rewatch'] == 42
        checks.append('응답 지연 1.5초: abc Enter → 응답 전 Esc → 늦은 오류 안내 없음, 저장값 42 표시')
    finally:
        delay_responses(window, 0)
    core.reset_recommendation_period_days('rewatch')


def recommend_kinds(window):
    window.navigate_web_tab('recommend')
    page = window.web_host.controllers['recommend']
    expected = sum(len(row['items']) for row in page.rows)
    wait_until(lambda: read(window, f"document.querySelectorAll('#recommendations [role=gridcell]').length === {expected}"), '추천 카드')
    return [row['kind'] for row in page.rows]


def screenshots():
    clock = Clock()
    core = library('periods', clock)
    clock.now += timedelta(days=10)
    window = make_window(core)
    assert recommend_kinds(window) == ['new_arrivals']
    open_section(window)
    capture(window, 'settings-recommend-default')
    layouts['default'] = state = layout(window)
    assert [row['label'] for row in state['rows']] == ['이어 보기', '하이라이트 복습', '새로 추가됨', '다시 보기', '잊고 있던 영상'], state
    assert [row['value'] for row in state['rows']] == ['30', '30', '14', '60', '30'], state
    assert not state['horizontal'] and all(row['controlsInside'] and not row['formOverflow'] for row in state['rows']), state
    checks.append(f"기본값: 다섯 기간·설명·저장된 값, 가로 넘침 없음 (세로 {state['clientHeight']}/{state['scrollHeight']})")
    scroll(window, 100000)
    capture(window, 'settings-recommend-default-bottom')
    scroll(window, 0)

    # 키보드로 모두 바꾼다. Enter가 저장하고 저장된 값 표시가 바뀐다.
    values = dict(zip(CRITERIA, ('7', '21.5', '5', '90', '45')))
    for criterion, text in values.items():
        edit(window, criterion, text)
        wait_until(lambda: f'저장된 값 {text}일' in saved(window, criterion), f'{criterion} 저장')
    assert core.recommendation_period_days() == {key: float(value) for key, value in values.items()}
    scroll(window, 0)
    capture(window, 'settings-recommend-changed')
    layouts['changed'] = state = layout(window)
    assert not any(row['unsaved'] or row['error'] for row in state['rows']), state
    checks.append('모두 바꾼 값: 키보드 입력 + Enter로 다섯 기간 저장, 저장 안 됨·오류 없음')
    assert recommend_kinds(window) == [], '새로 추가됨 5일이면 10일 전 영상은 빠져야 한다'
    checks.append('새로 추가됨 5일 저장 → 추천 탭 진입 시 10일 전 영상이 새로 추가됨에서 빠짐')

    # 여러 칸 오류: 저장하지 않고 칸마다 오류 안내를 보인다.
    open_section(window)
    bad = dict(zip(CRITERIA, ('abc', '', '-1', '365001', '1e')))
    for criterion, text in bad.items():
        edit(window, criterion, text)
    wait_until(lambda: sum(row['error'] is not None for row in layout(window)['rows']) == 5, '오류 안내')
    assert core.recommendation_period_days() == {key: float(value) for key, value in values.items()}
    scroll(window, 0)
    capture(window, 'settings-recommend-errors')
    layouts['errors'] = state = layout(window)
    assert all(row['invalid'] and row['unsaved'] for row in state['rows'] if row['error']), state
    assert not state['horizontal'] and all(row['controlsInside'] for row in state['rows']), state
    scroll(window, 100000)
    capture(window, 'settings-recommend-errors-bottom')
    checks.append(f"여러 칸 오류: {sum(row['error'] is not None for row in state['rows'])}칸에 오류 안내·aria-invalid, 저장값 그대로 (세로 스크롤 {state['clientHeight']}/{state['scrollHeight']})")

    # Esc: 저장 전 입력만 버리고 저장된 값으로 돌아간다.
    read(window, "(() => { const e = document.getElementById('settings-recommend-unwatched'); e.focus(); return true })()")
    key(window, Qt.Key.Key_Escape)
    wait_until(lambda: layout(window)['rows'][4]['value'] == '45' and not layout(window)['rows'][4]['unsaved'], 'Esc 초안 버리기')
    assert core.recommendation_period_days()['unwatched'] == 45
    assert window.web_host.active_tab == 'settings' and read(window, "document.activeElement.id") == 'settings-recommend-unwatched'
    checks.append('Esc: 저장 전 입력(1e)과 오류 안내를 버리고 저장된 값 45 표시')

    # 기본값 단추: 키보드 Enter로 누르면 초안·오류를 버리고 기본값을 저장한다.
    for criterion in CRITERIA:
        read(window, f"(() => {{ const e = document.querySelector('[aria-label=\"' + document.querySelector('label[for=settings-recommend-{criterion}]').textContent + ' 기본값\"]'); e.scrollIntoView({{block: 'nearest'}}); e.focus(); return true }})()")
        key(window, Qt.Key.Key_Return)
    wait_until(lambda: core.recommendation_period_days() == {'continue_watching': 30, 'revisit': 30, 'new_arrivals': 14, 'rewatch': 60, 'unwatched': 30}, '기본값 복원')
    wait_until(lambda: not any(row['error'] or row['unsaved'] for row in layout(window)['rows']), '초안 정리')
    checks.append('기본값 단추: 다섯 기간 기본값 복원, 초안·오류 안내 정리')
    late_responses(window, core)
    assert recommend_kinds(window) == ['new_arrivals']
    checks.append('기본값 복원 → 추천 탭 새로 추가됨 다시 표시')
    close(window)

    # 긴 이름·설명: 줄바꿈하며 입력·단추가 칸 밖으로 밀리지 않는다.
    core = library('long', Clock())
    long_text = '아주 긴 설명 문구가 들어와도 입력 칸과 저장·기본값 단추가 밀려나지 않고 줄바꿈되는지 확인하기 위한 문장입니다. ' * 2
    definitions = tuple(replace(period, label=period.label + ' 기간(긴 이름 확인용)', description=long_text.strip())
                        for period in core.recommendation_period_definitions())
    core.recommendation_period_definitions = lambda: definitions
    # 잘못된 저장값: 그 칸에만 경고를 보이고 화면은 연다.
    core.settings.set('recommend.revisit_days', -5)
    window = make_window(core)
    open_section(window)
    capture(window, 'settings-recommend-long')
    layouts['long'] = state = layout(window)
    assert not state['horizontal'] and all(row['controlsInside'] and not row['formOverflow'] for row in state['rows']), state
    assert [row['error'] is not None for row in state['rows']] == [False, True, False, False, False], state
    assert state['rows'][1]['value'] == '' and state['rows'][1]['invalid'], state
    checks.append('긴 이름·설명: 줄바꿈, 입력·단추 칸 안, 가로 넘침 없음 / 잘못된 저장값은 그 칸에만 경고')
    close(window)


def verify():
    clock = Clock()
    core = library('verify', clock)
    clock.now += timedelta(days=10)
    window = make_window(core)
    host = window.web_host
    try:
        key(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'recommend' and [row['kind'] for row in host.controllers['recommend'].rows] == ['new_arrivals'])
        key(window, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'settings' and read(window, "document.activeElement.closest('#settings-category') !== null"), 'Ctrl+8 설정 초점')
        for _ in range(10):
            if read(window, "document.activeElement.dataset.category") == 'recommend':
                break
            key(window, Qt.Key.Key_Tab)
        assert read(window, "document.activeElement.dataset.category") == 'recommend'
        key(window, Qt.Key.Key_Return)
        for _ in range(40):
            if read(window, "document.activeElement.id") == 'settings-recommend-new_arrivals':
                break
            key(window, Qt.Key.Key_Tab)
        assert read(window, "document.activeElement.id") == 'settings-recommend-new_arrivals'
        key(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text(window, '5')
        key(window, Qt.Key.Key_Return)
        wait_until(lambda: core.recommendation_period_days()['new_arrivals'] == 5, '키보드 저장')
        assert read(window, "document.activeElement.id") == 'settings-recommend-new_arrivals'
        checks.append('실창 Ctrl+8 → Tab·Enter로 추천 절 → 새로 추가됨 5 입력 후 Enter 저장, 초점 유지')
        key(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'recommend' and host.controllers['recommend'].rows == [], 'Ctrl+2 반영')
        assert read(window, "document.querySelector('main[aria-label=\"추천\"] section h2')?.textContent") == '지금은 추천할 영상이 없어요'
        checks.append('실창 Ctrl+2: 새 기간으로 다시 계산해 새로 추가됨 줄이 사라짐')
        key(window, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'settings' and read(window, "document.activeElement.closest('#settings-category') !== null"))
        assert read(window, "document.querySelector('#settings-category [aria-current=true]').dataset.category") == 'recommend'
        for _ in range(40):
            if read(window, "document.activeElement.getAttribute('aria-label')") == '새로 추가됨 기본값':
                break
            key(window, Qt.Key.Key_Tab)
        key(window, Qt.Key.Key_Return)
        wait_until(lambda: core.recommendation_period_days()['new_arrivals'] == 14, '기본값 단추')
        key(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'recommend' and [row['kind'] for row in host.controllers['recommend'].rows] == ['new_arrivals'])
        checks.append('실창 기본값 단추(Enter) → Ctrl+2: 새로 추가됨 줄 다시 표시')
    finally:
        close(window)


try:
    if args.offscreen:
        screenshots()
    if args.verify:
        verify()
    result = {'checks': checks, 'offscreen': args.offscreen, 'layouts': layouts}
    (args.output / ('verify.json' if args.verify else 'screens.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks}, ensure_ascii=False), flush=True)
finally:
    for window in list(windows):
        close(window)
