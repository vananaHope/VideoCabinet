"""공개 브리지 → 코어/Qt 흐름: 검사 잠금, 복원, 키 저장과 즉시 표시."""
from wait_helpers import UI_READY_TIMEOUT

import json
import threading
import time
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from test_web_library_data import core, Media
from test_web_library_page import window_factory
from test_playback_page_ui import Player
from my_video_manager.core import AppCore, CommandType, ScanResult


@pytest.mark.parametrize('section', ['excluded', 'dismissed'])
def test_library_restore_entry_opens_existing_folder_section(window_factory, section):
    window = window_factory()
    host = window.web_host
    requested = []
    host.controllers['folders'].bridge.foldersFocusRequested.connect(requested.append)
    host.bridge.ready()
    host.controllers['folders'].bridge.ready()
    if section == 'excluded':
        window.library_page.library_controls.show_excluded()
    else:
        window.library_page.hidden_gems.show_dismissed()
    assert host.active_tab == 'folders' and window.pages.currentWidget() is host
    assert requested[-1] == 'folders-' + section


def test_playback_settings_menu_entry_opens_web_key_bindings(window_factory, core):
    window = window_factory()
    window.player_factory = Player
    host = window.web_host
    requested = []
    host.controllers['settings'].bridge.settingsFocusRequested.connect(requested.append)
    host.bridge.ready()
    host.controllers['settings'].bridge.ready()
    window.play_video(core.videos()[0].id)
    video_id = core.playback.session.video_id
    window.player.positions.append((40, False))
    window.settings_menu.actions()[0].trigger()
    assert core.playback.session is None
    assert core.viewing_status(video_id).resume_point == 40
    assert host.active_tab == 'settings'
    assert requested[-1] == 'settings-keys'


def bridges(window):
    return window.web_host.channel.registeredObjects()


def draft(bridge):
    return {row['id']: row['keys'] for row in json.loads(bridge.snapshot())['bindings']}


def tick():
    # QTest.qWait는 WebEngine/검사 작업자와 함께 실행할 때 Qt 내부에서
    # 대기한 채 돌아오지 않을 수 있다. 실행 중 이벤트 루프로 완료 신호를 받는다.
    loop = QEventLoop()
    QTimer.singleShot(30, loop.quit)
    loop.exec()


def wait_for_scan(window, bridge=None):
    deadline = time.monotonic() + UI_READY_TIMEOUT
    try:
        while window.worker is not None or (bridge is not None and bridge.busy):
            assert time.monotonic() < deadline, '검사 완료 대기 시간 초과'
            tick()
    finally:
        # 실패해도 유한한 테스트 작업자를 먼저 회수한다. tray.quit의 확인창으로
        # 넘어가면 offscreen 전체 테스트가 영구 대기하므로 종료 신호까지 처리한다.
        if window.worker is not None:
            window.worker.wait()
            QApplication.processEvents()


def test_restore_lists_and_folder_removal_preserve_video(window_factory, core, tmp_path):
    folder = tmp_path / '감시 폴더'
    folder.mkdir()
    path = folder / '긴 한글 영상.mkv'
    path.write_bytes(b'folder video')
    core.add_watched_folder(folder)
    core.scan()
    video = next(v for v in core.videos() if v.title == path.stem)
    core.dismiss_video(video.id)
    core.exclude_video(video.id)
    window = window_factory()
    bridge = bridges(window)['folders']
    state = json.loads(bridge.snapshot())
    assert state['folders'] == [str(folder.resolve())]
    assert [v['id'] for v in state['excluded']] == [video.id]
    assert [v['id'] for v in state['dismissed']] == [video.id]
    assert json.loads(bridge.action('restoreExcluded', str(video.id)))['ok']
    tick()
    assert not core.excluded_videos()
    bridge.action('restoreDismissed', str(video.id))
    tick()
    assert not core.dismissed_videos()
    bridge.action('removeFolder', str(folder.resolve()))
    tick()
    assert core.watched_folders() == ()
    assert core.video(video.id).missing and path.exists()


def test_native_file_and_folder_pickers_and_tag_entry(window_factory, core, tmp_path, monkeypatch):
    folder = tmp_path / '선택한 폴더'
    folder.mkdir()
    path = tmp_path / '직접 추가.mkv'
    path.write_bytes(b'directly added')
    window = window_factory()
    bridge = bridges(window)['folders']
    calls = []
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: calls.append('folder') or str(folder))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (calls.append('file') or str(path), ''))
    monkeypatch.setattr(window.library_page, 'manage_tags', lambda: calls.append('tags'))
    for action in ('addFolder', 'addFile', 'manageTags'):
        assert json.loads(bridge.action(action, ''))['ok']
        wait_for_scan(window, bridge)
        assert window.worker is None
    assert calls == ['folder', 'file', 'tags']
    assert core.watched_folders()[0].path == folder.resolve()
    assert any(v.title == path.stem for v in core.videos())


