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
from my_video_manager.core import AppCore, CommandType, ScanIssue, ScanResult
from qt_wait import wait_for


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
        host.controllers['recommend'].show_dismissed()
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
        assert state['scanning'] and '검사' in state['report']['message']
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
    assert not state['scanning'] and '영상 0개 등록' in state['report']['message']


def test_scan_report_groups_issues_by_kind_and_keeps_status_summary(window_factory, core, tmp_path):
    # #201: 화면은 코어가 나눈 종류를 받는다. 상태 표시줄 요약은 예전처럼 안내 수까지 보인다.
    denied, subtitle, junction = tmp_path / '막힌 폴더', tmp_path / '영상.srt', tmp_path / '연결'
    issues = (ScanIssue(subtitle, '외부 자막: 2개 블록을 건너뜀', subtitle=True), ScanIssue(denied, '액세스가 거부되었습니다.'),
              ScanIssue(junction, '건너뜀: 연결', failed=False), ScanIssue(denied, '외부 자막: 자막 폴더를 읽지 못했습니다.', subtitle=True))
    window = window_factory()
    window.scan(operation=lambda: ScanResult(0, issues))
    wait_for_scan(window)
    report = json.loads(bridges(window)['folders'].snapshot())['report']
    total = len(core.videos())
    assert report.pop('revision') > 0
    assert report == {
        'message': f'영상 0개 등록 · 전체 {total}개', 'failed': False, 'dismissible': True,
        'failures': [{'path': str(denied), 'message': '액세스가 거부되었습니다.'}],
        'subtitleWarnings': [{'path': str(subtitle), 'message': '2개 블록을 건너뜀'},
                             {'path': str(denied), 'message': '자막 폴더를 읽지 못했습니다.'}],
        'notes': [{'path': str(junction), 'message': '건너뜀: 연결'}]}
    assert window.statusBar().currentMessage() == f'영상 0개 등록 · 전체 {total}개 · 안내 4개'

    def fail():
        raise RuntimeError('디스크 오류')

    window.scan(operation=fail)
    wait_for_scan(window)
    report = json.loads(bridges(window)['folders'].snapshot())['report']
    assert (report['message'], report['failed'], report['failures'], report['subtitleWarnings']) == (
        '검사 실패: 디스크 오류', True, [], [])
    assert window.statusBar().currentMessage() == '검사 실패: 디스크 오류'


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
    proposed['random_play:0'] = ['Ctrl+Alt+R']
    library_keys = []
    bridges(window)['library'].libraryKeyBindingsChanged.connect(lambda value: library_keys.append(json.loads(value)))
    assert 'error' not in json.loads(bridge.saveKeys(json.dumps(proposed)))
    expected = {'randomPlay': 'Ctrl+Alt+R', 'highlightGuidance': '재생 중 N 또는 Delete로 기억할 장면을 남기세요.'}
    assert library_keys == [expected]
    assert json.loads(bridges(window)['library'].snapshot())['keyBindings'] == expected
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
    for key in ('Ctrl+1', 'Ctrl+8', 'Alt+S', 'F1', 'Esc'):
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
    (Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier),
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


