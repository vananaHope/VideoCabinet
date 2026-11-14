"""재생 화면의 화면 번역 자막 검사.

python scripts/check_onscreen_playback.py --offscreen --output <임시 폴더>
python ~/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_onscreen_playback.py --real --output <임시 폴더>

두 모드 모두 합성 영상(파란 바탕, 위·아래 영역 자리에 흰 상자)을 실제 ffmpeg로 만들고, 영역을 정해 실제 영역 읽기
(가짜 OCR: 밝은 영역을 글자로 읽음)와 가짜 번역 주체로 화면 자막·화면 번역 자막을 만든다.

--offscreen은 오버레이 명령을 기록하는 가짜 플레이어로 재생해 시작 켬, 위치별 띠 묶음, 키·단추 켜고 끄기,
목록 왕복 뒤 새 엔진에서 다시 그리기의 명령 순서를 보고 재생 화면 grab 이미지를 남긴다.
--real은 데스크톱 잠금 안에서 실제 mpv로 띄우고 mpv screenshot-to-file(window 방식, 창 크기·OSD 포함) 이미지의
영역 픽셀로 띠를 확인한다: 영역 자리의 검은 띠, ] 키·'화면 번역' 단추(Windows 입력)로 끄고 켜기, 줄 없는 영역은
원래 그림, 전체 화면에서 영역 따라가기, 목록 왕복 뒤 띠가 남지 않음. 짧은 줄·긴 줄·여러 줄·영역 여럿의 띠 글자도 찍는다.
실창에서는 화면 캡처를 하지 않는다. 데이터는 worktree 밖 임시 폴더에 만들고 지운다.
"""

import argparse
import ctypes
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
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QCursor, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.onscreen_playback import OnScreenBand
from my_video_manager.onscreen_subtitles import RegionRect
from my_video_manager.translation import TranslatedLine
from my_video_manager.translation_source import ONSCREEN
from my_video_manager.ui import MainWindow

SIZE = (640, 360)
BOTTOM = RegionRect(0.1, 0.78, 0.8, 0.16)
TOP = RegionRect(0.05, 0.05, 0.3, 0.1)
TOP_UNTIL = 30  # 위 영역 글자는 30초까지만 보인다. 그 뒤 위 영역에는 줄이 없다.
TEXTS = {'bottom': 'Hello world', 'top': 'Sign'}
TRANSLATIONS = {'Hello world': '안녕하세요, 화면 번역입니다', 'Sign': '표지판'}


class Ocr:
    """밝은 영역 그림을 글자로 읽는 가짜 OCR. 넓은 영역은 아래, 좁은 영역은 위 글자다."""

    def language_available(self, language):
        return True

    def missing_language_guidance(self, language):
        return ''

    def read_text(self, image, language):
        if sum(image.pixels) / len(image.pixels) < 128:
            return ''
        return TEXTS['bottom' if image.width > SIZE[0] / 2 else 'top']


class Translator:
    def translate(self, lines, *args, **kwargs):
        return tuple(TranslatedLine(line.id, TRANSLATIONS[line.text]) for line in lines)


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


def box(rect):
    x, y = rect.x * SIZE[0], rect.y * SIZE[1]
    return f'{x:.0f}:{y:.0f}:{rect.width * SIZE[0]:.0f}:{rect.height * SIZE[1]:.0f}'


