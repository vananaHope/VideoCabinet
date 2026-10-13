"""키 캡처와 키 배치 편집 화면. 저장·검사는 AppCore 공개 API로 전달한다."""

import sqlite3

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)


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


class KeyCapture(QDialog):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.key = None
        self.setWindowTitle("새 키 입력")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{label}\n할당할 키를 누르세요. Esc로 취소합니다."))
        self.hint = QLabel("문자·숫자·방향키·기능키와 Ctrl/Alt/Shift 조합을 사용할 수 있습니다.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
            elif name := key_name(event):
                self.key = name
                self.accept()
            else:
                self.hint.setText("지원하는 키를 누르세요. 조합키는 Ctrl/Alt/Shift와 함께 누르세요. Esc로 취소합니다.")
            return True
        return super().event(event)


class KeySettings(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.rows = core.key_bindings()
        self.draft = {row.command: row.keys for row in self.rows}
        layout = QVBoxLayout(self)
        hint = QLabel("명령을 방향키로 고른 뒤 Enter 또는 ‘키 바꾸기’를 누르세요.\n"
                      "Tab으로 버튼에 이동하고 Space로 실행합니다. 변경은 ‘적용’ 또는 ‘저장 후 닫기’로 저장합니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(len(self.rows), 3)
        self.table.setHorizontalHeaderLabels(["명령", "현재 키", "기본 키"])
        self.table.setAccessibleName("명령별 키 배치")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setTabKeyNavigation(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemActivated.connect(self.capture)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for label, callback in (("키 바꾸기", self.capture), ("선택 명령 기본값", self.reset_selected),
                                ("전체 기본값", self.reset_all)):
            button = QPushButton(label)
            # 표의 Enter가 자동 기본 버튼으로 전파되어 캡처를 두 번 열지 않게 한다.
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        note = QLabel("Home/End는 현재 화면의 하이라이트, PgUp/PgDn은 시리즈·현재 목록에 따라 동작합니다.\n"
                      "Esc는 취소·목록 복귀 전용입니다. 목록 탐색과 편집 대화상자의 키는 바뀌지 않습니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.refresh()
        self.table.setCurrentCell(0, 0)
        self.setFocusProxy(self.table)

    def refresh(self):
        for index, row in enumerate(self.rows):
            for column, text in enumerate((row.label, " / ".join(self.draft[row.command]) or "미할당",
                                           " / ".join(row.default_keys) or "미할당")):
                self.table.setItem(index, column, QTableWidgetItem(text))

    def capture(self, *_):
        index = self.table.currentRow()
        if index < 0:
            return
        row = self.rows[index]
        dialog = KeyCapture(row.label, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.draft[row.command] = (dialog.key,)
            self.refresh()
        self.table.setFocus()

    def reset_selected(self):
        index = self.table.currentRow()
        if index >= 0:
            row = self.rows[index]
            self.draft[row.command] = row.default_keys
            self.refresh()

    def reset_all(self):
        self.draft = {row.command: row.default_keys for row in self.rows}
        self.refresh()

    def save(self):
        try:
            self.core.save_key_bindings(self.draft)
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "키 배치를 저장할 수 없습니다", str(error))
            return False
        return True


class SettingsDialog(QDialog):
    """후속 설정 항목은 탭을 추가한다."""
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(760, 650)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.keys = KeySettings(core)
        self.tabs.addTab(self.keys, "키 배치")
        layout.addWidget(self.tabs)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for label, callback in (("적용", self.keys.save), ("저장 후 닫기", self.save_and_close), ("취소", self.reject)):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.keys.table.setFocus()

    def save_and_close(self):
        if self.keys.save():
            self.accept()