def test_emergency_hide_capture_requires_ctrl_or_alt_and_does_not_hide(window_factory):
    window = window_factory()
    window.navigate_web_tab('settings')
    window.activateWindow()
    tick()
    bridge = bridges(window)['settings']
    results = []
    bridge.keyCaptured.connect(lambda raw: results.append(json.loads(raw)))
    target = window.web_host.view.focusProxy()
    bridge.beginCapture('emergency_hide:0')
    for key, modifier in ((Qt.Key.Key_H, Qt.KeyboardModifier.NoModifier),
                          (Qt.Key.Key_H, Qt.KeyboardModifier.ShiftModifier)):
        QTest.keyClick(target, key, modifier)
        assert results[-1]['continuing'] and not results[-1]['key']
        assert 'Ctrl·Alt·Win 중 하나' in results[-1]['error']
    # 캡처 중의 긴급 탈출 키는 창을 숨기지 않고 캡처된다.
    QTest.keyClick(target, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window.isVisible()
    assert results[-1]['key'] == 'Ctrl+Shift+H' and not results[-1]['continuing']
    keys = {row['id']: row['keys'] for row in json.loads(bridge.snapshot())['bindings']}
    note = next(row['note'] for row in json.loads(bridge.snapshot())['bindings'] if row['id'] == 'emergency_hide:0')
    assert '재생 화면 밖' in note and 'Ctrl·Alt·Win' in note
    keys['emergency_hide:0'] = ['H']
    assert 'Ctrl·Alt·Win 중 하나' in json.loads(bridge.saveKeys(json.dumps(keys)))['error']
    assert window.core.command_for_key('Ctrl+Shift+H').kind == CommandType.EMERGENCY_HIDE


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


def test_duplicate_scan_issues_are_shown_once(window_factory, core, tmp_path):
    # #201 R3: 코어가 같은 경로의 같은 안내를 두 번 내도 화면에는 한 번만, 개수도 맞춘다. 경로가 다르면 합치지 않는다.
    first, second = tmp_path / 'a.mkv', tmp_path / 'b.mkv'
    issues = (ScanIssue(first, 'Access denied'), ScanIssue(first, 'Access denied'), ScanIssue(second, 'Access denied'),
              ScanIssue(first, '외부 자막: 1개 블록을 건너뜀', subtitle=True),
              ScanIssue(first, '외부 자막: 1개 블록을 건너뜀', subtitle=True))
    window = window_factory()
    window.scan(operation=lambda: ScanResult(0, issues))
    wait_for_scan(window)
    report = json.loads(bridges(window)['folders'].snapshot())['report']
    assert report['failures'] == [{'path': str(first), 'message': 'Access denied'},
                                  {'path': str(second), 'message': 'Access denied'}]
    assert report['subtitleWarnings'] == [{'path': str(first), 'message': '1개 블록을 건너뜀'}]
    # 상태 표시줄 요약은 코어 결과 그대로다.
    assert window.statusBar().currentMessage().endswith('안내 5개')


def test_finished_scan_report_groups_can_be_dismissed_until_next_result(window_factory, core, tmp_path):
    # #201 R1: 끝난 검사의 결과는 묶음마다 닫을 수 있고, 새 결과는 다시 보인다. 처음 설명·검사 중 문구는 닫지 않는다.
    window = window_factory()
    api = bridges(window)['folders']

    def dismiss(revision, group):
        # 응답에는 데이터가 없고 바뀐 상태는 foldersChanged·snapshot으로 본다.
        assert json.loads(api.dismissReport(revision, group)) == {'ok': True}
        return json.loads(api.snapshot())['report']

    initial = json.loads(api.snapshot())['report']
    assert not initial['dismissible']
    api.dismissReport(initial['revision'], 'summary')
    assert json.loads(api.snapshot())['report']['message'] == initial['message']
    issues = (ScanIssue(tmp_path / 'a.mkv', '액세스가 거부되었습니다.'),
              ScanIssue(tmp_path / 'a.srt', '외부 자막: 1개 블록을 건너뜀', subtitle=True))
    window.scan(operation=lambda: ScanResult(0, issues))
    wait_for_scan(window)
    report = json.loads(api.snapshot())['report']
    assert report['dismissible'] and report['failures'] and report['subtitleWarnings'] and report['message']
    report = dismiss(report['revision'], 'failures')
    assert not report['failures'] and report['subtitleWarnings'] and report['message']
    report = dismiss(report['revision'], 'summary')
    assert (report['message'], report['subtitleWarnings'] != []) == ('', True)
    assert 'error' in json.loads(api.dismissReport(report['revision'], 'unknown'))
    stale = report['revision']
    window.scan(operation=lambda: ScanResult(0, issues))
    wait_for_scan(window)
    # 응답 전에 온 새 결과는 이전 화면의 닫기 요청으로 닫히지 않는다.
    report = dismiss(stale, 'subtitleWarnings')
    assert report['failures'] and report['subtitleWarnings'] and report['message']

    def fail():
        raise RuntimeError('디스크 오류')

    window.scan(operation=fail)
    wait_for_scan(window)
    report = json.loads(api.snapshot())['report']
    assert report['dismissible'] and report['message'] == '검사 실패: 디스크 오류'
    assert dismiss(report['revision'], 'summary')['message'] == ''


def test_scan_failure_and_progress_have_one_live_region(window_factory, core):
    # #201 R2: 같은 검사 사건은 셸 상태 안내 한 곳에서만 알리고, 폴더 화면의 검사 안내는 live region이 아니다.
    window = window_factory()
    host = window.web_host
    wait_for(lambda: host._frontend_ready)
    window.navigate_web_tab('folders')
    wait_for(lambda: 'folders' in host._ready_pages)

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait_for(lambda: bool(result))
        return result[0]

    def live(text):
        return js(f"[...document.querySelectorAll('[role=alert],[role=status]')]"
                  f".filter(e => e.textContent.includes({json.dumps(text)})).map(e => e.getAttribute('role')).join()")

    def shown(text):
        return text in js("document.querySelector('[aria-label=\"검사 안내\"]')?.textContent ?? ''")

    finished = threading.Event()

    def slow():
        finished.wait(5)
        raise RuntimeError('디스크 오류')

    window.scan(operation=slow)
    try:
        wait_for(lambda: shown('영상을 검사하고'))
        assert live('영상을 검사하고') == 'status'
    finally:
        finished.set()
        wait_for_scan(window)
    wait_for(lambda: shown('검사 실패: 디스크 오류'))
    assert live('검사 실패: 디스크 오류') == 'alert'
