"""Windows 기본 파일 창이 떠 있어도 긴급 탈출 키를 받는 어댑터.

Windows 기본 파일 열기·저장 창은 자체 메시지 루프를 돌려 Qt 이벤트 필터를 거치지 않는다.
GUI 스레드 키보드 훅으로 키를 보고, 앱 창이 소유한 기본 대화상자에서 긴급 탈출 키가 눌리면
그 대화상자를 취소로 닫고, 대화상자가 사라진 뒤 알린다.
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

_NAMED = {
    0x0D: "Enter", 0x20: "Space", 0x09: "Tab", 0x08: "Backspace", 0x25: "Left", 0x26: "Up",
    0x27: "Right", 0x28: "Down", 0x2D: "Insert", 0x2E: "Delete", 0x24: "Home", 0x23: "End",
    0x21: "PgUp", 0x22: "PgDn", 0x1B: "Esc", 0x13: "Pause", 0x2C: "Print",
}
_MODIFIER_KEYS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def virtual_key_name(vk, character, *, ctrl, alt, shift, meta):
    """Windows 가상 키를 코어 키 배치 이름으로 바꾼다. character는 수정자 없이 눌렀을 때의 글자다.

    Qt 키 이름(`qt_keys.key_name`)과 같은 형식이다. 이름을 붙일 수 없는 키는 None.
    """
    if vk in _MODIFIER_KEYS:
        return None
    if vk in _NAMED:
        name = _NAMED[vk]
    elif 0x70 <= vk <= 0x87:
        name = f"F{vk - 0x70 + 1}"
    elif 0x60 <= vk <= 0x69:
        name = str(vk - 0x60)  # 숫자 패드도 숫자로 다룬다.
    elif character and 33 <= ord(character) <= 126:
        name = character.upper()
    else:
        return None
    return "".join(f"{label}+" for pressed, label in (
        (ctrl, "Ctrl"), (alt, "Alt"), (shift, "Shift"), (meta, "Meta")) if pressed) + name


class NativeDialogEscape:
    """window가 소유한 Windows 기본 대화상자에서 is_emergency(키 이름)이면 취소로 닫고 escaped()를 부른다."""

    def __init__(self, window, is_emergency, escaped):
        self.window, self.is_emergency, self.escaped = window, is_emergency, escaped
        self._hook = None
        self._proc = None
        if QGuiApplication.platformName() == "windows":
            self.install()

    def install(self):
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._user32 = user32
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.GetActiveWindow.restype = wintypes.HWND
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        user32.GetKeyState.restype = ctypes.c_short
        self._proc = proc_type(self._keyboard)
        # WH_KEYBOARD(2) 스레드 훅: 이 GUI 스레드의 모든 메시지 루프(기본 대화상자 포함)에서 호출된다.
        self._hook = user32.SetWindowsHookExW(2, self._proc, None, kernel32.GetCurrentThreadId())

    def uninstall(self):
        if self._hook:
            self._user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _owned_dialog(self):
        """활성 창이 window가 (직접 또는 대화상자를 거쳐) 소유한 Windows 기본 대화상자면 그 핸들."""
        user32 = self._user32
        active = user32.GetActiveWindow()
        if not active:
            return None
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(active, name, 64)
        if name.value != "#32770":
            return None
        owner_target = int(self.window.winId())
        owner = user32.GetWindow(active, 4)  # GW_OWNER
        while owner:
            if owner == owner_target:
                return active
            owner = user32.GetWindow(owner, 4)
        return None

    def _keyboard(self, code, vk, flags):
        user32 = self._user32
        try:
            # HC_ACTION에서 누름(31번 비트 0)만 본다.
            if code == 0 and not flags & (1 << 31) and (dialog := self._owned_dialog()):
                pressed = lambda key: bool(user32.GetKeyState(key) & 0x8000)
                character = chr(user32.MapVirtualKeyW(vk, 2) & 0xFFFF)  # MAPVK_VK_TO_CHAR, 수정자 없는 글자
                name = virtual_key_name(vk, character, ctrl=pressed(0x11), alt=pressed(0x12),
                                        shift=pressed(0x10), meta=pressed(0x5B) or pressed(0x5C))
                if name and self.is_emergency(name):
                    if not flags & (1 << 30):  # 자동 반복이 아닌 첫 누름
                        user32.PostMessageW(dialog, 0x0111, 2, 0)  # WM_COMMAND, IDCANCEL: 취소(저장·선택 안 함)
                        QTimer.singleShot(0, lambda: self._after_closed(dialog))
                    return 1  # 대화상자에 전달하지 않는다.
        except Exception:
            pass  # 훅에서 예외를 내면 키 입력 전체가 멈춘다. 일반 경로로 넘긴다.
        return user32.CallNextHookEx(self._hook, code, vk, flags)

    def _after_closed(self, dialog):
        # 대화상자의 메시지 루프 안에서도 Qt 타이머가 돈다. 대화상자가 실제로 닫힌 뒤 숨긴다.
        if self._user32.IsWindow(dialog):
            QTimer.singleShot(10, lambda: self._after_closed(dialog))
        else:
            self.escaped()
