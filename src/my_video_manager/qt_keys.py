"""Qt 입력을 코어 키 배치 이름으로 변환한다."""
from PySide6.QtCore import Qt


def key_name(event):
    """캡처와 재생이 같은 Qt 키 이름을 사용한다. 숫자 패드도 동일하게 처리한다."""
    key = event.key()
    name = {
        Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Space: "Space",
        Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab", Qt.Key.Key_Backspace: "Backspace",
        Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right", Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down",
        Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete", Qt.Key.Key_Home: "Home",
        Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "PgUp", Qt.Key.Key_PageDown: "PgDn",
        Qt.Key.Key_Escape: "Esc", Qt.Key.Key_Pause: "Pause", Qt.Key.Key_Print: "Print",
    }.get(key)
    if name is None:
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            name = f"F{key - Qt.Key.Key_F1 + 1}"
        elif 33 <= key <= 126:
            name = chr(key).upper()
        else:
            return None
    modifiers = event.modifiers()
    return "".join(f"{label}+" for modifier, label in (
        (Qt.KeyboardModifier.ControlModifier, "Ctrl"), (Qt.KeyboardModifier.AltModifier, "Alt"),
        (Qt.KeyboardModifier.ShiftModifier, "Shift"), (Qt.KeyboardModifier.MetaModifier, "Meta"),
    ) if modifiers & modifier) + name
