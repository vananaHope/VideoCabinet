"""키 안내: 웹 셸 F1·⌨, 지금 화면 키, 바꾼 키 반영, 재생 키 안내의 셸 키 줄, 트레이 '창 숨기기'."""

import json

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.core import Command, CommandType
from my_video_manager.key_guide import app_key_guide
from my_video_manager.web_contract import TABS
from test_emergency_hide_ui import app, window, key, emergency_key
from test_emergency_hide_dialogs_ui import js, view, focus_field, rename_dialog, settle
from test_web_dialogs import within
from qt_wait import wait_for


GUIDE = 'Array.from(document.querySelectorAll("[role=dialog]")).find(e => e.textContent.includes("키 안내 ·"))'


def guide_text(window):
    """열린 키 안내의 글자. 닫혀 있으면 빈 문자열이다."""
    return js(window, f"{GUIDE}?.innerText ?? ''")


def wait_guide(window):
    """열린 키 안내의 글자. 앱 전체 키를 셸에서 읽어 올 때까지 기다린다."""
    wait_for(lambda: window.loaded)
    shown = []

    def loaded():
        text = guide_text(window)
        shown[:] = [text]
        return "앱 전체" in text and "읽는 중" not in text
    wait_for(loaded)
    return shown[0]


def wait_closed(window):
    wait_for(lambda: guide_text(window) == '')
    # 셸 모달 상태가 풀려야 다음 예약 키가 동작한다.
    wait_for(lambda: not window.web_host.dialogs.blocks_shell_actions)


def press_f1(window):
    wait_for(lambda: window.loaded)
    window.activateWindow()
    window.web_host.view.setFocus()
    QApplication.processEvents()
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    QApplication.processEvents()


def rebind(window, command, keys):
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[command] = keys
    window.core.save_key_bindings(bindings)


def test_app_key_guide_reads_current_bindings(window):
    rows = {entry.label: entry for entry in app_key_guide(window.core.key_bindings(), TABS)}
    assert rows["페이지 이동"].keys == ("Ctrl+1 ~ Ctrl+8",)
    assert all(label in rows["페이지 이동"].detail for _, label in TABS)
    assert rows["무작위 재생"].keys == ("Ctrl+Shift+R",)
    assert rows["긴급 탈출(창 숨기기)"].keys == ("Ctrl+Shift+H",)
    assert rows["설정 열기"].keys == ("Alt+S",)
    rebind(window, Command(CommandType.RANDOM_PLAY), ("Ctrl+Alt+R", "Ctrl+Shift+Left"))
    rebind(window, Command(CommandType.EMERGENCY_HIDE), ())
    rows = {entry.label: entry for entry in app_key_guide(window.core.key_bindings(), TABS)}
    # 키마다 화면 이름으로 따로 보이고, 지정되지 않은 명령은 빈 목록이다.
    assert rows["무작위 재생"].keys == ("Ctrl+Alt+R", "Ctrl+Shift+←")
    assert rows["긴급 탈출(창 숨기기)"].keys == ()


EXPECTED = {
    "library": ("영상 격자", "폴더 패널", "F2"),
    "recommend": ("추천 줄", "Backspace", "관심 없음"),
    "reel": ("하이라이트 목록", "라이브러리로 돌아가기"),
    "search": ("검색 칸", "검색 결과"),
    "queue": ("처리 상태 목록", "자동 자막 규칙 목록"),
    "statistics": ("이 화면에만 쓰는 키는 없습니다",),
    "folders": ("이 화면에만 쓰는 키는 없습니다",),
    "settings": ("새 키 입력 취소", "저장하지 않은 값 되돌리기"),
}


@pytest.mark.parametrize("tab", [name for name, _ in TABS])
def test_f1_opens_app_and_current_tab_keys_and_esc_closes(window, tab):
    assert set(EXPECTED) == {name for name, _ in TABS}
    label = dict(TABS)[tab]
    window.navigate_web_tab(tab)
    press_f1(window)
    text = wait_guide(window)
    assert f"키 안내 · {label}" in text and f"지금 화면 · {label}" in text
    for expected in ("앱 전체", "Ctrl+1 ~ Ctrl+8", "Alt+S", "Ctrl+Shift+R", "Ctrl+Shift+H", "F1", *EXPECTED[tab]):
        assert expected in text
    # 다른 탭에만 있는 키 목록은 보이지 않는다.
    others = {item for name, items in EXPECTED.items() if name != tab for item in items} - set(EXPECTED[tab])
    assert not [item for item in others if item in text]
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_closed(window)
    assert window.web_host.active_tab == tab and window.pages.currentWidget() is window.web_host


