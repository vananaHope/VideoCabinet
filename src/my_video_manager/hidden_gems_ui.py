"""숨겨진 보석 카드와 관심 없음 되돌리기. 도메인 판단은 AppCore에 맡긴다."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)


class GemList(QListWidget):
    dismiss_requested = Signal()
    play_requested = Signal(object)

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
        self.window, self.core = window, window.core
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.label = QLabel("숨겨진 보석")
        bar.addWidget(self.label)
        bar.addStretch()
        self.dismiss = QPushButton("선택 영상 관심 없음")
        self.dismiss.clicked.connect(self.dismiss_selected)
        bar.addWidget(self.dismiss)
        restore = QPushButton("관심 없음 되돌리기")
        restore.clicked.connect(self.show_dismissed)
        bar.addWidget(restore)
        layout.addLayout(bar)
        layout.addWidget(QLabel("←/→로 선택 · Enter 또는 클릭으로 재생 · 카드에서 Backspace로 관심 없음"))
        self.list = GemList()
        self.list.setAccessibleName("숨겨진 보석 추천 카드")
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setWordWrap(True)
        self.list.setIconSize(QSize(96, 54))
        self.list.setSpacing(4)
        self.list.setFixedHeight(150)
        self.list.itemClicked.connect(self.play)
        self.list.play_requested.connect(self.play)
        self.list.dismiss_requested.connect(self.dismiss_selected)
        layout.addWidget(self.list)

    def refresh(self):
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        row = max(0, self.list.currentRow())
        self.list.clear()
        gems = self.core.hidden_gems()
        for index, gem in enumerate(gems):
            item = QListWidgetItem(QIcon(str(gem.video.thumbnail)), f"{gem.video.title}\n{gem.reason}")
            item.setData(Qt.ItemDataRole.UserRole, gem.video.id)
            item.setToolTip(item.text())
            item.setSizeHint(QSize(280, 112))
            self.list.addItem(item)
            if gem.video.id == selected_id:
                row = index
        self.list.setCurrentRow(min(row, len(gems) - 1))
        self.dismiss.setEnabled(bool(gems))
        self.label.setText(f"숨겨진 보석 · {len(gems)}개" if gems else "숨겨진 보석 · 지금은 추천할 영상이 없어요")

    def play(self, item):
        self.window.playback_list = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole)
                                          for i in range(self.list.count()))
        self.window.play_video(item.data(Qt.ItemDataRole.UserRole))

    def dismiss_selected(self):
        if item := self.list.currentItem():
            self.core.dismiss_video(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()
            self.list.setFocus()

    def show_dismissed(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("관심 없음 되돌리기")
        dialog.resize(600, 400)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        listing.setAccessibleName("관심 없음 영상 목록")
        layout.addWidget(listing)
        restore = QPushButton("선택 영상 되돌리기")
        layout.addWidget(restore)

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
