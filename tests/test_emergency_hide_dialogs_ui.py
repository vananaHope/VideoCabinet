"""긴급 탈출: 대화상자·메뉴·팝업·입력 중에도 실제 키 입력으로 숨기고, 복귀하면 대화상자가 그대로다."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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
        assert player.paused

    open_playback_dialog(window, check, before_container=press)


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