def prepare(directory, player_factory=None):
    """합성 영상 하나를 등록하고 화면 자막·화면 번역 자막까지 만든 창."""
    media = FFmpegMediaReader()
    source = directory / '화면 번역 검사.mp4'
    filters = (f"drawbox={box(BOTTOM)}:color=white:t=fill,"
               f"drawbox={box(TOP)}:color=white:t=fill:enable='lt(t,{TOP_UNTIL})'")
    subprocess.run([media.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', f'color=c=0x2050c0:s={SIZE[0]}x{SIZE[1]}:r=24',
                    '-t', '60', '-vf', filters, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-y', str(source)], check=True)
    core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3',
                   ocr_engine=Ocr(), translator=Translator())
    core.add_file(source)
    video_id = core.videos()[0].id
    core.set_onscreen_subtitle_regions(video_id, ((BOTTOM, 'en'), (TOP, 'en')))
    assert core.process_next_onscreen_subtitle().state == 'completed'
    while core.translation_ready():
        core.process_next_translation()
    translation = core.translation(video_id, source=ONSCREEN)
    assert translation is not None and {line.text for line in translation.lines} == set(TRANSLATIONS.values())
    window = MainWindow(core, **({'player_factory': player_factory} if player_factory else {}))
    for timer in (window.translations.timer, window.onscreen_subtitles.timer, window.subtitles.timer):
        timer.stop()
    return core, window, video_id


class FakePlayer:
    """offscreen 확인용. 오버레이·받아쓰기 자막 자리 명령과 엔진 종료를 한 기록에 남긴다."""
    log = []

    def __init__(self, surface):
        self.options, self.paused, self.positions, self.statuses = (1, True), False, [], []

    def play(self, path, start, *, subtitle):
        self.positions = [(start or 0, True)]

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        return False

    def playback_options(self):
        return self.options

    def apply_playback_options(self, options):
        self.options = options

    def seek_to(self, position, *, resume=False):
        self.positions = [(position, True)]

    def set_subtitle(self, path):
        pass

    def execute(self, command):
        pass

    def show_status(self, text, duration):
        self.statuses.append(text)

    def show_onscreen_translation(self, bands):
        self.log.append([id(self), 'show', [band.text for band in bands]])

    def clear_onscreen_translation(self):
        self.log.append([id(self), 'clear'])

    def set_subtitles_raised(self, raised):
        self.log.append([id(self), 'raise', raised])

    def prepare_close(self):
        self.log.append([id(self), 'close'])

    def close(self):
        pass


def offscreen(app, directory, result):
    for name in ('malgun.ttf', 'malgunbd.ttf', 'segoeui.ttf', 'seguisym.ttf', 'seguiemj.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    core, window, video_id = prepare(directory, FakePlayer)
    window.resize(1100, 720)
    window.show()
    page = window.playback_page
    log = FakePlayer.log
    top, bottom = TRANSLATIONS['Sign'], TRANSLATIONS['Hello world']

    def at(position, seeked=True):
        window.player.positions = [(position, seeked)]
        window.sync_position()
        settle(50)

    window.play(video_id)
    at(10)
    first = id(window.player)
    assert page.onscreen_button.isChecked(), '시작 켬'
    assert log == [[first, 'show', [bottom, top]]], log
    at(10.5, False)
    assert len(log) == 1, '같은 줄 묶음을 다시 보냄'
    at(40)
    assert log[-1] == [first, 'show', [bottom]], '줄 없는 위 영역에 띠'
    result['passed'].append('bands-by-position')
    assert page.onscreen_button.grab().save(str(args.output / 'onscreen-button-on.png'))
    assert window.grab().save(str(args.output / 'playback-onscreen-on.png'))
    page.press(page.onscreen_button.command)
    assert log[-1] == [first, 'clear'] and window.player.statuses[-1] == '화면 번역 자막 꺼짐'
    assert not page.onscreen_button.isChecked()
    assert page.onscreen_button.grab().save(str(args.output / 'onscreen-button-off.png'))
    page.press(page.onscreen_button.command)
    assert log[-1] == [first, 'show', [bottom]] and window.player.statuses[-1] == '화면 번역 자막 켜짐'
    result['passed'].append('button-toggle')
    window.back_to_list()
    wait(lambda: core.playback.session is None, '목록 복귀')
    assert log[-2:] == [[first, 'clear'], [first, 'close']], log[-2:]
    window.play(video_id)
    at(10)
    second = id(window.player)
    assert second != first and log[-1] == [second, 'show', [bottom, top]]
    assert all(entry[0] == second for entry in log[log.index([first, 'close']) + 1:]), '닫힌 엔진에 보냄'
    result['passed'].append('list-round-trip')
    result['log'] = [[('first' if entry[0] == first else 'second'), *entry[1:]] for entry in log]
    window.tray.quit()


def real(app, directory, result):
    user32 = ctypes.windll.user32
    core, window, video_id = prepare(directory)
    window.move(40, 40)
    window.resize(1100, 720)
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 5000), '앱 창 활성화 실패'
    # 다른 앱이 검사 창 위로 올라와 OS 입력을 가로채지 않게 검사 동안만 맨 위에 둔다.
    user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    page = window.playback_page
    window.play(video_id)
    wait(lambda: core.playback.position > 1, '재생 시작')
    shots = iter(range(1, 100))

    def press(vk):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x2, 0)
        settle(300)

    def click(widget):
        ratio = widget.screen().devicePixelRatio()
        center = widget.mapToGlobal(widget.rect().center())
        user32.SetCursorPos(round(center.x() * ratio), round(center.y() * ratio))
        settle(80)
        assert QApplication.widgetAt(QCursor.pos()) is widget, f'커서 아래가 {widget.accessibleName()}가 아님'
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        settle(300)

    def screenshot(name):
        """mpv가 그린 창(영상·자막·OSD)을 창 크기 그대로 파일로 받는다."""
        settle(400)  # OSD 다시 그리기를 기다린다
        path = args.output / f'{next(shots):02}-{name}.png'
        window.player._player.command('screenshot-to-file', str(path), 'window')
        wait(path.is_file, f'{name} 스크린샷')
        settle(200)
        image = QImage(str(path))
        assert not image.isNull(), name
        result['images'].append(path.name)
        return image

    def video_rect(image):
        """창 이미지 안에서 영상이 그려진 자리. 영상 화면비(16:9)로 창에 맞춘 가운데 사각형이다."""
        width, height = image.width(), image.height()
        scale = min(width / SIZE[0], height / SIZE[1])
        drawn = SIZE[0] * scale, SIZE[1] * scale
        return (width - drawn[0]) / 2, (height - drawn[1]) / 2, drawn[0], drawn[1]

    def samples(image, rect):
        """영역 안쪽 네 모서리 근처(글자를 피한 띠 자리)의 화소."""
        left, top, width, height = video_rect(image)
        x0, y0 = left + rect.x * width, top + rect.y * height
        x1, y1 = x0 + rect.width * width, y0 + rect.height * height
        inset = 4
        return [image.pixelColor(round(x), round(y)) for x, y in (
            (x0 + inset, y0 + inset), (x1 - inset, y0 + inset), (x0 + inset, y1 - inset), (x1 - inset, y1 - inset))]

    def kind(color):
        if max(color.red(), color.green(), color.blue()) < 40:
            return 'band'
        if min(color.red(), color.green(), color.blue()) > 200:
            return 'white'  # 영상에 입혀진 원래 글자 자리(흰 상자)
        if color.blue() > 120 and color.red() < 90:
            return 'video'  # 파란 바탕
        return f'other{color.getRgb()[:3]}'

    def expect(image, name, **regions):
        found = {key: sorted({kind(color) for color in samples(image, rect)}) for key, rect in
                 (('bottom', BOTTOM), ('top', TOP)) if key in regions}
        result.setdefault('pixels', {})[name] = found
        assert found == {key: [value] for key, value in regions.items()}, (name, found)
        # 띠가 영역 밖으로 번지지 않는다: 아래 영역 바로 위는 파란 바탕이다.
        left, top, width, height = video_rect(image)
        above = image.pixelColor(round(left + (BOTTOM.x + BOTTOM.width / 2) * width),
                                 round(top + BOTTOM.y * height - 6))
        assert kind(above) == 'video', (name, '영역 밖', above.getRgb())
        result['passed'].append(name)

    # 일시정지한 장면에서 비교한다(줄이 바뀌지 않게 10초 자리).
    window.player.seek_to(10)
    wait(lambda: abs(core.playback.position - 10) < 0.5, '10초로 이동')
    press(0x0D)  # Enter: 일시정지
    wait(lambda: window.player.paused, '일시정지')
    expect(screenshot('start-on'), 'start-on', bottom='band', top='band')
    press(0xDD)  # ]: 화면 번역 자막 끄기
    wait(lambda: not page.onscreen_button.isChecked(), '] 키로 끄기')
    expect(screenshot('key-off'), 'key-off', bottom='white', top='white')
    click(page.onscreen_button)
    wait(page.onscreen_button.isChecked, '단추로 켜기')
    assert window.surface.hasFocus(), '단추 클릭이 영상 초점을 가져감'
    expect(screenshot('button-on'), 'button-on', bottom='band', top='band')
    assert window.player._player.sub_align_y == 'bottom', '위·아래 영역이면 받아쓰기 자막은 그대로'

    # 위 영역 줄이 끝난 뒤(40초): 위 영역은 원래 그림(파란 바탕), 아래 영역만 띠.
    window.player.seek_to(40)
    wait(lambda: abs(core.playback.position - 40) < 0.5, '40초로 이동')
    expect(screenshot('no-line-region'), 'no-line-region', bottom='band', top='video')

    press(0xDE)  # ': 전체 화면
    wait(window.isFullScreen, '전체 화면')
    settle(800)
    image = screenshot('fullscreen')
    result['fullscreen_size'] = [image.width(), image.height()]
    assert image.width() > 1100, '전체 화면 크기의 스크린샷이 아님'
    expect(image, 'fullscreen', bottom='band', top='video')
    press(0x1B)  # Esc: 전체 화면 끄기
    wait(lambda: not window.isFullScreen(), '전체 화면 끄기')
    settle(800)
    expect(screenshot('window-again'), 'window-again', bottom='band', top='video')

    # 끈 채로 목록에 돌아갔다가 다시 틀면 켬으로 시작하고, 띠는 새 엔진의 영역 자리에만 있다.
    press(0xDD)
    wait(lambda: not page.onscreen_button.isChecked(), '] 키로 끄기')
    old = window.player
    press(0x1B)  # Esc: 목록
    wait(lambda: core.playback.session is None, '목록 복귀')
    wait(lambda: not window.web_host.return_pending and window.pages.currentWidget() is window.web_host, '웹 복귀')
    window.play(video_id)
    wait(lambda: window.player is not None and window.player is not old and core.playback.position > 1, '다시 재생')
    assert page.onscreen_button.isChecked(), '목록 왕복 뒤 켬으로 시작'
    window.player.seek_to(10)
    wait(lambda: abs(core.playback.position - 10) < 0.5, '10초로 이동')
    press(0x0D)
    wait(lambda: window.player.paused, '일시정지')
    expect(screenshot('after-list-round-trip'), 'after-list-round-trip', bottom='band', top='band')
    press(0xDD)
    wait(lambda: not page.onscreen_button.isChecked(), '] 키로 끄기')
    expect(screenshot('after-list-round-trip-off'), 'after-list-round-trip-off', bottom='white', top='white')

    # 띠 글자 배치: 짧은 줄·긴 줄·여러 줄·영역 여럿을 어댑터로 직접 그려 찍는다(판정은 띠 자리 화소, 글자는 눈으로).
    middle, corner = RegionRect(0.3, 0.42, 0.4, 0.12), RegionRect(0.7, 0.05, 0.25, 0.08)
    variants = {
        'text-short': (OnScreenBand(BOTTOM, '네'),),
        'text-long': (OnScreenBand(BOTTOM, '아주 길게 이어지는 화면 번역 자막 줄이 영역 폭을 넘으면 글자를 줄여 띠 안에 둡니다'),),
        'text-multiline': (OnScreenBand(BOTTOM, '첫째 줄입니다\n둘째 줄입니다'),),
        'text-many-regions': (OnScreenBand(BOTTOM, '아래 영역'), OnScreenBand(TOP, '위'),
                              OnScreenBand(middle, '가운데 영역'), OnScreenBand(corner, 'Corner')),
    }
    for name, bands in variants.items():
        window.player.show_onscreen_translation(bands)
        image = screenshot(name)
        for band in bands:
            assert {kind(color) for color in samples(image, band.rect)} == {'band'}, (name, band.text)
        result['passed'].append(name)
    window.player.clear_onscreen_translation()
    window.tray.quit()


def main():
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    directory = Path(tempfile.mkdtemp(prefix='onscreen-playback-'))
    result = {'mode': 'offscreen' if args.offscreen else 'real', 'passed': [], 'images': []}
    try:
        (offscreen if args.offscreen else real)(app, directory, result)
    finally:
        path = args.output / f'{result["mode"]}-result.json'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        settle()
        shutil.rmtree(directory, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
