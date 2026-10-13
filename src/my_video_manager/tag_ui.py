"""태그 편집 화면. 이름 정책과 연결 변경은 AppCore에 맡긴다."""

import sqlite3

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .tag_editing import resolve_tag_input


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
        help_text = QLabel("Enter로 입력한 이름을 추가합니다. 후보를 쓰려면 ↓/↑로 고른 뒤 Enter를 누르세요.\n"
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
        self.selected_candidate = None
        self.name.textEdited.connect(self.complete)
        self.completer.activated[str].connect(self.add_candidate)
        # Qt의 자동 선정을 명시적인 사용자 선택과 구분하고 Enter를 한 번만 처리한다.
        self.name.installEventFilter(self)
        self.completer.popup().installEventFilter(self)
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
        self.selected_candidate = None
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

    def add_candidate(self, candidate):
        self.name.setText(candidate)
        self.add()

    def eventFilter(self, watched, event):
        popup = self.completer.popup()
        if watched in (self.name, popup) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                name = resolve_tag_input(self.name.text(), self.selected_candidate if popup.isVisible() else None)
                popup.hide()
                self.name.setText(name)
                self.add()
                return True
            if popup.isVisible() and key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = popup.model().rowCount()
                if count:
                    step = 1 if key == Qt.Key.Key_Down else -1
                    if self.selected_candidate is None:
                        row = 0 if step == 1 else count - 1
                    else:
                        row = (popup.currentIndex().row() + step) % count
                    index = popup.model().index(row, 0)
                    popup.setCurrentIndex(index)
                    self.selected_candidate = index.data()
                return True
            if key == Qt.Key.Key_Escape:
                self.selected_candidate = None
        return super().eventFilter(watched, event)

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
