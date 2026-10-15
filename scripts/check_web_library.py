"""Windows 실제 창에서 웹 셸 검증과 측정. 원본 영상은 --source에서 복사해 사용한다.

python scripts/check_web_library.py --prepare --count 24 --source <읽기 전용 폴더>
python scripts/check_web_library.py --count 24 --verify --stay
python scripts/check_web_library.py --verify-gems
python scripts/check_web_library.py --prepare --count 5000
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
import tempfile
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true', help='실제 데스크톱 대신 offscreen에서 화면 캡처')
parser.add_argument('--no-screenshots', action='store_true', help='실창 입력 검사 중 캡처 생략')
parser.add_argument('--count', type=int, default=24)
parser.add_argument('--prepare', action='store_true')
parser.add_argument('--source', type=Path)
parser.add_argument('--verify', action='store_true')
parser.add_argument('--verify-shell', action='store_true')
parser.add_argument('--verify-library', action='store_true', help='카드 통계·태그와 하이라이트 재생·편집·복귀 확인')
parser.add_argument('--profile-refresh', action='store_true', help='갱신의 Python·JSON 파싱·후속 웹 프레임 비용 측정')
parser.add_argument('--long-content', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-46')
parser.add_argument('--verify-gems', action='store_true', help='보석 0·1·4·5·10개의 배치와 가로 키 이동 검증')
parser.add_argument('--stay', action='store_true')
args = parser.parse_args()
if args.verify_gems:
    if args.prepare or args.verify:
        parser.error('--verify-gems는 단독으로 사용하세요')
    args.count = 10
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    # 표시 표면 없는 Windows offscreen 캡처는 GPU 컨텍스트 대신 소프트웨어로 그린다.
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '') + ' --disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer, QPoint, QPointF, QObject, QEvent
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow

app = QApplication([])
directory = ROOT / '.local' / 'issue46' / f'demo-{args.count}'
directory.mkdir(parents=True, exist_ok=True)
if args.verify_gems:
    directory = Path(tempfile.mkdtemp(prefix='gems-', dir=directory.parent))
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
if args.verify_gems:
    # 기존 데모 DB나 실제 영상을 바꾸지 않고 공개 API로 추천 경계 데이터를 만든다.
    titles = ('바다', '숲', '음악', '도시', '과학', '역사', '여행', '요리', '그림', '언어')
    for index, title in enumerate(titles):
        # 같은 접두사 + 회차 번호는 시리즈로 묶여 첫 미완료 영상만 추천된다.
        path = media_dir / f'{title}.mkv'
        path.write_bytes(f'gem scenario {index}'.encode())
        core.add_file(path)
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

if args.long_content and core.videos():
    first = next((v for v in core.videos() if v.title.startswith('아주 긴 한글')), core.videos()[0])
    core.rename_video(first.id, '아주 긴 한글 제목과 공백 없는 영문 제목의 카드 경계 확인 ' + 'LongVideoTitle' * 14)
    for index in range(4):
        core.add_video_tag(first.id, f'{index} 긴 태그 이름 ' + '태그' * 20)

window = MainWindow(core)
window.setWindowTitle(f'이슈 46 검증 · web · {args.count}')
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page = window.library_page
host = window.home_page


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
    host.engine_page.runJavaScript(code, values.append)
    wait_until(lambda: bool(values))
    return values[0]


def js_json(code):
    return json.loads(js(f'JSON.stringify({code})'))


def settle(milliseconds=250):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def run_web_frames(script):
    """측정 동안 Qt 이벤트 루프만 돌린다. JS 종료 알림 뒤에만 결과를 읽는다."""
    loop = QEventLoop()
    completed = []
    marker = f'mvm-frame-done-{time.perf_counter_ns()}'

    def finished(title):
        if title == marker:
            completed.append(True)
            loop.quit()

    host.engine_page.titleChanged.connect(finished)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)
    host.engine_page.runJavaScript(f'(() => {{ const done = () => document.title = {json.dumps(marker)}; {script} }})()')
    loop.exec()
    timeout.stop()
    host.engine_page.titleChanged.disconnect(finished)
    assert completed, '웹 프레임 완료 알림 시간 초과'


startup_loop = QEventLoop()
host.frontend_loaded.connect(startup_loop.quit)
startup_timeout = QTimer()
startup_timeout.setSingleShot(True)
startup_timeout.timeout.connect(startup_loop.quit)
startup_timeout.start(20000)
if not host._frontend_ready:
    startup_loop.exec()
startup_timeout.stop()
host.frontend_loaded.disconnect(startup_loop.quit)
assert host._frontend_ready, '첫 React 렌더 완료 시간 초과'
run_web_frames('requestAnimationFrame(() => requestAnimationFrame(done));')
settle()
if args.long_content:
    page.selected_id = first.id
    page.refresh()
    columns = int(js("document.getElementById('library-grid').getAttribute('aria-colcount')"))
    row_height = float(js("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--grid-row-height')) * parseFloat(getComputedStyle(document.documentElement).fontSize)"))
    index = page.visible_ids.index(first.id)
    js(f"document.getElementById('library-grid').scrollTop = {index // columns * row_height}")
    settle()
startup = (time.perf_counter() - STARTED) * 1000
screens = args.output
screens.mkdir(parents=True, exist_ok=True)


def capture_window(name):
    if not args.no_screenshots:
        window.grab().save(str(screens / name))


capture_window(f'web-{args.count}.png')
metrics = {'mode': 'web', 'count': args.count, 'startup_ms': round(startup, 2), 'checks': []}


if args.verify_shell:
    from my_video_manager.web_contract import TABS

    def shell_key(target, key, modifiers=Qt.KeyboardModifier.NoModifier):
        # 전역 필터는 비활성 창의 키를 의도적으로 무시한다. 다른 검증 창이
        # 포커스를 가져갔다면 먼저 이 실창을 활성화한 뒤 키를 보낸다.
        if not window.isActiveWindow():
            window.raise_()
            window.activateWindow()
            assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
        QTest.keyClick(target, key, modifiers)

    assert not window.menuBar().isVisible() and not window.statusBar().isVisible()
    assert js("document.querySelector('[aria-label=\"라이브러리 등록·표시 개수\"]').textContent") == f'등록 영상 {len(page.cards)}개 · 표시 {len(page.visible_ids)}개'
    window.show_status('검사 완료 · 웹 작업 알림 확인')
    wait_until(lambda: js("document.querySelector('[role=status][aria-label=\"작업 알림\"]')?.textContent") == '검사 완료 · 웹 작업 알림 확인')
    settle()  # DOM 커밋 뒤 Chromium paint까지 기다린다.
    capture_window(f'web-notice-{args.count}.png')
    window.statusBar().clearMessage()
    wait_until(lambda: not js("!!document.querySelector('[role=status][aria-label=\"작업 알림\"]')"))
    # 탭 클릭은 실제 DOM 버튼을 사용하고, 복귀 키는 Qt WebEngine 포커스 프록시에 전달한다.
    for index, (tab, _) in enumerate(TABS):
        window.navigate_web_tab('library')
        settle()
        js(f"document.querySelectorAll('nav button')[{index}].click()")
        settle()
        assert host.active_tab == tab
        assert window.pages.currentWidget() is host
        assert not window.menuBar().isVisible() and not window.statusBar().isVisible()
        capture_window(f'tab-{tab}-{args.count}.png')
        shell_key(host.view.focusProxy(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        settle()
        assert host.active_tab == 'library'
    for index, (tab, _) in enumerate(TABS):
        window.navigate_web_tab('library')
        settle()
        shell_key(host.view.focusProxy(), Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        settle()
        assert host.active_tab == tab, (tab, host.active_tab, window.isActiveWindow())
    # 웹 탭 사이에서 예약 키를 연속 처리한다.
    for index in range(len(TABS)):
        shell_key(window.focusWidget(), Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        settle()
        assert host.active_tab == TABS[index][0]
    window.navigate_web_tab('library')
    settle()
    shell_key(host.view.focusProxy(), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: host.active_tab == 'settings' and window.pages.currentWidget() is host)
    assert not window.settings_menu.isVisible()
    window.navigate_web_tab('library')
    settle()
    assert window.pages.count() == 2
    metrics['checks'].append('일곱 탭 클릭·Ctrl+1~7·Alt+S')


def gem_layout():
    return js_json("""(() => {
      const panel = document.querySelector('aside').getBoundingClientRect();
      const buttons = [...document.querySelectorAll('[aria-label="영상 작업"] button')];
      const row = document.getElementById('hidden-gems');
      const bounds = row?.getBoundingClientRect();
      const cards = [...document.querySelectorAll('#hidden-gems [role=option]')];
      const visible = el => { const r = el.getBoundingClientRect();
        return r.left >= bounds.left && r.right <= bounds.right && r.top >= bounds.top && r.bottom <= bounds.bottom;
      };
      return {headerHeight: document.querySelector('header').getBoundingClientRect().height,
      buttons: buttons.length, visibleButtons: buttons.filter(el => {
        const r = el.getBoundingClientRect(); return r.top >= panel.top && r.bottom <= panel.bottom;
      }).length, gems: cards.length, visibleGems: cards.filter(visible).length,
      rowHeight: bounds?.height ?? 0, gridHeight: document.getElementById('library-grid').clientHeight,
      visibleGridRows: (document.getElementById('library-grid').clientHeight - 8) /
        document.querySelector('#library-grid [role=row]').getBoundingClientRect().height,
      scrollbarColor: row ? getComputedStyle(row).scrollbarColor : null,
      cardWidth: cards[0]?.getBoundingClientRect().width ?? 0,
      rows: new Set(cards.map(el => el.getBoundingClientRect().top)).size,
      horizontalOverflow: row ? row.scrollWidth > row.clientWidth : false};
    })()""")


if core.videos():
    metrics['layout'] = gem_layout()


def verify_detail_access():
    """작업 8개가 스크롤 없이 보이고 Tab으로 모두 닿아야 한다."""
    js("document.querySelector('[aria-label=\"영상 작업\"] button').focus()")
    reached = []
    for index in range(8):
        settle(40)
        state = js_json("""(() => {
          const button = document.activeElement; const panel = document.querySelector('aside');
          const b = button.getBoundingClientRect(), p = panel.getBoundingClientRect();
          return {text: button.textContent, inPanel: panel.contains(button), visible: b.top >= p.top && b.bottom <= p.bottom};
        })()""")
        assert state['inPanel'] and state['visible'], state
        reached.append(state['text'])
        if index < 7:
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab)
    assert len(set(reached)) == 8, reached
    js("document.querySelector('aside').scrollTop = 0")
    page.focus_content()
    settle()
    return reached


def contrast(selector):
    # 실제 Chromium 계산색을 canvas의 sRGB로 변환해 투명 배경을 부모 색과 합성한다.
    return js_json("""(() => {
      const el = document.querySelector(SELECTOR);
      const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently:true});
      const rgba = color => {ctx.clearRect(0,0,1,1); ctx.fillStyle=color; ctx.fillRect(0,0,1,1); return [...ctx.getImageData(0,0,1,1).data];};
      const over = (a,b) => a.slice(0,3).map((v,i) => v*a[3]/255 + b[i]*(1-a[3]/255));
      const ancestors = []; for(let p=el;p;p=p.parentElement) ancestors.unshift(p);
      const background = ancestors.reduce((bg,p) => over(rgba(getComputedStyle(p).backgroundColor),bg),[255,255,255]);
      const foreground = over(rgba(getComputedStyle(el).color),background);
      const luminance = rgb => rgb.map(v => {v/=255; return v<=0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4;}).reduce((sum,v,i) => sum+v*[0.2126,0.7152,0.0722][i],0);
      const [a,b] = [luminance(foreground),luminance(background)].sort((a,b)=>b-a);
      return {foreground,background,ratio:(a+0.05)/(b+0.05),hovered:el.matches(':hover'),hoverCapable:matchMedia('(hover:hover)').matches};
    })()""".replace('SELECTOR', json.dumps(selector)))


if args.verify_gems:
    layouts = []
    previous_count = 0
    videos = core.videos()
    for count in (0, 1, 4, 5, 10):
        for video in videos[previous_count:count]:
            core.playback.start(video.id, 0)
            core.playback.report(35)
            core.playback.end()
        previous_count = count
        assert len(core.hidden_gems()) == count
        page.refresh()
        wait_until(lambda: js("document.querySelectorAll('#hidden-gems [role=option]').length") == count)
        run_web_frames('requestAnimationFrame(() => requestAnimationFrame(done));')
        layout = gem_layout()
        layouts.append(layout)
        capture_window(f'web-gems-{count}.png')
        print(json.dumps(layout, ensure_ascii=False), flush=True)
        (screens / 'web-gems-check.json').write_text(json.dumps(layouts, ensure_ascii=False, indent=2), encoding='utf-8')
        assert layout['buttons'] == 8, layout
        layout['keyboardAccessibleActions'] = verify_detail_access()
        assert layout['rows'] == (1 if count else 0), layout
        assert layout['visibleGems'] == min(count, 4), layout
        if count:
            assert layout['rowHeight'] == layouts[1]['rowHeight'], layouts
            assert layout['gridHeight'] == layouts[1]['gridHeight'], layouts
            assert layout['cardWidth'] == layouts[1]['cardWidth'], layouts
        if count > 4:
            js("document.getElementById('hidden-gems').focus()")
            for index in range(1, count):
                QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Right)
                wait_until(lambda: js("document.getElementById('hidden-gems').getAttribute('aria-activedescendant')") == f'gem-{page.gem_ids[index]}')
            run_web_frames('requestAnimationFrame(() => requestAnimationFrame(done));')
            end_position = js_json("""(() => {const row = document.getElementById('hidden-gems');
              const card = document.getElementById(row.getAttribute('aria-activedescendant')).getBoundingClientRect();
              const r = row.getBoundingClientRect(); return {scrollLeft: row.scrollLeft, maxScroll:row.scrollWidth-row.clientWidth, width:row.clientWidth, left:card.left, right:card.right, rowLeft:r.left, rowRight:r.right};})()""")
            assert end_position['scrollLeft'] > 0 and end_position['left'] >= end_position['rowLeft'] and end_position['right'] <= end_position['rowRight'], end_position
            for index in range(count - 2, -1, -1):
                QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Left)
                wait_until(lambda: js("document.getElementById('hidden-gems').getAttribute('aria-activedescendant')") == f'gem-{page.gem_ids[index]}')
            assert js("""(() => {const row = document.getElementById('hidden-gems');
              const card = document.getElementById(row.getAttribute('aria-activedescendant')).getBoundingClientRect();
              const r = row.getBoundingClientRect(); return card.left >= r.left && card.right <= r.right;})()"""), '왼쪽 첫 추천 카드가 보여야 한다'
            layout['keyboardScrolledToEndAndBack'] = True
            js("document.getElementById('hidden-gems').scrollLeft = 0")
            point = js_json("(() => {const r = document.getElementById('hidden-gems').getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2]})()")
            local = QPoint(*map(int, point))
            wheel = QWheelEvent(QPointF(local), QPointF(host.view.mapToGlobal(local)), QPoint(), QPoint(0, -120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(host.view.focusProxy(), wheel)
            wait_until(lambda: js("document.getElementById('hidden-gems').scrollLeft") > 0)
            layout['verticalWheelScrolledHorizontally'] = True
            js("document.getElementById('hidden-gems').scrollLeft = 0")
    (screens / 'web-gems-check.json').write_text(json.dumps(layouts, ensure_ascii=False, indent=2), encoding='utf-8')
    button_selector = 'aside button[data-variant="destructive-outline"]'
    contrasts = {'button': contrast(button_selector)}
    point = js_json(f"(() => {{const r = document.querySelector({json.dumps(button_selector)}).getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2];}})()")
    QTest.mouseMove(host.view.focusProxy(), QPoint(*map(int, point)))
    settle(250)
    contrasts['buttonHover'] = contrast(button_selector)
    page.focus_content()
    settle(100)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: js("!!document.querySelector('[role=menu]')"))
    menu_selector = '[data-slot="context-menu-item"][data-variant="destructive"]'
    contrasts['menu'] = contrast(menu_selector)
    js(f'document.querySelector({json.dumps(menu_selector)}).focus()')
    settle(100)
    contrasts['menuFocus'] = contrast(menu_selector)
    assert all(value['ratio'] >= 4.5 for value in contrasts.values()), contrasts
    (screens / 'web-exclude-contrast.json').write_text(json.dumps(contrasts, indent=2), encoding='utf-8')
    print(json.dumps({'contrast': contrasts}, ensure_ascii=False), flush=True)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Escape)
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    raise SystemExit()

if args.verify:
    assert js("document.querySelector('img')?.naturalWidth") > 0, '썸네일 스킴'
    wait_until(lambda: js('document.activeElement.id') == 'library-grid')
    metrics['checks'].append('시작 직후 격자 포커스 (명시적 focus_content 호출 없음)')
    layout = gem_layout()
    assert layout['buttons'] == layout['visibleButtons'] == 8, layout
    layout['keyboardAccessibleActions'] = verify_detail_access()
    assert layout['gems'] == len(page.gem_ids) and layout['rows'] <= 1, layout
    assert layout['visibleGems'] == min(4, len(page.gem_ids)), layout
    metrics['layout'] = layout
    metrics['checks'].append('1100×720 작업 버튼 8개 동시 노출·Tab 접근, 보석 한 줄과 첫 4개 노출')
    js("document.getElementById('library-grid').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true, isComposing:true}))")
    settle(100)
    assert core.playback.session is None
    metrics['checks'].append('격자 isComposing Enter 가드 (합성 이벤트)')
    initial_id = page.selected_video_id()
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Right)
    wait_until(lambda: page.selected_video_id() != initial_id)
    metrics['checks'].append('Chromium 방향키 선택')
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: bool(js("!!document.querySelector('[role=menu]')")))
    metrics['checks'].append('Shift+F10 메뉴')
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Escape)
    QTest.qWait(100)
    page.focus_content()
    QTest.qWait(100)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Menu)
    wait_until(lambda: bool(js("!!document.querySelector('[role=menu]')")))
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Escape)
    metrics['checks'].append('메뉴 키')
    # 태그 삭제 후 UI 값과 다음 검색이 모두 전체 태그를 사용해야 한다.
    temporary_tag = core.add_video_tag(page.selected_video_id(), '검증용 임시 태그')
    page.refresh()
    wait_until(lambda: js(f"!!document.querySelector('select option[value=\"{temporary_tag.id}\"]')"))
    js(f"document.querySelector('select').value = '{temporary_tag.id}'; document.querySelector('select').dispatchEvent(new Event('change', {{bubbles:true}})); true")
    wait_until(lambda: page.tag_id == temporary_tag.id)
    core.delete_tag(temporary_tag.id)
    page.refresh()
    wait_until(lambda: js("document.querySelector('select').value") == '0')
    assert page.tag_id is None and len(page.visible_video_ids()) == args.count
    metrics['checks'].append('선택 태그 삭제 뒤 필터 해제·다음 검색 전체 태그 적용')
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
    assert window.pages.currentWidget() is host and core.playback.session is None
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
    metrics['checks'].append('composition 중 입력·목록 보존, 완료 후 한글 필터; 검색 입력에는 재생 경로 없음(구조적)')
    point = js_json("(() => {const r = document.querySelector('input').getBoundingClientRect(); return [r.x + 10, r.y + 10]})()")
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    wait_until(lambda: js('document.activeElement.tagName') == 'INPUT')
    QTest.qWait(100)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.tagName') == 'SELECT')
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
    wait_until(lambda: page.tag_id is not None)
    assert len(page.visible_video_ids()) < len(original_ids)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Home)
    wait_until(lambda: page.tag_id is None)
    assert page.visible_video_ids() == original_ids
    metrics['checks'].append('NativeSelect 방향키 필터 변경·Home 전체 복원')
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.id') == 'hidden-gems')
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab)
    wait_until(lambda: js('document.activeElement.id') == 'library-grid')
    metrics['checks'].append('Tab 검색 → 태그 → 숨겨진 보석 → 격자')
    from my_video_manager.web_contract import TABS
    for index, (tab, _) in enumerate(TABS):
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
        page.focus_content()
        window.pages.setCurrentWidget(host)
        QTest.qWait(80)
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        route = host.routes[tab]
        target = host
        wait_until(lambda: window.pages.currentWidget() is target)
    window.navigate_web_tab('library')
    page.focus_content()
    QTest.qWait(100)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: window.pages.currentWidget() is host)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    wait_until(lambda: host.active_tab == 'settings' and window.pages.currentWidget() is host)
    assert not window.settings_menu.isVisible()
    window.navigate_web_tab('library')
    settle()
    page.focus_content()
    metrics['checks'].append('웹 포커스 Ctrl+1~7, Alt+S 설정 탭')
    # 실제 mpv로 열 수 있는 복사본만 골라 Enter 재생·Esc 복귀를 확인한다.
    playable = next((v for v in reversed(core.videos()) if any(loc.path.stat().st_size > 1000 for loc in v.locations)), None)
    if playable:
        index = next(i for i, v in enumerate(core.videos()) if v.id == playable.id)
        columns = int(js("Number(document.getElementById('library-grid').getAttribute('aria-colcount'))"))
        row_height = float(js("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--grid-row-height')) * parseFloat(getComputedStyle(document.documentElement).fontSize)"))
        js(f"document.getElementById('library-grid').scrollTop = {index // columns * row_height}")
        wait_until(lambda: bool(js(f"!!document.getElementById('video-{playable.id}')")))
        js(f"document.getElementById('video-{playable.id}')?.click()")
        wait_until(lambda: page.selected_video_id() == playable.id)
        page.focus_content()
        QTest.qWait(100)
        before = js_json("({id: document.getElementById('library-grid').getAttribute('aria-activedescendant'), top: document.getElementById('library-grid').scrollTop, cols: document.getElementById('library-grid').getAttribute('aria-colcount'), width: document.getElementById('library-grid').clientWidth, height: document.getElementById('library-grid').scrollHeight})")
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(500)
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000), '재생 검증 창 활성화 실패'
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Apostrophe)
        wait_until(window.isFullScreen)
        assert not window.menuBar().isVisible() and not window.statusBar().isVisible()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait_until(lambda: not window.isFullScreen())
        assert window.pages.currentWidget() is window.playback_page
        assert not window.menuBar().isVisible() and not window.statusBar().isVisible()
        capture_window(f'mpv-{args.count}.png')
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait_until(lambda: window.pages.currentWidget() is host)
        QTest.qWait(250)
        after = js_json("({id: document.getElementById('library-grid').getAttribute('aria-activedescendant'), top: document.getElementById('library-grid').scrollTop, cols: document.getElementById('library-grid').getAttribute('aria-colcount'), width: document.getElementById('library-grid').clientWidth, height: document.getElementById('library-grid').scrollHeight})")
        assert before == after, (before, after)
        assert js('document.activeElement.id') == 'library-grid'
        metrics['checks'].append('실제 mpv Enter 재생 / Esc 선택·스크롤·포커스 복귀')
        for tab, _ in TABS:
            if tab == 'library':
                continue
            window.navigate_web_tab(tab)
            settle()
            window.navigate_web_tab('library')
            settle()
            returned = js_json("({id: document.getElementById('library-grid').getAttribute('aria-activedescendant'), top: document.getElementById('library-grid').scrollTop})")
            assert returned == {'id': before['id'], 'top': before['top']}, (tab, before, returned)
        metrics['checks'].append('모든 웹 탭 왕복 뒤 라이브러리 선택·스크롤 복원')
        # 더블클릭도 브리지를 거쳐 같은 네이티브 플레이어를 연다.
        js(f"document.getElementById('video-{playable.id}').dispatchEvent(new MouseEvent('dblclick', {{bubbles:true}}))")
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait_until(lambda: window.pages.currentWidget() is host)
        metrics['checks'].append('카드 더블클릭 mpv 전환')
    # 업무 대화상자를 실제 웹 작업 버튼으로 열고 같은 웹 호스트에서 취소한다.
    for title, expected in (('태그 편집', 'tags'), ('자막 만들기 / 원어 지정', 'subtitles'), ('자막 검수 / SRT 내보내기', 'review'), ('시리즈 편집', 'series'), ('제목 변경', 'video-rename')):
        observed = []
        def close_dialog():
            if host.dialogs.active:
                observed.append(host.dialogs.stack[-1].kind)
                host.dialogs.pop()
        closer = QTimer()
        closer.setInterval(20)
        closer.timeout.connect(close_dialog)
        closer.start()
        js(f"[...document.querySelectorAll('aside button')].find(button => button.textContent === {json.dumps(title)}).click()")
        wait_until(lambda: bool(observed) and not page.bridge.busy)
        closer.stop()
        assert expected in observed, (expected, observed)
    metrics['checks'].append('태그·자막·검수·시리즈·제목 변경 웹 대화상자 연결')
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

if args.verify_library:
    layout = gem_layout()
    assert layout['buttons'] == layout['visibleButtons'] == 8, layout
    assert layout['visibleGems'] == min(4, len(page.gem_ids)), layout
    metrics['layout'] = layout
    stats = core.video_viewing_statistics()[page.selected_id]
    card = js(f"document.getElementById('video-{page.selected_id}').textContent")
    last_view_label = '마지막 틀어보기' if stats.viewing_count == 0 and stats.last_viewed_at else '마지막 시청'
    assert f'{stats.viewing_count}회' in card and '횟수 · 시간' in card and last_view_label in card
    assert layout['visibleGridRows'] >= 1.5, layout
    if args.long_content:
        assert '+3' in card or '+2' in card, card
        assert js("""[...document.querySelectorAll('[role=gridcell] [aria-label="태그"] span')].some(el => getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth)"""), '긴 태그 말줄임'
    metrics['checks'].append('통계 카드·긴 태그 말줄임과 +N·작업 8개·보석 4개')
    first = page.selected_id
    for highlight in core.highlights(first):
        core.delete_highlight(highlight.id)
    page.refresh_details(first)
    js("document.querySelector('aside [data-tab=highlights]').click()")
    wait_until(lambda: js("document.getElementById('detail-scroll')?.textContent.includes('하이라이트 없음')"))
    settle()
    capture_window('web-highlights-0.png')

    playable = max((v for v in core.videos() if any(loc.path.stat().st_size > 1000 for loc in v.locations)),
                   key=lambda v: max(loc.path.stat().st_size for loc in v.locations))
    for h in core.highlights(playable.id):
        core.delete_highlight(h.id)
    for index in range(32):
        core.playback.start(playable.id, 1.125 + index * 0.25)
        core.execute_highlight_command(core.command_for_key('Insert'))
        core.playback.end()
    for index, h in enumerate(core.highlights(playable.id)):
        core.update_highlight(h.id, start=h.start, end=h.start + 0.125 if index % 2 else None,
                              note=f'장면 {index + 1} · 긴 메모 ' + '다시 보고 싶은 순간 ' * 4)
        core.add_highlight_tag(h.id, '복습')
        if index == 0:
            core.add_highlight_tag(h.id, '긴 하이라이트 태그 ' + '태그' * 18)
    page.selected_id = playable.id
    page.refresh()
    wait_until(lambda: js("document.querySelectorAll('[role=option][id^=highlight-]').length") == 32)
    js("document.getElementById('detail-scroll').focus()")
    settle()
    capture_window('web-highlights-many.png')
    metrics['visibleHighlights'] = js("""(() => {
      const bounds = document.getElementById('detail-scroll').getBoundingClientRect();
      return [...document.querySelectorAll('[id^=highlight-]')].filter(el => {
        const r = el.getBoundingClientRect(); return r.top >= bounds.top && r.bottom <= bounds.bottom;
      }).length;
    })()""")
    assert metrics['visibleHighlights'] >= 6, metrics
    assert js("[...document.querySelectorAll('[id^=highlight-] button')].every(el => el.tabIndex === -1)")
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab)
    settle()
    assert js("!document.getElementById('detail-scroll').contains(document.activeElement)")
    js("document.getElementById('detail-scroll').focus()")
    for _ in range(16):
        QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Down)
    settle()
    selection = js("document.getElementById('detail-scroll').getAttribute('aria-activedescendant')")
    top = js("document.getElementById('detail-scroll').scrollTop")
    hid = int(selection.removeprefix('highlight-'))
    start = next(h.start for h in core.highlights(playable.id) if h.id == hid)
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Return)
    wait_until(lambda: window.pages.currentWidget() is window.playback_page)
    assert core.playback.session.video_id == playable.id
    assert abs(core.playback.position - start) < 1.0, (core.playback.position, start)
    settle(250)
    capture_window('web-highlight-mpv.png')
    QTest.keyClick(window.surface, Qt.Key.Key_Escape)
    wait_until(lambda: window.pages.currentWidget() is host)
    settle(400)
    assert js("document.querySelector('aside [data-tab=highlights]').getAttribute('aria-current')") == 'page'
    assert js("document.getElementById('detail-scroll').getAttribute('aria-activedescendant')") == selection
    assert js("document.getElementById('detail-scroll').scrollTop") == top
    assert js("document.activeElement.id") == 'detail-scroll'
    capture_window('web-highlight-return.png')
    metrics['checks'].append('하이라이트 ↑/↓·Enter 실제 mpv 정확한 시각 재생·Esc 탭/선택/스크롤/포커스 복원')
    js(f"document.getElementById('{selection}').querySelector('button').click()")
    wait_until(lambda: window.pages.currentWidget() is window.playback_page)
    QTest.keyClick(window.surface, Qt.Key.Key_Escape)
    wait_until(lambda: window.pages.currentWidget() is host)
    settle(300)
    observed = []

    def edit_note():
        if host.dialogs.active and host.dialogs.stack[-1].kind == 'highlight':
            frame = host.dialogs.stack[-1]
            observed.append(frame.context['highlight'].id)
            host.dialogs.act(frame.identifier, 'save', {**frame.values, 'text': '웹에서 연 기존 편집기로 저장한 메모'})

    closer = QTimer()
    closer.setInterval(20)
    closer.timeout.connect(edit_note)
    closer.start()
    js("document.getElementById('detail-scroll').focus()")
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_F2)
    wait_until(lambda: bool(observed) and not page.bridge.busy)
    closer.stop()
    wait_until(lambda: js(f"document.getElementById('{selection}').textContent.includes('웹에서 연 기존 편집기로 저장한 메모')"))
    assert observed == [hid]
    metrics['checks'].append('하이라이트 클릭 재생·F2 기존 HighlightEditor 저장 후 목록 반영·행 버튼 Tab 제외')
    js("document.querySelector('aside [data-tab=info]').click()")
    settle()

# 목록 갱신: Python 조회부터 다음 웹 프레임/Qt paint까지.
if args.profile_refresh:
    js("""(() => {
      window.__refreshParsing = [];
      const parse = JSON.parse;
      JSON.parse = function(...args) {
        const started = performance.now();
        const result = parse.apply(this, args);
        if (result && Array.isArray(result.videos)) {
          const ended = performance.now();
          const sample = {parseMs: ended - started};
          window.__refreshParsing.push(sample);
          requestAnimationFrame(() => requestAnimationFrame(() => sample.afterParseToFrameMs = performance.now() - ended));
        }
        return result;
      };
    })()""")
refresh = []
refresh_python = []
for _ in range(5):
    start = time.perf_counter()
    window.refresh()
    refresh_python.append(round((time.perf_counter() - start) * 1000, 2))
    run_web_frames('requestAnimationFrame(() => requestAnimationFrame(done));')
    refresh.append(round((time.perf_counter() - start) * 1000, 2))
metrics['refresh_ms'] = refresh
metrics['refresh_python_ms'] = refresh_python
if args.profile_refresh:
    metrics['refresh_web_parsing'] = js_json('window.__refreshParsing')

run_web_frames("""
  window.__scrollFrames = [];
  const grid = document.getElementById('library-grid'); let previous; let index = 0;
  function step(now) {
    if (previous !== undefined) window.__scrollFrames.push(now - previous);
    previous = now; grid.scrollTop = (index * 180) % Math.max(1, grid.scrollHeight - grid.clientHeight);
    if (++index < 121) requestAnimationFrame(step); else done();
  }
  requestAnimationFrame(step);
""")
metrics['scroll_frame_ms'] = js_json('window.__scrollFrames')
metrics['rendered_cards'] = js("document.querySelectorAll('[role=gridcell]').length")
metrics['scroll_clock'] = 'Chromium requestAnimationFrame, 120 intervals, no polling'

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
out = screens / f'web-{args.count}{"-verify" if args.verify else ""}.json'
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({
    'mode': 'web', 'count': args.count, 'startup_ms': metrics['startup_ms'],
    'refresh_median_ms': median(metrics['refresh_ms']),
    'scroll_frame_median_ms': median(metrics['scroll_frame_ms']),
    'working_set_mib': metrics['working_set_mib'], 'checks': metrics['checks'],
    'report': str(out),
}, ensure_ascii=False), flush=True)
if args.stay:
    js("document.getElementById('library-grid').scrollTop = 0")
    app.exec()
else:
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
