"""긴급 탈출: 대화상자·메뉴·팝업·입력 중에도 실제 키 입력으로 숨기고, 복귀하면 대화상자가 그대로다."""

import json
import os
import time
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QSystemTrayIcon

from test_emergency_hide_ui import app, window, key, emergency_key, play_to_twenty_seconds
from test_web_dialogs import state, within
import qt_wait
from qt_wait import wait_for
from my_video_manager.app_version import DISPLAY_NAME


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


def view(window):
    return window.web_host.view.focusProxy() or window.web_host.view


def shown(selector):
    """보이는 요소. 웹 셸은 탭 페이지를 모두 띄워 두므로 첫 일치 요소가 숨은 페이지의 것일 수 있다."""
    return (f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
            ".find(e => e.getClientRects().length > 0)")


def labeled(label):
    return shown(f'[aria-label="{label}"]')


def wait_shown(window, selector):
    wait_for(lambda: js(window, f"!!{shown(selector)}"))


def settle(window):
    """입력과 React 갱신이 두 프레임을 지났는지 기다린다."""
    js(window, "window.settled = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.settled = true }))")
    wait_for(lambda: js(window, "window.settled"))


def focus_field(window, label):
    """웹 입력란에 초점을 두고 기존 값을 선택한다. Qt 초점도 웹 뷰로 옮긴다.

    시작 때 예약된 페이지 초점 요청이 늦게 올 수 있으므로 초점이 남아 있을 때까지 다시 준다.
    """
    wait_for(lambda: window.loaded)
    wait_shown(window, f'[aria-label="{label}"]')
    window.web_host.view.setFocus()

    def focused():
        js(window, f"(() => {{ const e = {labeled(label)}; if (document.activeElement !== e) {{ e.focus(); e.select?.() }} }})()")
        settle(window)
        return active_label(window) == label
    wait_for(focused)


def field_value(window, label):
    return js(window, f"{labeled(label)}.value")


def active_label(window):
    return js(window, "document.activeElement && document.activeElement.getAttribute('aria-label')")


def type_text(window, text):
    """실제 키 입력. QTest는 한글 키를 만들지 못하고 offscreen Chromium은 IME 이벤트를 받지 않으므로 영문만 쓴다."""
    for char in text:
        QTest.keyClick(view(window), char)
    settle(window)


def assert_focus_returned(window, top, label):
    """복귀 뒤 초점이 숨기기 전 입력란이다.

    offscreen은 숨겼다 다시 보인 창을 활성 창으로 되돌리지 않으므로 창의 초점 위젯으로 확인하고,
    실제 키보드 초점은 실창 검사에서 확인한다.
    Qt 창이 먼저 보인 뒤 Chromium의 초점 이벤트가 도착하므로 웹 입력란의 복귀도 기다린다.
    """
    wait_for(lambda: top.focusWidget() is view(window) and active_label(window) == label)
    assert top.focusWidget() is view(window)
    assert active_label(window) == label


def restore(window):
    """트레이 열기로 복귀하고 웹 페이지가 다시 보일 때까지 기다린다(사용자는 보이기 전에 누를 수 없다)."""
    window.tray.open()
    QApplication.processEvents()
    wait_for(lambda: js(window, "document.visibilityState") == "visible")


