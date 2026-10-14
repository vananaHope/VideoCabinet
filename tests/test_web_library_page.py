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

    def create(mode):
        monkeypatch.setenv('MVM_WEB_UI', mode)
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


@pytest.mark.parametrize('mode', ['0', '1', 'true'])
def test_library_switch_requires_explicit_one(window_factory, mode):
    from my_video_manager.library_page import LibraryPage
    from my_video_manager.web_library_page import WebLibraryPage

    window = window_factory(mode)
    assert isinstance(window.library_page, WebLibraryPage if mode == '1' else LibraryPage)


def test_real_web_snapshot_filter_tag_deletion_and_count(window_factory, core):
    video = core.videos()[0]
    tag = core.add_video_tag(video.id, '강의')
    window = window_factory('1')
    page = window.library_page
    state = json.loads(page.bridge.snapshot())
    assert {v['id'] for v in state['videos']} == {v.id for v in core.videos()}
    assert json.loads(page.bridge.filter('', tag.id))['visibleIds'] == [video.id]
    assert window.library_count.text() == '등록 영상 3개 · 표시 1개'

    core.delete_tag(tag.id)
    window.refresh()
    state = json.loads(page.bridge.snapshot())
    assert state['tags'] == []
    assert set(state['visibleIds']) == {v.id for v in core.videos()}
    assert window.library_count.text() == '등록 영상 3개 · 표시 3개'

    core.exclude_video(video.id)
    window.refresh()
    assert window.library_count.text() == '등록 영상 2개 · 표시 2개'


def test_focus_request_survives_until_frontend_ready(window_factory):
    window = window_factory('1')
    page = window.library_page
    targets = []
    page.bridge.libraryFocusRequested.connect(targets.append)
    page.focus_content()
    assert targets == []
    assert json.loads(page.bridge.snapshot())['videos']
    page.bridge.ready()
    assert targets == ['grid']


def test_qt_settings_menu_keeps_native_focus_return(window_factory):
    window = window_factory('0')
    from PySide6.QtWidgets import QLineEdit

    search = window.library_page.findChild(QLineEdit)
    window.activateWindow()
    search.setFocus()
    QTest.qWait(30)
    assert search.hasFocus()
    QTest.keyClick(search, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    assert window.settings_menu.isVisible()
    QTest.keyClick(window.settings_menu, Qt.Key.Key_Escape)
    QTest.qWait(30)
    # offscreen은 네이티브 활성 창을 잃기도 하므로 창이 기억하는 포커스를 확인한다.
    assert window.focusWidget() is window.menuBar()


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
    window = window_factory('1')
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
