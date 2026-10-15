"""웹 폴더·설정 화면과 실제 Qt/WebEngine 포커스 검사 (독립 임시 라이브러리).

스크린샷: python scripts/check_web_folders_settings.py --offscreen
실창: desktop_lock.py run --owner issue-51 -- python scripts/check_web_folders_settings.py
실창 실행은 캡처하지 않는다. QTest가 실제 포커스 위젯에 키를 전달한다.
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
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-51')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, CommandType, MediaInfo, ScanResult
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
        self.commands = []

    def play(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def execute(self, command):
        self.commands.append(command)


app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='fs-', dir=ROOT / '.local'))
core = AppCore(database=workspace / 'data.sqlite3', media=Media(), clock=lambda: datetime.now(timezone.utc))
window = MainWindow(core, player_factory=Player)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
host = window.web_host
checks = []



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


def click(selector):
    window.activateWindow()
    host.view.setFocus()
    point = json.loads(js(f'JSON.stringify((() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) throw new Error("missing element"); e.scrollIntoView({{block:"nearest"}}); const r=e.getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})())'))
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle()


def key(code, modifiers=Qt.KeyboardModifier.NoModifier):
    target = QApplication.focusWidget()
    assert target is not None, '실제 키보드 포커스가 없습니다'
    if not args.offscreen:
        assert window.isActiveWindow(), '검사 창이 활성 창이 아닙니다'
    QTest.keyClick(target, code, modifiers)
    settle()


def navigate(tab):
    window.navigate_web_tab(tab)
    settle()


def category(name):
    click(f'[data-category="{name}"]')


def begin(command='point_highlight:0'):
    click(f'[data-command="{command}"]')
    wait(lambda: js('!!document.querySelector("[role=dialog]")'), '키 캡처 열기')


def button(text):
    # 사용자에게 보이는 버튼만 선택한다. 다른 분류의 숨은 버튼은 제외한다.
    point = json.loads(js(f'JSON.stringify((() => {{ const e=[...document.querySelectorAll("button")].find(e=>e.textContent==={json.dumps(text)} && e.getClientRects().length); if(!e)return null; e.scrollIntoView({{block:"nearest"}}); const r=e.getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})())'))
    if point is None:
        return False
    window.activateWindow()
    host.view.setFocus()
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle()
    return True


def content(selector):
    return js(f'document.querySelector({json.dumps(selector)}).textContent')


def capture(name):
    if not args.offscreen:
        return
    settle()
    web = window.grab().toImage()
    assert (web.width(), web.height()) == (1100, 720)
    web.save(str(args.output / f'web-{name}.png'))


try:
    wait(lambda: host._frontend_ready and {'folders', 'settings'} <= host._ready_pages, 'React 초기화')
    navigate('folders')
    capture('folders-empty')
    folders = []
    for index in range(80):
        folder = workspace / f'감시 폴더 {index:02}' / ('긴 경로 설명 ' * 4).strip()
        folder.mkdir(parents=True)
        core.add_watched_folder(folder)
        folders.append(folder)
        if index == 0:
            window.refresh()
            capture('folders-one-long')
    window.refresh()
    capture('folders-many')
    assert js('document.documentElement.scrollWidth <= innerWidth'), '페이지가 가로로 넘칩니다'
    checks.append('폴더 0·1·80개와 긴 경로 배치')
    finish = threading.Event()

    def slow_scan():
        finish.wait(10)
        return ScanResult(0, ())

    window.scan(operation=slow_scan)
    try:
        settle()
        assert js('document.getElementById("folders-add").disabled')
        assert js('!!document.querySelector("[role=progressbar]")')
        capture('folders-scanning')
    finally:
        finish.set()
        wait(lambda: window.worker is None)
    checks.append('실제 검사 작업자의 진행 표시와 잠금')
    for title in ('복원할 긴 한글 영상 제목 ' * 4, '관심 없음 영상'):
        path = workspace / f'{title[:75]}.mkv'
        path.write_bytes(title.encode())
        core.add_file(path)
    first, second = core.videos()
    core.exclude_video(first.id)
    core.dismiss_video(second.id)
    window.refresh()
    click('[data-tab="excluded"]')
    assert '파일 없음' not in content('[aria-label="폴더 관리"]')
    # 제외 항목이 실제로 파일 없음일 때만 그 상태를 표시한다.
    missing_folder = workspace / '파일 없는 제외 영상'
    missing_folder.mkdir()
    missing_path = missing_folder / '다시 연결할 영상.mkv'
    missing_path.write_bytes(b'missing excluded')
    core.add_watched_folder(missing_folder)
    core.add_file(missing_path)
    missing_video = next(v for v in core.videos() if v.title == missing_path.stem)
    core.exclude_video(missing_video.id)
    core.remove_watched_folder(missing_folder)
    window.refresh()
    settle()
    assert content('[aria-label="폴더 관리"]').count('파일 없음') == 1
    capture('folders-excluded')
    core.dismiss_video(missing_video.id)
    window.refresh()
    click('[data-tab="dismissed"]')
    missing_row = lambda: js('[...document.querySelectorAll(\'[aria-label="되돌리기 목록"] li\')].find(row => row.textContent.includes(\'다시 연결할 영상\')).textContent')
    assert '제외' in missing_row() and '파일 없음' not in missing_row()
    core.restore_video(missing_video.id)
    window.refresh()
    settle()
    assert '파일 없음' in missing_row() and '제외' not in missing_row()
    core.restore_dismissed_video(missing_video.id)
    window.refresh()
    click('[data-tab="excluded"]')
    settle()
    assert button('되돌리기')
    wait(lambda: not core.excluded_videos())
    click('[data-tab="dismissed"]')
    capture('folders-dismissed')
    assert button('되돌리기')
    wait(lambda: not core.dismissed_videos())
    checks.append('웹 제외 목록·관심 없음 복원과 제외/파일 없음 꼬리표 우선순위')
    # 브리지의 저장 응답 이후 두 페이지에 같은 값이 보인다.
    click('#folders-minimum')
    key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(QApplication.focusWidget(), '25.5')
    settle()
    assert js('document.getElementById("folders-minimum").value') == '25.5', '숫자 입력 포커스'
    assert button('저장')
    wait(lambda: core.minimum_duration == 25.5, '최소 길이 저장')
    navigate('settings')
    assert js('document.getElementById("settings-minimum").value') == '25.5'
    capture('settings-general')
    category('translation')
    assert 'codex' in content('[aria-label="번역 CLI 설정"]')
    capture('settings-translation')
    category('transcription')
    capture('settings-transcription')
    category('keys')

    capture('settings-keys')
    begin()

    capture('keys-capture')
    # 조합 중의 웹 입력은 키 배치를 바꾸거나 캡처를 종료하지 않는다.
    js('document.dispatchEvent(new KeyboardEvent("keydown", {key:"n", isComposing:true, bubbles:true, cancelable:true}))')
    assert js('!!document.querySelector("[role=dialog]")')
    key(Qt.Key.Key_Escape)
    wait(lambda: not js('!!document.querySelector("[role=dialog]")'))
    begin()
    js('document.dispatchEvent(new KeyboardEvent("keydown", {key:"7", ctrlKey:true, bubbles:true, cancelable:true}))')
    wait(lambda: not js('!!document.querySelector("[role=dialog]")'))
    assert host.active_tab == 'settings'
    assert 'Ctrl+7' in content('[aria-label="키 배치 편집"] [role="alert"]')
    begin()
    js('document.dispatchEvent(new KeyboardEvent("keydown", {key:"s", altKey:true, bubbles:true, cancelable:true}))')
    wait(lambda: not js('!!document.querySelector("[role=dialog]")'))
    assert 'Alt+S' in content('[aria-label="키 배치 편집"] [role="alert"]')
    for code, modifiers in (*((Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier) for index in range(7)),
                             (Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier),
                             (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier)):
        begin()
        key(code, modifiers)
        assert host.active_tab == 'settings' and not window.settings_menu.isVisible()
        assert '예약 키' in content('[aria-label="키 배치 편집"]')
        wait(lambda: not js('!!document.querySelector("[role=dialog]")'))
    checks.append('실제 포커스 키 캡처: Ctrl+1~7, Alt+S, F1, Esc 및 조합 중 무시')
    begin()
    key(Qt.Key.Key_MediaPlay)
    assert '지원하는 키를 누르세요' in content('[role="dialog"]')
    js('document.dispatchEvent(new KeyboardEvent("keydown", {key:"Unidentified", bubbles:true, cancelable:true}))')
    settle()
    assert '지원하는 키를 누르세요' in content('[role="dialog"]')
    key(Qt.Key.Key_Up)
    row_selector = '[data-command="point_highlight:0"]'
    row_text = lambda: js(f'document.querySelector({json.dumps(row_selector)}).closest("tr").textContent')
    assert '↑' in row_text() and 'Insert' in row_text()
    assert '적용하지 않은 변경 1건' in content('[aria-label="키 배치 편집"]')
    navigate('folders')
    navigate('settings')
    assert '↑' in row_text()
    begin('range_highlight:0')
    key(Qt.Key.Key_Comma)
    assert ', (쉼표)' in content('[aria-label="키 배치 편집"]')
    assert '적용하지 않은 변경 2건' in content('[aria-label="키 배치 편집"]')
    capture('keys-draft')
    assert button('변경 취소')
    assert not js('document.querySelector("tr[data-changed=true]") !== null')
    assert core.command_for_key('Insert').kind == CommandType.POINT_HIGHLIGHT
    checks.append('초안 표시·건수·탭 왕복 유지·전체 취소·Python 키 이름·미지원 키 캡처 유지')
    begin()
    key(Qt.Key.Key_Return)
    assert '같은 키를 사용' in content('[aria-label="키 배치 편집"]')
    assert js('[...document.querySelectorAll("button")].find(e=>e.textContent==="적용").disabled')
    capture('keys-conflict')
    begin()
    key(Qt.Key.Key_N)
    assert button('적용')
    wait(lambda: core.command_for_key('N') is not None, '키 배치 저장')
    assert core.command_for_key('N').kind == CommandType.POINT_HIGHLIGHT
    assert 'N로 지점' in window.web_host.controllers['reel'].payload()['emptyDescription']
    assert js('document.activeElement.dataset.command') == 'point_highlight:0', js('document.activeElement.outerHTML')[:600]
    navigate('reel')
    assert 'N로 지점' in content('[aria-label="하이라이트 모아보기"]')
    navigate('settings')
    checks.append('충돌 경고·저장 차단·웹 적용·Qt 및 웹 빈 모아보기 안내 즉시 반영')
    category('general')
    assert button('완전 종료')
    wait(lambda: js('!!document.querySelector("[role=alertdialog]")'))
    capture('settings-quit-confirm')
    assert button('취소')
    settle()
    assert window.isVisible()
    checks.append('공용 destructive 완전 종료 확인과 취소')
    if not args.offscreen:
        window.activateWindow()
        navigate('folders')
        key(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert host.active_tab == 'settings'
        assert js('document.activeElement.closest("#settings-category") !== null')
        checks.append('Alt+S 설정 탭과 분류 포커스')
    window.play_video(first.id)
    window.activateWindow()
    settle()
    session = core.playback.session
    player = window.player
    for fullscreen in (False, True):
        if fullscreen:
            key(Qt.Key.Key_Apostrophe)
        key(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert QApplication.activePopupWidget() is window.settings_menu
        assert core.playback.session is session and window.player is player
        assert window.isFullScreen() is fullscreen
        QTest.keyClick(window.settings_menu, Qt.Key.Key_Escape)
        settle()
        assert not window.settings_menu.isVisible()
        assert (window.focusWidget() is window.surface) if args.offscreen else window.surface.hasFocus()
        assert core.playback.session is session and window.player is player
    key(Qt.Key.Key_Escape)
    checks.append('일반·전체 화면 재생 중 Alt+S 메뉴·동일 세션 유지·닫은 뒤 재생 포커스')
    key(Qt.Key.Key_N)
    assert core.highlights(first.id), '웹에서 바꾼 실제 재생 키가 적용되지 않았습니다'
    key(Qt.Key.Key_F1)
    assert '<b>N</b>' in window.playback_page.help_panel.text.text()
    key(Qt.Key.Key_Escape)
    key(Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is host
    assert host.active_tab == 'settings'
    checks.append('재생 키·F1 안내 즉시 반영과 설정 복귀 포커스')
    category('keys')
    assert button('전체 기본값')
    assert button('적용')
    wait(lambda: core.command_for_key('Insert') is not None)
    assert core.command_for_key('N') is None
    checks.append('전체 기본값 복원')
    window.play_video(first.id)
    core.playback.report(40)
    key(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    window.settings_menu.actions()[0].trigger()
    window.settings_menu.hide()
    settle()
    assert core.playback.session is None
    assert core.viewing_status(first.id).resume_point == 40
    assert host.active_tab == 'settings'
    assert js('document.querySelector("#settings-category [aria-current=true]").textContent') == '키 배치'
    checks.append('Alt+S 키 배치 선택: 이어볼 위치 저장 후 웹 키 배치 구역으로 이동')
    window.library_page.library_controls.show_excluded()
    settle()
    assert '제외 목록' in content('[aria-label="폴더 관리 구역"] [aria-current="page"]')
    window.library_page.hidden_gems.show_dismissed()
    settle()
    assert '관심 없음' in content('[aria-label="폴더 관리 구역"] [aria-current="page"]')
    checks.append('라이브러리 되돌리기 진입점: 폴더 관리의 제외·관심 없음 구역 선택')
    result = {'mode': 'offscreen' if args.offscreen else 'windows', 'checks': checks, 'passed': len(checks)}
    (args.output / f'{result["mode"]}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
finally:
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
