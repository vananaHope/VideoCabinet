"""Qt Windows 키 매퍼(qt_keys.key_name)와 Win32Dialogs.key_name을 같은 가상 키·수정자로 대조한다.

test_native_dialogs.py가 windows 플랫폼 하위 프로세스로 실행한다. 창은 화면 밖 투명 창이라 보이지 않고 초점도 옮기지 않는다.
이 스레드의 키보드 상태(SetKeyboardState)로 수정자를 정하고 키 메시지를 숨은 Qt 창에 보낸다.
"""
import ctypes
from ctypes import wintypes
import json
import os

os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

from my_video_manager.native_dialogs import Win32Dialogs
from my_video_manager.qt_keys import key_name

KEYS = [0x48, 0x41, 0x5A, 0x31, 0x30, 0x32, 0x36, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE,
        0x61, 0x69, 0x6A, 0x6B, 0x6D, 0x6E, 0x6F, 0x74, 0x25, 0x20, 0x2E]
EXTENDED = {0x25, 0x2E, 0x6F}
MODIFIERS = [("Ctrl",), ("Ctrl", "Shift"), ("Alt",), ("Alt", "Shift"), ("Ctrl", "Alt"), ("Ctrl", "Meta"), ("Shift", "Meta"),
             ("Ctrl", "Alt", "Shift")]
VK = {"Ctrl": (0x11, 0xA2), "Shift": (0x10, 0xA0), "Alt": (0x12, 0xA4), "Meta": (0x5B,)}

user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetKeyboardState.argtypes = [ctypes.c_void_p]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]


class Capture(QObject):
    def __init__(self):
        super().__init__()
        self.names = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            self.names.append(key_name(event))
        return False


def set_modifiers(modifiers):
    state = (ctypes.c_ubyte * 256)()
    for modifier in modifiers:
        for vk in VK[modifier]:
            state[vk] = 0x80
    user32.SetKeyboardState(state)


app = QApplication([])
# Qt는 보이지 않는 창에 키 이벤트를 넘기지 않는다. 화면 밖에 투명하고 활성화되지 않는 도구 창으로 띄운다.
widget = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
widget.setWindowOpacity(0)
widget.setGeometry(-32000, -32000, 10, 10)
widget.show()
app.processEvents()
hwnd = int(widget.winId())
capture = Capture()
app.installEventFilter(capture)
native = Win32Dialogs()
rows = []
for modifiers in MODIFIERS:
    for vk in KEYS:
        if vk == 0x20 and "Alt" in modifiers:
            continue  # Alt+Space는 Windows 창 메뉴를 연다.
        set_modifiers(modifiers)
        scan = user32.MapVirtualKeyW(vk, 0)
        alt = "Alt" in modifiers
        flags = 1 | (scan << 16) | ((1 << 24) if vk in EXTENDED else 0) | ((1 << 29) if alt else 0)
        capture.names.clear()
        user32.PostMessageW(hwnd, 0x0104 if alt else 0x0100, vk, flags)  # WM_SYSKEYDOWN / WM_KEYDOWN
        for _ in range(20):
            app.processEvents()
            if capture.names:
                break
        set_modifiers(modifiers)  # 메시지 처리 뒤의 상태를 다시 맞춘다(훅이 볼 때와 같은 상태).
        rows.append({"vk": vk, "modifiers": list(modifiers), "qt": capture.names[0] if capture.names else None,
                     "native": native.key_name(vk)})
        set_modifiers(())
        user32.PostMessageW(hwnd, 0x0105 if alt else 0x0101, vk, flags | (3 << 30))  # 뗌
        for _ in range(5):
            app.processEvents()
set_modifiers(())
print(json.dumps(rows, ensure_ascii=False))
