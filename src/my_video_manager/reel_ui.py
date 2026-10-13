"""모아보기 목록과 코어가 정한 재생 대상의 화면 연결."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .highlight_ui import timestamp
from .core import CommandType
from .key_display import display_keys


class ReelControls:
    def __init__(self, window):
        self.window, self.core = window, window.core
        self.shown = None
        self.page = QWidget()
        layout = QVBoxLayout(self.page)
        back = QPushButton("라이브러리로 (Esc)")
        back.clicked.connect(window.show_library)
        layout.addWidget(back)
        layout.addWidget(QLabel("하이라이트 모아보기 · 시청 기록과 별도로 복습을 기록합니다."))
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
        self.list.setAccessibleName("모든 영상의 하이라이트")
        self.list.itemActivated.connect(self.play_selected)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.play_all = QPushButton("처음부터 차례 재생")
        self.play_all.clicked.connect(lambda: self.start())
        buttons.addWidget(self.play_all)
        self.play_button = QPushButton("선택한 하이라이트부터 재생")
        self.play_button.clicked.connect(lambda: self.play_selected(self.list.currentItem()))
        buttons.addWidget(self.play_button)
        layout.addLayout(buttons)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.page_index = window.pages.addWidget(self.page)

    def button(self):
        button = QPushButton("하이라이트 모아보기")
        button.clicked.connect(self.open)
        return button

    def open(self):
        self.window.end_playback()
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
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
            if h.id == selected_id:
                row = index
        if entries:
            self.list.setCurrentRow(row)
        self.play_all.setEnabled(any(e.playable and e.highlight.start < e.duration for e in entries))
        self.selection_changed()
        self.status.setText(f"하이라이트 {len(entries)}개 · 영상 제목 → 영상 안 시각 순\n"
                            "파일 없음과 영상 끝의 길이 0인 지점은 건너뜁니다. 새 하이라이트는 목록 갱신 때 반영됩니다.")

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
        current = self.core.reel_playback
        self.window.reel_label.setVisible(current is not None)
        self.window.video_navigation_label.setVisible(current is None)
        self.window.back_button.setText("모아보기 목록으로 (Esc)" if current else "목록으로 (Esc)")
        if current:
            repeat = "켜짐" if self.core.reel_repeat else "꺼짐"
            keys = {row.command.kind: display_keys(row.keys) for row in self.core.key_bindings()}
            self.window.reel_label.setText(
                f"모아보기 · {current.entry.video_title} · {timestamp(current.start)} — {timestamp(current.end)}\n"
                f"반복 {repeat} ({keys[CommandType.TOGGLE_REEL_REPEAT]}) · "
                f"이전/다음 하이라이트: {keys[CommandType.PREVIOUS_HIGHLIGHT]} / {keys[CommandType.NEXT_HIGHLIGHT]} · "
                f"영상 단위 이동: {keys[CommandType.PREVIOUS_VIDEO]} / {keys[CommandType.NEXT_VIDEO]}")
