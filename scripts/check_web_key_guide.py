"""#236 웹 키 안내와 트레이 '창 숨기기'. offscreen은 탭마다 키 안내를 연 1100×720 위젯을 캡처하고 배치를 잰다.

실창은 MVM_REAL_WINDOW_TESTS=1과 desktop_lock.py run --owner issue-236 안에서만 실행한다.
실제 키보드(keybd_event) F1을 탭마다·웹 대화상자 열림 중·한글 조합 중에 누르고, mpv 재생 키 안내의 셸 키 줄과
트레이 '창 숨기기'(숨은 상태 비활성)를 확인한다.
"""
import argparse
from contextlib import closing
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from time import perf_counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--count', type=int, default=24)
parser.add_argument('--variant', choices=('default', 'multi'), default='default',
                    help='multi: 무작위 재생에 키 셋, 긴급 탈출은 미할당')
parser.add_argument('--output', type=Path, default=Path('.local/issue-236-check'))
args = parser.parse_args()
if not args.offscreen and os.environ.get('MVM_REAL_WINDOW_TESTS') != '1':
    parser.error('실창은 MVM_REAL_WINDOW_TESTS=1과 desktop_lock 안에서 실행하세요.')
if args.count < 0 or (not args.offscreen and args.count != 2):
    parser.error('count는 0 이상이며 실창은 합성 영상 2개로 검사합니다.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.adapters import FFmpegMediaReader, MpvPlayer, executable
from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.ui import MainWindow
from my_video_manager.web_contract import TABS


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        pass

    def play(self, path, start, *, subtitle):
        pass

    def pause(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def close(self):
        pass


app = QApplication([])
if args.offscreen:
    # offscreen에는 OS 트레이가 없다. 메뉴 QAction과 창 숨김·복원은 그대로 검사한다.
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
args.output.mkdir(parents=True, exist_ok=True)
prefix = f'{args.count}-{args.variant}' + ('' if args.offscreen else '-real')
metrics = {'count': args.count, 'variant': args.variant, 'offscreen': args.offscreen, 'checks': [], 'layout': {}, 'screenshots': []}
user32 = None if args.offscreen else ctypes.windll.user32
VK_F1, VK_ESCAPE, VK_CONTROL = 0x70, 0x1B, 0x11
GUIDE = 'Array.from(document.querySelectorAll("[role=dialog]")).find(e => e.textContent.includes("키 안내 ·"))'


def wait(predicate, seconds=30):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


with tempfile.TemporaryDirectory(prefix='mvm-236-') as temporary:
    root = Path(temporary)
    core = AppCore(media=Media() if args.offscreen else FFmpegMediaReader(),
                   database=root / 'data/library.sqlite3', clock=lambda: datetime.now(timezone.utc))
    core.set_automatic_detection_enabled(False)
    core.set_automatic_update_check_enabled(False)
    core.set_minimum_duration(0)
    if args.offscreen:
        # 대량 합성 자료 준비는 이 검증 전용 DB에만 기록한다. 동작은 공개 코어·UI 경계를 쓴다.
        with closing(sqlite3.connect(core.database)) as db, db:
            for index in range(args.count):
                path = root / f'{index}.mkv'
                path.write_bytes(str(index).encode())
                title = ('아주 긴 제목 ' * 30) if index == 0 else f'합성 영상 {index:04}'
                vid = db.execute('INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked) VALUES (?,?,?,?,?,?,?,?,1)',
                                 (f'synthetic-{index}', title, 120, 'matroska', '', '2026-10-20T00:00:00+00:00', 640, 360)).lastrowid
                db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(path), vid))
    else:
        for index, color in enumerate(('darkblue', 'darkred')):
            path = root / f'{index}.mkv'
            subprocess.run([executable('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                            f'color=c={color}:s=640x360:r=24', '-t', '60', '-c:v', 'mpeg4', str(path)], check=True)
            core.add_file(path)
    if args.variant == 'multi':
        bindings = {row.command: row.keys for row in core.key_bindings()}
        bindings[Command(CommandType.RANDOM_PLAY)] = ('Ctrl+Shift+R', 'Ctrl+Alt+R', 'Ctrl+Alt+Shift+Left')
        bindings[Command(CommandType.EMERGENCY_HIDE)] = ()
        core.save_key_bindings(bindings)
    window = MainWindow(core, player_factory=Player if args.offscreen else MpvPlayer)
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    window.show()
    window.activateWindow()
    wait(lambda: loaded)
    host = window.web_host

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait(lambda: bool(result))
        return result[0]

    def settle(ms=120):
        QTest.qWait(ms)
        app.processEvents()

    def capture(name):
        if not args.offscreen:
            return
        settle(250)
        path = args.output / f'{prefix}-{name}.png'
        assert window.grab().save(str(path))
        assert (QImage(str(path)).width(), QImage(str(path)).height()) == (1100, 720)
        metrics['screenshots'].append(str(path.resolve()))

    def activate():
        window.raise_()
        window.activateWindow()
        app.processEvents()
        if not args.offscreen:
            assert QTest.qWaitForWindowActive(window, 5000)

    def press(vk, qt_key):
        """실창은 OS 키보드 입력, offscreen은 초점 위젯에 QTest 키."""
        if args.offscreen:
            QTest.keyClick(QApplication.focusWidget() or window, qt_key)
        else:
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, 2, 0)
        settle()

    def guide():
        return js(f"{GUIDE}?.innerText ?? ''")

    def wait_guide():
        wait(lambda: '앱 전체' in guide() and '읽는 중' not in guide())
        return guide()

    def wait_closed():
        wait(lambda: guide() == '' and not host.dialogs.blocks_shell_actions)

    def layout():
        """키 안내가 창 안에 들어오고 가로로 넘치지 않는지, 본문이 스크롤하는지 잰다."""
        return json.loads(js(f"""JSON.stringify((() => {{
          const dialog = {GUIDE}; const rect = dialog.getBoundingClientRect();
          const body = dialog.querySelector('[aria-label="키 목록"]');
          const keys = Array.from(dialog.querySelectorAll('dt')).filter(dt => dt.scrollWidth > dt.clientWidth + 1).length;
          return {{ top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right,
                    viewport: [innerWidth, innerHeight], scrolls: body.scrollHeight > body.clientHeight + 1,
                    horizontal: body.scrollWidth > body.clientWidth + 1, overflowingKeys: keys }}
        }})())"""))

    try:
        capture('0-header')
        for index, (tab, label) in enumerate(TABS):
            window.navigate_web_tab(tab)
            wait(lambda: host.active_tab == tab and tab in host._ready_pages)
            activate()
            host.view.setFocus()
            settle(300)
            press(VK_F1, Qt.Key.Key_F1)
            text = wait_guide()
            assert f'키 안내 · {label}' in text and f'지금 화면 · {label}' in text, text
            if args.variant == 'multi':
                assert 'Ctrl+Alt+Shift+←' in text and '키 미할당' in text, text
            box = layout()
            metrics['layout'][tab] = box
            assert 0 <= box['top'] and box['bottom'] <= box['viewport'][1], box
            assert 0 <= box['left'] and box['right'] <= box['viewport'][0], box
            assert not box['horizontal'] and not box['overflowingKeys'], box
            capture(f'{index + 1}-{tab}')
            press(VK_ESCAPE, Qt.Key.Key_Escape)
            wait_closed()
            assert host.active_tab == tab and window.pages.currentWidget() is host
        metrics['checks'].append('탭마다 F1로 열기·앱 전체와 지금 화면 키·창 안 배치·Esc 닫기(탭 유지)')

        window.navigate_web_tab('library')
        wait(lambda: host.active_tab == 'library')
        js('document.querySelector("header button[aria-label=\\"키 안내 (F1)\\"]").click()')
        wait_guide()
        capture('button')
        activate()
        press(VK_F1, Qt.Key.Key_F1)
        wait_closed()
        metrics['checks'].append('⌨ 단추로 열기·F1로 닫기')

        if not args.offscreen:
            # 웹 대화상자가 열려 있으면 실제 F1이 키 안내를 열지 않는다.
            video = core.videos()[0]
            window.library_page.bridge.select(video.id)
            result = {}

            def in_dialog():
                try:
                    wait(lambda: host.dialogs.active and js('!!document.querySelector("[aria-label=\\"영상 제목\\"]")'))
                    activate()
                    host.view.setFocus()
                    settle(300)
                    press(VK_F1, Qt.Key.Key_F1)
                    settle(400)
                    result['guide'] = guide()
                    result['dialog'] = host.dialogs.active
                finally:
                    while host.dialogs.active:
                        host.dialogs.pop()
            QTimer.singleShot(50, in_dialog)
            window.library_page.library_controls.rename()
            assert result == {'guide': '', 'dialog': True}, result
            metrics['checks'].append('웹 대화상자 열림 중 실제 F1: 키 안내 열리지 않음')

            # 한글 조합 중의 실제 F1. IME가 먼저 확정하는지와 입력 글자를 기록한다.
            user32.GetKeyboardLayout.restype = ctypes.c_void_p
            user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
            user32.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            previous = user32.GetKeyboardLayout(0)
            user32.LoadKeyboardLayoutW('00000412', 1)
            try:
                activate()
                host.view.setFocus()
                field = '[aria-label="영상 제목 빠른 검색"]'
                js(f'document.querySelector({json.dumps(field)}).focus()')
                settle(200)
                composing = False
                for attempt in range(2):
                    js(f"window.ime = []; document.querySelector({json.dumps(field)}).addEventListener('compositionstart', () => window.ime.push('start'))")
                    for key in 'GK':
                        press(ord(key), 0)
                    composing = window._composing_widget is not None
                    if composing:
                        break
                    press(0x15, 0)  # VK_HANGUL: 레이아웃의 영문 상태라면 한글로 바꾼다.
                    js(f"(() => {{ const e = document.querySelector({json.dumps(field)}); e.value = ''; e.dispatchEvent(new Event('input', {{bubbles: true}})) }})()")
                press(VK_F1, Qt.Key.Key_F1)
                settle(400)
                metrics['ime'] = {'composing_before_f1': composing, 'guide_opened': guide() != '',
                                  'value': js(f'document.querySelector({json.dumps(field)}).value')}
                if guide():
                    press(VK_ESCAPE, Qt.Key.Key_Escape)
                    wait_closed()
                metrics['checks'].append('한글 조합 중 실제 F1(결과는 ime 항목)')
            finally:
                user32.ActivateKeyboardLayout(previous, 0)
                js(f"(() => {{ const e = document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]'); e.value = ''; e.dispatchEvent(new Event('input', {{bubbles: true}})) }})()")

            # mpv 재생 화면의 F1 키 안내에 셸 키 줄이 보인다.
            window.play_video(core.videos()[0].id)
            wait(lambda: core.playback.position > 0.2)
            activate()
            press(VK_F1, Qt.Key.Key_F1)
            help_panel = window.playback_page.help_panel
            wait(help_panel.isVisible)
            text = help_panel.text.text()
            assert 'Alt+S 설정 메뉴' in text and 'Ctrl+1 ~ Ctrl+8 재생을 끝내고 페이지 이동' in text, text
            press(VK_F1, Qt.Key.Key_F1)
            wait(lambda: not help_panel.isVisible())
            metrics['checks'].append('mpv 재생 중 실제 F1 키 안내의 Alt+S·Ctrl+1~8 줄')

        # 트레이 '창 숨기기': 긴급 탈출과 같은 결과, 숨은 동안 비활성.
        if core.videos():
            window.play_video(core.videos()[0].id)
            if not args.offscreen:
                wait(lambda: core.playback.position > 0.2)
            session = core.playback.session
            menu = window.tray.icon.contextMenu()
            menu.aboutToShow.emit()
            action = window.tray.hide_action
            expected = '창 숨기기' if args.variant == 'multi' else '창 숨기기 · Ctrl+Shift+H'
            assert action.text() == expected and action.isEnabled(), action.text()
            action.trigger()
            settle(300)
            assert not window.isVisible() and core.playback.session is session
            menu.aboutToShow.emit()
            assert not action.isEnabled()
            window.tray.open()
            if not args.offscreen:
                wait(window.isActiveWindow)
            assert window.pages.currentWidget() is window.playback_page and core.playback.session is session
            position = core.playback.position
            settle(600)
            assert abs(core.playback.position - position) < 0.05, '복귀 뒤 저절로 재생함'
            metrics['checks'].append('트레이 창 숨기기 → 일시정지·숨김·숨은 동안 비활성 → 열기로 같은 장면 복귀')
            activate()
            press(VK_ESCAPE, Qt.Key.Key_Escape)
            wait(lambda: core.playback.session is None)
    finally:
        window.tray.quit()
    (args.output / f'{prefix}-metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