def press_emergency(target):
    QTest.keyClick(target, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()


def rename_dialog(window):
    video = window.core.videos()[0]
    window.library_page.bridge.select(video.id)
    return window.library_page.library_controls.rename


def test_web_modal_hides_with_window_and_returns_with_typed_text(window):
    dialogs = window.web_host.dialogs
    video = window.core.videos()[0]

    def check():
        identifier = state(dialogs)["id"]
        focus_field(window, "영상 제목")
        type_text(window, "New title")
        assert field_value(window, "영상 제목") == "New title"
        press_emergency(view(window))
        assert not window.isVisible()
        assert window.balloons == []
        assert dialogs.active and state(dialogs)["id"] == identifier
        QTest.qWait(200)
        assert not window.isVisible()

        restore(window)
        assert window.isVisible()
        assert dialogs.active and state(dialogs)["id"] == identifier
        assert_focus_returned(window, window, "영상 제목")
        assert field_value(window, "영상 제목") == "New title"
        # 대화상자의 기존 키: Enter는 그대로 저장한다.
        QTest.keyClick(view(window), Qt.Key.Key_Return)
        wait_for(lambda: not dialogs.active)

    within(rename_dialog(window), dialogs, check)
    assert window.core.video(video.id).title == "New title"


def test_web_modal_escape_still_closes_after_return(window):
    dialogs = window.web_host.dialogs
    video = window.core.videos()[0]

    def check():
        focus_field(window, "영상 제목")
        type_text(window, "Dropped")
        press_emergency(view(window))
        assert not window.isVisible()
        restore(window)
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)

    within(rename_dialog(window), dialogs, check)
    assert window.core.video(video.id).title == video.title


def test_other_shell_keys_still_pass_while_web_modal_is_open(window):
    dialogs = window.web_host.dialogs

    def check():
        window.activateWindow()
        QTest.keyClick(view(window), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(view(window), Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert window.web_host.active_tab == "library" and not window.settings_menu.isVisible()
        assert window.isVisible() and dialogs.active

    within(rename_dialog(window), dialogs, check)


def test_composition_in_web_modal_does_not_block_and_stays_in_the_field(window):
    """조합 중 표시가 있어도 탈출하고, 복귀 뒤 조합을 마치면 같은 입력란에서 기존 키가 동작한다.

    실제 한글 IME 조합(확정 글자가 다른 곳에 들어가지 않음)은 실창에서 확인한다.
    """
    dialogs = window.web_host.dialogs
    video = window.core.videos()[0]

    def check():
        focus_field(window, "영상 제목")
        type_text(window, "Draft")
        js(window, "document.activeElement.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}))")
        settle(window)
        press_emergency(view(window))
        assert not window.isVisible() and dialogs.active
        restore(window)
        assert_focus_returned(window, window, "영상 제목")
        # 조합 중 Esc는 대화상자를 닫지 않는다(기존 동작).
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        settle(window)
        assert dialogs.active
        js(window, "document.activeElement.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true}))")
        settle(window)
        assert field_value(window, "영상 제목") == "Draft"
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)

    within(rename_dialog(window), dialogs, check)
    assert window.core.video(video.id).title == video.title


def test_search_field_typing_returns_with_text_and_focus(window):
    window.navigate_web_tab("search")
    focus_field(window, "검색어")
    type_text(window, "Python")
    assert field_value(window, "검색어") == "Python"
    press_emergency(view(window))
    assert not window.isVisible() and window.balloons == []
    restore(window)
    assert window.web_host.active_tab == "search"
    assert_focus_returned(window, window, "검색어")
    assert field_value(window, "검색어") == "Python"


def open_playback_dialog(window, check, *, before_container=None, entry=None):
    """재생 중 메뉴의 자막 만들기를 열어 웹 대화상자를 창 모달 QDialog로 옮겨 띄운다."""
    dialogs = window.web_host.dialogs
    if before_container is not None:
        def opened(_payload):
            dialogs.bridge.dialogsChanged.disconnect(opened)
            # 대화상자를 연 직후, 웹 뷰가 옮기기 응답을 돌려주기 전에 누른다.
            QTimer.singleShot(0, before_container)
        dialogs.bridge.dialogsChanged.connect(opened)
    within(entry or window.subtitles.request, dialogs, check)


def test_playback_dialog_hides_pauses_and_returns_as_it_was(window):
    _, player = play_to_twenty_seconds(window)
    dialogs = window.web_host.dialogs

    def check():
        wait_for(lambda: dialogs.container is not None and dialogs.container.isVisible())
        container = dialogs.container
        identifier = state(dialogs)["id"]
        focus_field(window, "원어")
        type_text(window, "ko")
        assert field_value(window, "원어") == "ko"
        assert QApplication.activeWindow() is container
        press_emergency(view(window))
        assert not window.isVisible() and not container.isVisible()
        assert player.paused
        assert window.balloons == []
        assert dialogs.active and state(dialogs)["id"] == identifier
        wait_for(lambda: js(window, "document.visibilityState") == "hidden")
        # 준비 완료 대기가 아니라, 지연된 콜백이 숨긴 창을 다시 띄우지 않는지 보는 관찰 구간이다.
        QTest.qWait(300)
        assert not window.isVisible() and not container.isVisible()

        restore(window)
        assert window.isVisible() and window.pages.currentWidget() is window.playback_page
        assert dialogs.container is container and container.isVisible()
        assert window.web_host.view.parent() is container
        assert state(dialogs)["id"] == identifier
        assert player.paused and player.played == 1
        assert_focus_returned(window, container, "원어")
        assert field_value(window, "원어") == "ko"
        # 대화상자의 기존 키: Esc는 그대로 대화상자를 닫는다.
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)

    open_playback_dialog(window, check)
    assert window.isVisible() and player.paused
    assert dialogs.container is None


