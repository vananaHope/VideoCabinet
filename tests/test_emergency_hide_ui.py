"""긴급 탈출: 실제 키 입력으로 숨기고 트레이 열기·두 번째 실행으로 같은 화면에 돌아온다."""

from datetime import datetime, timezone
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.single_instance import SingleInstance
from my_video_manager.ui import MainWindow
from qt_wait import wait_for


class Media:
    def read(self, path):
        return MediaInfo(120, "matroska")

    def capture(self, path, destination, seconds):
        pass


class Player:
    """일시정지 중에는 mpv처럼 같은 위치만 보고한다."""

    # 0이 아니면 mpv처럼 탐색 명령·정지 해제 뒤 탐색 완료(seeked) 보고를 이 시간(ms) 뒤에 보낸다.
    seek_report_delay = 0

    def __init__(self, surface):
        self.paused = False
        self.position = 0
        self.positions = []
        self.played = 0
        self.eof = False
        self.options = (1, True)

    def play(self, path, start, *, subtitle):
        self.played += 1
        self.paused = False
        self.position = start

    def advance(self, position):
        self.position = position if not self.paused else self.position
        self.positions.append((self.position, False))

    def pause(self):
        self.paused = True

    def reach_end(self, duration):
        """mpv의 EOF처럼 길이 위치와 끝 신호를 함께 보고한다. 정지 직전에 엔진이 보낸 늦은 보고일 수 있다."""
        self.position = duration
        self.positions.append((duration, False))
        self.eof = True

    def execute(self, command):
        if command.kind == CommandType.TOGGLE_PAUSE:
            self.paused = not self.paused
        elif command.kind == CommandType.SEEK:
            self._seek(self.position + command.amount, resume=False)

    def seek_to(self, position, *, resume=False):
        # mpv 어댑터처럼 절대 탐색 전에 남은 보고와 끝 신호를 버린다.
        self.positions, self.eof = [], False
        self._seek(position, resume=resume)

    def _seek(self, position, *, resume):
        self.position = position
        self.paused = self.paused and not resume

        def report():
            self.positions.append((position, True))
        if self.seek_report_delay:
            QTimer.singleShot(self.seek_report_delay, report)
        else:
            report()

    def playback_options(self):
        return self.options

    def apply_playback_options(self, options):
        self.options = options

    def close(self):
        pass

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        eof, self.eof = self.eof, False
        return eof


class DelayedSeekPlayer(Player):
    seek_report_delay = 200


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


@pytest.fixture
def window(tmp_path, app, monkeypatch):
    yield from open_window(tmp_path, app, monkeypatch)


def open_window(tmp_path, app, monkeypatch, *, transcriber=None, **options):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=transcriber)
    for index in (1, 2):
        path = tmp_path / f"강의 {index:02}강.mkv"
        path.write_bytes(bytes([index]))
        core.add_file(path)
    window = MainWindow(core, player_factory=Player, **options)
    # 웹 셸 첫 로드 완료(공개 신호). 이벤트를 처리하기 전에 연결하므로 놓치지 않는다.
    window.loaded = []
    window.web_host.frontend_loaded.connect(lambda: window.loaded.append(True))
    window.balloons = []
    monkeypatch.setattr(window.tray.icon, "showMessage", lambda *args: window.balloons.append(args))
    window.show()
    window.activateWindow()
    app.processEvents()
    yield window
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def key(window, key, modifiers=Qt.KeyboardModifier.NoModifier):
    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(QApplication.focusWidget() or window, key, modifiers)
    QApplication.processEvents()


def emergency_key(window):
    key(window, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)


def play_to_twenty_seconds(window):
    video = window.core.videos()[0]
    window.play(video.id)
    player = window.player
    for position in (10, 20):
        player.advance(position)
        window.sync_position()
    return video, player


