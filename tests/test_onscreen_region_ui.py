"""재생 작업 메뉴의 화면 자막 영역 정하기: 가짜 플레이어 위 끌기 입력, 웹 업무 대화상자, 긴급 탈출."""
from datetime import datetime, timezone
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.adapters import VideoFrame
from my_video_manager.core import AppCore
from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_emergency_hide_ui import Player, emergency_key, key
from test_onscreen_subtitles import FakeMedia, FakeOcr
from test_web_dialogs import state


class FramePlayer(Player):
    """mpv처럼 지금 장면(16:9, bgr0)을 돌려준다."""

    def __init__(self, surface):
        super().__init__(surface)
        self.frames = 0

    def video_frame(self):
        self.frames += 1
        return VideoFrame(160, 90, 640, bytes(range(256)) * 225)


class Transcriber:
    def __init__(self, language):
        self.language = language

    def transcribe(self, path, spoken_language, *, cancellation, progress=None):
        return TranscriberResult(self.language, (TranscriptSegment(1, 2, "말"),), model="test")


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


def open_window(tmp_path, monkeypatch, spoken=None):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc), ocr_engine=FakeOcr(),
                   transcriber=Transcriber(spoken) if spoken else None, database=tmp_path / "data/library.sqlite3")
    path = tmp_path / "예능 01화.mkv"
    path.write_bytes(b"episode")
    core.add_file(path)
    if spoken:
        core.request_subtitles(core.videos()[0].id)
        core.process_next_subtitle()
    window = MainWindow(core, player_factory=FramePlayer)
    window.loaded = []
    window.web_host.frontend_loaded.connect(lambda: window.loaded.append(True))
    window.balloons = []
    monkeypatch.setattr(window.tray.icon, "showMessage", lambda *args: window.balloons.append(args))
    # 화면 자막 작업자는 각 테스트에서 직접 확인한다.
    window.onscreen_subtitles.timer.stop()
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    return window


@pytest.fixture
def window(tmp_path, app, monkeypatch):
    window = open_window(tmp_path, monkeypatch)
    yield window
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def start(window):
    """재생을 시작하고 재생 작업 메뉴의 '화면 자막 영역 정하기'를 고른다."""
    wait_for(lambda: window.loaded)
    video = window.core.videos()[0]
    window.play(video.id)
    window.player.advance(20)
    window.sync_position()
    page = window.playback_page
    action, = (action for action in page.menu.actions() if action.text() == "화면 자막 영역 정하기")
    action.trigger()
    QApplication.processEvents()
    return video, page.region_selector


def point(selector, x, y):
    frame = selector.video_rect()
    return QPoint(round(frame.x() + x * frame.width()), round(frame.y() + y * frame.height()))


def drag(selector, start, end):
    QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=point(selector, *start))
    QTest.mouseMove(selector, point(selector, *end))
    QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=point(selector, *end))


def with_dialog(window, callback):
    """끌기를 마치면 열리는 대화상자 안에서 callback을 실행한다. 웹 화면의 버튼과 같은 브리지 명령을 쓴다."""
    dialogs, errors = window.web_host.dialogs, []

    def run():
        try:
            wait_for(lambda: dialogs.active)
            callback(dialogs)
        except BaseException as error:
            errors.append(error)
        finally:
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(0, run)
    wait_for(lambda: window.playback_page.region_selector is None)
    # 재생 화면에서 연 대화상자를 옮기는 JS 응답이 창을 닫은 뒤에 오지 않게 한 번 왕복해 둔다.
    replies = []
    window.web_host.engine_page.runJavaScript('1', replies.append)
    wait_for(lambda: replies)
    if errors:
        raise errors[0]


def act(dialogs, action, **payload):
    return json.loads(dialogs.bridge.act(state(dialogs)["id"], action, json.dumps(payload)))


def test_drag_on_paused_frame_saves_ratio_region_and_queues_on_confirm(window):
    video, selector = start(window)
    player = window.player
    assert player.paused and player.frames == 1
    assert selector.isVisible() and selector.image is not None and selector.aspect == pytest.approx(16 / 9)
    seen, tolerance = {}, 1 / selector.video_rect().height()

    def confirm(dialogs):
        seen.update(state(dialogs))
        assert "error" not in act(dialogs, "save", choice="en")
        assert not dialogs.active
    drag(selector, (0.1, 0.75), (0.9, 0.95))
    with_dialog(window, confirm)
    assert seen["kind"] == "onscreen-region" and seen["values"]["choice"] == ""
    assert seen["choices"][0] == dict(id="", title="읽을 언어 고르기", detail="", status="", start=0, end=None)
    assert "ko" not in {row["id"] for row in seen["choices"]}
    assert "가로 10%–90%, 세로 75%–95%" in seen["description"]
    region, = window.core.onscreen_subtitle_regions(video.id)
    assert (region.rect.x, region.rect.y, region.rect.width, region.rect.height) == pytest.approx(
        (0.1, 0.75, 0.8, 0.2), abs=tolerance)
    assert region.language == "en"
    assert [e.state for e in window.core.subtitle_queue(kind=ONSCREEN_SUBTITLE)] == ["queued"]
    assert "화면 자막 만들기를 추가했습니다" in window.statusBar().currentMessage()
    assert player.paused  # 정한 뒤에도 사용자가 다시 재생하기 전까지 멈춘 장면 그대로다.