def test_playback_dialog_moved_after_hiding_stays_hidden_until_return(window):
    """웹 뷰의 옮기기 응답이 숨긴 뒤에 와도 대화상자가 숨은 창 없이 혼자 뜨지 않는다."""
    _, player = play_to_twenty_seconds(window)
    dialogs = window.web_host.dialogs
    pressed = []

    def press():
        pressed.append((dialogs.active, dialogs.moving, dialogs.container))
        press_emergency(QApplication.focusWidget() or window)

    def check():
        assert pressed == [(True, True, None)]
        assert not window.isVisible() and player.paused
        wait_for(lambda: not dialogs.moving)
        QTest.qWait(200)
        assert dialogs.container is not None and not dialogs.container.isVisible()
        assert not window.isVisible()
        window.tray.open()
        QApplication.processEvents()
        assert dialogs.container.isVisible() and window.web_host.view.parent() is dialogs.container
        assert dialogs.container.focusWidget() is view(window)
        assert player.paused

    open_playback_dialog(window, check, before_container=press)


def test_tray_queue_view_after_hiding_playback_dialog_keeps_the_dialog_over_the_shell(window):
    """숨긴 동안 트레이 대기열 보기로 돌아오면 재생을 정리하고 대화상자는 웹 셸 위에 그대로 남는다."""
    play_to_twenty_seconds(window)
    dialogs = window.web_host.dialogs

    def check():
        wait_for(lambda: dialogs.container is not None and dialogs.container.isVisible())
        identifier = state(dialogs)["id"]
        focus_field(window, "원어")
        type_text(window, "ja")
        press_emergency(view(window))
        assert not window.isVisible()
        window.tray.show_queue()
        QTest.qWait(300)
        assert window.isVisible() and window.pages.currentWidget() is window.web_host
        assert window.web_host.active_tab == "queue"
        assert dialogs.container is None and window.web_host.view.parent() is window.web_host
        assert dialogs.active and state(dialogs)["id"] == identifier
        assert field_value(window, "원어") == "ja"

    open_playback_dialog(window, check)


def test_playback_dialog_without_tray_minimizes_with_the_dialog_left_to_the_os(window, monkeypatch):
    """트레이가 없으면 최소화로 대신한다. 대화상자는 운영체제가 소유 창과 함께 내리므로 따로 감추지 않는다."""
    _, player = play_to_twenty_seconds(window)
    dialogs = window.web_host.dialogs
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)

    def check():
        wait_for(lambda: dialogs.container is not None and dialogs.container.isVisible())
        press_emergency(view(window))
        assert window.isMinimized() and player.paused
        # 작업표시줄에서 복원했을 때 보이지 않는 대화상자가 남지 않는다.
        assert dialogs.container.isVisible() and dialogs.active
        window.showNormal()
        QApplication.processEvents()
        assert dialogs.container.isVisible() and window.web_host.view.parent() is dialogs.container

    open_playback_dialog(window, check)


