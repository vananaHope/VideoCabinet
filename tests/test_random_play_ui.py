"""앱 수준 무작위 재생: 실제 키 입력, 기록 전환, 모달·IME 차단과 트레이 복원."""

import json
import threading

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout

from my_video_manager.core import Command, CommandType, ScanResult
from my_video_manager.random_play import NO_CANDIDATE_MESSAGE
from my_video_manager.web_contract import TABS
from test_emergency_hide_ui import app, window, key, emergency_key
from test_emergency_hide_dialogs_ui import js, view, rename_dialog, focus_field, type_text, field_value
from test_web_dialogs import within
from qt_wait import wait_for


MODIFIERS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier


def random_key(window):
    key(window, Qt.Key.Key_R, MODIFIERS)


@pytest.mark.parametrize("tab", [name for name, _ in TABS])
def test_all_web_tabs_play_from_whole_library_and_return(window, tab):
    wait_for(lambda: window.loaded)
    window.library_page.bridge.filter("no matching video", 0)
    assert window.library_page.visible_video_ids() == ()
    window.navigate_web_tab(tab)
    window.web_host.view.setFocus()
    random_key(window)
    assert window.core.playback.session.video_id in {video.id for video in window.core.videos()}
    assert window.pages.currentWidget() is window.playback_page
    key(window, Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == tab
    assert window.core.playback.session is None


def test_playing_random_key_closes_viewing_and_resumes_selected_video(window):
    random_key(window)
    first = window.core.playback.session.video_id
    second = next(video.id for video in window.core.videos() if video.id != first)
    # 선택 대상의 이전 시청을 공개 재생 API로 만든다.
    window.end_playback()
    window.core.switch_to(second)
    window.core.playback.report(30)
    window.core.playback.end()
    window.play_video(first)
    window.player.advance(10)
    window.player.advance(20)
    random_key(window)
    assert window.core.playback.session.video_id == second
    assert window.player.position == 27
    assert window.core.viewings(first)[-1].ended_at is not None
    assert window.core.viewings(first)[-1].last_position == 20
    key(window, Qt.Key.Key_Escape)
    assert window.core.playback.session is None


def test_rebinding_works_and_autorepeat_does_not_switch_again(window):
    command = Command(CommandType.RANDOM_PLAY)
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[command] = ("Ctrl+Alt+R",)
    window.core.save_key_bindings(bindings)
    random_key(window)
    assert window.player is None
    modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    key(window, Qt.Key.Key_R, modifiers)
    session = window.core.playback.session
    QApplication.sendEvent(window.surface, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, modifiers, "", True))
    assert window.core.playback.session is session


def test_web_dialog_blocks_random_key_then_allows_it_after_close(window):
    dialogs = window.web_host.dialogs

    def check():
        focus_field(window, "영상 제목")
        random_key(window)
        assert dialogs.active
        assert window.player is None

    within(rename_dialog(window), dialogs, check)
    random_key(window)
    assert window.player is not None


def test_qt_modal_blocks_random_key_then_allows_it_after_close(window):
    dialog = QDialog(window)
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)
    edit = QLineEdit(dialog)
    layout.addWidget(edit)
    dialog.show()
    dialog.activateWindow()
    edit.setFocus()
    QApplication.processEvents()
    try:
        assert QApplication.activeModalWidget() is dialog
        QTest.keyClick(edit, Qt.Key.Key_R, MODIFIERS)
        assert window.player is None and dialog.isVisible()
    finally:
        dialog.close()
    random_key(window)
    assert window.player is not None


