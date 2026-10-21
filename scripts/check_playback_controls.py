"""재생 조작 줄 검사.

python scripts/check_playback_controls.py --offscreen
python ~/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_playback_controls.py --real

--offscreen은 가짜 플레이어로 1100×720(가장 넓은 상태 포함)과 더 좁은 창의 조작 줄이 넘치지 않는지,
하이라이트·속도 단추부터 짧게 줄이는지 보고 위젯 grab 이미지를 남긴다. 모아보기 단추가 더해진 가장 넓은 줄과
그 전체 화면 구성(1280 폭)도 재고, 상태별 남은 폭(slack)과 더 줄여 확보할 수 있는 폭(reducible)을 결과 JSON에 남긴다.
--real은 데스크톱 잠금 안에서 합성 영상과 실제 mpv, Windows 마우스·키 입력으로 단추 클릭, Tab 이동,
단추 초점에서의 재생 키, 하이라이트·구간 단추, 속도 목록 고르기와 목록 밖 속도 표시,
재생 메뉴 '설정'(창 모드·전체 화면), 전체 화면 조작 줄의 '목록으로'·'전체 화면 끄기', 키 안내 마우스 닫기,
전체 화면 모아보기의 ⇤ ⇥ ↻ 반복·⏮ ⏭ 단추 클릭을 확인한다.
실창에서는 화면 캡처를 하지 않는다. 데이터는 worktree 밖 임시 폴더에 만들고 지운다.
"""