def second_launch(window, core):
    instance = SingleInstance(core.database.parent)
    assert instance.start()
    instance.activated.connect(window.tray.open)
    try:
        assert not SingleInstance(core.database.parent).start()
        wait_for(window.isVisible)
    finally:
        instance.close()
        instance.deleteLater()


@pytest.mark.parametrize("restore", ["tray", "second_launch"])
def test_playback_emergency_hide_returns_to_same_paused_scene(window, restore):
    core = window.core
    video, player = play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()

    emergency_key(window)
    assert not window.isVisible()
    assert not window.isFullScreen()
    assert player.paused
    assert window.balloons == []
    # 숨긴 동안 멈춘 엔진은 같은 위치만 보고하므로 시청 시간이 늘지 않는다.
    for _ in range(3):
        player.advance(90)
        window.sync_position()
    assert core.playback.session.video_id == video.id
    viewing = core.viewings(video.id)[-1]
    assert viewing.ended_at is None and viewing.played_seconds == 20

    if restore == "tray":
        window.tray.open()
    else:
        second_launch(window, core)
    QApplication.processEvents()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.playback_page
    assert not window.isFullScreen()
    assert window.player is player and player.played == 1 and player.paused
    assert core.playback.session.video_id == video.id
    assert core.playback.position == 20
    assert window.balloons == []
    assert QApplication.focusWidget() is window.surface

    # 복귀 뒤 같은 시청이 이어진다.
    key(window, Qt.Key.Key_Return)
    player.advance(30)
    window.sync_position()
    assert core.viewings(video.id)[-1].id == viewing.id
    assert core.viewings(video.id)[-1].played_seconds == 30


def test_emergency_hide_keeps_open_range_and_first_tray_notice(window):
    core = window.core
    play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Delete)
    assert core.open_highlight_start == 20
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    assert core.open_highlight_start == 20
    assert window.balloons == []
    # 첫 트레이 안내는 긴급 탈출에서 소모되지 않고 다음 창 닫기에서 한 번 보인다.
    window.close()
    assert not window.isVisible()
    assert len(window.balloons) == 1 and "트레이에서 계속 처리" in window.balloons[0][1]
    window.tray.open()
    window.close()
    assert len(window.balloons) == 1


@pytest.mark.parametrize("tab", ["library", "search", "statistics", "queue", "folders", "reel", "settings"])
def test_web_tab_emergency_hide_returns_to_same_tab_without_refresh(window, monkeypatch, tab):
    window.navigate_web_tab(tab)
    QApplication.processEvents()
    refreshed = []
    monkeypatch.setattr(window.library_page, "refresh", lambda **kwargs: refreshed.append(kwargs))
    emergency_key(window)
    assert not window.isVisible()
    assert window.balloons == []
    window.tray.open()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == tab
    assert refreshed == []


