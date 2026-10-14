"""모아보기 목록과 코어가 정한 재생 대상의 화면 연결."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .core import CommandType
from .highlight_ui import timestamp
from .key_display import display_keys
from .dialog_ui import primary_button, space_layout
from .empty_state import EmptyState
from .theme import hint_label, page_title
from .thumbnail_ui import ThumbnailIcons


class ReelPage(QWidget):
    def __init__(self, controls):
        super().__init__()
        self.controls = controls

    def focus_content(self):
        self.controls.list.setFocus()

    def handle_key(self, event) -> bool:
        if event.key() == Qt.Key.Key_Escape:
            self.controls.window.show_library()
            return True
        if self.controls.list.hasFocus() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.controls.play_selected(self.controls.list.currentItem())
            return True
        return False


class ReelControls:
    def __init__(self, window):
        self.window, self.core = window, window.core
        self.shown = None
        self.page = ReelPage(self)
        self.icons = ThumbnailIcons()
        layout = space_layout(QVBoxLayout(self.page))
        layout.addWidget(page_title("하이라이트 모아보기"))
        layout.addWidget(hint_label("모든 영상의 하이라이트를 이어서 봅니다. 시청 기록과 별도로 복습을 기록합니다."))
        controls = QHBoxLayout()
        controls.addWidget(QLabel("하이라이트 태그"))
        self.filter = QComboBox()
        self.filter.setAccessibleName("하이라이트 모아보기 태그 필터")
        self.filter.currentIndexChanged.connect(self.refresh_entries)
        controls.addWidget(self.filter, 1)
        refresh = QPushButton("목록 갱신")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.list = QListWidget()
        self.list.setIconSize(QSize(128, 72))
        self.list.setSpacing(6)
        self.list.setWordWrap(True)
        self.list.setAccessibleName("모든 영상의 하이라이트")
        self.list.itemActivated.connect(self.play_selected)
        self.empty = EmptyState(self.list)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.play_all = primary_button(QPushButton("처음부터 차례 재생"))
        self.play_all.clicked.connect(lambda: self.start())
        buttons.addWidget(self.play_all)
        self.play_button = QPushButton("선택한 하이라이트부터 재생")
        self.play_button.clicked.connect(lambda: self.play_selected(self.list.currentItem()))
        buttons.addWidget(self.play_button)
        layout.addLayout(buttons)
        self.status = hint_label()
        layout.addWidget(self.status)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.page_index = window.pages.addWidget(self.page)

    def button(self):
        button = QPushButton("하이라이트 모아보기")
        button.clicked.connect(self.open)
        return button

    def open(self):
        self.window.end_playback()
        self.window._return_to_gems = False
        self.shown = None
        self.window.pages.setCurrentWidget(self.page)
        self.refresh()
        self.list.setFocus()

    def refresh(self):
        tag_id = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("모든 하이라이트", None)
        for tag in self.core.tags():
            self.filter.addItem(tag.name, tag.id)
        self.filter.setCurrentIndex(max(0, self.filter.findData(tag_id)))
        self.filter.blockSignals(False)
        self.refresh_entries()

    def refresh_entries(self):
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole).highlight.id if selected else None
        self.list.clear()
        entries = self.core.reel_entries(self.filter.currentData())
        thumbnails = {video.id: video.thumbnail for video in self.core.videos()}
        self.icons.retain(thumbnails.values())
        row = 0
        for index, entry in enumerate(entries):
            h = entry.highlight
            times = timestamp(h.start) + (f" — {timestamp(h.end)}" if h.end is not None else " · 지점")
            last = entry.last_revisited_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if entry.last_revisited_at else "아직 없음"
            text = f"{entry.video_title} · {times}\n마지막 복습: {last}"
            if not entry.playable:
                text += " · 파일 없음 — 재생 불가 (차례 재생에서 건너뜀)"
            if h.note:
                text += "\n" + h.note.text
            tags = self.core.highlight_tags(h.id)
            if tags:
                text += "\n태그: " + ", ".join(t.name for t in tags)
            item = QListWidgetItem(text)
            if path := thumbnails.get(h.video_id):
                item.setIcon(self.icons.get(path))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
            if h.id == selected_id:
                row = index
        if entries:
            self.list.setCurrentRow(row)
            self.empty.clear()
        elif self.filter.currentData() is not None:
            self.empty.show_message("이 태그가 붙은 하이라이트가 없습니다", "다른 하이라이트 태그를 골라 보세요.")
        else:
            keys = {row.command.kind: display_keys(row.keys) for row in self.core.key_bindings()}
            point = keys.get(CommandType.POINT_HIGHLIGHT, "키 미할당")
            span = keys.get(CommandType.RANGE_HIGHLIGHT, "키 미할당")
            self.empty.show_message("아직 하이라이트가 없습니다",
                                    f"영상을 보다가 {point}로 지점, {span}로 구간을 표시하면 여기에 모입니다.")
        self.play_all.setEnabled(any(e.playable and e.highlight.start < e.duration for e in entries))
        self.selection_changed()
        self.status.setText(f"하이라이트 {len(entries)}개 · 영상 제목 → 영상 안 시각 순\n"
                            "파일 없음·길이 0인 지점은 건너뜁니다. 새 항목은 ‘목록 갱신’으로 불러옵니다.")

    def selection_changed(self, *_):
        item = self.list.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.play_button.setEnabled(bool(entry and entry.playable and entry.highlight.start < entry.duration))

    def play_selected(self, item):
        if item:
            self.start(item.data(Qt.ItemDataRole.UserRole).highlight.id)

    def start(self, highlight_id=None):
        try:
            self.window.end_playback()
            self.core.start_reel(self.filter.currentData(), highlight_id)
            self.sync()
        except Exception as error:
            self.open()
            QMessageBox.warning(self.window, "모아보기 재생 실패", str(error))

    def sync(self):
        current = self.core.reel_playback
        if current == self.shown:
            self.update_label()
            return
        if current is not None and current.action == "seek" and self.window.player:
            # 같은 영상은 파일을 다시 열지 않는다. 명령의 판단은 코어가 담당한다.
            self.window.player.seek_to(current.start, resume=True)
            self.shown = current
            self.window.refresh_highlights()
            self.update_label()
            return
        options = None
        if self.window.player:
            options = self.window.player.playback_options()
            # 코어는 이미 새 항목으로 전환했다. 이전 엔진에 남은 보고는 새 항목에 보내지 않는다.
            self.window.position_timer.stop()
            self.window.player.close()
            self.window.player = None
        self.shown = current
        if current is None:
            self.open()
            self.status.setText("모아보기를 마쳤습니다. 다시 재생할 하이라이트를 고르세요.")
            return
        try:
            location = self.core.playback_location(current.video_id)
            self.window.pages.setCurrentIndex(1)
            self.window.player = self.window.player_factory(int(self.window.surface.winId()))
            if options is not None:
                self.window.player.apply_playback_options(options)
            self.window.player.play(location.path, current.start,
                                    subtitle=self.core.playback_subtitle(current.video_id))
            self.window.progress.duration = current.entry.duration
            self.window.refresh_highlights()
            self.window.position_timer.start()
            self.window.surface.setFocus()
            self.update_label()
        except Exception:
            self.open()
            raise

    def update_label(self):
        keys = {row.command.kind: display_keys(row.keys) for row in self.core.key_bindings()}
        self.window.playback_page.show_reel(self.core.reel_playback, self.core.reel_repeat, keys)