import argparse
import ctypes
import ctypes.wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--real', action='store_true')
parser.add_argument('--output', type=Path, default=Path('.local/playback-controls'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QCursor, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Transcriber:
    def transcribe(self, *args, **kwargs):
        return TranscriberResult('ko', (TranscriptSegment(0, 55, '카드로 결재 할수 있어요.'),))


class Translator:
    def translate(self, lines, *args, **kwargs):
        return tuple(TranslatedLine(line.id, line.text.replace('할수', '할 수')) for line in lines)


class Player:
    """offscreen 배치 확인용 가짜 플레이어."""

    def __init__(self, surface):
        self.options, self.paused = (1, True), False

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        pass

    def take_positions(self):
        return ()

    def take_eof(self):
        return False

    def playback_options(self):
        return self.options

    def apply_playback_options(self, options):
        self.options = options

    def seek_to(self, position, *, resume=False):
        pass

    def set_subtitle(self, path):
        pass

    def execute(self, command):
        pass


def settle(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, label, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f'대기 시간 초과: {label}')
        settle(20)


def fits(page):
    """조작 줄의 최소 폭이 줄 폭 안이고 보이는 단추가 모두 줄 안에 있다."""
    row = page.controls.layout()
    inside = all(widget.geometry().right() < page.controls.width()
                 for widget in (*page.control_buttons, page.menu_button) if widget.isVisible())
    return row.minimumSize().width() <= page.controls.width() and inside


def offscreen(app, directory, result):
    # Windows offscreen 플러그인은 시스템 글꼴을 자동 열거하지 않는 경우가 있다.
    for name in ('malgun.ttf', 'malgunbd.ttf', 'segoeui.ttf', 'seguisym.ttf', 'seguiemj.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3',
                   transcriber=Transcriber(), translator=Translator())
    for index in (1, 2):
        path = directory / f'아주 긴 제목의 강의 영상 {index:02}강.mkv'
        path.write_bytes(bytes([index]))
        core.add_file(path)
    video_id = core.videos()[0].id
    # 다듬은 자막이 가장 긴 자막 종류 이름표다. 한국어 받아쓰기 → 자동 다듬기 요청 → 다듬기 완료를 코어로 만든다.
    core.request_subtitles(video_id)
    assert core.process_next_subtitle().state == 'completed'
    assert core.process_next_translation().state == 'completed'
    window = MainWindow(core, player_factory=Player)
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    window.resize(1100, 720)
    window.show()
    window.play(video_id)
    window.sync_position()
    page = window.playback_page

    def check(name, language, compact=()):
        """compact는 이 상태에서 짧게 줄어야 하는 단추. 줄이는 순서(하이라이트·속도 먼저)를 지켜야 한다."""
        settle()
        # 위치 갱신(0.1초)이 의도한 상태를 되돌렸으면 여기서 실패한다.
        assert page.subtitle_language_button.label == language, (name, page.subtitle_language_button.label)
        assert fits(page), name
        shortened = [button for button in page.compact_order if button.compact]
        # 짧은 글자가 따로 없는 단추(창 모드의 ⛶)와 숨은 단추(일반 재생의 모아보기 단추)는 순서에서 건너뛴다.
        order = [button for button in page.compact_order
                 if button.compact or (button.compact_saving() > 0 and not button.isHidden())]
        assert shortened == order[:len(shortened)], (name, [b.accessibleName() for b in shortened])
        assert set(compact) <= set(shortened), (name, [b.accessibleName() for b in shortened])
        if not compact:
            assert not shortened, (name, [b.accessibleName() for b in shortened])
        # 아이콘·값만 남은 단추도 기능 이름(툴팁·접근성 이름)은 그대로다.
        assert all(button.toolTip() and button.accessibleName() for button in page.control_buttons), name
        result.setdefault('compact', {})[name] = [button.accessibleName() for button in shortened]
        # 줄인 뒤 줄에 남는 폭. 뒤 이슈가 단추를 더할 때 기준으로 쓴다.
        result.setdefault('slack', {})[name] = page.controls.width() - page.controls.layout().minimumSize().width()
        result.setdefault('reducible', {})[name] = sum(button.compact_saving() for button in page.compact_order
                                                       if not button.compact and not button.isHidden())
        image = args.output / f'playback-{name}.png'
        assert window.grab().save(str(image))
        result['passed'].append(name)
        result['images'].append(str(image))

    window.core.toggle_subtitle_language()
    assert core.playback_subtitle_language == 'original'
    check('plain', '원어 자막')
    # 열린 구간('구간 끝내기')·목록 밖 긴 속도·자막 꺼짐·일시정지와 다듬은 자막이 함께 보이는 가장 넓은 창 모드 줄.
    # 1100 폭에서는 하이라이트 단추가 아이콘만 남아야 들어간다.
    window.core.toggle_subtitle_language()
    assert core.playback_subtitle_language == 'translated'
    core.playback.report(10)
    window.core.execute_highlight_command(Command(CommandType.RANGE_HIGHLIGHT))
    window.player.options = (99.75, False)
    window.player.paused = True
    window.sync_position()
    check('widest', '다듬은 자막', compact=(page.point_button, page.range_button))
    assert page.open_range_label.isVisible() and page.pause_button.text() == '▶'
    assert page.range_button.isChecked() and page.range_button.accessibleName() == '구간 하이라이트 끝내기'
    assert page.range_button.label == '】 구간 끝내기' and page.range_button.text() == '】'
    assert page.subtitles_button.text() == '자막 꺼짐' and page.speed_button.label == '속도 99.75×'
    # 1100보다 좁은 화면(전체 화면 등)에서는 속도 단추가 값만 남고, 그다음에 자막·전체 화면 단추를 줄인다.
    window.resize(1040, 720)
    check('narrow', '다듬은 자막', compact=(page.point_button, page.range_button, page.speed_button))
    assert page.speed_button.text() == '99.75×'
    window.resize(1100, 720)
    page.key_guide_button.click()
    settle()
    assert page.help_panel.isVisible()
    assert page.help_panel.grab().save(str(args.output / 'playback-key-guide.png'))
    page.help_panel.close_button.click()
    assert not page.help_panel.isVisible()
    result['passed'].append('key-guide-close-button')
    reel(window, page, check)
    window.tray.quit()


def reel(window, page, check):
    """하이라이트 모아보기 중의 조작 줄. 모아보기 단추 셋이 더해진 가장 넓은 줄과 모아보기를 끝낸 줄."""
    core = window.core
    core.playback.report(20)
    core.execute_highlight_command(Command(CommandType.RANGE_HIGHLIGHT))  # 열린 구간을 닫아 첫 항목으로 쓴다.
    core.playback.report(30)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    window.reel.start()
    assert core.reel_playback is not None and all(button.isVisible() for button in page.reel_buttons)
    # 열린 구간('구간 끝내기')·목록 밖 긴 속도·자막 꺼짐·일시정지·다듬은 자막에 반복 켜짐까지 함께 보이는 줄.
    # 한국어 영상은 다듬은 자막으로 시작한다.
    assert core.playback_subtitle_language == 'translated'
    core.playback.report(core.reel_playback.start + 1)
    core.execute_highlight_command(Command(CommandType.RANGE_HIGHLIGHT))
    window.player.options = (99.75, False)
    window.player.paused = True
    page.reel_repeat_button.click()
    window.sync_position()
    assert core.reel_repeat and page.reel_repeat_button.isChecked()
    assert page.reel_repeat_button.label == '↻ 반복 켜짐'
    # 1100 폭에서는 하이라이트·속도·반복 단추에 이어 자막 단추와 열린 구간 표시까지 줄여야 들어간다.
    check('reel-widest', '다듬은 자막', compact=(page.point_button, page.range_button, page.speed_button,
                                              page.reel_repeat_button, page.open_range_label))
    assert page.open_range_label.text() == '【 00:00:11' and page.reel_repeat_button.text() == '↻'
    # 전체 화면 줄에는 '모아보기 목록'과 '⛶ 전체 화면 끄기'가 더해진다. 흔한 가장 작은 화면 폭(1280)에서 그 구성을 잰다.
    window.resize(1280, 720)
    page.set_fullscreen(True)
    page.bottom_bar.show()
    check('reel-fullscreen-bar-1280', '다듬은 자막', compact=(page.point_button, page.range_button, page.speed_button))
    page.set_fullscreen(False)
    window.resize(1100, 720)
    window.end_playback()
    assert not any(button.isVisible() or not button.isHidden() for button in page.reel_buttons)


def real(app, directory, result):
    from my_video_manager.adapters import FFmpegMediaReader
    user32 = ctypes.windll.user32
    source = directory / '실창 조작 줄.mp4'
    subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                    '-t', '120', '-c:v', 'libx264', '-preset', 'ultrafast', '-y', str(source)], check=True)
    core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                   database=directory / 'library.sqlite3')
    core.add_file(source)
    window = MainWindow(core)
    window.move(40, 40)
    window.resize(1100, 720)
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000), '앱 창 활성화 실패'
    # 다른 앱(IDE 등)이 검사 창 위로 올라와 OS 클릭을 가로채지 않게 검사 동안만 z 순서를 맨 위로 둔다.
    # Qt 창 플래그는 바꾸지 않으므로 활성화·초점 동작은 앱과 같다.
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    page = window.playback_page
    window.play(core.videos()[0].id)
    wait(lambda: core.playback.position > 1, '재생 시작')

    def point(widget):
        """Qt 논리 좌표의 위젯 가운데를 Windows 물리 좌표로 바꾼다. 창은 원점에 있는 주 화면에 둔다."""
        assert widget.screen().geometry().topLeft() == QPoint(0, 0), '주 화면 밖의 창'
        ratio = widget.screen().devicePixelRatio()
        center = widget.mapToGlobal(widget.rect().center())
        return round(center.x() * ratio), round(center.y() * ratio)

    def click(widget):
        x, y = point(widget)
        user32.SetCursorPos(x, y)
        settle(80)
        # 커서 아래 위젯을 먼저 확인해 OS 입력 누락(다른 창이 가림 등)과 제품 실패를 구분한다.
        under = QApplication.widgetAt(QCursor.pos())
        if under is not widget:
            hwnd = user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
            title, kind, pid = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256), ctypes.c_ulong()
            user32.GetWindowTextW(hwnd, title, 256)
            user32.GetClassNameW(hwnd, kind, 256)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = ctypes.wintypes.RECT()
            root = user32.GetAncestor(hwnd, 2)
            user32.GetWindowRect(root, ctypes.byref(rect))
            topmost = bool(user32.GetWindowLongW(root, -20) & 0x8)
            print(f'가린 창: {title.value!r} {kind.value!r} pid {pid.value} (이 프로세스 {os.getpid()})'
                  f' 영역 {(rect.left, rect.top, rect.right, rect.bottom)} 항상 위 {topmost}')
        assert under is widget, (f'커서 아래가 {under!r}({QCursor.pos()}), 기대 {widget.accessibleName()}'
                                 f' · 활성 창 {QApplication.activeWindow()!r} · 창 {window.geometry()}'
                                 f' · 화면 {widget.screen().geometry()} ×{widget.screen().devicePixelRatio()}'
                                 f' · 위젯 {widget.mapToGlobal(widget.rect().center())}')
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        settle(250)

    def press(vk, extended=False):
        flag = 0x1 if extended else 0
        user32.keybd_event(vk, 0, flag, 0)
        user32.keybd_event(vk, 0, flag | 0x2, 0)
        settle(250)

    def passed(name):
        assert window.isActiveWindow(), f'{name}: 앱 창이 활성 창이 아님'
        result['passed'].append(name)

    def choose(button, menu, text):
        """단추로 연 메뉴에서 항목을 Windows 마우스로 고른다.

        InstantPopup 메뉴는 exec 안에서 열려 click()의 대기가 메뉴가 닫힐 때까지 끝나지 않으므로,
        메뉴가 보이면 타이머에서 항목을 누른다.
        """
        def run():
            if not menu.isVisible():
                return
            timer.stop()
            item = next(action for action in menu.actions() if action.text() == text)
            ratio = menu.screen().devicePixelRatio()
            center = menu.mapToGlobal(menu.actionGeometry(item).center())
            user32.SetCursorPos(round(center.x() * ratio), round(center.y() * ratio))
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)

        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(run)
        timer.start()
        # 항목 클릭이 빗나가도 검사가 멈추지 않게 닫는다.
        QTimer.singleShot(8000, lambda: menu.isVisible() and menu.close())
        click(button)
        timer.stop()
        assert not menu.isVisible(), f'{text}: 메뉴가 닫히지 않음'

    window.surface.setFocus()
    click(page.pause_button)
    wait(lambda: window.player.paused, '⏸ 단추로 일시정지')
    assert page.pause_button.text() == '▶' and page.pause_button.accessibleName() == '재생'
    assert window.surface.hasFocus(), '단추 클릭이 영상 초점을 가져감'
    passed('pause-button-click')
    press(0x0D)  # Enter: 초점이 영상에 남아 재생 키가 그대로 동작한다.
    wait(lambda: not window.player.paused, 'Enter로 재개')
    passed('playback-key-after-click')

    # ⏮ ⏯ ⏭ ◆ 【 속도 다음이 자막 단추다.
    for _ in range(7):
        press(0x09)
    assert page.subtitles_button.hasFocus(), 'Tab 일곱 번 뒤 자막 단추 초점'
    before = core.playback.position
    press(0x27, extended=True)  # →
    wait(lambda: core.playback.position >= before + 4, '단추 초점에서 → 탐색')
    # 머리 줄 '목록으로'와 같은 규칙: Enter는 초점과 관계없이 재생 명령, Space는 초점 단추 누르기.
    press(0x0D)
    wait(lambda: window.player.paused, '자막 단추 초점에서 Enter로 일시정지')
    assert window.player.playback_options()[1], 'Enter가 자막 단추를 눌렀다'
    press(0x20)
    wait(lambda: not window.player.playback_options()[1], 'Space로 자막 단추 누르기')
    assert window.player.paused, 'Space가 재생 명령으로 갔다'
    press(0x20)
    wait(lambda: window.player.playback_options()[1], 'Space로 자막 다시 켜기')
    press(0x0D)
    wait(lambda: not window.player.paused, 'Enter로 재개')
    passed('tab-focus-keys')
    window.surface.setFocus()

    click(page.subtitles_button)
    wait(lambda: not window.player.playback_options()[1], '자막 끄기 단추')
    assert not page.subtitles_button.isChecked()
    click(page.subtitles_button)
    wait(lambda: window.player.playback_options()[1], '자막 켜기 단추')
    passed('subtitles-button-click')

    click(page.key_guide_button)
    wait(page.help_panel.isVisible, '⌨ 단추로 키 안내 열기')
    click(page.help_panel.close_button)
    wait(lambda: not page.help_panel.isVisible(), '닫기 단추로 키 안내 닫기')
    assert not page.key_guide_button.isChecked()
    passed('key-guide-mouse-close')

    window.surface.setFocus()
    video_id = core.playback.session.video_id
    click(page.point_button)
    wait(lambda: len(core.highlights(video_id)) == 1, '◆ 단추로 지점 하이라이트')
    assert window.surface.hasFocus(), '하이라이트 단추 클릭이 영상 초점을 가져감'
    click(page.range_button)
    wait(lambda: core.open_highlight_start is not None, '【 단추로 구간 시작')
    assert page.range_button.isChecked() and page.range_button.label == '】 구간 끝내기'
    settle(1200)
    click(page.range_button)
    wait(lambda: core.open_highlight_start is None, '】 단추로 구간 끝내기')
    assert any(h.end is not None for h in core.highlights(video_id)), '구간 하이라이트 없음'
    assert not page.range_button.isChecked() and page.range_button.label == '【 구간 시작'
    passed('highlight-buttons-click')

    choose(page.speed_button, page.speed_menu, '1.5×')
    wait(lambda: window.player.playback_options()[0] == 1.5, '속도 목록에서 1.5×')
    assert page.speed_button.label == '속도 1.5×'
    for _ in range(3):
        press(0x26, extended=True)  # ↑: 목록 밖 2.25×까지
    wait(lambda: window.player.playback_options()[0] == 2.25, '↑ 키로 2.25×')
    wait(lambda: page.speed_button.label == '속도 2.25×', '목록 밖 속도 표시')
    choose(page.speed_button, page.speed_menu, '1×')
    wait(lambda: window.player.playback_options()[0] == 1, '속도 목록에서 1×')
    assert window.surface.hasFocus(), '속도 목록 뒤 영상 초점'
    passed('speed-list-choose')

    def settings_from_menu(name):
        choose(page.menu_button, page.menu, '설정 · Alt+S')
        wait(lambda: QApplication.activePopupWidget() is window.settings_menu, f'{name}: 재생 메뉴의 설정')
        press(0x1B)  # Esc: 설정 메뉴만 닫는다.
        wait(lambda: not window.settings_menu.isVisible(), f'{name}: 설정 메뉴 닫기')
        assert core.playback.session is not None and window.surface.hasFocus(), f'{name}: 재생 세션·초점'
        passed(name)

    settings_from_menu('playback-menu-settings-window')

    click(page.fullscreen_button)
    wait(window.isFullScreen, '⛶ 단추로 전체 화면')
    x, y = point(page.surface)
    user32.SetCursorPos(x - 30, y - 30)
    wait(page.bottom_bar.isVisible, '전체 화면 조작 줄 표시')
    settings_from_menu('playback-menu-settings-fullscreen')
    assert window.isFullScreen(), '설정 메뉴 뒤 전체 화면 유지'
    settle(300)
    page.hide_temporary_bar()
    assert not page.bottom_bar.isVisible()
    x, y = point(page.surface)
    user32.SetCursorPos(x + 30, y + 30)
    wait(page.bottom_bar.isVisible, '마우스 움직임으로 조작 줄 표시')
    assert page.list_button.isVisible() and fits(page), '전체 화면 조작 줄 배치'
    result['fullscreen_bar'] = {'width': page.controls.width(),
                                'minimum': page.controls.layout().minimumSize().width(),
                                'fullscreen_label': page.fullscreen_button.text()}
    click(page.fullscreen_button)
    wait(lambda: not window.isFullScreen(), '전체 화면 끄기 단추')
    assert core.playback.session is not None
    passed('fullscreen-off-button')

    press(0xDE)  # ': 전체 화면
    wait(window.isFullScreen, "' 키로 전체 화면")
    x, y = point(page.surface)
    user32.SetCursorPos(x + 60, y + 60)
    wait(page.bottom_bar.isVisible, '조작 줄 다시 표시')
    click(page.list_button)
    wait(lambda: core.playback.session is None, '목록으로 단추')
    assert not window.isFullScreen() and window.pages.currentWidget() is window.web_host
    passed('fullscreen-list-button')
    real_reel(window, page, directory, click, press, passed)
    window.tray.quit()


