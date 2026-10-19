"""Windows 기본 파일 창이 떠 있어도 긴급 탈출 키를 받는 어댑터.

Windows 기본 파일 열기·저장 창은 자체 메시지 루프를 돌려 Qt 이벤트 필터를 거치지 않는다.
GUI 스레드 키보드 훅으로 키를 보고, 앱 창이 소유한 기본 대화상자에서 긴급 탈출 키가 눌리면
그 대화상자를 취소로 닫고, 대화상자가 사라진 뒤 알린다. Win32 호출은 `Win32Dialogs` 경계 뒤에 둔다.
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


def windows_key_name(vk, translate, base, *, ctrl, alt, shift, meta):
    """Windows 가상 키를 Qt 캡처(`qt_keys.key_name`)와 같은 코어 키 배치 이름으로 바꾼다.

    translate(shift, ctrl, alt)는 그 수정자 상태에서 현재 키보드 배열이 내는 글자(없으면 ''),
    base는 수정자 없이 눌렀을 때의 글자다. Qt Windows 키 매퍼처럼 Ctrl 상태에서 글자가 없으면
    Ctrl을 빼고 다시 보고(Ctrl+Shift+; → :), Ctrl 제어 문자는 원래 글자로 되돌린다(Ctrl+H → H).
    이름을 붙일 수 없는 키는 None.
    """
    if vk in _MODIFIER_KEYS:
        return None
    if vk in _NAMED:
        name = _NAMED[vk]
    elif 0x70 <= vk <= 0x87:
        name = f"F{vk - 0x70 + 1}"
    else:
        text = translate(shift, ctrl, alt) or (translate(shift, False, alt) if ctrl else "")
        code = ord(text[0].upper()) if text else 0
        if code < 0x20 and ctrl and text:
            code += 0x40  # Ctrl 제어 문자는 Qt처럼 원래 글자로 되돌린다(Ctrl+Shift+- → 0x1F → _).
        if code < 0x20 or code == 0x7F:
            code = ord(base.upper()) if base else 0
        if not 33 <= code <= 126:
            return None
        name = chr(code)
    return "".join(f"{label}+" for pressed, label in (
        (ctrl, "Ctrl"), (alt, "Alt"), (shift, "Shift"), (meta, "Meta")) if pressed) + name


class Win32Dialogs:
    """NativeDialogEscape가 쓰는 Win32 호출. 처음 쓸 때 user32를 읽는다."""

    def __init__(self):
        self._user32 = None
        self._procs = {}

    @property
    def user32(self):
        if self._user32 is None:
            user32 = ctypes.windll.user32
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
            user32.GetActiveWindow.restype = wintypes.HWND
            user32.GetWindow.restype = wintypes.HWND
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.GetKeyState.restype = ctypes.c_short
            user32.GetKeyboardLayout.restype = wintypes.HKL
            user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
            user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.LPWSTR,
                                           ctypes.c_int, wintypes.UINT, wintypes.HKL]
            self._user32 = user32
        return self._user32

    def install_hook(self, pressed):
        """GUI 스레드 키보드 훅을 건다. pressed(vk, repeat)가 참이면 그 키를 소비한다. 실패하면 None."""
        user32 = self.user32
        handle = []

        @ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        def proc(code, vk, flags):
            try:
                # HC_ACTION에서 누름(31번 비트 0)만 본다. 30번 비트는 자동 반복이다.
                if code == 0 and not flags & (1 << 31) and pressed(vk, bool(flags & (1 << 30))):
                    return 1
            except Exception:
                pass  # 훅에서 예외를 내면 키 입력 전체가 멈춘다. 일반 경로로 넘긴다.
            return user32.CallNextHookEx(handle[0] if handle else None, code, vk, flags)
        # WH_KEYBOARD(2) 스레드 훅: 이 GUI 스레드의 모든 메시지 루프(기본 대화상자 포함)에서 호출된다.
        hook = user32.SetWindowsHookExW(2, ctypes.cast(proc, ctypes.c_void_p), None,
                                        ctypes.windll.kernel32.GetCurrentThreadId())
        if not hook:
            return None
        handle.append(hook)
        self._procs[hook] = proc  # 해제할 때까지 콜백을 살려 둔다.
        return hook

    def remove_hook(self, hook):
        self.user32.UnhookWindowsHookEx(hook)
        self._procs.pop(hook, None)

    def owned_dialog(self, owner):
        """활성 창이 owner가 (직접 또는 다른 창을 거쳐) 소유한 Windows 기본 대화상자면 그 핸들."""
        user32 = self.user32
        active = user32.GetActiveWindow()
        if not active:
            return None
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(active, name, 64)
        if name.value != "#32770":
            return None
        node = user32.GetWindow(active, 4)  # GW_OWNER
        while node:
            if node == owner:
                return active
            node = user32.GetWindow(node, 4)
        return None

    def key_name(self, vk):
        """지금 눌린 수정자와 현재 키보드 배열로 만든 코어 키 배치 이름."""
        user32 = self.user32
        pressed = lambda key: bool(user32.GetKeyState(key) & 0x8000)
        layout = user32.GetKeyboardLayout(0)
        scan = user32.MapVirtualKeyExW(vk, 0, layout)  # MAPVK_VK_TO_VSC

        def translate(shift, ctrl, alt):
            state = (ctypes.c_ubyte * 256)()
            for down, keys in ((shift, (0x10, 0xA0)), (ctrl, (0x11, 0xA2)), (alt, (0x12, 0xA4))):
                for key in keys if down else ():
                    state[key] = 0x80
            text = ctypes.create_unicode_buffer(8)
            # 4: 데드 키 상태를 바꾸지 않는다.
            count = user32.ToUnicodeEx(vk, scan, state, text, 8, 4, layout)
            return text.value[:count] if count > 0 else ""
        base = chr(user32.MapVirtualKeyExW(vk, 2, layout) & 0xFFFF)  # MAPVK_VK_TO_CHAR
        return windows_key_name(vk, translate, base.strip("\0"), ctrl=pressed(0x11), alt=pressed(0x12),
                                shift=pressed(0x10), meta=pressed(0x5B) or pressed(0x5C))

    def cancel(self, dialog):
        self.user32.PostMessageW(dialog, 0x0111, 2, 0)  # WM_COMMAND, IDCANCEL: 취소(저장·선택 안 함)

    def is_window(self, dialog):
        return bool(self.user32.IsWindow(dialog))


class NativeDialogEscape:
    """window가 소유한 Windows 기본 대화상자에서 is_emergency(키 이름)이면 취소로 닫고 escaped()를 부른다.

    system은 Win32 경계다(None이면 아무것도 하지 않는다). install()로 훅을 걸고 uninstall()로 푼다.
    """

    def __init__(self, window, is_emergency, escaped, system):
        self.window, self.is_emergency, self.escaped, self.system = window, is_emergency, escaped, system
        self._hook = None
        self._closing = []
        self._timer = QTimer(window)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._check_closed)

    @property
    def installed(self):
        return self._hook is not None

    def install(self):
        if self.system is not None and self._hook is None:
            self._hook = self.system.install_hook(self.key_pressed)
        return self.installed

    def uninstall(self):
        """훅을 풀고, 닫히기를 기다리던 대화상자의 숨기기 예약도 버린다(앱 종료 중)."""
        self._timer.stop()
        self._closing.clear()
        if self._hook is not None:
            hook, self._hook = self._hook, None
            self.system.remove_hook(hook)

    def key_pressed(self, vk, repeat):
        """훅이 부른다. 앱 창이 소유한 기본 대화상자에서 긴급 탈출 키면 소비한다."""
        dialog = self.system.owned_dialog(int(self.window.winId()))
        if not dialog or not self.is_emergency(self.system.key_name(vk)):
            return False
        if not repeat and dialog not in self._closing:
            self.system.cancel(dialog)
            self._closing.append(dialog)
            # 대화상자의 메시지 루프 안에서도 Qt 타이머가 돈다. 대화상자가 실제로 닫힌 뒤 숨긴다.
            self._timer.start()
        return True

    def _check_closed(self):
        self._closing = [dialog for dialog in self._closing if self.system.is_window(dialog)]
        if not self._closing:
            self._timer.stop()
            self.escaped()


def native_dialog_escape(window, is_emergency, escaped):
    """기본 어댑터. Windows 플랫폼에서만 Win32 경계를 쓴다."""
    system = Win32Dialogs() if QGuiApplication.platformName() == "windows" else None
    return NativeDialogEscape(window, is_emergency, escaped, system)