def test_cancel_in_dialog_saves_nothing(window):
    video, selector = start(window)
    drag(selector, (0.2, 0.1), (0.6, 0.3))
    with_dialog(window, lambda dialogs: act(dialogs, "close", accepted=False))
    assert window.core.onscreen_subtitle_regions(video.id) == ()
    assert window.core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()


def test_missing_language_pack_shows_warning_and_keeps_dialog_open(window):
    video, selector = start(window)

    def choose_missing_pack(dialogs):
        result = act(dialogs, "save", choice="ja")
        assert "error" not in result
        assert dialogs.active
        assert "일본어(ja)의 언어 팩이 없어" in result["dialog"]["warning"]
        assert "ja 언어 팩을 설치하세요" in result["dialog"]["warning"]
        assert window.core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()
    drag(selector, (0.1, 0.75), (0.9, 0.95))
    with_dialog(window, choose_missing_pack)
    assert window.core.onscreen_subtitle_regions(video.id) == ()


@pytest.mark.parametrize("spoken,default", [("ja", "ja"), ("en", "en"), ("zh", "zh-Hans"), ("ko", "")])
def test_read_language_defaults_to_spoken_language_unless_korean(tmp_path, app, monkeypatch, spoken, default):
    window = open_window(tmp_path, monkeypatch, spoken=spoken)
    try:
        _, selector = start(window)
        seen = {}
        drag(selector, (0.1, 0.75), (0.9, 0.95))
        with_dialog(window, lambda dialogs: seen.update(state(dialogs)))
        assert seen["values"]["choice"] == default
        assert ("직접 고르세요" in seen["description"]) is (not default)
    finally:
        window.tray.quit()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_escape_and_tiny_drag_do_not_open_dialog_and_playback_keys_wait(window):
    video, selector = start(window)
    position = window.player.position
    key(window, Qt.Key.Key_Right)  # 정하는 동안 재생 키는 장면을 바꾸지 않는다.
    assert window.player.position == position and window.playback_page.region_selector is selector
    drag(selector, (0.5, 0.5), (0.505, 0.505))
    QApplication.processEvents()
    assert not window.web_host.dialogs.active and "너무 작습니다" in selector.hint
    key(window, Qt.Key.Key_Escape)
    assert window.playback_page.region_selector is None
    assert window.core.playback.session is not None  # Esc는 영역 정하기만 끝낸다.
    assert window.core.onscreen_subtitle_regions(video.id) == ()


def test_mouse_playback_controls_wait_while_selecting_and_work_after(window):
    from my_video_manager.core import Command, CommandType
    core, page = window.core, window.playback_page
    video, selector = start(window)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))  # 20초 지점
    highlight, = core.highlights(video.id)
    player = window.player
    player.seek_to(60)
    window.sync_position()
    position = player.position
    # 덮개 밖의 재생 단추·진행 막대·하이라이트 목록은 정하는 동안 장면을 바꾸지 않는다.
    QTest.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    page.progress.seek_requested.emit(90.0)
    page.highlights_panel.activated.emit(highlight)
    QApplication.processEvents()
    assert player.paused and player.position == position
    assert page.region_selector is selector
    key(window, Qt.Key.Key_Escape)
    assert page.region_selector is None
    page.progress.seek_requested.emit(90.0)
    assert player.position == 90
    page.highlights_panel.activated.emit(highlight)
    # 하이라이트 이동은 그 장면부터 다시 재생한다(기존 동작).
    assert player.position == highlight.start and not player.paused
    QTest.mouseClick(page.pause_button, Qt.MouseButton.LeftButton)
    assert player.paused


def test_leaving_playback_closes_the_selector(window):
    start(window)
    window.back_to_list()
    wait_for(lambda: window.core.playback.session is None)
    assert window.playback_page.region_selector is None


def test_emergency_hide_while_drawing_returns_to_the_same_selection(window):
    video, selector = start(window)
    player = window.player
    emergency_key(window)
    assert not window.isVisible() and player.paused
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.pages.currentWidget() is window.playback_page
    assert window.playback_page.region_selector is selector and selector.isVisible()
    assert window.focusWidget() is selector
    drag(selector, (0.1, 0.75), (0.9, 0.95))
    with_dialog(window, lambda dialogs: act(dialogs, "save", choice="en"))
    assert window.core.onscreen_subtitle_regions(video.id)[0].language == "en"


def test_emergency_hide_with_language_dialog_open_returns_to_the_dialog(window):
    video, selector = start(window)

    def hide_and_return(dialogs):
        identifier = state(dialogs)["id"]
        emergency_key(window)
        assert not window.isVisible() and dialogs.active
        window.tray.open()
        QApplication.processEvents()
        assert window.isVisible() and dialogs.active and state(dialogs)["id"] == identifier
        assert window.playback_page.region_selector is selector and selector.isVisible()
        assert "error" not in act(dialogs, "save", choice="en")
    drag(selector, (0.1, 0.75), (0.9, 0.95))
    with_dialog(window, hide_and_return)
    assert [e.state for e in window.core.subtitle_queue(kind=ONSCREEN_SUBTITLE)] == ["queued"]
    assert window.core.onscreen_subtitle_regions(video.id)[0].language == "en"
