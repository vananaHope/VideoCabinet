"""감시 폴더와 검사 안내. 영상별 작업은 라이브러리 상세에서만 제공한다."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)


class FolderPage(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        library = window.library_page
        controls = library.library_controls
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("폴더 관리"))
        layout.addWidget(QLabel("감시 폴더의 하위 폴더까지 검사합니다. 해제해도 실제 파일과 영상 기록은 남습니다."))
        self.folders = QListWidget()
        self.folders.setAccessibleName("감시 폴더 목록")
        layout.addWidget(self.folders, 1)
        operations = QHBoxLayout()
        self.scan_buttons = []
        for title, callback in (("감시 폴더 추가", library.add_folder), ("선택 폴더 해제", self.remove_folder),
                                ("다시 검사", window.scan), ("파일 직접 추가", controls.add_file)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            operations.addWidget(button)
            self.scan_buttons.append(button)
        layout.addLayout(operations)
        self.minimum = QLabel()
        layout.addWidget(self.minimum)
        other = QHBoxLayout()
        self.other_buttons = []
        for title, callback in (("제외 목록", controls.show_excluded), ("최소 길이 설정", controls.settings),
                                ("관심 없음 되돌리기", library.hidden_gems.show_dismissed),
                                ("모든 태그 관리", library.manage_tags)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            other.addWidget(button)
            self.other_buttons.append(button)
            if title in ("제외 목록", "최소 길이 설정"):
                # 복원과 최소 길이 변경도 Library의 검사 잠금을 사용한다.
                self.scan_buttons.append(button)
        layout.addLayout(other)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setAccessibleName("영상 검사 중")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setAccessibleName("검사 진행 상태와 안내")
        self.report.setPlainText("폴더를 추가하면 자동으로 검사합니다. 파일을 옮긴 뒤에는 다시 검사를 누르세요.")
        layout.addWidget(self.report, 1)
        library.scan_state_changed.connect(self.scan_state_changed)
        library.scan_message.connect(self.report.setPlainText)
        library.refreshed.connect(self.refresh)
        self.folders.currentRowChanged.connect(self.update_remove_button)
        self.refresh()

    def refresh(self):
        item = self.folders.currentItem()
        selected = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.folders.clear()
        for folder in self.core.watched_folders():
            item = QListWidgetItem(str(folder.path))
            item.setData(Qt.ItemDataRole.UserRole, str(folder.path))
            self.folders.addItem(item)
            if str(folder.path) == selected:
                self.folders.setCurrentItem(item)
        if self.folders.currentRow() < 0:
            self.folders.setCurrentRow(0)
        self.minimum.setText(f"새 영상의 최소 길이: {self.core.minimum_duration:g}초 · 기존 영상은 유지합니다.")
        self.update_remove_button()

    def update_remove_button(self, *_):
        self.scan_buttons[1].setEnabled(self.folders.currentItem() is not None and self.window.worker is None)

    def remove_folder(self):
        if item := self.folders.currentItem():
            self.window.library_page.library_controls.remove_folder(item.data(Qt.ItemDataRole.UserRole))

    def scan_state_changed(self, running):
        for button in self.scan_buttons:
            button.setEnabled(not running)
        self.progress.setVisible(running)
        self.update_remove_button()

    def handle_key(self, event) -> bool:
        return False

    def focus_content(self):
        self.folders.setFocus()