def press_in_modal(window, kind):
    """exec 중인 Qt 대화상자가 뜨면 그 안에서 실제 키로 긴급 탈출을 누르고, exec가 반환되기 전 상태를 기록한다.

    사용자가 키를 누르는 때처럼 대화상자가 활성 창이 된 뒤에 누른다. 활성화 전에는 키가 앱 창 쪽 단축키 문맥에서 처리돼
    대화상자 자신의 단축키(Qt 파일 창의 Ctrl+Shift+H)와 부딪히는지 잴 수 없다.
    """
    seen = {}
    deadline = time.monotonic() + 10

    def press():
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, kind) or not modal.isActiveWindow():
            if isinstance(modal, kind) and time.monotonic() > deadline:
                seen["inside_exec"] = "대화상자가 활성 창이 되지 않음"
                modal.done(0)
                return
            QTimer.singleShot(20, press)
            return
        seen["title"] = modal.windowTitle()
        press_emergency(modal)
        # 아직 호출부의 exec 안이다. 창은 이미 숨었고 대화상자는 닫혔다.
        seen["inside_exec"] = (window.isVisible(), modal.isVisible())
        if modal.isVisible():
            modal.done(0)  # 탈출이 대화상자를 닫지 못했다. 테스트가 멈추지 않고 실패하게 끝낸다.
    QTimer.singleShot(50, press)
    return seen


def assert_no_modal_after_return(window):
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible()
    assert QApplication.activeModalWidget() is None
    assert not any(isinstance(w, (QMessageBox, QFileDialog)) and w.isVisible() for w in QApplication.topLevelWidgets())


def test_playback_warning_closes_and_caller_does_not_resume_playback(window, monkeypatch):
    """재생 중 '재생 조작 실패' 경고에서 탈출: 경고는 닫히고, exec 뒤 호출부가 이어져도 창·재생이 다시 켜지지 않는다."""
    _, player = play_to_twenty_seconds(window)

    def fail(command):
        raise RuntimeError("mpv 명령 실패")
    monkeypatch.setattr(player, "execute", fail)
    seen = press_in_modal(window, QMessageBox)
    key(window, Qt.Key.Key_Return)  # 재생 토글 → 실패 경고 exec → 그 안에서 긴급 탈출
    assert seen == {"title": "재생 조작 실패", "inside_exec": (False, False)}
    QTest.qWait(200)
    assert not window.isVisible() and player.paused
    assert window.balloons == []
    assert window.core.playback.session is not None
    assert_no_modal_after_return(window)
    assert window.pages.currentWidget() is window.playback_page and player.paused


def test_close_cancel_warning_closes_and_quit_stays_cancelled(window):
    """완전 종료가 막혀 창 닫기 취소 경고가 뜬 채 탈출: 경고를 닫고 숨기며, 종료는 취소된 채 작업이 이어진다."""
    play_to_twenty_seconds(window)
    window.tray.quit_blocker = lambda: "백업 작업이 끝난 뒤 완전 종료해 주세요."
    try:
        seen = press_in_modal(window, QMessageBox)
        window.tray.quit()
        assert seen == {"title": DISPLAY_NAME, "inside_exec": (False, False)}
        assert not window.isVisible() and not window.tray.quitting
        assert window.player.paused and window.balloons == []
        assert window.subtitles.timer.isActive()
    finally:
        del window.tray.quit_blocker
    assert_no_modal_after_return(window)


