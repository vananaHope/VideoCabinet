"""사이드바 탐색과 후속 페이지로 교체할 임시 작업 진입 화면."""

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget,
)

PAGE_NAMES = ("라이브러리", "하이라이트 모아보기", "검색", "자막 대기열", "폴더 관리", "설정")


class Sidebar(QWidget):
    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setObjectName("navigation")
        self.list.setAccessibleName("페이지 이동 · Ctrl+1부터 Ctrl+5")
        self.list.setSpacing(4)
        self._current_index = 0
        for index, title in enumerate(PAGE_NAMES[:-1], 1):
            self.list.addItem(f"{title}\nCtrl+{index}")
            self.list.item(index - 1).setSizeHint(QSize(180, 64))
        self.list.setCurrentRow(0)
        self.list.currentRowChanged.connect(self.activate_row)
        self.list.itemClicked.connect(lambda item: self.activate_row(self.list.row(item)))
        self.list.itemActivated.connect(lambda item: self.activate_row(self.list.row(item)))
        layout.addWidget(self.list, 1)
        self.settings = QPushButton("설정  ·  Ctrl+6")
        self.settings.setCheckable(True)
        self.settings.clicked.connect(lambda: self.selected.emit(5))
        layout.addWidget(self.settings)

    def activate_row(self, index):
        if index >= 0 and index != self._current_index:
            self.selected.emit(index)

    def select(self, index):
        self._current_index = index
        self.list.blockSignals(True)
        if index < 5:
            self.list.setCurrentRow(index)
        else:
            # 현재 행까지 지우면 숨김/복귀 중 Qt의 자동 첫 행 선택이 페이지 이동을 일으킨다.
            self.list.clearSelection()
        self.list.blockSignals(False)
        self.settings.setChecked(index == 5)


class ActionPage(QWidget):
    """기존 대화상자·작업을 호출한다. 실제 검색·대기열·폴더 UI는 후속 이슈에서 교체한다."""

    def __init__(self, title, actions, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        self.buttons = []
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch()

    def focus_content(self):
        self.buttons[0].setFocus()


def build_shell(window):
    """페이지 자체의 구현과 별개로 셸에 탐색 목적지를 등록한다."""
    library = window.library_page
    controls = library.library_controls
    search = ActionPage("검색", (("검색 열기", window.show_search),))
    queue = ActionPage("자막 대기열", (("자막 대기열 / 자동 규칙", window.tray.show_queue),))
    folders = ActionPage("폴더 관리", (
        ("감시 폴더 추가", library.add_folder), ("감시 폴더 해제", controls.remove_folder),
        ("다시 검사", window.scan), ("파일 직접 추가", controls.add_file),
        ("제외 목록", controls.show_excluded), ("최소 길이 설정", controls.settings),
        ("관심 없음 되돌리기", library.hidden_gems.show_dismissed),
        ("선택 영상 제목 변경", controls.rename), ("선택 영상 파일 다시 연결", controls.reconnect),
    ))
    library.scan_state_changed.connect(folders.setDisabled)
    settings = ActionPage("설정", (
        ("키 배치…", window.show_settings),
        ("번역 CLI / 재시도", window.translations.settings),
        ("완전 종료", window.tray.quit),
    ))
    for page in (search, queue, folders, settings):
        window.pages.addWidget(page)
    window.navigation_pages = (library, window.reel.page, search, queue, folders, settings)
    root = QWidget()
    layout = QHBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    window.sidebar = Sidebar()
    window.sidebar.selected.connect(window.navigate)
    layout.addWidget(window.sidebar)
    layout.addWidget(window.pages, 1)
    window.setCentralWidget(root)
