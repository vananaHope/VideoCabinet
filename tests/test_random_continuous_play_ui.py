"""기존 키 경로·웹 진입점과 EOF 보고 순서를 MainWindow + 가짜 플레이어로 확인한다."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from my_video_manager.random_continuous_play import RandomPlayScope
from test_emergency_hide_ui import app, window, key, emergency_key, open_window  # noqa: F401
from test_random_play_ui import random_key, tray_action
from qt_wait import wait_for


@pytest.mark.parametrize('entry', ['key', 'tray', 'list', 'tags', 'all_scope'])
def test_random_entries_enable_their_scope(window, entry):
    wait_for(lambda: window.loaded)
    core = window.core
    source = window.library_page.visible_video_ids()
    if entry == 'key':
        random_key(window)
    elif entry == 'tray':
        tray_action(window).trigger()
    elif entry == 'list':
        assert json.loads(window.library_page.bridge.randomPlay())['videoId'] in source
    elif entry == 'all_scope':
        window.library_page.bridge.filter('no matching video', 0)
        assert window.library_page.visible_video_ids() == ()
        assert json.loads(window.library_page.bridge.randomPlayAll())['videoId'] in source
    else:
        tag = core.add_video_tag(source[0], 'test')
        assert json.loads(window.library_page.bridge.randomPlayTags(json.dumps([tag.id])))['videoId'] == source[0]
    wait_for(lambda: core.playback.session is not None)
    assert core.random_continuous_enabled
    expected = {'key': 'all', 'tray': 'all', 'list': 'list', 'tags': 'tags', 'all_scope': 'all'}[entry]
    assert core.random_continuous_scope.kind == expected
    if expected == 'all':
        assert window.playback_list == core.playback_video_ids == tuple(v.id for v in core.videos())
    if entry == 'tags':
        assert core.random_continuous_scope.tag_ids == (tag.id,)
    if entry == 'list':
        assert core.random_continuous_scope.video_ids == source


def test_direct_entry_starts_off_and_enable_uses_source_list(window):
    wait_for(lambda: window.loaded)
    window.play(window.core.videos()[0].id)
    assert not window.core.random_continuous_enabled
    window.core.set_random_continuous_enabled(True)
    assert window.core.random_continuous_scope.video_ids == window.playback_list


def test_reel_highlight_jump_keeps_starting_library_list(window):
    wait_for(lambda: window.loaded)
    core = window.core
    source = window.library_page.visible_video_ids()
    assert len(source) > 1
    window.play(source[0])
    window.player.advance(10)
    window.sync_position()
    core.execute_highlight_command(core.command_for_key('Insert'))
    highlight = core.highlights(source[0])[0]
    core.start_reel(highlight_id=highlight.id)
    window.reel.sync()

    window.playback_page.jump_highlight(highlight)

    assert core.reel_playback is None
    assert core.playback.session.record_viewing
    assert not core.random_continuous_enabled
    assert window.playback_list == core.playback_video_ids == source
    core.set_random_continuous_enabled(True)
    assert core.random_continuous_scope == RandomPlayScope('list', source)
    key(window, Qt.Key.Key_PageDown)
    assert core.playback.session.video_id == source[1]


@pytest.fixture
def review_window(tmp_path, app, monkeypatch):
    from test_review import Transcriber
    yield from open_window(tmp_path, app, monkeypatch, transcriber=Transcriber())


@pytest.mark.parametrize('origin', ['library', 'reel', 'other_video', 'same_video'])
def test_review_jump_preserves_matching_core_and_window_start_list(review_window, origin):
    window, core = review_window, review_window.core
    wait_for(lambda: window.loaded)
    source = window.library_page.visible_video_ids()
    assert len(source) > 1
    video_id = source[0]
    core.request_subtitles(video_id)
    assert core.process_next_subtitle().state == 'completed'
    line = core.transcript(video_id).lines[1]
    if origin == 'reel':
        window.play(video_id)
        core.execute_highlight_command(core.command_for_key('Insert'))
        core.start_reel()
        window.reel.sync()
    elif origin in ('other_video', 'same_video'):
        # 현재 라이브러리 결과와 다른 출발 목록을 만들어 탐색/새 시청을 구별한다.
        window.playback_list = (source[1], video_id)
        window.play_video(source[1] if origin == 'other_video' else video_id)
        core.set_random_continuous_enabled(True)
    session = core.playback.session
    old_source = window.playback_list
    count = len(core.viewings(video_id))

    window.review_jump(video_id, line.id)

    expected = old_source if origin == 'same_video' else source
    assert window.playback_list == core.playback_video_ids == expected
    assert core.playback.session.video_id == video_id
    assert core.reel_playback is None
    if origin == 'same_video':
        assert core.playback.session is session
        assert core.random_continuous_enabled
        assert len(core.viewings(video_id)) == count
    else:
        assert core.playback.session is not session
        assert not core.random_continuous_enabled
        assert len(core.viewings(video_id)) == count + 1
    core.set_random_continuous_enabled(True)
    assert core.random_continuous_scope == RandomPlayScope('list', expected)


@pytest.mark.parametrize('control', ['key', 'button'])
def test_tag_pgdn_does_not_escape_to_library_or_series(window, tmp_path, control):
    core = window.core
    first, other = core.videos()
    path = tmp_path / 'tag-only.mkv'
    path.write_bytes(b'tag-only')
    tagged = core.add_file(path)
    # add_file 반환 형식에 기대지 않고 공개 영상 목록으로 찾는다.
    tagged = next(v for v in core.videos() if v.title == 'tag-only')
    tag = core.add_video_tag(first.id, 'pair')
    core.add_video_tag(tagged.id, 'pair')
    window.play(first.id, random_scope=RandomPlayScope('tags', tag_ids=(tag.id,)))
    def navigate(forward):
        if control == 'key':
            key(window, Qt.Key.Key_PageDown if forward else Qt.Key.Key_PageUp)
        else:
            button = window.playback_page.next_button if forward else window.playback_page.previous_button
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            QApplication.processEvents()

    navigate(True)
    assert core.playback.session.video_id == tagged.id
    navigate(False)
    assert core.playback.session.video_id == first.id
    navigate(True)
    assert core.playback.session.video_id == tagged.id
    assert not core.viewings(other.id)


@pytest.mark.parametrize('enabled', [False, True])
def test_eof_waits_for_all_reports_and_records_one_viewing(window, enabled):
    core = window.core
    first, other = core.videos()
    window.play(first.id, random_scope=RandomPlayScope() if enabled else None)
    observed = []

    class Listener:
        def playback_started(self, session, position):
            observed.append(('start', session.video_id, position))

        def playback_position(self, session, position, seeked):
            observed.append(('position', session.video_id, position))

        def playback_ended(self, session, position):
            observed.append(('end', session.video_id, position))

    core.playback.subscribe(Listener())
    old = core.playback.session
    window.player.advance(110)
    window.player.reach_end(120)
    window.sync_position()
    assert core.playback.session is old
    QApplication.processEvents()
    assert observed[:2] == [('position', first.id, 110), ('position', first.id, 120)]
    if enabled:
        assert core.playback.session.video_id == other.id
        assert observed[2:] == [('end', first.id, 120), ('start', other.id, 0)]
        viewing, = core.viewings(first.id)
        assert viewing.ended_at is not None and viewing.played_seconds == 120
        assert len(core.viewings(other.id)) == 1
    else:
        assert core.playback.session is old and core.playback.position == 120
        assert core.viewings(first.id)[0].ended_at is None


@pytest.mark.parametrize('action', ['next', 'back', 'seek'])
def test_eof_overlapping_user_action_does_not_double_advance(window, action):
    core = window.core
    first, other = core.videos()
    window.play(first.id, random_scope=RandomPlayScope())
    old = core.playback.session
    window.player.reach_end(120)
    # 이벤트를 처리하지 않고 키 경로 자체를 보낸다: PgDn 내부의 sync_position이 EOF를 본다.
    if action == 'next':
        QTest.keyClick(window.surface, Qt.Key.Key_PageDown)
    elif action == 'back':
        window.sync_position()
        window.back_to_list()
    else:
        window.sync_position()
        window.playback_page.seek(position=10)
    QApplication.processEvents()
    if action == 'next':
        assert core.playback.session.video_id == other.id
        assert len(core.viewings(first.id)) == len(core.viewings(other.id)) == 1
    elif action == 'back':
        assert core.playback.session is None
        assert not core.random_continuous_enabled
        assert not core.viewings(other.id)
    else:
        assert core.playback.session is old
        assert not core.viewings(other.id)


@pytest.mark.parametrize('late_eof', [False, True])
def test_emergency_hide_defers_eof_until_explicit_resume(window, late_eof):
    core = window.core
    first, other = core.videos()
    window.play(first.id, random_scope=RandomPlayScope())
    old = core.playback.session
    if late_eof:
        window.player.reach_end(120)
        window.sync_position()
        window.emergency_hide()
    else:
        emergency_key(window)
        window.player.reach_end(120)
        window.sync_position()
    QApplication.processEvents()
    window.tray.open()
    QApplication.processEvents()
    assert core.playback.session is old
    assert window.player.paused
    key(window, Qt.Key.Key_Return)
    window.sync_position()
    QApplication.processEvents()
    assert core.playback.session.video_id == other.id
    assert len(core.viewings(first.id)) == len(core.viewings(other.id)) == 1


def test_emergency_eof_seek_discards_pending_transition(window):
    core = window.core
    first, other = core.videos()
    window.play(first.id, random_scope=RandomPlayScope())
    emergency_key(window)
    window.player.reach_end(120)
    window.sync_position()
    window.tray.open()
    window.playback_page.seek(position=10)
    window.sync_position()
    key(window, Qt.Key.Key_Return)
    window.sync_position()
    QApplication.processEvents()
    assert core.playback.session.video_id == first.id
    assert not core.viewings(other.id)


def test_no_candidates_at_eof_stays_and_shows_notice(window):
    first = window.core.videos()[0]
    window.play(first.id, random_scope=RandomPlayScope())
    window.core.set_random_continuous_scope(RandomPlayScope('tags'))
    window.player.reach_end(120)
    window.sync_position()
    QApplication.processEvents()
    assert window.core.playback.session.video_id == first.id
    assert window.playback_page.message_label.text()
    assert window.core.viewings(first.id)[0].ended_at is None


def test_return_selects_last_video_and_discards_state(window):
    wait_for(lambda: window.loaded)
    first, other = window.core.videos()
    window.play(first.id, random_scope=RandomPlayScope())
    key(window, Qt.Key.Key_PageDown)
    key(window, Qt.Key.Key_Escape)
    assert window.library_page.selected_video_id() == other.id
    assert not window.core.random_continuous_enabled
    assert window.core.random_continuous_scope is None
    window.play(first.id)
    assert not window.core.random_continuous_enabled


def test_player_failure_closes_viewings_and_discards_state(window, monkeypatch):
    first, other = window.core.videos()
    window.play(first.id, random_scope=RandomPlayScope())
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args))

    def fail(surface):
        raise OSError('test player failure')

    window.player_factory = fail
    key(window, Qt.Key.Key_PageDown)
    assert errors
    assert window.core.playback.session is None
    assert not window.core.random_continuous_enabled
    assert all(v.ended_at is not None for v in window.core.viewings(first.id) + window.core.viewings(other.id))