def test_question_warning_closes_as_cancel(window):
    """질문형 경고(받아쓰기 중 종료 확인)는 닫기가 '취소'로 처리돼 종료하지 않는다."""
    class Busy:
        def isRunning(self):
            return True

        def wait(self):
            pass
    window.subtitles.worker = Busy()
    try:
        seen = press_in_modal(window, QMessageBox)
        window.tray.quit()
        assert seen == {"title": DISPLAY_NAME, "inside_exec": (False, False)}
        assert not window.isVisible() and not window.tray.quitting
        assert not window.subtitles.stopping and window.subtitles.timer.isActive()
        assert window.balloons == []
    finally:
        window.subtitles.worker = None
    assert_no_modal_after_return(window)


def test_file_dialog_closes_as_cancel_without_adding(window):
    """파일 선택 창(offscreen은 Qt 파일 창)에서 탈출하면 취소로 끝나 아무것도 추가하지 않는다.

    Windows 기본 파일 창은 Qt 이벤트 필터를 거치지 않아 별도 어댑터가 받으며 실창에서 확인한다.
    """
    _, player = play_to_twenty_seconds(window)
    videos = window.core.videos()
    seen = press_in_modal(window, QFileDialog)
    window.library_page.library_controls.add_file()
    assert seen["inside_exec"] == (False, False)
    assert not window.isVisible() and player.paused and window.balloons == []
    QTest.qWait(200)
    assert window.worker is None and window.core.videos() == videos
    assert_no_modal_after_return(window)