def test_rebound_emergency_key_hides_and_old_key_does_nothing(window):
    core = window.core
    bindings = {row.command: row.keys for row in core.key_bindings()}
    bindings[Command(CommandType.EMERGENCY_HIDE)] = ("Ctrl+Alt+B",)
    core.save_key_bindings(bindings)
    emergency_key(window)
    assert window.isVisible()
    key(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert not window.isVisible()


def test_subtitle_queue_keeps_processing_after_emergency_hide(tmp_path, app, monkeypatch):
    from test_subtitles import FakeTranscriber
    transcriber = FakeTranscriber()
    opened = open_window(tmp_path, app, monkeypatch, transcriber=transcriber)
    window = next(opened)
    try:
        video = window.core.videos()[0]
        window.core.request_subtitles(video.id)
        emergency_key(window)
        assert not window.isVisible()
        wait_for(lambda: window.core.library_details(video.id).original_lines)
        assert transcriber.calls and not window.isVisible()
    finally:
        opened.close()


def test_maximized_window_returns_maximized_after_fullscreen_emergency_hide(window):
    play_to_twenty_seconds(window)
    window.showMaximized()
    QApplication.processEvents()
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.isMaximized() and not window.isFullScreen()


def late_end_report(player):
    """일시정지 직전에 엔진이 이미 보낸 구간 끝 보고."""
    player.position = 20
    player.positions.append((20, False))


def hide_and_return_at_reel_boundary(window, report_end):
    """구간 끝 직전에 숨기고, 엔진의 늦은 끝 보고를 처리한 뒤 트레이로 돌아온다."""
    player = window.player
    player.advance(window.core.reel_playback.start + 5)
    window.sync_position()
    emergency_key(window)
    assert not window.isVisible() and player.paused
    report_end(player)  # 숨긴 뒤에 엔진이 늦게 보낸 구간 끝·EOF 보고
    QTest.qWait(400)
    assert not window.isVisible()
    assert window.player is player and player.paused
    window.tray.open()
    QTest.qWait(400)
    assert window.isVisible() and window.pages.currentWidget() is window.playback_page
    assert window.player is player and player.paused
    return player


def resume(window):
    key(window, Qt.Key.Key_Return)
    QTest.qWait(400)


@pytest.mark.parametrize("engine", [Player, DelayedSeekPlayer])
def test_reel_next_item_in_same_video_waits_until_user_resumes(window, engine):
    from test_reel import mark
    window.player_factory = engine
    core = window.core
    video = core.videos()[0]
    first = mark(core, video, 10, 20)
    mark(core, video, 40, 50)
    window.reel.start(first.id)
    player = hide_and_return_at_reel_boundary(window, late_end_report)
    # 같은 장면: 첫 항목의 끝에서 멈춰 있고 복습 보고는 반영됐다.
    assert core.reel_playback.entry.highlight.id == first.id
    assert core.playback.position == 20
    assert core.last_highlight_revisited_at(first.id) is not None
    resume(window)
    assert core.reel_playback.start == 40
    assert window.player is player and not player.paused and player.position == 40


@pytest.mark.parametrize("engine", [Player, DelayedSeekPlayer])
def test_reel_next_item_in_other_video_waits_until_user_resumes(window, engine):
    from test_reel import mark
    window.player_factory = engine
    core = window.core
    one, two = core.videos()
    first = mark(core, one, 10, 20)
    mark(core, two, 30, 40)
    window.reel.start(first.id)
    player = hide_and_return_at_reel_boundary(window, late_end_report)
    assert core.reel_playback.video_id == one.id
    assert core.playback.session.video_id == one.id
    resume(window)
    assert core.reel_playback.video_id == two.id
    assert window.player is not player and not window.player.paused and window.player.position == 30


@pytest.mark.parametrize("engine", [Player, DelayedSeekPlayer])
def test_reel_repeat_waits_until_user_resumes(window, engine):
    from test_reel import mark
    window.player_factory = engine
    core = window.core
    video = core.videos()[0]
    first = mark(core, video, 10, 20)
    mark(core, video, 40, 50)
    window.reel.start(first.id)
    key(window, Qt.Key.Key_Backslash)
    assert core.reel_repeat
    player = hide_and_return_at_reel_boundary(window, late_end_report)
    assert player.position == 20 and core.reel_playback.entry.highlight.id == first.id
    resume(window)
    assert core.reel_playback.entry.highlight.id == first.id
    assert not player.paused and player.position == 10


@pytest.mark.parametrize("engine", [Player, DelayedSeekPlayer])
def test_reel_last_item_eof_waits_until_user_resumes(window, engine):
    from test_reel import mark
    window.player_factory = engine
    core = window.core
    video = core.videos()[0]
    last = mark(core, video, 100, 120)
    window.reel.start(last.id)
    hide_and_return_at_reel_boundary(window, lambda player: player.reach_end(120))
    assert core.reel_playback.entry.highlight.id == last.id
    assert window.web_host.active_tab != 'reel' or window.pages.currentWidget() is window.playback_page
    resume(window)
    # 사용자가 재개하면 미룬 EOF로 모아보기를 마치고 목록으로 간다.
    assert core.reel_playback is None
    assert window.pages.currentWidget() is window.web_host and window.web_host.active_tab == 'reel'


@pytest.mark.parametrize("engine", [Player, DelayedSeekPlayer])
def test_seeking_back_before_resume_cancels_held_reel_transition(window, engine):
    from test_reel import mark
    window.player_factory = engine
    core = window.core
    video = core.videos()[0]
    first = mark(core, video, 10, 20)
    mark(core, video, 40, 50)
    window.reel.start(first.id)
    player = hide_and_return_at_reel_boundary(window, late_end_report)
    key(window, Qt.Key.Key_Left)
    assert player.paused and player.position == 15
    resume(window)
    assert core.reel_playback.entry.highlight.id == first.id
    assert not player.paused and player.position == 15


def test_repeated_emergency_hide_keeps_engine_paused(window):
    _, player = play_to_twenty_seconds(window)
    for _ in range(2):
        emergency_key(window)
        assert not window.isVisible() and player.paused
        window.tray.open()
        QTest.qWait(200)
        assert window.isVisible() and player.paused


def held_eof_at_last_item(window, *spans):
    """같은 영상에 구간들을 만들고 마지막 항목 EOF를 보류한 채 숨겼다가 돌아온다."""
    from test_reel import mark
    window.player_factory = DelayedSeekPlayer
    video = window.core.videos()[0]
    highlights = [mark(window.core, video, start, end) for start, end in spans]
    window.reel.start(highlights[-1].id)
    player = hide_and_return_at_reel_boundary(window, lambda player: player.reach_end(120))
    return highlights, player


def test_home_after_held_eof_keeps_the_chosen_previous_item(window):
    (first, last), player = held_eof_at_last_item(window, (10, 20), (100, 120))
    key(window, Qt.Key.Key_Home)
    assert window.core.reel_playback.entry.highlight.id == first.id
    QTest.qWait(600)  # 늦은 탐색 완료 보고와 위치 확인 타이머를 지난다.
    # 이전 항목의 보류 EOF가 사용자가 고른 항목에 적용되지 않는다.
    assert window.core.reel_playback.entry.highlight.id == first.id
    assert window.player is player and player.position == 10 and not player.paused


def test_end_after_held_item_end_keeps_the_chosen_next_item(window):
    from test_reel import mark
    window.player_factory = DelayedSeekPlayer
    video = window.core.videos()[0]
    first = mark(window.core, video, 10, 20)
    second = mark(window.core, video, 40, 50)
    mark(window.core, video, 70, 80)
    window.reel.start(first.id)
    player = hide_and_return_at_reel_boundary(window, late_end_report)
    key(window, Qt.Key.Key_End)
    QTest.qWait(600)
    assert window.core.reel_playback.entry.highlight.id == second.id
    assert player.position == 40 and not player.paused


def test_end_on_last_item_after_held_eof_finishes_the_reel(window):
    held_eof_at_last_item(window, (10, 20), (100, 120))
    key(window, Qt.Key.Key_End)
    QTest.qWait(600)
    assert window.core.reel_playback is None
    assert window.pages.currentWidget() is window.web_host and window.web_host.active_tab == 'reel'


def test_seek_back_after_held_eof_and_immediate_resume_stays_in_item(window):
    (_, last), player = held_eof_at_last_item(window, (10, 20), (100, 120))
    key(window, Qt.Key.Key_Left)
    # 탐색 완료 보고가 오기 전에 바로 재개한다.
    key(window, Qt.Key.Key_Return)
    assert not player.paused
    QTest.qWait(600)
    assert window.core.reel_playback is not None
    assert window.core.reel_playback.entry.highlight.id == last.id
    assert window.pages.currentWidget() is window.playback_page
    assert player.position == 115 and not player.paused
