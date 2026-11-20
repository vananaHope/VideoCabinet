"""#242: 무작위 이어 재생 범위 고르기 창 offscreen 검사.

python scripts/check_web_random_scope.py --offscreen
MVM_REAL_WINDOW_TESTS=1 python ~/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- \
    .venv/Scripts/python.exe scripts/check_web_random_scope.py --real --library <영상 폴더>

가짜 플레이어로 재생하며 조작 줄의 범위 이름 단추로 범위 고르기 창(웹 대화상자)을 열고,
1100×720 창 가운데에 놓은 대화상자 grab 이미지를 남긴다. 데이터 개수별 배치를 본다.
- 태그 많음·긴 태그 이름, 큰 시작 목록(현재 결과 1200편)에서 태그 고르기와 후보 수
- 태그 0개 라이브러리와 후보가 0인 시작 목록(고를 수 없는 범위와 이유)
- 고른 태그의 후보가 0이면 확인할 수 없음
- 영상 전체를 고르면 지금 영상은 그대로이고 범위만 바뀜(다음 영상부터 적용)
--real은 desktop_lock 안에서 실제 mpv로 무작위 재생 키로 시작 → 🔀 켜짐·범위 이름 → 범위 고르기 창
(창 모드·전체 화면) → 영상 끝에서 새 범위의 영상으로 넘어가는지, 🔀를 끄면 영상 끝에서 멈추는지 본다.
이어서 범위 창 열고 닫기 → 목록으로 → 목록에서 직접 재생(🔀 꺼짐·범위 이름 없음) → 무작위 재생 키를 다시 본다.
화면 캡처는 하지 않으며 4분 뒤 스스로 끝낸다.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--real', action='store_true')
parser.add_argument('--library', type=Path)
parser.add_argument('--output', type=Path, default=Path('.local/issue-242'))
args = parser.parse_args()
if args.real and (os.environ.get('MVM_REAL_WINDOW_TESTS') != '1' or args.library is None):
    parser.error('실창은 desktop_lock 안에서 MVM_REAL_WINDOW_TESTS=1, --library로 실행하세요.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
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
if args.offscreen:
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
      .find(e => e.querySelector('.text-body-strong')?.textContent === {json.dumps(title)});
      label.querySelector('[role=radio]').click(); }})()""")
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


def real(root):
    """실제 mpv와 실창. 짧은 영상 셋 중 하나에만 태그를 붙여, 범위를 그 태그로 바꾸면 다음 영상이 정해지게 한다."""
    import threading
    from my_video_manager.adapters import FFmpegMediaReader, MpvPlayer
    # 멈춰도 데스크톱 잠금을 오래 잡지 않게 스스로 끝낸다.
    watchdog = threading.Timer(240, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    media = FFmpegMediaReader()
    core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc),
                   database=root / 'data/library.sqlite3', random_choice=min)
    core.set_automatic_detection_enabled(False)
    core.set_automatic_update_check_enabled(False)
    core.set_minimum_duration(0)
    paths = [p for p in args.library.rglob('*') if p.suffix.lower() in ('.mkv', '.mp4', '.webm')]
    for duration, name in sorted((media.read(p).duration, str(p)) for p in paths)[:3]:
        core.add_file(Path(name))
    assert len(core.videos()) == 3
    evidence['media'] = [{'path': str(v.locations[0].path), 'duration': v.duration} for v in core.videos()]
    window = MainWindow(core, player_factory=MpvPlayer)
    window.resize(1100, 720)
    loaded = []
    window.web_host.frontend_loaded.connect(lambda: loaded.append(True))
    page, dialogs = window.playback_page, window.web_host.dialogs
    try:
        window.show()
        window.activateWindow()
        wait(lambda: loaded)
        wait(window.isActiveWindow)
        QTest.keyClick(window.web_host.view, Qt.Key.Key_R,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        wait(lambda: core.playback.session is not None and core.playback.position > 0)
        first = core.playback.session.video_id
        wait(lambda: page.random_button.isChecked() and page.random_scope_button.isVisible())
        assert page.random_scope_button.text() == '전체', page.random_scope_button.text()
        evidence['checks'].append('Ctrl+Shift+R: 🔀 켜짐·범위 이름 전체')
        target = next(v.id for v in core.videos() if v.id != first)
        tag = core.add_video_tag(target, '실창 범위')

        def choose_tag():
            assert dialogs.container is not None and dialogs.container.isVisible()
            click_radio(window, '태그 고르기')
            js(window, f"""Array.from(document.querySelectorAll('[role=option]'))
              .find(e => e.textContent.startsWith({json.dumps(tag.name)})).click()""")
            settle()
            assert js(window, "document.querySelector('[role=dialog] [role=status]')?.textContent") == '후보 1개'
            js(window, "Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === '확인').click()")
            wait(lambda: not dialogs.active)
        scope_dialog(window, choose_tag)
        assert core.random_continuous_scope == RandomPlayScope('tags', tag_ids=(tag.id,))
        assert core.playback.session.video_id == first
        wait(lambda: page.random_scope_button.text() == '태그: 실창 범위')
        evidence['checks'].append('창 모드 범위 고르기: 태그로 바꿔도 지금 영상 유지')

        window.set_playback_fullscreen(True)
        wait(window.isFullScreen)
        page.reveal_bar()

        def fullscreen_cancel():
            wait(lambda: dialogs.container is not None and dialogs.container.isVisible())
            wait(lambda: QApplication.activeWindow() is dialogs.container)
            evidence['fullscreen_dialog'] = [dialogs.container.width(), dialogs.container.height()]
            js(window, "Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === '취소').click()")
            wait(lambda: not dialogs.active)
        scope_dialog(window, fullscreen_cancel)
        assert window.isFullScreen() and core.random_continuous_scope.kind == 'tags'
        evidence['checks'].append('전체 화면 범위 고르기 창: 위에 뜨고 활성, 취소하면 범위·전체 화면 유지')

        page.seek(core.video(first).duration - 1)
        wait(lambda: core.playback.session.video_id != first, seconds=20)
        assert core.playback.session.video_id == target
        evidence['checks'].append('영상 끝: 새 범위(태그)의 영상으로 넘어감')

        wait(lambda: core.playback.position > 0)
        page.random_button.click()
        assert not core.random_continuous_enabled and not page.random_button.isChecked()
        session = core.playback.session
        page.seek(core.video(target).duration - 1)
        settle(4000)
        assert core.playback.session is session
        evidence['checks'].append('🔀 끄기: 영상 끝에서 멈춤')
        window.set_playback_fullscreen(False)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: core.playback.session is None)
        real_return(window)
    finally:
        close(window)