def real_reel(window, page, directory, click, press, passed):
    """하이라이트 모아보기를 전체 화면에서 재생하며 모아보기 단추와 ⏮ ⏭를 Windows 마우스로 누른다."""
    from my_video_manager.adapters import FFmpegMediaReader
    core = window.core
    source = directory / '실창 조작 줄 2.mp4'
    subprocess.run([FFmpegMediaReader().ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
                    '-t', '90', '-c:v', 'libx264', '-preset', 'ultrafast', '-y', str(source)], check=True)
    core.add_file(source)
    # 첫 영상(앞 검사의 하이라이트 포함)에 항목 둘을 더하고, 둘째 영상에 항목 하나를 둔다.
    # 검사 중 자동으로 다음 항목에 넘어가지 않게 40초 구간으로 둔다.
    videos = sorted(core.videos(), key=lambda v: v.title)
    for video, starts in zip(videos, ((10, 60), (10,))):
        core.switch_to(video.id)
        for start in starts:
            core.playback.report(start, seeked=True)
            core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
            highlight = next(h for h in core.highlights(video.id) if h.start == start)
            core.update_highlight(highlight.id, start=start, end=start + 40, note='')
    core.end_playback()
    window.reel.start()
    wait(lambda: core.reel_playback is not None and core.playback.position > 10.5, '모아보기 재생 시작')
    index = lambda: core.reel_playback.index
    second_video_first = 1 + sum(1 for entry in core.reel_entries() if entry.highlight.video_id == videos[0].id)
    press(0xDE)  # ': 전체 화면
    wait(window.isFullScreen, '모아보기 전체 화면')

    offsets = iter(range(-60, 60, 7))

    def press_button(button, done, label):
        # 커서를 영상 위에서 움직여 숨은 조작 줄을 다시 보이게 한 뒤 누른다.
        center = page.surface.mapToGlobal(page.surface.rect().center())
        ratio = page.screen().devicePixelRatio()
        ctypes.windll.user32.SetCursorPos(round((center.x() + next(offsets)) * ratio), round(center.y() * ratio))
        wait(button.isVisible, f'{label}: 조작 줄 표시')
        click(button)
        wait(done, label)
        assert window.isFullScreen() and window.surface.hasFocus(), f'{label}: 전체 화면·영상 초점'

    press_button(page.reel_next_button, lambda: index() == 2, '⇥ 다음 항목')
    press_button(page.reel_previous_button, lambda: index() == 1, '⇤ 이전 항목')
    press_button(page.reel_repeat_button, lambda: core.reel_repeat and page.reel_repeat_button.isChecked(), '↻ 반복 켜기')
    press(0xDC)  # \: 키로 끄면 단추도 꺼진다.
    wait(lambda: not core.reel_repeat and not page.reel_repeat_button.isChecked(), '백슬래시 키로 반복 끄기')
    press_button(page.next_button, lambda: index() == second_video_first, '⏭ 다음 영상 첫 하이라이트')
    press_button(page.previous_button, lambda: index() == 1, '⏮ 이전 영상 첫 항목')
    passed('reel-buttons-fullscreen-click')
    press(0x1B)  # Esc: 전체 화면 끄기
    press(0x1B)  # Esc: 모아보기 목록
    wait(lambda: core.reel_playback is None, '모아보기 목록 복귀')
    assert all(button.isHidden() for button in page.reel_buttons)
    passed('reel-buttons-hidden-after-reel')


def main():
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    directory = Path(tempfile.mkdtemp(prefix='playback-controls-'))
    result = {'mode': 'offscreen' if args.offscreen else 'real', 'passed': [], 'images': []}
    try:
        (offscreen if args.offscreen else real)(app, directory, result)
    finally:
        settle()
        shutil.rmtree(directory, ignore_errors=True)
    path = args.output / f'{result["mode"]}-result.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
