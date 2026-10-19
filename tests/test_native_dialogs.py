"""Windows 기본 파일 창 어댑터: Qt와 같은 키 이름, 가짜 Win32 경계로 훅 수명과 긴급 탈출."""

import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest

from my_video_manager.native_dialogs import NativeDialogEscape
from test_emergency_hide_ui import app, open_window, play_to_twenty_seconds
from qt_wait import wait_for


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 키 매퍼 대조")
def test_native_key_names_match_qt_capture_names():
    """같은 가상 키·수정자를 실제 Qt Windows 키 매퍼(qt_keys.key_name)와 네이티브 이름으로 만들어 대조한다.

    문자·숫자·기호(Shift 적용 글자 포함)·숫자 패드·기능키·방향키, Ctrl·Alt·Shift·Win 조합.
    """
    probe = Path(__file__).with_name("windows_key_probe.py")
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, encoding="utf-8",
                            env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    rows = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(rows) > 150 and all(row["qt"] for row in rows)
    assert [row for row in rows if row["qt"] != row["native"]] == []
    names = {row["qt"] for row in rows}
    # 리뷰에서 어긋났던 Shift 적용 기호가 대조 대상에 들어 있다.
    assert {"Ctrl+Shift+:", "Ctrl+Shift+!", "Ctrl+Shift+_", "Ctrl+Alt+Shift+?"} <= names


class FakeWin32:
    """Win32Dialogs와 같은 공개 메서드를 가진 가짜 경계. 훅 콜백으로 키를 누르고 대화상자를 연다·닫는다."""

    def __init__(self, *, install_fails=False):
        self.install_fails = install_fails
        self.installs, self.removed, self.cancelled = [], [], []
        self.pressed = None
        self.dialog = None
        self.name = None
        self.open = set()

    def install_hook(self, pressed):
        self.installs.append(pressed)
        if self.install_fails:
            return None
        self.pressed = pressed
        return f"hook-{len(self.installs)}"

    def remove_hook(self, hook):
        self.removed.append(hook)
        self.pressed = None

    def owned_dialog(self, owner):
        return self.dialog

    def key_name(self, vk):
        return self.name

    def cancel(self, dialog):
        self.cancelled.append(dialog)

    def is_window(self, dialog):
        return dialog in self.open

    def show_dialog(self, dialog="dialog-1"):
        self.dialog = dialog
        self.open.add(dialog)

    def close_dialog(self):
        self.open.discard(self.dialog)
        self.dialog = None

    def press(self, name, *, repeat=False):
        self.name = name
        return self.pressed(0x48, repeat)


@pytest.fixture
def fake(tmp_path, app, monkeypatch, request):
    system = FakeWin32(**getattr(request, "param", {}))
    opened = open_window(tmp_path, app, monkeypatch,
                         native_dialogs_factory=lambda window, is_emergency, escaped:
                         NativeDialogEscape(window, is_emergency, escaped, system))
    window = next(opened)
    yield window, system
    opened.close()


def test_emergency_key_in_owned_native_dialog_cancels_then_hides_after_it_closes(fake):
    window, system = fake
    _, player = play_to_twenty_seconds(window)
    assert window.native_dialogs.installed and len(system.installs) == 1
    system.show_dialog()
    assert system.press("Ctrl+Shift+H") is True  # 대화상자에 넘기지 않는다.
    assert system.cancelled == ["dialog-1"]
    QTest.qWait(100)
    # 대화상자가 아직 닫히는 중이면 숨기지 않는다.
    assert window.isVisible() and not player.paused
    assert system.press("Ctrl+Shift+H", repeat=True) is True and system.cancelled == ["dialog-1"]
    system.close_dialog()
    wait_for(lambda: not window.isVisible())
    assert player.paused and window.balloons == []


def test_other_keys_and_unowned_windows_pass_through(fake):
    window, system = fake
    assert system.press("Ctrl+Shift+H") is False  # 앱 창이 소유한 기본 대화상자가 없다.
    system.show_dialog()
    assert system.press("Ctrl+Shift+J") is False and system.press(None) is False
    assert system.cancelled == [] and window.isVisible()


def test_install_is_idempotent_and_quit_removes_the_hook(fake):
    window, system = fake
    escape = window.native_dialogs
    assert escape.install() and escape.install()
    assert len(system.installs) == 1
    window.tray.quit()
    assert system.removed == ["hook-1"] and not escape.installed
    escape.uninstall()
    assert system.removed == ["hook-1"]


def test_quit_while_waiting_for_dialog_to_close_does_not_hide_later(fake):
    window, system = fake
    escaped = []
    escape = window.native_dialogs
    escape.escaped = lambda: escaped.append(True)
    system.show_dialog()
    assert system.press("Ctrl+Shift+H")
    escape.uninstall()  # 앱 종료 중
    system.close_dialog()
    QTest.qWait(100)
    assert escaped == [] and system.removed == ["hook-1"] and system.pressed is None


@pytest.mark.parametrize("fake", [{"install_fails": True}], indirect=True)
def test_failed_install_leaves_the_app_working(fake):
    window, system = fake
    escape = window.native_dialogs
    assert not escape.installed and len(system.installs) == 1
    # Qt 경로의 긴급 탈출은 그대로 동작하고, 종료 때 풀 훅이 없다.
    from test_emergency_hide_ui import emergency_key
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    window.tray.quit()
    assert system.removed == []