@pytest.mark.parametrize("finish", ["commit", "focus_out"])
def test_web_ime_preedit_blocks_key_and_releases_after_composition(window, finish):
    focus_field(window, "영상 제목 빠른 검색")
    target = view(window)
    # OS IME가 Qt/WebEngine 입력란에 보내는 이벤트. offscreen에서는 Chromium의
    # 실제 한글 후보창을 만들 수 없으므로 수신 경계까지 합성한다.
    QApplication.sendEvent(target, QInputMethodEvent("조합", []))
    QTest.keyClick(target, Qt.Key.Key_R, MODIFIERS)
    QApplication.processEvents()
    assert window.player is None
    if finish == "commit":
        event = QInputMethodEvent()
        event.setCommitString("조합")
        QApplication.sendEvent(target, event)
    else:
        window.setFocus()
        QApplication.processEvents()
    random_key(window)
    assert window.player is not None


def test_other_window_focus_does_not_run_random_play(window):
    other = QLineEdit()
    other.show()
    other.activateWindow()
    other.setFocus()
    QApplication.processEvents()
    try:
        QTest.keyClick(other, Qt.Key.Key_R, MODIFIERS)
        assert window.player is None
    finally:
        other.close()


@pytest.mark.parametrize("entry", ["key", "tray"])
def test_no_candidates_shows_information_and_keeps_page(window, entry):
    wait_for(lambda: window.loaded)
    for video in window.core.videos():
        window.core.exclude_video(video.id)
    if entry == "tray":
        window.close()
        tray_action(window).trigger()
    else:
        random_key(window)
    assert window.isVisible() and window.player is None
    assert window.statusBar().currentMessage() == NO_CANDIDATE_MESSAGE
    wait_for(lambda: js(window, f"document.body.innerText.includes({json.dumps(NO_CANDIDATE_MESSAGE)})"))


def tray_action(window):
    actions = [action for action in window.tray.icon.contextMenu().actions() if action.text() == "무작위 재생"]
    assert len(actions) == 1 and actions[0].menu() is None
    return actions[0]