def test_scan_locks_mutations_but_allows_dismissed_restore_and_reports(window_factory, core):
    video = core.videos()[0]
    core.dismiss_video(video.id)
    window = window_factory()
    api = bridges(window)
    finished = threading.Event()

    def scan():
        finished.wait(5)
        return ScanResult(0, ())

    window.scan(operation=scan)
    try:
        state = json.loads(api['folders'].snapshot())
        assert state['scanning'] and '검사' in state['report']
        for action in ('addFolder', 'removeFolder', 'addFile', 'scan', 'restoreExcluded'):
            assert 'error' in json.loads(api['folders'].action(action, ''))
        for name in ('folders', 'settings'):
            assert 'error' in json.loads(api[name].setMinimum(12))
        assert json.loads(api['folders'].action('restoreDismissed', str(video.id)))['ok']
        tick()
        assert not core.dismissed_videos()
    finally:
        finished.set()
        wait_for_scan(window)
    state = json.loads(api['folders'].snapshot())
    assert not state['scanning'] and '영상 0개 등록' in state['report']


def test_minimum_shared_between_pages_and_survives_restart(window_factory, core):
    api = bridges(window_factory())
    for name, value in (('folders', 12.5), ('settings', 0)):
        assert 'error' not in json.loads(api[name].setMinimum(value))
        for page in ('folders', 'settings'):
            assert json.loads(api[page].snapshot())['minimum'] == value
    for bad in (-1, float('nan'), float('inf'), 31536001):
        assert 'error' in json.loads(api['folders'].setMinimum(bad))
        assert 'error' in json.loads(api['settings'].setMinimum(bad))
    assert AppCore(database=core.database, media=Media(), clock=lambda: datetime.now(timezone.utc)).minimum_duration == 0


def test_key_save_updates_playback_f1_empty_reel_and_restart(window_factory, core):
    window = window_factory()
    window.player_factory = Player
    bridge = bridges(window)['settings']
    proposed = draft(bridge)
    proposed['point_highlight:0'] = ['N']
    proposed['toggle_pause:0'] = ['P']
    assert 'error' not in json.loads(bridge.saveKeys(json.dumps(proposed)))
    assert 'N로 지점' in window.web_host.controllers['reel'].payload()['emptyDescription']
    assert 'N로 지점' in json.loads(bridges(window)['reel'].snapshot())['emptyDescription']
    assert core.command_for_key('N').kind == CommandType.POINT_HIGHLIGHT
    assert core.command_for_key('Insert') is None
    window.play_video(core.videos()[0].id)
    window.activateWindow()
    tick()
    QTest.keyClick(window.surface, Qt.Key.Key_P)
    assert window.player.commands[-1].kind == CommandType.TOGGLE_PAUSE
    QTest.keyClick(window.surface, Qt.Key.Key_F1)
    assert '<b>N</b>' in window.playback_page.help_panel.text.text()
    assert '<b>P</b>' in window.playback_page.help_panel.text.text()
    reopened = AppCore(database=core.database, media=Media(), clock=lambda: datetime.now(timezone.utc))
    assert reopened.command_for_key('N').kind == CommandType.POINT_HIGHLIGHT


def test_conflicts_reserved_keys_and_reset_do_not_partially_save(window_factory, core):
    bridge = bridges(window_factory())['settings']
    before = draft(bridge)
    proposed = {**before, 'point_highlight:0': ['Enter']}
    assert '같은 키' in json.loads(bridge.saveKeys(json.dumps(proposed)))['error']
    for key in ('Ctrl+1', 'Ctrl+7', 'Alt+S', 'F1', 'Esc'):
        proposed['point_highlight:0'] = [key]
        assert 'error' in json.loads(bridge.saveKeys(json.dumps(proposed)))
        assert draft(bridge) == before
    for malformed in ('{}', '[]', '{', json.dumps({**before, 'point_highlight:0': 1})):
        assert 'error' in json.loads(bridge.saveKeys(malformed))
    proposed['point_highlight:0'] = ['N']
    bridge.saveKeys(json.dumps(proposed))
    defaults = {row['id']: row['defaults'] for row in json.loads(bridge.snapshot())['bindings']}
    bridge.saveKeys(json.dumps(defaults))
    assert draft(bridge) == before
    assert core.settings.get('keys.bindings') == {}


