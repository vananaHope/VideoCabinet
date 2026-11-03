"""숨김 뒤 도착한 웹 모달 상태를 트레이 동작과 복귀 초점이 즉시 사용한다."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QSystemTrayIcon

from my_video_manager.web_dialogs_bridge import DialogsBridge
from qt_wait import wait_for
from test_emergency_hide_ui import app, window
from test_emergency_hide_dialogs_ui import activated, js, settle, view


@pytest.fixture
def modal_reports(window, monkeypatch):
    """실제 WebChannel 슬롯을 그대로 실행하고 수신 시점의 창 상태만 기록한다."""
    reports = []
    receive = DialogsBridge.modalState

    def received(bridge, opened):
        result = receive(bridge, opened)
        reports.append((bool(opened), window.isVisible(), window.isMinimized()))
        return result

    monkeypatch.setattr(DialogsBridge, 'modalState', received)
    return reports


def open_and_hide(window, reports, hide='emergency'):
    window.resize(1100, 720)
    wait_for(lambda: window.loaded)
    wait_for(lambda: js(window, "document.activeElement?.id") == 'library-grid')
    settle(window)
    window.web_host.view.setFocus()
    reports.clear()
    # 사이에 이벤트 처리나 프레임 대기 없이 실제 F1 다음 입력으로 숨긴다.
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    if hide in ('emergency', 'minimize'):
        QTest.keyClick(view(window), Qt.Key.Key_H,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    elif hide == 'tray':
        window.tray.hide_window()
    else:
        window.close()
    if hide == 'minimize':
        assert window.isMinimized()
        wait_for(lambda: (True, True, True) in reports)
    else:
        assert not window.isVisible()
        wait_for(lambda: (True, False, False) in reports)
    assert js(window, "!!document.querySelector('[role=dialog][data-state=open]')")


@pytest.mark.parametrize('action', ['random_play', 'open'])
@pytest.mark.parametrize('hide', ['emergency', 'tray', 'close', 'minimize'])
def test_late_modal_open_preserves_dialog_and_focus_on_return(window, modal_reports, monkeypatch, action, hide):
    if hide == 'minimize':
        monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    open_and_hide(window, modal_reports, hide)
    focus_requests = QSignalSpy(window.library_page.bridge.libraryFocusRequested)
    modal_reports.clear()
    getattr(window.tray, action)()
    assert window.pages.currentWidget() is window.web_host
    assert window.player is None
    assert focus_requests.count() == 0
    activated(window)
    # 복귀 재알림까지 왕복한 뒤 초점과 다음 키 입력을 확인한다.
    wait_for(lambda: (True, True, False) in modal_reports)
    settle(window)
    assert js(window, "!!document.activeElement?.closest('[role=dialog]')")
    QTest.keyClick(view(window), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    settle(window)
    assert window.web_host.active_tab == 'library'
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_for(lambda: not js(window, "!!document.querySelector('[role=dialog]')"))
    wait_for(lambda: not window.web_host.dialogs.blocks_shell_actions)
    QTest.keyClick(view(window), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: window.web_host.active_tab == 'recommend')


@pytest.mark.parametrize('keep_open', [False, True])
def test_return_resync_replaces_stale_hidden_modal_state(window, modal_reports, keep_open):
    open_and_hide(window, modal_reports)
    dialogs = window.web_host.dialogs
    assert dialogs.blocks_shell_actions
    if not keep_open:
        # 숨은 동안 웹에서 닫힌 경우도 같은 수신 경로로 즉시 반영한다.
        assert js(window, """(() => {
            const close = Array.from(document.querySelectorAll('[role=dialog] button'))
                .find(button => button.textContent === '닫기');
            if (!close) return false;
            close.click();
            return true;
        })()""")
        wait_for(lambda: (False, False, False) in modal_reports)
        assert not dialogs.blocks_shell_actions
        assert not js(window, "!!document.querySelector('[role=dialog]')")

    # 기록과 실제 DOM이 다르면 복귀 뒤 더 나중에 수신한 웹 상태가 우선한다.
    dialogs.bridge.modalState(int(not keep_open))
    assert dialogs.blocks_shell_actions is not keep_open
    modal_reports.clear()
    window.tray.open()
    activated(window)
    wait_for(lambda: (keep_open, True, False) in modal_reports)
    assert dialogs.blocks_shell_actions is keep_open
    settle(window)
    if keep_open:
        assert js(window, "!!document.activeElement?.closest('[role=dialog]')")
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.blocks_shell_actions)
    QTest.keyClick(view(window), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: window.web_host.active_tab == 'recommend')


@pytest.mark.parametrize('hidden', [False, True])
def test_late_modal_open_during_playback_does_not_block_tray(window, modal_reports, hidden):
    wait_for(lambda: window.loaded)
    window.random_play()
    if hidden:
        window.tray.hide_window()
    dialogs = window.web_host.dialogs
    dialogs.bridge.modalState(1)
    assert not dialogs.blocks_shell_actions
    before = window.core.playback.session.video_id
    window.tray.random_play()
    assert window.pages.currentWidget() is window.playback_page
    assert window.core.playback.session.video_id != before
