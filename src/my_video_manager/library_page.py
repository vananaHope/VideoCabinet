"""라이브러리 스냅숏 필터·선택·공유 작업과 검사 수명주기."""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QSplitter, QVBoxLayout, QWidget,
)
from .empty_state import EmptyState
from .hidden_gems_ui import HiddenGemControls
from .library_ui import LibraryControls
from .library_grid import LibraryGrid, VideoCard, CARD_ROLE
from .library_detail_ui import LibraryDetailPanel
from .thumbnail_ui import ThumbnailIcons
from .tag_ui import TagEditor, TagManager
from .series_ui import SeriesEditor


from .library_operations import LibraryOperations, ScanWorker


class LibraryPage(LibraryOperations, QWidget):
    scan_state_changed = Signal(bool)
    scan_message = Signal(str)
    refreshed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.worker = None
        self.snapshot = None
        self.cards = ()
        self.thumbnail_icons = ThumbnailIcons()
        self.library_controls = LibraryControls(window)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.quick_search = QLineEdit()
        self.quick_search.setPlaceholderText("제목으로 빠른 검색")
        self.quick_search.setAccessibleName("영상 제목 빠른 검색")
        self.quick_search.setClearButtonEnabled(True)
        self.quick_search.textChanged.connect(self.apply_filters)
        filters.addWidget(self.quick_search, 1)
        filters.addWidget(QLabel("태그"))
        self.tag_filter = QComboBox()
        self.tag_filter.setAccessibleName("라이브러리 태그 필터")
        self.tag_filter.currentIndexChanged.connect(self.apply_filters)
        filters.addWidget(self.tag_filter)
        layout.addLayout(filters)
        self.hidden_gems = HiddenGemControls(window)
        layout.addWidget(self.hidden_gems)
        splitter = QSplitter()
        self.grid = LibraryGrid(self.thumbnail_icons)
        self.grid.activated.connect(self.play_index)
        self.grid.menu_requested.connect(self.show_context_menu)
        self.grid.selectionModel().currentChanged.connect(self.selection_changed)
        self.empty = EmptyState(self.grid)
        splitter.addWidget(self.grid)
        self.actions = []
        for title, callback in (
            ("재생", self.play_selected), ("태그 편집", self.edit_video_tags),
            ("자막 만들기 / 원어 지정", self.request_subtitles),
            ("자막 검수 / SRT 내보내기", self.show_review), ("시리즈 편집", self.show_series),
            ("제목 변경", self.library_controls.rename),
            ("파일 다시 연결", self.library_controls.reconnect), ("제외", self.library_controls.exclude),
        ):
            action = QAction(title, self)
            action.triggered.connect(callback)
            self.actions.append(action)
        self.detail = LibraryDetailPanel(self.thumbnail_icons, self.actions)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([650, 300])
        layout.addWidget(splitter, 1)
        window.subtitles.video_changed.connect(self.refresh_details)
        window.translations.video_changed.connect(self.refresh_details)
        self.selection_changed()

    def refresh(self, *, focus_gems=None):
        focus = QApplication.focusWidget()
        preserve_focus = (focus_gems is None and focus is not None and self.isAncestorOf(focus)
                          and focus not in (self.grid, self.hidden_gems.list))
        if focus_gems is None:
            focus_gems = self.hidden_gems.list.hasFocus()
        self.snapshot = self.core.library_snapshot()
        self.thumbnail_icons.retain(v.thumbnail for v in self.snapshot.videos)
        self.hidden_gems.refresh(snapshot=self.snapshot)
        tag_id = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("모든 태그", None)
        for tag in self.core.tags():
            self.tag_filter.addItem(tag.name, tag.id)
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(tag_id)))
        self.tag_filter.blockSignals(False)
        series = {vid: f"{s.name} · {i + 1}/{len(s.video_ids)}"
                  for s in self.snapshot.series for i, vid in enumerate(s.video_ids)}
        self.cards = tuple(VideoCard(v, self.snapshot.statuses[v.id], self.snapshot.tags.get(v.id, ()),
                                    series.get(v.id, "")) for v in self.snapshot.videos)
        self.apply_filters()
        if preserve_focus:
            focus.setFocus()
        elif not self.isHidden():
            (self.hidden_gems.list if focus_gems and self.hidden_gems.list.count() else self.grid).setFocus()
        self.refreshed.emit()

    def apply_filters(self, *_):
        if self.snapshot is None:
            return
        selected = self.selected_video_id()
        query = self.quick_search.text().strip().casefold()
        tag_id = self.tag_filter.currentData()
        cards = tuple(c for c in self.cards if query in c.video.title.casefold()
                      and (tag_id is None or any(t.id == tag_id for t in c.tags)))
        self.grid.model().replace(cards)
        row = next((i for i, c in enumerate(cards) if c.video.id == selected), 0)
        self.grid.setCurrentIndex(self.grid.model().index(row, 0))
        if not cards:
            self.selection_changed()  # 모델 reset은 빈 현재 항목의 변경 신호를 내지 않을 수 있다.
        if cards:
            self.empty.clear()
        elif not self.cards:
            self.empty.show_message("라이브러리가 비어 있습니다",
                                    "폴더 관리(Ctrl+5)에서 감시 폴더나 영상 파일을 추가하세요.")
        else:
            self.empty.show_message("조건에 맞는 영상이 없습니다", "제목 검색이나 태그 필터를 바꿔 보세요.")
        self.window.library_count.setText(f"등록 영상 {len(self.cards)}개 · 표시 {len(cards)}개")

    def selection_changed(self, *_):
        card = self.grid.currentIndex().data(CARD_ROLE)
        for action in self.actions:
            action.setEnabled(card is not None)
        # Library의 검사 잠금을 쓰는 제목·위치·제외 변경은 UI 스레드를 기다리게 하지 않는다.
        for action in self.actions[5:]:
            action.setEnabled(card is not None and self.worker is None)
        self.detail.show_card(card, None)
        self.refresh_details()

    def refresh_details(self, changed_video_id=None):
        if not self.isVisible() or self.window.isMinimized():
            return
        card = self.grid.currentIndex().data(CARD_ROLE)
        if card and (changed_video_id is None or changed_video_id == card.video.id):
            self.detail.show_card(card, self.core.library_details(card.video.id))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_details()

    def create_context_menu(self):
        menu = QMenu(self)
        menu.addActions(self.actions)
        return menu

    def show_context_menu(self, position):
        if self.selected_video_id() is not None:
            menu = self.create_context_menu()
            menu.exec(position)
            menu.deleteLater()

    def visible_video_ids(self) -> tuple[int, ...]:
        return tuple(c.video.id for c in self.grid.model().cards)

    def selected_video_id(self) -> int | None:
        return self.grid.currentIndex().data(Qt.ItemDataRole.UserRole)

    def play_index(self, index):
        if index.isValid():
            self.window.play(index.data(Qt.ItemDataRole.UserRole))

    def play_selected(self):
        self.play_index(self.grid.currentIndex())

    def handle_key(self, event) -> bool:
        if not self.grid.hasFocus():
            return False
        if (event.key() == Qt.Key.Key_Menu or
                (event.key() == Qt.Key.Key_F10 and event.modifiers() == Qt.KeyboardModifier.ShiftModifier)):
            if not event.isAutoRepeat():
                self.show_context_menu(self.grid.viewport().mapToGlobal(
                    self.grid.visualRect(self.grid.currentIndex()).center()))
            return True
        if (event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.play_selected()
            return True
        return False

    def focus_content(self):
        self.grid.setFocus()