@pytest.mark.parametrize('key,modifier', [
    (Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier),
    (Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier),
    (Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier),
    (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier),
    (Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
    (Qt.Key.Key_N, Qt.KeyboardModifier.NoModifier),
])
def test_qt_capture_precedes_shell_keys(window_factory, key, modifier):
    window = window_factory()
    window.navigate_web_tab('settings')
    window.activateWindow()
    tick()
    bridge = bridges(window)['settings']
    captured = []
    bridge.keyCaptured.connect(lambda raw: captured.append(json.loads(raw)))
    assert json.loads(bridge.beginCapture('point_highlight:0'))['ok']
    QTest.keyClick(window.web_host.view.focusProxy(), key, modifier)
    tick()
    assert window.web_host.active_tab == 'settings'
    assert not window.settings_menu.isVisible()
    captured = [result for result in captured if not result['continuing']]
    assert len(captured) == 1
    if key == Qt.Key.Key_Escape:
        assert captured[0]['cancelled']
    elif key == Qt.Key.Key_N:
        assert captured[0]['key'] == 'N'
    else:
        assert captured[0]['error']


def test_capture_cancelled_when_leaving_and_alt_s_opens_web_settings(window_factory):
    window = window_factory()
    window.activateWindow()
    tick()
    bridge = bridges(window)['settings']
    assert 'error' in json.loads(bridge.beginCapture('point_highlight:0'))
    QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    assert window.web_host.active_tab == 'settings'
    bridge.beginCapture('point_highlight:0')
    window.navigate_web_tab('folders')
    assert 'error' in json.loads(bridge.captureKey('N'))
    QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert window.web_host.active_tab == 'library'


def test_translation_and_quit_use_current_entry_points(window_factory, core, monkeypatch):
    window = window_factory()
    bridge = bridges(window)['settings']
    calls = []
    monkeypatch.setattr(window.translations, 'settings', lambda: (calls.append('translation'), core.set_translation_cli('claude')))
    monkeypatch.setattr(window.tray, 'quit', lambda: calls.append('quit'))
    bridge.action('translation')
    tick()
    assert json.loads(bridge.snapshot())['translationCli'] == 'claude'
    assert json.loads(bridge.snapshot())['heldTranslations'] == 0
    bridge.action('quit')
    tick()
    assert calls == ['translation', 'quit']


@pytest.mark.parametrize('fullscreen', [False, True])
def test_web_playback_alt_s_preserves_session_and_focus(window_factory, core, fullscreen):
    window = window_factory()
    window.player_factory = Player
    window.play_video(core.videos()[0].id)
    window.activateWindow()
    tick()
    if fullscreen:
        QTest.keyClick(window.surface, Qt.Key.Key_Apostrophe)
    session = core.playback.session
    player = window.player
    QTest.keyClick(window.surface, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
    assert QApplication.activePopupWidget() is window.settings_menu
    assert core.playback.session is session and window.player is player
    assert window.pages.currentWidget() is window.playback_page
    assert window.isFullScreen() is fullscreen
    QTest.keyClick(window.settings_menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not window.settings_menu.isVisible()
    # offscreen은 숨은 QMenu를 활성 창으로 남긴다. 실창 검사는 hasFocus도 확인한다.
    assert window.focusWidget() is window.surface
    assert core.playback.session is session and window.player is player
    assert window.isFullScreen() is fullscreen


def test_unsupported_key_keeps_capture_until_supported_input(window_factory):
    window = window_factory()
    window.navigate_web_tab('settings')
    window.activateWindow()
    tick()
    bridge = bridges(window)['settings']
    results = []
    bridge.keyCaptured.connect(lambda raw: results.append(json.loads(raw)))
    bridge.beginCapture('point_highlight:0')
    QTest.keyClick(window.web_host.view.focusProxy(), Qt.Key.Key_MediaPlay)
    assert results[-1]['continuing']
    assert '지원하는 키를 누르세요' in results[-1]['error']
    bridge.captureKey('Unidentified')
    assert results[-1]['continuing']
    QTest.keyClick(window.web_host.view.focusProxy(), Qt.Key.Key_Up)
    assert results[-1]['key'] == 'Up' and results[-1]['display'] == '↑'
    assert not results[-1]['continuing']
    bridge.beginCapture('point_highlight:0')
    bridge.captureKey('Alt+s')
    assert not results[-1]['continuing']
    assert '예약 키' in results[-1]['error']


def test_inactive_refresh_skips_payload_and_timer_only_emits_changes(window_factory, core, monkeypatch):
    window = window_factory()
    pages = window.web_host.controllers
    for name in ('folders', 'settings'):
        with monkeypatch.context() as patch:
            patch.setattr(pages[name], 'payload', lambda: pytest.fail('비활성 payload 생성'))
            window.library_page.refreshed.emit()
    window.navigate_web_tab('settings')
    changes = []
    pages['settings'].bridge.settingsChanged.connect(changes.append)
    for _ in range(3):
        pages['settings'].timer.timeout.emit()
    assert not changes
    core.set_translation_cli('claude')
    pages['settings'].timer.timeout.emit()
    assert len(changes) == 1
    assert json.loads(changes[0])['translationCli'] == 'claude'
    pages['settings'].timer.timeout.emit()
    assert len(changes) == 1


def test_folders_reactivation_delivers_changes_skipped_while_hidden(window_factory, core, tmp_path):
    window = window_factory()
    window.navigate_web_tab('folders')
    changes = []
    bridges(window)['folders'].foldersChanged.connect(lambda value: changes.append(json.loads(value)))
    window.web_host.hide()
    folder = tmp_path / '비활성 동안 추가한 폴더'
    folder.mkdir()
    core.add_watched_folder(folder)
    window.library_page.refreshed.emit()
    assert changes == []
    window.web_host.show()
    assert len(changes) == 1
    assert str(folder.resolve()) in changes[0]['folders']
