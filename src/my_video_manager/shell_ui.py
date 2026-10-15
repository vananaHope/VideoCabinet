"""사이드바 탐색과 후속 페이지로 교체할 임시 작업 진입 화면.

페이지는 handle_key(event) -> bool을 둘 수 있으며, 처리한 키에는 True를 돌려준다.
focus_content()는 페이지의 주 작업 영역으로 포커스를 옮긴다. 웹 내부 키는 웹 페이지가 처리한다.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from .dialog_ui import space_layout
from .theme import MUTED_TEXT, TEXT, hint_label, page_title, with_role

PAGE_NAMES = ("라이브러리", "하이라이트 모아보기", "검색", "자막 대기열", "폴더 관리", "설정")
SEARCH_PAGE_INDEX = PAGE_NAMES.index("검색")
QUEUE_PAGE_INDEX = PAGE_NAMES.index("자막 대기열")


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
        self.list.setItemDelegate(NavigationDelegate(self.list))
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


class NavigationDelegate(QStyledItemDelegate):
    """페이지 이름은 본문 색, 단축키는 흐린 색으로 그린다. 선택·포커스 표시는 스타일시트가 그린다."""

    def paint(self, painter, option, index):
        title, _, shortcut = index.data().partition("\n")
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        rect = option.rect.adjusted(16, 10, -8, -10)
        painter.save()
        painter.setPen(QColor(TEXT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
        painter.setPen(QColor(MUTED_TEXT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, shortcut)
        painter.restore()


class ActionPage(QWidget):
    """제목·설명과 버튼 하나로 된 작업 줄을 모은 페이지. role="danger"는 되돌릴 수 없는 작업이다."""

    def __init__(self, title, actions, parent=None):
        super().__init__(parent)
        layout = space_layout(QVBoxLayout(self))
        layout.addWidget(page_title(title))
        self.buttons = []
        for name, description, label, callback, *role in actions:
            card = with_role(QFrame(), "card")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 10, 14, 10)
            text = QVBoxLayout()
            text.addWidget(with_role(QLabel(name), "sectionTitle"))
            text.addWidget(hint_label(description))
            row.addLayout(text, 1)
            button = QPushButton(label)
            button.setMinimumWidth(120)
            button.clicked.connect(callback)
            if role:
                with_role(button, role[0])
            row.addWidget(button)
            layout.addWidget(card)
            self.buttons.append(button)
        layout.addStretch()

    def handle_key(self, event) -> bool:
        return False

    def focus_content(self):
        self.buttons[0].setFocus()


def search_page(window):
    from .search_ui import SearchPage

    preparation = window.web_host.controllers['search'].preparation if window.web_ui else None
    page = SearchPage(window.core, preparation=preparation)

    def play_result(result):
        window.playback_list = page.video_ids
        window.play_video(result.video_id, start=result.start)

    page.result_chosen.connect(play_result)
    return page


def queue_page(window):
    from .queue_ui import SubtitleQueuePage

    return SubtitleQueuePage(window.core)


def folder_page(window):
    from .folder_page import FolderPage
    return FolderPage(window)


def settings_page(window):
    return ActionPage("설정", (
        ("키 배치", "재생 명령마다 쓸 키를 바꿉니다. 설정 메뉴는 어디서든 Alt+S로도 열 수 있습니다.",
         "키 배치…", window.show_settings),
        ("번역 CLI", "번역에 쓸 구독 CLI를 고르고, 보류된 번역을 다시 시도합니다.",
         "번역 CLI / 재시도", window.translations.settings),
        ("완전 종료", "창을 닫으면 트레이로 숨습니다. 자막 처리를 멈추고 앱을 끝내려면 여기서 종료합니다.",
         "완전 종료", window.tray.quit, "danger"),
    ))


def build_shell(window):
    """페이지 자체의 구현과 별개로 셸에 탐색 목적지를 등록한다."""
    library = window.home_page
    search = search_page(window)
    queue = queue_page(window)
    folders = folder_page(window)
    settings = settings_page(window)
    for page in (search, queue, folders, settings):
        window.pages.addWidget(page)
    window.navigation_pages = (library, window.reel.page, search, queue, folders, settings)
    root = QWidget()
    layout = QVBoxLayout(root) if window.web_ui else QHBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    window.sidebar = Sidebar(root)
    window.sidebar.selected.connect(window.navigate)
    if window.web_ui:
        window.sidebar.hide()
        window.web_return_bar = QWidget()
        return_layout = QVBoxLayout(window.web_return_bar)
        back_layout = QHBoxLayout()
        return_layout.addLayout(back_layout)
        back = QPushButton("← 웹 화면으로 돌아가기 (Esc)")
        back.clicked.connect(window.return_to_web)
        back_layout.addWidget(back)
        back_layout.addWidget(QLabel("페이지 이동 Ctrl+1~7 · 설정 Alt+S"))
        back_layout.addStretch()
        window.web_notice = QLabel()
        window.web_notice.setWordWrap(True)
        window.web_notice.setAccessibleName("작업 알림")
        window.web_notice.hide()
        return_layout.addWidget(window.web_notice)
        window.statusBar().messageChanged.connect(window.web_notice.setText)
        window.statusBar().messageChanged.connect(lambda text: window.web_notice.setVisible(bool(text)))
        layout.addWidget(window.web_return_bar)
        window.web_return_bar.hide()
    else:
        layout.addWidget(window.sidebar)
    layout.addWidget(window.pages, 1)
    window.setCentralWidget(root)