def real_return(window):
    """무작위 재생 → 범위 창 열고 닫기 → 목록으로 → 직접 재생 → 무작위 재생. 이전 범위·켜짐이 남지 않는다."""
    core, page, dialogs = window.core, window.playback_page, window.web_host.dialogs
    wait(lambda: window.pages.currentWidget() is window.web_host and not window.web_host.return_pending)
    window.activateWindow()
    wait(window.isActiveWindow)
    QTest.keyClick(window.web_host.view, Qt.Key.Key_R,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait(lambda: core.playback.session is not None and core.playback.position > 0)
    wait(lambda: page.random_button.isChecked() and page.random_scope_button.text() == '전체')

    def cancel():
        wait(lambda: dialogs.container is not None and dialogs.container.isVisible())
        js(window, "Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === '취소').click()")
        wait(lambda: not dialogs.active)
    scope_dialog(window, cancel)
    assert dialogs.container is None and core.random_continuous_enabled
    page.back_button.click()
    wait(lambda: core.playback.session is None and window.pages.currentWidget() is window.web_host
         and not window.web_host.return_pending)
    assert not dialogs.active and dialogs.container is None
    evidence['checks'].append('복귀: 무작위 재생 → 범위 창 열고 닫기 → 목록으로, 대화상자 컨테이너 없음')
    video_id = window.library_page.visible_video_ids()[0]
    assert json.loads(window.library_page.bridge.action('play', video_id)) == {'ok': True}
    wait(lambda: core.playback.session is not None and core.playback.position > 0)
    window.sync_position()
    assert not core.random_continuous_enabled and not page.random_button.isChecked()
    assert not page.random_scope_button.isVisible()
    evidence['checks'].append('복귀 뒤 목록에서 직접 재생: 🔀 꺼짐·범위 이름 없음')
    page.back_button.click()
    wait(lambda: core.playback.session is None and not window.web_host.return_pending)
    window.activateWindow()
    wait(window.isActiveWindow)
    QTest.keyClick(window.web_host.view, Qt.Key.Key_R,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait(lambda: core.playback.session is not None and core.playback.position > 0)
    wait(lambda: page.random_button.isChecked() and page.random_scope_button.text() == '전체')
    evidence['checks'].append('다시 Ctrl+Shift+R: 🔀 켜짐·범위 이름 전체')
    page.back_button.click()
    wait(lambda: core.playback.session is None)


with tempfile.TemporaryDirectory(prefix='check-', dir=args.output) as temporary:
    if args.real:
        real(Path(temporary))
    else:
        for index, scenario in enumerate((many_tags, no_tags, empty_tags)):
            directory = Path(temporary) / str(index)
            directory.mkdir()
            scenario(directory)
(args.output / 'random-scope-result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False))
