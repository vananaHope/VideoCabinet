"""트레이 복귀와 모아보기 전환에서 목록에 드러나는 회귀만 검증한다."""

from datetime import datetime, timezone
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        picture = QPixmap(320, 180)
        picture.fill(QColor("#405060"))
        picture.save(str(destination), "JPG")


class Player:
    def __init__(self, surface):
        self.positions = []

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        pass

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        return False


@pytest.fixture(scope="module")
def app(qapp):
    return qapp


@pytest.fixture
def library_window(tmp_path, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3")
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    core.playback.start(video.id, 0)
    core.playback.report(40)
    core.playback.end()
    window = MainWindow(core, player_factory=Player)
    window.show()
    app.processEvents()
    yield window, core, video
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_tray_reopen_updates_finished_viewing_without_refreshing_while_hidden(library_window, app):
    window, core, video = library_window
    assert window.library_page.snapshot.statuses[video.id].abandoned
    assert len(window.library_page.gems) == 1
    window.play_video(video.id, start=0, from_gems=True)
    # 마지막 엔진 보고를 닫기 경로에서 받아 시청을 저장한다.
    window.player.positions.append((95, False))
    window.close()
    app.processEvents()
    assert not window.isVisible()
    assert core.viewing_status(video.id).finished
    assert window.library_page.snapshot.statuses[video.id].abandoned
    assert len(window.library_page.gems) == 1

    window.tray.open()
    app.processEvents()
    assert window.isVisible()
    assert window.library_page.snapshot.statuses[video.id].finished
    assert len(window.library_page.gems) == 0
    assert window.web_host._pending_focus == 'grid' or window.web_host.view.hasFocus()


def test_tray_open_of_visible_playback_does_not_end_viewing(library_window):
    window, core, video = library_window
    window.play_video(video.id)
    window.tray.open()
    assert core.playback.session.video_id == video.id
    assert window.pages.currentIndex() == 1


def test_tray_queue_during_playback_finishes_viewing(library_window):
    window, core, video = library_window
    window.play_video(video.id)
    window.tray.show_queue()
    assert core.playback.session is None
    assert window.web_host.active_tab == 'queue'


@pytest.mark.parametrize("return_first", [False, True])
def test_reel_return_does_not_reuse_previous_gem_focus(library_window, app, return_first):
    window, core, video = library_window
    window.library_page.bridge.perform('playGem', video.id)
    if return_first:
        window.show_library()
        app.processEvents()
        assert window.web_host._pending_focus == 'gems' or window.web_host.view.hasFocus()
    window.reel.open()
    window.show_library()
    app.processEvents()
    assert len(window.library_page.gems) == 1
    assert window.web_host._pending_focus == 'grid' or window.web_host.view.hasFocus()


def test_playback_return_builds_library_index_once(library_window, app, monkeypatch):
    import my_video_manager.core as core_module
    window, core, video = library_window
    window.play_video(video.id)
    calls = []
    original = core_module.build_index
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(core_module, 'build_index', counted)
    window.show_library()
    app.processEvents()
    assert len(calls) == 1
