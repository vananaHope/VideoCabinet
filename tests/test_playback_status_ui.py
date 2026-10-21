"""재생 상태 표시: 키·단추 조작이 바꾼 상태를 플레이어 OSD 문구로 보낸다."""

from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QEvent, Qt

from my_video_manager.core import AppCore
from my_video_manager.playback_page import SPEED_CHOICES
from my_video_manager.ui import MainWindow
from test_playback_page_ui import Player, app, click, key, window
from test_translation import Media, Transcriber, Translator, finish, source


def statuses(window):
    return [text for text, _ in window.player.statuses]


def test_status_lasts_one_and_a_half_seconds(window):
    key(window, Qt.Key.Key_Return)
    assert window.player.statuses == [("⏸ 일시정지", 1.5)]


@pytest.mark.parametrize(("pressed", "button", "expected"), [
    (Qt.Key.Key_Return, "pause_button", ["⏸ 일시정지", "▶ 재생"]),
    (Qt.Key.Key_Slash, "subtitles_button", ["자막 꺼짐", "자막 켜짐"]),
    (Qt.Key.Key_Insert, "point_button", ["◆ 지점 하이라이트 추가"] * 2),
    (Qt.Key.Key_Delete, "range_button", ["【 구간 시작", "】 구간 끝"]),
])
def test_key_and_button_show_same_playback_status(window, pressed, button, expected):
    window.player.positions = [(10, True)]
    key(window, pressed)
    window.player.positions = [(20, False)]
    click(getattr(window.playback_page, button))
    assert statuses(window) == expected


def test_speed_key_and_speed_list_show_new_speed(window):
    key(window, Qt.Key.Key_Up)
    page = window.playback_page
    page.speed_menu.actions()[SPEED_CHOICES.index(0.5)].trigger()
    key(window, Qt.Key.Key_Down)
    assert statuses(window) == ["1.25×", "0.5×", "0.25×"]


def test_reel_repeat_key_shows_on_and_off_only_during_reel(window):
    key(window, Qt.Key.Key_Backslash)
    assert statuses(window) == []
    core = window.core
    for video in core.videos():
        core.switch_to(video.id)
        core.playback.report(10)
        core.execute_highlight_command(core.command_for_key("Insert"))
    window.reel.open()
    window.reel.start()
    window.sync_position()
    key(window, Qt.Key.Key_Backslash)
    key(window, Qt.Key.Key_Backslash)
    assert statuses(window) == ["모아보기 반복 켜짐", "모아보기 반복 꺼짐"]


def test_seek_and_video_moves_have_no_playback_status(window):
    key(window, Qt.Key.Key_Right)
    key(window, Qt.Key.Key_Home)
    key(window, Qt.Key.Key_PageDown)
    assert statuses(window) == []


def test_unavailable_subtitle_language_shows_notice_instead_of_status(window):
    page = window.playback_page
    key(window, Qt.Key.Key_Period)
    click(page.subtitle_language_button)
    assert statuses(window) == []
    assert "아직 없습니다" in page.message_label.text()


class SubtitlePlayer(Player):
    def set_subtitle(self, path):
        self.subtitle = path


@pytest.fixture
def translated_window(tmp_path, app):
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3",
                   transcriber=Transcriber(), translator=Translator())
    path = tmp_path / "lecture.mkv"
    path.write_text("lecture")
    core.add_file(path)
    video_id = core.videos()[0].id
    source(core, video_id)
    core.process_next_translation()
    finish(core)
    window = MainWindow(core, player_factory=SubtitlePlayer)
    window.show()
    window.activateWindow()
    app.processEvents()
    window.play(video_id)
    window.sync_position()
    app.processEvents()
    yield window
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_subtitle_language_key_and_button_show_chosen_language(translated_window):
    window = translated_window
    window.statusBar().clearMessage()
    key(window, Qt.Key.Key_Period)
    click(window.playback_page.subtitle_language_button)
    assert statuses(window) == ["번역 자막", "원어 자막"]
    # 바뀐 자막 종류는 재생 상태 표시로만 보이고 안내 줄에는 남지 않는다.
    assert not window.playback_page.message_label.isVisible()
