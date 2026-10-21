"""#242: 무작위 이어 재생 범위 고르기 창 offscreen 검사.

python scripts/check_web_random_scope.py --offscreen

가짜 플레이어로 재생하며 조작 줄의 범위 이름 단추로 범위 고르기 창(웹 대화상자)을 열고,
1100×720 창 가운데에 놓은 대화상자 grab 이미지를 남긴다. 데이터 개수별 배치를 본다.
- 태그 많음·긴 태그 이름, 큰 시작 목록(현재 결과 1200편)에서 태그 고르기와 후보 수
- 태그 0개 라이브러리와 후보가 0인 시작 목록(고를 수 없는 범위와 이유)
- 고른 태그의 후보가 0이면 확인할 수 없음
- 영상 전체를 고르면 지금 영상은 그대로이고 범위만 바뀜(다음 영상부터 적용)
실창 확인(전체 화면 포함, 영상 끝에서 새 범위)은 desktop_lock 안에서 사람이 하거나 별도 검사로 한다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--offscreen', action='store_true', required=True)
parser.add_argument('--output', type=Path, default=Path('.local/issue-242'))
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.random_continuous_play import RandomPlayScope
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        self.paused = False

    def play(self, path, start, *, subtitle):
        pass

    def take_positions(self):
        return ()

    def take_eof(self):
        return False

    def close(self):
        pass


args.output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
for name in ('malgun.ttf', 'malgunbd.ttf', 'segoeui.ttf', 'seguisym.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
evidence = {'checks': [], 'screens': []}


def settle(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('조건 대기 시간 초과')
        app.processEvents()
        QTest.qWait(20)


def build(root, *, count, tags):
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=root / 'data/library.sqlite3', random_choice=min)
    core.set_automatic_detection_enabled(False)
    core.set_automatic_update_check_enabled(False)
    core.set_minimum_duration(0)
    for index in range(count):
        path = root / f'영상 {index:04}.mkv'
        path.write_bytes(index.to_bytes(4, 'big'))
        core.add_file(path)
    videos = core.videos()
    for index, name in enumerate(tags):
        core.add_video_tag(videos[index % len(videos)].id, name)
    window = MainWindow(core, player_factory=Player)
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    window.resize(1100, 720)
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    window.show()
    wait(lambda: loaded)
    return core, window


def close(window):
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def js(window, code):
    result = []
    window.web_host.engine_page.runJavaScript(code, result.append)
    wait(lambda: bool(result))
    return result[0]


def capture(window, name):
    """재생 중 대화상자는 창 밖 컨테이너에 뜬다. 1100×720 창 크기 바탕 가운데에 놓아 저장한다."""
    dialogs = window.web_host.dialogs
    wait(lambda: dialogs.container is not None)
    settle(400)
    captured = dialogs.container.grab()
    assert captured.width() <= 1100 and captured.height() <= 720, (captured.width(), captured.height())
    canvas = QImage(1100, 720, QImage.Format.Format_RGB32)
    canvas.fill(window.palette().window().color())
    painter = QPainter(canvas)
    painter.drawPixmap((1100 - captured.width()) // 2, (720 - captured.height()) // 2, captured)
    painter.end()
    path = args.output / f'random-scope-{name}.png'
    assert canvas.save(str(path))
    evidence['screens'].append(str(path.resolve()))


def state(window):
    return json.loads(window.web_host.dialogs.bridge.snapshot())['dialog']


def scope_dialog(window, scenario):
    """범위 이름 단추로 창을 열고 scenario를 실행한다. 창은 scenario가 닫지 않았으면 닫는다."""
    dialogs = window.web_host.dialogs
    failures = []

    def run():
        try:
            wait(lambda: js(window, "!!document.querySelector('[data-dialog-body=\"random-scope\"]')"))
            scenario()
        except BaseException as error:
            failures.append(error)
        finally:
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(0, run)
    window.playback_page.random_scope_button.click()
    settle()
    if failures:
        raise failures[0]


def click_radio(window, title):
    js(window, f"""(() => {{ const label = Array.from(document.querySelectorAll('[role=radiogroup] label'))
      .find(e => e.querySelector('.font-medium')?.textContent === {json.dumps(title)});
      label.querySelector('input').click(); }})()""")
    settle()


def confirm_enabled(window):
    return js(window, "!Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === '확인').disabled")


def many_tags(root):
    """태그 많음·긴 태그 이름·큰 시작 목록. 태그 범위로 시작해 고르기 화면과 후보 수를 본다."""
    long_names = [('아주아주긴태그이름이들어간음악영상모음집' * 3)[:50], ('공백 없는 긴 영어 이름 SuperLongTagNameWithoutSpaces' * 2)[:50]]
    names = long_names + [f'태그 {index:02}' for index in range(60)]
    core, window = build(root, count=1200, tags=names)
    try:
        page = window.playback_page
        listed = window.library_page.visible_video_ids()
        tags = {tag.name: tag.id for tag in core.tags()}
        window.play(listed[0], random_scope=RandomPlayScope('tags', tag_ids=(tags[long_names[0]], tags['태그 01'])))
        wait(lambda: core.playback.session is not None)
        window.sync_position()
        assert page.random_button.isChecked() and page.random_scope_button.isVisible()
        assert page.random_scope_button.label == '태그: 아주아주긴태그… 외 1', page.random_scope_button.label

        def scenario():
            data = state(window)
            assert data['values']['choice'] == 'tags'
            assert data['choices'][1]['detail'] == '현재 결과 1200편 · 후보 1200개', data['choices'][1]
            assert js(window, "document.querySelector('[role=dialog] [role=status]')?.textContent") == '후보 2개'
            capture(window, 'many-tags')
            # 목록 전체 보기(태그 행 목록)와 긴 이름 줄임을 본다.
            js(window, "Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent.startsWith('모두 보기'))?.click()")
            settle()
            capture(window, 'many-tags-all')
            click_radio(window, '재생을 시작한 목록')
            assert confirm_enabled(window)
            capture(window, 'large-list')
        scope_dialog(window, scenario)
        evidence['checks'].append('태그 62개·긴 태그 이름·시작 목록 1200편: 태그 고르기와 후보 수, 시작 목록 고르기')
    finally:
        close(window)


def no_tags(root):
    """태그 0개 라이브러리와 후보 0인 시작 목록. 고를 수 없는 범위는 이유를 보이고 확인할 수 없다."""
    core, window = build(root, count=3, tags=[])
    try:
        page = window.playback_page
        videos = core.videos()
        window.play_random_video(videos[0].id)
        wait(lambda: core.playback.session is not None)
        # 재생을 시작한 목록을 지금 영상 하나로 두고 그 영상을 제외해 후보 0인 시작 목록을 만든다.
        window.set_playback_list((videos[1].id,), '검색 결과')
        window.play_video(videos[1].id, new_playback=True)
        core.set_random_continuous_enabled(True)
        core.exclude_video(videos[1].id)
        window.sync_position()
        assert page.random_scope_button.label == '검색 결과 1편', page.random_scope_button.label

        def scenario():
            data = state(window)
            statuses = {row['id']: row['status'] for row in data['choices']}
            assert statuses == {'all': '', 'list': '후보가 없어 고를 수 없습니다.', 'tags': '후보가 없어 고를 수 없습니다.'}, statuses
            assert data['values']['choice'] == 'list'
            assert not confirm_enabled(window)
            capture(window, 'no-tags-empty-list')
            click_radio(window, '영상 전체')
            assert confirm_enabled(window)
            # 화면 우회로 후보 0인 범위를 보내도 코어가 다시 세어 거절한다.
            result = json.loads(window.web_host.dialogs.bridge.act(data['id'], 'save', json.dumps({'choice': 'list', 'members': []})))
            assert '재생할 수 있는 영상이 없습니다' in result['error'], result
            session = core.playback.session
            js(window, "Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === '확인').click()")
            wait(lambda: not window.web_host.dialogs.active)
            assert core.random_continuous_scope == RandomPlayScope() and core.playback.session is session
        scope_dialog(window, scenario)
        window.sync_position()
        assert page.random_scope_button.label == '전체'
        evidence['checks'].append('태그 0개·후보 0 시작 목록: 이유 표시·확인 막기, 영상 전체로 바꾸면 지금 영상 유지')
    finally:
        close(window)


def empty_tags(root):
    """고른 태그의 후보가 0이면 확인할 수 없다."""
    core, window = build(root, count=2, tags=['제외한 영상 태그', '남은 영상 태그'])
    try:
        videos = core.videos()
        excluded = next(tag for tag in core.tags() if tag.name == '제외한 영상 태그')
        core.exclude_video(next(v.id for v in videos if excluded in core.video_tags(v.id)))
        window.play(core.videos()[0].id)
        wait(lambda: core.playback.session is not None)
        window.playback_page.random_button.click()
        assert core.random_continuous_enabled

        def scenario():
            click_radio(window, '태그 고르기')
            js(window, """Array.from(document.querySelectorAll('[role=option]'))
              .find(e => e.textContent.startsWith('제외한 영상 태그')).click()""")
            settle()
            assert js(window, "document.querySelector('[role=dialog] [role=status]')?.textContent").startswith('후보 0개')
            assert not confirm_enabled(window)
            capture(window, 'tag-zero-candidates')
        scope_dialog(window, scenario)
        evidence['checks'].append('후보 0인 태그: 확인 막기와 이유')
    finally:
        close(window)


with tempfile.TemporaryDirectory(prefix='check-', dir=args.output) as temporary:
    for index, scenario in enumerate((many_tags, no_tags, empty_tags)):
        directory = Path(temporary) / str(index)
        directory.mkdir()
        scenario(directory)
(args.output / 'random-scope-result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False))
