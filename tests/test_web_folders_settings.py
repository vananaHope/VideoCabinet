"""공개 브리지 → 코어/Qt 흐름: 검사 잠금, 복원, 키 저장과 즉시 표시."""
import json
import threading
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from test_web_library_data import core, Media
from test_web_library_page import window_factory
from test_playback_page_ui import Player
from my_video_manager.core import AppCore, CommandType, ScanResult


def bridges(window):
    return window.web_host.channel.registeredObjects()


def draft(bridge):
    return {row['id']: row['keys'] for row in json.loads(bridge.snapshot())['bindings']}


def tick():
    QTest.qWait(30)


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
    window = window_factory('1')
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
    window = window_factory('1')
    bridge = bridges(window)['folders']
    calls = []
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: calls.append('folder') or str(folder))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (calls.append('file') or str(path), ''))
    monkeypatch.setattr(window.library_page, 'manage_tags', lambda: calls.append('tags'))
    for action in ('addFolder', 'addFile', 'manageTags'):
        assert json.loads(bridge.action(action, ''))['ok']
        for _ in range(100):
            tick()
            if window.worker is None and not bridge.busy:
                break
        assert window.worker is None
    assert calls == ['folder', 'file', 'tags']
    assert core.watched_folders()[0].path == folder.resolve()
    assert any(v.title == path.stem for v in core.videos())


def test_scan_locks_mutations_but_allows_dismissed_restore_and_reports(window_factory, core):
    video = core.videos()[0]
    core.dismiss_video(video.id)
    window = window_factory('1')
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
        for _ in range(100):
            tick()
            if window.worker is None:
                break
    state = json.loads(api['folders'].snapshot())
    assert not state['scanning'] and '영상 0개 등록' in state['report']


def test_minimum_shared_between_pages_and_survives_restart(window_factory, core):
    api = bridges(window_factory('1'))
    for name, value in (('folders', 12.5), ('settings', 0)):
        assert 'error' not in json.loads(api[name].setMinimum(value))
        for page in ('folders', 'settings'):
            assert json.loads(api[page].snapshot())['minimum'] == value
    for bad in (-1, float('nan'), float('inf'), 31536001):
        assert 'error' in json.loads(api['folders'].setMinimum(bad))
        assert 'error' in json.loads(api['settings'].setMinimum(bad))
    assert AppCore(database=core.database, media=Media(), clock=lambda: datetime.now(timezone.utc)).minimum_duration == 0


def test_key_save_updates_playback_f1_empty_reel_and_restart(window_factory, core):
    window = window_factory('1')
    window.player_factory = Player
    bridge = bridges(window)['settings']
    proposed = draft(bridge)
    proposed['point_highlight:0'] = ['N']
    proposed['toggle_pause:0'] = ['P']
    assert 'error' not in json.loads(bridge.saveKeys(json.dumps(proposed)))
    assert 'N로 지점' in window.reel.empty.text()
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
    bridge = bridges(window_factory('1'))['settings']
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
    window = window_factory('1')
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
    assert len(captured) == 1
    if key == Qt.Key.Key_Escape:
        assert captured[0]['cancelled']
    elif key == Qt.Key.Key_N:
        assert captured[0]['key'] == 'N'
    else:
        assert captured[0]['error']


def test_capture_cancelled_when_leaving_and_alt_s_opens_web_settings(window_factory):
    window = window_factory('1')
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
    window = window_factory('1')
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