def test_f1_again_and_mouse_close_the_guide(window):
    press_f1(window)
    wait_guide(window)
    wait_for(lambda: window.web_host.dialogs.blocks_shell_actions)
    QTest.keyClick(view(window), Qt.Key.Key_F1)
    wait_closed(window)
    # ⌨ 단추로 열고 '닫기'로 닫는다.
    js(window, 'document.querySelector("header button[aria-label=\\"키 안내 (F1)\\"]").click()')
    wait_guide(window)
    js(window, f'Array.from({GUIDE}.querySelectorAll("button")).find(b => b.textContent === "닫기").click()')
    wait_closed(window)
    # 바깥(오버레이)을 누르면 닫힌다.
    js(window, 'document.querySelector("header button[aria-label=\\"키 안내 (F1)\\"]").click()')
    wait_guide(window)
    wait_for(lambda: window.web_host.dialogs.blocks_shell_actions)
    QTest.mouseClick(view(window), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(4, view(window).height() - 4))
    wait_closed(window)


def test_changed_bindings_appear_next_time_the_guide_opens(window):
    press_f1(window)
    assert "Ctrl+Shift+R" in wait_guide(window)
    QTest.keyClick(view(window), Qt.Key.Key_Escape)
    wait_closed(window)
    window.navigate_web_tab("settings")
    settings = window.web_host.controllers["settings"]
    payload = json.loads(settings.bridge.snapshot())
    draft = {row["id"]: row["keys"] for row in payload["bindings"]}
    draft["random_play:0"] = ["Ctrl+Alt+R", "Ctrl+Alt+P"]
    draft["emergency_hide:0"] = []
    assert "error" not in json.loads(settings.bridge.saveKeys(json.dumps(draft)))
    press_f1(window)
    text = wait_guide(window)
    assert "Ctrl+Alt+R" in text and "Ctrl+Alt+P" in text and "키 미할당" in text
    assert "Ctrl+Shift+R" not in text and "Ctrl+Shift+H" not in text


def test_web_dialog_ignores_f1_without_opening_the_guide(window):
    dialogs = window.web_host.dialogs

    def check():
        focus_field(window, "영상 제목")
        QTest.keyClick(view(window), Qt.Key.Key_F1)
        settle(window)
        assert dialogs.active and guide_text(window) == ''

    within(rename_dialog(window), dialogs, check)
    press_f1(window)
    wait_guide(window)


@pytest.mark.parametrize("finish", ["commit", "focus_out"])
def test_ime_preedit_and_autorepeat_ignore_f1(window, finish):
    focus_field(window, "영상 제목 빠른 검색")
    target = view(window)
    QApplication.sendEvent(target, QInputMethodEvent("조합", []))
    QTest.keyClick(target, Qt.Key.Key_F1)
    settle(window)
    assert guide_text(window) == ''
    if finish == "commit":
        event = QInputMethodEvent()
        event.setCommitString("조합")
        QApplication.sendEvent(target, event)
    else:
        window.setFocus()
        QApplication.processEvents()
    QApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier, "", True))
    settle(window)
    assert guide_text(window) == ''
    press_f1(window)
    wait_guide(window)


def test_playback_key_help_lists_shell_keys(window):
    window.play_video(window.core.videos()[0].id)
    text = window.playback_page.help_panel.text.text()
    assert "Alt+S 설정 메뉴" in text and "Ctrl+1 ~ Ctrl+8 재생을 끝내고 페이지 이동" in text


def hide_action(window):
    menu = window.tray.icon.contextMenu()
    menu.aboutToShow.emit()
    actions = [action for action in menu.actions() if action.text().startswith("창 숨기기")]
    assert len(actions) == 1
    return actions[0]


def test_tray_hide_matches_emergency_hide_and_is_disabled_while_hidden(window):
    window.play_video(window.core.videos()[0].id)
    window.player.advance(12)
    session = window.core.playback.session
    action = hide_action(window)
    assert action.text() == "창 숨기기 · Ctrl+Shift+H" and action.isEnabled()
    action.trigger()
    QApplication.processEvents()
    assert not window.isVisible() and window.player.paused
    assert window.core.playback.session is session
    assert not hide_action(window).isEnabled()
    hide_action(window).trigger()
    assert not window.isVisible()
    window.tray.open()
    QApplication.processEvents()
    # 긴급 탈출처럼 같은 장면의 일시정지 상태로 돌아온다.
    assert window.isVisible() and window.pages.currentWidget() is window.playback_page
    assert window.core.playback.session is session and window.player.paused
    assert hide_action(window).isEnabled()
    emergency_key(window)
    assert not window.isVisible() and window.core.playback.session is session
    window.tray.open()
    assert window.pages.currentWidget() is window.playback_page


def test_tray_hide_keeps_web_tab_like_emergency_hide(window):
    window.navigate_web_tab("statistics")
    hide_action(window).trigger()
    assert not window.isVisible()
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.web_host.active_tab == "statistics"


def test_tray_hide_label_follows_emergency_key(window):
    rebind(window, Command(CommandType.EMERGENCY_HIDE), ("Ctrl+Alt+H", "Ctrl+Alt+J"))
    assert hide_action(window).text() == "창 숨기기 · Ctrl+Alt+H / Ctrl+Alt+J"
    rebind(window, Command(CommandType.EMERGENCY_HIDE), ())
    assert hide_action(window).text() == "창 숨기기"