def test_tray_random_restores_hidden_window_and_ignores_filter(window):
    window.library_page.bridge.filter("no matching video", 0)
    window.close()
    assert not window.isVisible()
    tray_action(window).trigger()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.playback_page
    assert window.core.playback.session.video_id in {video.id for video in window.core.videos()}
    key(window, Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is window.web_host


def test_library_whole_random_uses_random_key_scope_and_playlist(window):
    window.library_page.bridge.filter("no matching video", 0)
    reply = json.loads(window.library_page.bridge.randomPlayAll())
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    all_ids = tuple(video.id for video in window.core.videos())
    assert window.core.playback.session.video_id == reply["videoId"]
    assert reply["videoId"] in all_ids and window.playback_list == all_ids
    assert window.core.playback_video_ids == all_ids
    assert window.core.random_continuous_enabled
    assert window.core.random_continuous_scope.kind == "all"
    key(window, Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is window.web_host


def assert_shell_keys_blocked(window, target):
    page, tab, session = window.pages.currentWidget(), window.web_host.active_tab, window.core.playback.session
    keys = [(Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier) for index in range(8)]
    keys += [(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier), (Qt.Key.Key_R, MODIFIERS)]
    for code, modifiers in keys:
        QTest.keyClick(target, code, modifiers)
        QApplication.processEvents()
        assert window.pages.currentWidget() is page
        assert window.web_host.active_tab == tab
        assert window.core.playback.session is session
        assert not window.settings_menu.isVisible()


@pytest.mark.parametrize("emergency", [False, True])
def test_tray_random_keeps_web_dialog_visible_and_shell_keys_blocked(window, emergency):
    dialogs = window.web_host.dialogs

    def check():
        focus_field(window, "영상 제목")
        type_text(window, "Unsaved title")
        if emergency:
            emergency_key(window)
            assert not window.isVisible()
        tray_action(window).trigger()
        QApplication.processEvents()
        assert window.player is None and window.core.playback.session is None
        assert window.isVisible() and window.pages.currentWidget() is window.web_host
        assert dialogs.active and window.web_host.view.isVisible()
        wait_for(lambda: js(window, '!!document.querySelector("[role=dialog]")?.getClientRects().length'))
        assert field_value(window, "영상 제목") == "Unsaved title"
        # offscreen은 숨겼다 연 창을 활성 창으로 복원하지 않는다. Qt 활성 상태를
        # 명시해 비활성 창 가드가 대화상자 키 차단의 결함을 가리지 않게 한다.
        QApplication.setActiveWindow(window)
        QApplication.processEvents()
        assert window.isActiveWindow()
        assert_shell_keys_blocked(window, view(window))
        assert dialogs.active and window.web_host.view.isVisible()
        QTest.keyClick(view(window), Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)

    within(rename_dialog(window), dialogs, check)
    tray_action(window).trigger()
    assert window.player is not None


@pytest.mark.parametrize("modality", [Qt.WindowModality.WindowModal, Qt.WindowModality.ApplicationModal])
def test_tray_random_keeps_qt_modal_visible_and_shell_keys_blocked(window, modality):
    dialog = QDialog(window)
    dialog.setWindowModality(modality)
    layout = QVBoxLayout(dialog)
    edit = QLineEdit(dialog)
    edit.setText("Unsaved text")
    layout.addWidget(edit)
    dialog.show()
    dialog.activateWindow()
    edit.setFocus()
    QApplication.processEvents()
    try:
        assert QApplication.activeModalWidget() is dialog
        tray_action(window).trigger()
        QApplication.processEvents()
        assert window.player is None and window.core.playback.session is None
        assert window.isVisible() and dialog.isVisible()
        assert QApplication.activeModalWidget() is dialog
        assert QApplication.activeWindow() is dialog
        assert edit.text() == "Unsaved text"
        assert_shell_keys_blocked(window, edit)
        assert dialog.isVisible()
        QTest.keyClick(edit, Qt.Key.Key_Escape)
        assert not dialog.isVisible()
    finally:
        dialog.close()
    tray_action(window).trigger()
    assert window.player is not None


def test_settings_catalog_capture_and_save_random_key(window):
    window.navigate_web_tab("settings")
    settings = window.web_host.controllers["settings"]
    wait_for(lambda: window.loaded)
    payload = json.loads(settings.bridge.snapshot())
    row = next(row for row in payload["bindings"] if row["id"] == "random_play:0")
    assert row["keys"] == ["Ctrl+Shift+R"] and row["note"]
    settings.bridge.beginCapture("random_play:0")
    captured = []
    settings.bridge.keyCaptured.connect(lambda value: captured.append(json.loads(value)))
    random_key(window)
    assert window.player is None
    assert captured[-1]["key"] == "Ctrl+Shift+R"
    draft = {row["id"]: row["keys"] for row in payload["bindings"]}
    draft["random_play:0"] = ["Ctrl+Alt+R"]
    assert "error" not in json.loads(settings.bridge.saveKeys(json.dumps(draft)))
    key(window, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert window.player is not None


@pytest.mark.parametrize("entry", ["key", "tray"])
def test_random_play_remains_available_during_scan(window, entry):
    entered, release = threading.Event(), threading.Event()

    def scan():
        entered.set()
        assert release.wait(15)
        return ScanResult()

    window.scan(operation=scan)
    wait_for(entered.is_set)
    try:
        if entry == "tray":
            window.close()
            tray_action(window).trigger()
        else:
            random_key(window)
        assert window.isVisible() and window.player is not None
        assert not release.is_set()
    finally:
        release.set()
        wait_for(lambda: window.worker is None)


@pytest.mark.parametrize("fullscreen", [False, True])
def test_no_candidates_during_playback_keeps_current_viewing(window, fullscreen):
    random_key(window)
    if fullscreen:
        key(window, Qt.Key.Key_Apostrophe)
    session = window.core.playback.session
    for video in window.core.videos():
        window.core.exclude_video(video.id)
    random_key(window)
    assert window.core.playback.session is session
    assert window.playback_page.message_label.isVisible()
    assert window.playback_page.message_label.text() == NO_CANDIDATE_MESSAGE
    assert window.isFullScreen() is fullscreen

