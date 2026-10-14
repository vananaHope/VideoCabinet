"""숨겨진 보석 카드와 관심 없음 되돌리기. 도메인 판단은 AppCore에 맡긴다."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)
from .dialog_ui import primary_button, space_layout
from .empty_state import EmptyState
from .library_grid import CARD_ROLE, VideoCard, VideoCardDelegate
from .theme import hint_label, with_role
from .thumbnail_ui import ThumbnailIcons


class GemList(QListWidget):
    dismiss_requested = Signal()
    play_requested = Signal(object)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_Backspace:
                if not event.isAutoRepeat():
                    self.dismiss_requested.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.currentItem() is not None:
                    self.play_requested.emit(self.currentItem())
                event.accept()
                return
        super().keyPressEvent(event)


class HiddenGemControls(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.window, self.core = window, window.core
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(16)
        self.label = with_role(QLabel("숨겨진 보석"), "sectionTitle")
        bar.addWidget(self.label)
        self.help = hint_label("←/→ 선택 · Enter 재생 · Backspace 또는 우클릭으로 관심 없음")
        self.help.setWordWrap(False)
        bar.addWidget(self.help, 1)
        layout.addLayout(bar)
        self.list = GemList()
        self.icons = ThumbnailIcons()
        self.delegate = VideoCardDelegate(self.icons, self.list, compact=True)
        self.list.setItemDelegate(self.delegate)
        self.list.setAccessibleName("숨겨진 보석 추천 카드")
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setWordWrap(True)
        self.list.setIconSize(QSize(96, 54))
        self.list.setSpacing(4)
        # 카드 한 줄과 가로 스크롤 막대가 들어가는 높이. 격자와 상세 패널에 공간을 남긴다.
        self.list.setFixedHeight(self.delegate.card_size.height() + 28)
        self.list.itemClicked.connect(self.play)
        self.list.play_requested.connect(self.play)
        self.list.dismiss_requested.connect(self.dismiss_selected)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.list)

    def refresh(self, *, snapshot=None):
        snapshot = snapshot or self.core.library_snapshot()
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        row = max(0, self.list.currentRow())
        self.list.clear()
        try:
            gems = self.core.hidden_gems(snapshot=snapshot)
        except Exception as error:
            self.label.setText(f"숨겨진 보석을 불러오지 못했어요: {error}")
            self.list.hide()
            self.help.hide()
            return
        for index, gem in enumerate(gems):
            item = QListWidgetItem(f"{gem.video.title}\n{gem.reason}")
            item.setData(Qt.ItemDataRole.UserRole, gem.video.id)
            item.setToolTip(item.text())
            item.setData(CARD_ROLE, VideoCard(gem.video, snapshot.statuses[gem.video.id],
                                             snapshot.tags.get(gem.video.id, ()), reason=gem.reason))
            item.setSizeHint(self.delegate.card_size)
            self.list.addItem(item)
            if gem.video.id == selected_id:
                row = index
        self.list.setCurrentRow(min(row, len(gems) - 1))
        self.icons.retain(gem.video.thumbnail for gem in gems)
        self.list.setVisible(bool(gems))
        self.help.setVisible(bool(gems))
        # 추천이 사라지면 고정 높이를 줄여 격자에 공간을 돌려준다(페이지가 숨겨진 동안 갱신된 경우 포함).
        self.layout().invalidate()
        self.updateGeometry()
        self.label.setText(f"숨겨진 보석 · {len(gems)}개" if gems else "숨겨진 보석 · 지금은 추천할 영상이 없어요")

    def play(self, item):
        self.window.playback_list = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole)
                                          for i in range(self.list.count()))
        self.window.play_video(item.data(Qt.ItemDataRole.UserRole), from_gems=True)

    def context_menu(self, position):
        item = self.list.itemAt(position)
        if item is None:
            return
        # 현재 선택과 무관하게 우클릭한 카드만 대상으로 삼고 재생 신호를 내지 않는다.
        video_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        dismiss = menu.addAction("관심 없음")
        if menu.exec(self.list.viewport().mapToGlobal(position)) == dismiss:
            self.dismiss_video(video_id)

    def dismiss_video(self, video_id):
        self.core.dismiss_video(video_id)
        self.refresh()
        (self.list if self.list.count() else self.window.library_page.grid).setFocus()

    def dismiss_selected(self):
        if item := self.list.currentItem():
            self.dismiss_video(item.data(Qt.ItemDataRole.UserRole))

    def show_dismissed(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("관심 없음 되돌리기")
        dialog.resize(600, 400)
        layout = space_layout(QVBoxLayout(dialog))
        layout.addWidget(hint_label("되돌린 영상은 다시 숨겨진 보석으로 추천될 수 있습니다. 라이브러리 표시는 원래 그대로입니다."))
        listing = QListWidget()
        listing.setAccessibleName("관심 없음 영상 목록")
        empty = EmptyState(listing)
        layout.addWidget(listing, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        restore = primary_button(QPushButton("선택 영상 되돌리기"))
        close = QPushButton("닫기")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(restore)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        def refresh():
            row = max(0, listing.currentRow())
            listing.clear()
            for video in self.core.dismissed_videos():
                suffix = " · 제외" if video.excluded else " · 파일 없음" if video.missing else ""
                item = QListWidgetItem(video.title + suffix)
                item.setData(Qt.ItemDataRole.UserRole, video.id)
                listing.addItem(item)
            listing.setCurrentRow(min(row, listing.count() - 1))
            restore.setEnabled(listing.count() > 0)
            if listing.count():
                empty.clear()
            else:
                empty.show_message("관심 없음으로 뺀 영상이 없습니다")

        def restore_selected():
            if item := listing.currentItem():
                self.core.restore_dismissed_video(item.data(Qt.ItemDataRole.UserRole))
                refresh()
                self.refresh()
                listing.setFocus()

        restore.clicked.connect(restore_selected)
        listing.itemActivated.connect(lambda _: restore_selected())
        refresh()
        dialog.exec()
