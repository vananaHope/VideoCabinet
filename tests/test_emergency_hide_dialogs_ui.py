"""긴급 탈출: 대화상자·메뉴·팝업·입력 중에도 실제 키 입력으로 숨기고, 복귀하면 대화상자가 그대로다."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QSystemTrayIcon

from test_emergency_hide_ui import app, window, key, emergency_key, play_to_twenty_seconds
from test_web_dialogs import state, within
from qt_wait import wait_for


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
    wait_for(lambda: window.web_host._loaded_notified)
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
    """
    assert top.focusWidget() is view(window)
    assert active_label(window) == label


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

        window.tray.open()
        QApplication.processEvents()
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
        window.tray.open()
        QApplication.processEvents()
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
        window.tray.open()
        QApplication.processEvents()
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
    window.tray.open()
    QApplication.processEvents()
    assert window.web_host.active_tab == "search"
    assert_focus_returned(window, window, "검색어")
    assert field_value(window, "검색어") == "Python"


def open_playback_dialog(window, check, *, before_container=None):
    """재생 중 메뉴의 자막 만들기를 열어 웹 대화상자를 창 모달 QDialog로 옮겨 띄운다."""
    dialogs = window.web_host.dialogs
    if before_container is not None:
        def opened(_payload):
            dialogs.bridge.dialogsChanged.disconnect(opened)
            # 대화상자를 연 직후, 웹 뷰가 옮기기 응답을 돌려주기 전에 누른다.
            QTimer.singleShot(0, before_container)
        dialogs.bridge.dialogsChanged.connect(opened)
    within(window.subtitles.request, dialogs, check)


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
        QTest.qWait(300)
        assert not window.isVisible() and not container.isVisible()

        window.tray.open()
        QApplication.processEvents()
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
    """exec 중인 Qt 대화상자가 뜨면 그 안에서 실제 키로 긴급 탈출을 누르고, exec가 반환되기 전 상태를 기록한다."""
    seen = {}

    def press():
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, kind):
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
    """완전 종료가 막혀 '창 닫기 취소' 경고가 뜬 채 탈출: 경고를 닫고 숨기며, 종료는 취소된 채 작업이 이어진다."""
    play_to_twenty_seconds(window)
    window.tray.quit_blocker = lambda: "백업 작업이 끝난 뒤 완전 종료해 주세요."
    try:
        seen = press_in_modal(window, QMessageBox)
        window.tray.quit()
        assert seen == {"title": "창 닫기 취소", "inside_exec": (False, False)}
        assert not window.isVisible() and not window.tray.quitting
        assert window.player.paused and window.balloons == []
        assert window.subtitles.timer.isActive()
    finally:
        del window.tray.quit_blocker
    assert_no_modal_after_return(window)


def test_question_warning_closes_as_cancel(window):
    """질문형 경고('받아쓰기 중 종료')는 닫기가 '취소'로 처리돼 종료하지 않는다."""
    class Busy:
        def isRunning(self):
            return True

        def wait(self):
            pass
    window.subtitles.worker = Busy()
    try:
        seen = press_in_modal(window, QMessageBox)
        window.tray.quit()
        assert seen == {"title": "받아쓰기 중 종료", "inside_exec": (False, False)}
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


@pytest.mark.parametrize("vk,character,modifiers,expected", [
    (0x48, "H", dict(ctrl=True, shift=True), "Ctrl+Shift+H"),
    (0x42, "B", dict(ctrl=True, alt=True), "Ctrl+Alt+B"),
    (0x37, "7", dict(alt=True), "Alt+7"),
    (0x63, "", dict(ctrl=True, alt=True), "Ctrl+Alt+3"),
    (0x78, "", dict(ctrl=True), "Ctrl+F9"),
    (0x25, "", dict(meta=True), "Meta+Left"),
    (0xBA, ";", dict(ctrl=True), "Ctrl+;"),
    (0x11, "", dict(ctrl=True), None),
    (0xE5, "", dict(ctrl=True), None),
])
def test_windows_virtual_key_names_match_key_binding_names(vk, character, modifiers, expected):
    from my_video_manager.key_bindings import normalize_key
    from my_video_manager.native_dialogs import virtual_key_name
    flags = dict(ctrl=False, alt=False, shift=False, meta=False) | modifiers
    name = virtual_key_name(vk, character, **flags)
    assert name == expected
    if name is not None:
        assert normalize_key(name) == name


@pytest.mark.parametrize("menu", ["settings", "playback"])
def test_playback_popup_menu_closes_and_window_hides(window, menu):
    _, player = play_to_twenty_seconds(window)
    key(window, Qt.Key.Key_Apostrophe)
    assert window.isFullScreen()
    if menu == "settings":
        key(window, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        popup = window.settings_menu
    else:
        popup = window.playback_page.menu
        popup.popup(window.playback_page.menu_button.mapToGlobal(window.playback_page.menu_button.rect().topRight()))
        QApplication.processEvents()
    assert QApplication.activePopupWidget() is popup
    QTest.keyClick(popup, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()
    assert not window.isVisible() and not window.isFullScreen()
    assert QApplication.activePopupWidget() is None and not popup.isVisible()
    assert player.paused and window.balloons == []
    QTest.qWait(100)
    window.tray.open()
    QApplication.processEvents()
    # 팝업은 창 비활성화처럼 닫힌 채 돌아오고 재생 화면 초점이 남는다.
    assert window.isVisible() and window.pages.currentWidget() is window.playback_page
    assert not popup.isVisible() and player.paused
    assert QApplication.focusWidget() is window.surface


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


def test_dropdown_open_in_web_page_still_hides(window):
    window.navigate_web_tab("library")
    focus_field(window, "정렬")
    QTest.keyClick(view(window), Qt.Key.Key_Down)
    wait_shown(window, "[role=option]")
    press_emergency(view(window))
    assert not window.isVisible() and window.balloons == []
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.web_host.active_tab == "library"
