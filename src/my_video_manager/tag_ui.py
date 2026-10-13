"""태그 편집 화면. 이름 정책과 연결 변경은 AppCore에 맡긴다."""

import sqlite3

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)


def _button(text, callback):
    button = QPushButton(text)
    button.setAutoDefault(False)
    button.clicked.connect(callback)
    return button


class TagManager(QDialog):
    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("모든 태그 관리")
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("이름 변경과 삭제는 모든 영상·하이라이트에 적용됩니다."))
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.rename_button = _button("이름 변경", self.rename)
        self.delete_button = _button("태그 삭제", self.delete)
        for button in (self.rename_button, self.delete_button, _button("닫기", self.accept)):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        row = self.list.currentRow()
        self.list.clear()
        for tag in self.core.tags():
            item = QListWidgetItem(tag.name)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.list.addItem(item)
        self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        self.rename_button.setEnabled(self.list.count() > 0)
        self.delete_button.setEnabled(self.list.count() > 0)

    def rename(self):
        if item := self.list.currentItem():
            tag = item.data(Qt.ItemDataRole.UserRole)
            name, accepted = QInputDialog.getText(self, "태그 이름 변경", "새 이름", text=tag.name)
            if accepted:
                try:
                    self.core.rename_tag(tag.id, name)
                except (ValueError, OSError, sqlite3.Error) as error:
                    QMessageBox.warning(self, "태그 이름 변경 실패", str(error))
                self.refresh()

    def delete(self):
        if item := self.list.currentItem():
            tag = item.data(Qt.ItemDataRole.UserRole)
            answer = QMessageBox.question(self, "태그 삭제",
                                          f"‘{tag.name}’ 태그를 모든 영상·하이라이트에서 삭제할까요?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    self.core.delete_tag(tag.id)
                except (ValueError, OSError, sqlite3.Error) as error:
                    QMessageBox.warning(self, "태그 삭제 실패", str(error))
                self.refresh()


class TagEditor(QDialog):
    def __init__(self, core, *, video_id=None, highlight_id=None, parent=None):
        super().__init__(parent)
        self.core = core
        if (video_id is None) == (highlight_id is None):
            raise ValueError("영상 또는 하이라이트 하나를 지정하세요.")
        if video_id is not None:
            self.identifier = video_id
            self.list_tags, self.add_tag, self.remove_tag = core.video_tags, core.add_video_tag, core.remove_video_tag
            self.setWindowTitle("영상 태그")
        else:
            self.identifier = highlight_id
            self.list_tags, self.add_tag, self.remove_tag = core.highlight_tags, core.add_highlight_tag, core.remove_highlight_tag
            self.setWindowTitle("하이라이트 태그")
        self.resize(500, 400)
        layout = QVBoxLayout(self)
        help_text = QLabel("이름 입력 후 Enter로 추가합니다. 자동 완성은 ↓/↑와 Enter로 고르세요.\n"
                           "Tab으로 이동해 버튼을 Space로 누를 수 있습니다. 변경은 즉시 저장됩니다.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        entry = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("새 태그 또는 기존 태그 이름")
        self.name.setAccessibleName("태그 이름")
        self.suggestions = QStringListModel(self)
        self.completer = QCompleter(self.suggestions, self)
        # 후보는 코어가 정규화된 접두어로 고른다. Qt에서 다시 필터링하지 않는다.
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.name.setCompleter(self.completer)
        self.name.textEdited.connect(self.complete)
        self.name.returnPressed.connect(self.add_from_keyboard)
        entry.addWidget(self.name)
        entry.addWidget(_button("추가", self.add))
        layout.addLayout(entry)
        self.list = QListWidget()
        self.list.setAccessibleName("붙어 있는 태그")
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.remove_button = _button("선택한 태그 떼기", self.remove)
        for button in (self.remove_button, _button("모든 태그 관리", self.manage), _button("닫기", self.accept)):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.refresh()
        self.name.setFocus()

    def complete(self, text):
        self.suggestions.setStringList([tag.name for tag in self.core.tags(text)])

    def refresh(self):
        row = self.list.currentRow()
        self.list.clear()
        for tag in self.list_tags(self.identifier):
            item = QListWidgetItem(tag.name)
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            self.list.addItem(item)
        self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        self.remove_button.setEnabled(self.list.count() > 0)
        self.complete(self.name.text())

    def add(self):
        try:
            self.add_tag(self.identifier, self.name.text())
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "태그 추가 실패", str(error))
            return
        self.name.clear()
        self.refresh()
        self.name.setFocus()

    def add_from_keyboard(self):
        # QCompleter가 후보를 확정하기 전에도 QLineEdit.returnPressed가 발생한다.
        # 팝업의 Enter는 후보 선택에만 쓰고 다음 Enter에서 연결을 저장한다.
        if not self.completer.popup().isVisible():
            self.add()

    def remove(self):
        if item := self.list.currentItem():
            try:
                self.remove_tag(self.identifier, item.data(Qt.ItemDataRole.UserRole))
            except (ValueError, OSError, sqlite3.Error) as error:
                QMessageBox.warning(self, "태그 떼기 실패", str(error))
            self.refresh()

    def manage(self):
        TagManager(self.core, self).exec()
        self.refresh()