def open_playback_menu(window, menu):
    if menu == "settings":
        key(window, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        return window.settings_menu
    popup = window.playback_page.menu
    button = window.playback_page.menu_button
    popup.popup(button.mapToGlobal(button.rect().topRight()))
    QApplication.processEvents()
    return popup


def while_button_menu_open(button, menu, during):
    """단추의 InstantPopup 메뉴는 exec 안에서 열린다. 열린 동안 during(menu)를 하고, 남아 있으면 닫는다."""
    qt_wait.while_button_menu_open(button, menu, lambda: during(menu))
    QApplication.processEvents()


def activated(window):
    """OS가 복귀한 창을 활성화한다. offscreen은 다시 보인 창의 활성화를 앱에 알리지 않으므로 같은 알림을 준다."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        QApplication.setActiveWindow(window)
    QApplication.processEvents()
    QApplication.processEvents()


def press_emergency_on(popup):
    QTest.keyClick(popup, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()


@pytest.mark.parametrize("menu", ["settings", "playback", "speed"])
def test_playback_popup_menu_hides_with_window_and_reopens_as_it_was(window, menu):
    _, player = play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()
    if menu == "speed":
        # 속도 목록은 조작 줄 단추로만 연다. 전체 화면에서 열고 그대로 긴급 탈출한다.
        page = window.playback_page
        page.reveal_bar()
        popup, seen = page.speed_menu, {}

        def hide_while_open(opened):
            seen["popup"] = QApplication.activePopupWidget()
            seen["fullscreen_pos"] = opened.pos()
            QTest.keyClick(opened, Qt.Key.Key_Down)
            seen["highlighted"] = opened.activeAction()
            press_emergency_on(opened)

        while_button_menu_open(page.speed_button, popup, hide_while_open)
        assert seen["popup"] is popup
        highlighted = seen["highlighted"]
    else:
        popup = open_playback_menu(window, menu)
        assert QApplication.activePopupWidget() is popup
        QTest.keyClick(popup, Qt.Key.Key_Down)
        highlighted = popup.activeAction()
        press_emergency_on(popup)
    assert highlighted is not None
    assert not window.isVisible() and not window.isFullScreen()
    assert QApplication.activePopupWidget() is None and not popup.isVisible()
    assert player.paused and window.balloons == []
    QTest.qWait(100)
    window.tray.open()
    activated(window)
    # 메뉴는 같은 기준 위치(전체 화면을 푼 창 기준)에 다시 열리고 고르던 항목도 그대로다.
    assert window.pages.currentWidget() is window.playback_page
    assert QApplication.activePopupWidget() is popup and popup.isVisible()
    assert popup.activeAction() is highlighted
    assert window.frameGeometry().contains(popup.pos())
    assert window.isActiveWindow() and window.has_emergency_focus()
    assert player.paused
    reopened = popup.pos()
    # 다시 연 메뉴의 기존 키: Esc로 닫으면 영상 화면 초점으로 돌아간다.
    QTest.keyClick(popup, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not popup.isVisible() and window.focusWidget() is window.surface
    if menu == "speed":
        # 전체 화면 당시 좌표가 아니라, 창 모드에서 단추로 새로 열 때와 같은 자리다.
        fresh = {}
        while_button_menu_open(page.speed_button, popup, lambda opened: fresh.update(pos=opened.pos()))
        assert reopened == fresh["pos"] != seen["fullscreen_pos"]


def test_popup_menu_is_not_reopened_when_returning_to_another_screen(window):
    play_to_twenty_seconds(window)
    popup = open_playback_menu(window, "playback")
    press_emergency_on(popup)
    assert not window.isVisible()
    window.tray.show_queue()
    activated(window)
    assert window.web_host.active_tab == "queue" and QApplication.activePopupWidget() is None
    # 대기열에서 다시 숨겼다 돌아와도 예전 메뉴가 열리지 않는다.
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    activated(window)
    assert window.isVisible() and QApplication.activePopupWidget() is None


def test_popup_menu_hidden_again_from_the_reopened_menu_follows_the_latest_screen(window):
    """다시 연 메뉴 위에서 곧바로 긴급 탈출 키를 누르면 메뉴와 함께 숨고, 그 뒤 돌아온 화면 기준으로만 다시 열린다."""
    play_to_twenty_seconds(window)
    popup = open_playback_menu(window, "settings")
    QTest.keyClick(popup, Qt.Key.Key_Down)
    highlighted = popup.activeAction()
    press_emergency_on(popup)
    window.tray.open()
    activated(window)
    assert QApplication.activePopupWidget() is popup
    press_emergency_on(popup)
    assert not window.isVisible() and not popup.isVisible() and QApplication.activePopupWidget() is None
    window.tray.open()
    activated(window)
    assert QApplication.activePopupWidget() is popup and popup.activeAction() is highlighted
    press_emergency_on(popup)
    assert not window.isVisible()
    window.tray.show_queue()
    activated(window)
    assert window.web_host.active_tab == "queue" and QApplication.activePopupWidget() is None
    assert not popup.isVisible()


def test_popup_menu_waiting_for_activation_is_dropped_when_hidden_again(window):
    """복귀했지만 창이 활성화되기 전에 다시 숨기고 다른 화면으로 돌아오면 예전 메뉴가 늦게 열리지 않는다."""
    play_to_twenty_seconds(window)
    popup = open_playback_menu(window, "settings")
    press_emergency_on(popup)
    window.tray.open()
    # 창 활성화 알림이 오기 전에는 열지 않는다. 먼저 열면 메뉴가 전경 창이 되어 앱 창이 활성 창이 아니게 된다.
    assert not window.isActiveWindow() and QApplication.activePopupWidget() is None
    window.emergency_hide()  # 활성화되기 전이라 키 대신 같은 동작을 부른다.
    window.tray.show_queue()
    activated(window)
    QTest.qWait(50)
    assert window.web_host.active_tab == "queue" and QApplication.activePopupWidget() is None


def test_key_help_hides_with_window_and_returns(window):
    _, player = play_to_twenty_seconds(window)
    help_panel = window.playback_page.help_panel
    key(window, Qt.Key.Key_F1)
    assert help_panel.isVisible()
    emergency_key(window)
    assert not window.isVisible() and not help_panel.isVisible()
    assert player.paused and window.balloons == []
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and help_panel.isVisible()
    # 키 안내의 기존 키: Esc는 안내를 닫는다.
    key(window, Qt.Key.Key_Escape)
    assert not help_panel.isVisible() and window.pages.currentWidget() is window.playback_page


def settle_hidden(window):
    """숨은 페이지는 애니메이션 프레임을 돌리지 않으므로 타이머로 React 갱신을 기다린다."""
    js(window, "window.blurred = false; setTimeout(() => setTimeout(() => { window.blurred = true }, 20)); true")
    wait_for(lambda: js(window, "window.blurred"))


def busy_page(window, ms=400):
    """웹 쪽이 잠시 바빠 숨기기 전에 보낸 닫기 신호가 복귀·화면 전환 뒤에 처리되게 한다."""
    window.web_host.engine_page.runJavaScript(
        f"(() => {{ const end = performance.now() + {ms}; while (performance.now() < end); }})()")


def no_popup(window, selector):
    """어느 탭에도(숨은 탭의 Portal 포함) 열린 목록·메뉴가 없다."""
    return js(window, f"document.querySelectorAll({json.dumps(selector)}).length") == 0


def assert_stays_closed(window, selector):
    wait_for(lambda: no_popup(window, selector))
    QTest.qWait(1100)
    assert no_popup(window, selector)


def open_sort_list_on_another_item(window):
    """라이브러리 정렬 목록을 펼치고 커서를 다른 항목으로 옮긴다(아직 확정하지 않음)."""
    window.navigate_web_tab("library")
    focus_field(window, "정렬")
    value = js(window, f"{labeled('정렬')}.textContent")
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_shown(window, "[role=option]")
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    settle(window)
    cursor = js(window, "document.activeElement.textContent")
    assert cursor != value
    return value


def test_dropdown_closes_on_hiding_and_returns_closed_without_committing_the_cursor(window):
    value = open_sort_list_on_another_item(window)
    press_emergency(view(window))
    assert not window.isVisible() and window.balloons == []
    # 숨긴 동안 닫힌다(offscreen은 실제 창 blur를 보내지 않으므로 셸이 보낸 닫기 신호로 닫힌다).
    settle_hidden(window)
    assert no_popup(window, "[role=option]")
    restore(window)
    assert window.isVisible() and window.web_host.active_tab == "library"
    assert_stays_closed(window, "[role=option]")
    assert js(window, f"{labeled('정렬')}.getAttribute('aria-expanded')") == "false"
    assert js(window, f"{labeled('정렬')}.textContent") == value
    assert_focus_returned(window, window, "정렬")


def test_dropdown_closed_late_after_quick_return_stays_closed(window):
    """닫기 신호가 복귀보다 늦게 처리돼도 목록은 닫히고 다시 열리지 않는다."""
    value = open_sort_list_on_another_item(window)
    busy_page(window)
    QTest.keyClick(view(window), Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert not window.isVisible()
    window.tray.open()
    assert window.isVisible()
    assert_stays_closed(window, "[role=option]")
    assert js(window, f"{labeled('정렬')}.textContent") == value


def test_dropdown_closed_late_does_not_stay_over_the_queue_view(window):
    """대기열 보기로 바로 돌아와도 이전 탭(라이브러리)의 목록이 대기열 위에 남지 않는다."""
    value = open_sort_list_on_another_item(window)
    busy_page(window)
    QTest.keyClick(view(window), Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    window.tray.show_queue()
    assert window.isVisible() and window.web_host.active_tab == "queue"
    assert_stays_closed(window, "[role=option]")
    window.navigate_web_tab("library")
    wait_shown(window, '[aria-label="정렬"]')
    assert js(window, f"{labeled('정렬')}.textContent") == value
    assert no_popup(window, "[role=option]")


def test_dropdown_stays_closed_after_hiding_again_right_after_return(window):
    """복귀 직후 다시 숨기고 대기열 보기로 돌아와도 목록이 열리지 않는다."""
    open_sort_list_on_another_item(window)
    press_emergency(view(window))
    restore(window)
    QTest.qWait(150)
    window.emergency_hide()  # offscreen은 다시 보인 창을 활성으로 되돌리지 않으므로 키 대신 같은 동작을 부른다.
    assert not window.isVisible()
    window.tray.show_queue()
    assert window.web_host.active_tab == "queue"
    assert_stays_closed(window, "[role=option]")


def test_dropdown_in_playback_dialog_closes_and_the_dialog_returns(window):
    """재생 중 옮겨 띄운 대화상자(번역 설정) 안의 선택 목록은 닫히고 대화상자는 그대로 복귀한다."""
    play_to_twenty_seconds(window)
    dialogs = window.web_host.dialogs

    def check():
        wait_for(lambda: dialogs.container is not None and dialogs.container.isVisible())
        focus_field(window, "번역 방식")
        value = js(window, f"{labeled('번역 방식')}.textContent")
        QTest.keyClick(view(window), Qt.Key.Key_Down)
        wait_shown(window, "[role=option]")
        QTest.keyClick(view(window), Qt.Key.Key_Down)
        press_emergency(view(window))
        assert not window.isVisible() and not dialogs.container.isVisible()
        window.tray.open()
        QApplication.processEvents()
        assert dialogs.container.isVisible() and dialogs.active
        assert_stays_closed(window, "[role=option]")
        assert js(window, f"{labeled('번역 방식')}.textContent") == value

    open_playback_dialog(window, check, entry=window.translations.settings)


def test_tag_picker_drops_active_candidate_on_hiding_and_the_typed_text_returns(window):
    from my_video_manager.web_dialogs_entries import TagEditor
    core = window.core
    first, second = core.videos()
    core.add_video_tag(second.id, "lecture")
    dialogs = window.web_host.dialogs
    active = '[data-dialog-frame] [role=option][data-active]'

    def check():
        focus_field(window, "태그 검색")
        type_text(window, "le")
        wait_shown(window, '[aria-label="태그 검색 결과"]')
        QTest.keyClick(view(window), Qt.Key.Key_Down)
        settle(window)
        assert js(window, f"!!document.querySelector('{active}')")
        press_emergency(view(window))
        assert not window.isVisible() and dialogs.active
        settle_hidden(window)
        assert no_popup(window, active)
        restore(window)
        assert_stays_closed(window, active)
        # 고르던 후보는 붙지 않고 입력한 글자와 초점이 그대로다. 목록은 대화상자 안에 늘 펼쳐져 있다.
        assert field_value(window, "태그 검색") == "le"
        assert js(window, "!!" + shown('[aria-label="태그 검색 결과"]'))
        assert [tag.name for tag in core.video_tags(first.id)] == []
        assert_focus_returned(window, window, "태그 검색")

    within(lambda: TagEditor(core, video_id=first.id, parent=window).exec(), dialogs, check)


def test_context_menu_closes_on_hiding_and_returns_closed(window):
    window.navigate_web_tab("library")
    wait_shown(window, "#library-grid [id^=video-]")
    js(window, f"""(() => {{ const card = {shown('#library-grid [id^=video-]')}; const r = card.getBoundingClientRect();
        card.dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, cancelable: true, clientX: r.left + 20, clientY: r.top + 20}})) }})()""")
    wait_shown(window, "[role=menu]")
    # 포인터를 항목 위에 올려 고르는 중인 상태로 둔다(실행하지 않음).
    # 탭 이동 뒤 라이브러리가 늦게 격자로 초점을 되돌릴 수 있으므로 항목 초점이 아니라 메뉴가 열려 항목이 보이는지로 준비를 확인한다.
    js(window, f"{shown('[role=menuitem]')}.dispatchEvent(new PointerEvent('pointermove', {{bubbles: true, pointerType: 'mouse'}}))")
    settle(window)
    wait_shown(window, "[role=menu] [role=menuitem]")
    press_emergency(view(window))
    assert not window.isVisible()
    settle_hidden(window)
    assert no_popup(window, "[role=menu]")
    restore(window)
    assert_stays_closed(window, "[role=menu]")
    # 고르던 메뉴 항목은 실행되지 않았다.
    assert not window.web_host.dialogs.active and not window.web_host.dialogs.web_modal
