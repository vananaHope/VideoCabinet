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
def window_factory(core, monkeypatch, qapp):
    app = qapp
    windows = []

    def create(mode='1'):
        if mode != '1':
            raise ValueError("window_factory는 웹 기본 모드 '1'만 지원합니다.")
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


@pytest.mark.parametrize('args', [(), ('1',)])
def test_library_is_web_by_default(window_factory, args):
    from my_video_manager.web_library_page import WebLibraryPage

    window = window_factory(*args)
    assert isinstance(window.library_page, WebLibraryPage)


def test_window_factory_rejects_removed_qt_mode(window_factory):
    with pytest.raises(ValueError, match="웹 기본 모드 '1'만 지원"):
        window_factory('0')


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


def test_view_channel_composes_filters_persists_and_refreshes_presence(window_factory, core):
    from my_video_manager.library_views import default_options
    window = window_factory()
    page = window.library_page
    video = core.videos()[0]
    tag = core.add_video_tag(video.id, '고른 태그')
    page.refresh()
    options = {**default_options(), 'mode': 'folders', 'folder': 'direct', 'tags': [tag.id],
               'card_size': 'large', 'sort': 'added', 'descending': True}
    result = json.loads(page.bridge.view(json.dumps(options)))
    assert result['visibleIds'] == [video.id]
    assert result['chips'] == [{'key': f'tag:{tag.id}', 'label': tag.name, 'reset': {**options, 'tags': []}}]
    assert core.library_view_options() == options
    assert 'error' in json.loads(page.bridge.view('{broken'))
    assert 'error' in json.loads(page.bridge.view(json.dumps({'sort': 'invalid'})))
    assert page.options == options
    page.return_from_playback()
    assert page.visible_ids == [video.id] and page.options == options
    core.delete_tag(tag.id)
    page.refresh()
    assert page.options['tags'] == [] and len(page.visible_ids) == 3


def test_subtitle_or_highlight_change_reapplies_current_filter(window_factory, core):
    from my_video_manager.library_views import default_options
    from my_video_manager.core import Command, CommandType
    window = window_factory()
    page = window.library_page
    page.bridge.view(json.dumps({**default_options(), 'highlights': True}))
    assert page.visible_ids == []
    video = core.videos()[0]
    core.playback.start(video.id, 5)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    page.refresh_details(video.id)
    assert page.visible_ids == [video.id]




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


def test_thumbnails_send_only_ids_and_batch_while_hidden(window_factory):
    window = window_factory()
    page = window.library_page
    changes, details, thumbnails = [], [], []
    page.bridge.libraryChanged.connect(changes.append)
    page.bridge.libraryDetailsChanged.connect(details.append)
    page.bridge.thumbnailsChanged.connect(lambda value: thumbnails.append(json.loads(value)))
    ids = list(page.video_ids)
    page.refresh_thumbnails({ids[0]})
    assert thumbnails == [[ids[0]]]
    assert changes == details == []
    window.hide()
    page.refresh_thumbnails({ids[0]})
    page.refresh_thumbnails(set(ids[1:]))
    assert len(thumbnails) == 1
    window.show()
    assert thumbnails == [[ids[0]], sorted(ids)]
    assert changes == []


def test_collapsed_folders_survive_view_switch_and_settings_reload(window_factory, core):
    from my_video_manager.library_views import default_options
    window = window_factory()
    page = window.library_page
    options = {**default_options(), 'mode': 'folders', 'collapsed_folders': ['root|child']}
    page.bridge.view(json.dumps(options))
    page.bridge.view(json.dumps({**page.options, 'mode': 'all'}))
    assert core.library_view_options()['collapsed_folders'] == ['root|child']
    page.bridge.view(json.dumps({**core.library_view_options(), 'mode': 'folders'}))
    assert page.options['collapsed_folders'] == ['root|child']
