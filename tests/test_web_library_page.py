"""실제 웹 페이지와 셸의 공개 동작을 offscreen에서 검증한다."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_web_library_data import core
from my_video_manager.ui import MainWindow


@pytest.fixture
def window_factory(core, monkeypatch):
    app = QApplication.instance() or QApplication([])
    windows = []

    def create():
        window = MainWindow(core)
        windows.append(window)
        window.show()
        app.processEvents()
        return window

    yield create
    for window in windows:
        window.tray.quit()
        window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_library_is_web_by_default(window_factory):
    from my_video_manager.web_library_page import WebLibraryPage

    window = window_factory()
    assert isinstance(window.library_page, WebLibraryPage)


def test_real_web_snapshot_filter_tag_deletion_and_count(window_factory, core):
    video = core.videos()[0]
    tag = core.add_video_tag(video.id, '강의')
    window = window_factory()
    page = window.library_page
    state = json.loads(page.bridge.snapshot())
    assert {v['id'] for v in state['videos']} == {v.id for v in core.videos()}
    assert json.loads(page.bridge.filter('', tag.id))['visibleIds'] == [video.id]
    assert len(page.payload()['videos']) == 3 and len(page.payload()['visibleIds']) == 1

    core.delete_tag(tag.id)
    window.refresh()
    state = json.loads(page.bridge.snapshot())
    assert state['tags'] == []
    assert set(state['visibleIds']) == {v.id for v in core.videos()}
    assert len(state['videos']) == 3 and len(state['visibleIds']) == 3

    core.exclude_video(video.id)
    window.refresh()
    state = json.loads(page.bridge.snapshot())
    assert len(state['videos']) == 2 and len(state['visibleIds']) == 2


def test_focus_request_survives_until_frontend_ready(window_factory):
    window = window_factory()
    page = window.library_page
    targets = []
    page.bridge.libraryFocusRequested.connect(targets.append)
    page.focus_content()
    assert targets == []
    assert json.loads(page.bridge.snapshot())['videos']
    window.web_host.bridge.ready()
    page.bridge.ready()
    assert targets == ['grid']




def test_completed_subtitles_refresh_unselected_card_badge(window_factory, core):
    from my_video_manager.subtitles import TranscriberResult
    from test_web_library_data import Media
    from my_video_manager.core import AppCore
    from datetime import datetime, timezone

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            return TranscriberResult('ko', ())

    writer = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                     database=core.database, transcriber=Transcriber())
    window = window_factory()
    page = window.library_page
    video_id = next(vid for vid in page.video_ids if vid != page.selected_id)
    changes = []
    page.bridge.libraryChanged.connect(lambda value: changes.append(json.loads(value)))
    writer.request_subtitles(video_id)
    writer.process_next_subtitle()
    window.subtitles.video_changed.emit(video_id)
    assert len(changes) == 1
    assert next(v for v in changes[0]['videos'] if v['id'] == video_id)['hasSubtitles']
    assert changes[0]['selectedId'] == page.selected_id
