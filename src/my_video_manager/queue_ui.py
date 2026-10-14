"""대기열과 자동 자막 규칙 화면. 데이터 접근은 AppCore 공개 API만 사용한다."""

import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from .key_display import display_key, display_keys
from .dialog_ui import primary_button, space_layout


STATES = {"queued": "대기", "transcribing": "받아쓰는 중", "translating": "번역 중",
          "held": "보류", "completed": "완료", "failed": "실패"}


class SubtitleQueuePage(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        layout = space_layout(QVBoxLayout(self))
        title = QLabel("자막 대기열")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.queue = SubtitleQueueView(core)
        self.rules = AutoSubtitleRulesPage(core)
        self.tabs.addTab(self.queue, "처리 상태")
        self.tabs.addTab(self.rules, "자동 자막 규칙")
        layout.addWidget(self.tabs)

    def focus_content(self):
        self.tabs.currentWidget().list.setFocus()

    def handle_key(self, event) -> bool:
        return False


class SubtitleQueueView(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        layout = space_layout(QVBoxLayout(self))
        layout.addWidget(QLabel(f"{display_keys(('Up', 'Down'))} 선택 · {display_key('Tab')} 버튼 이동 · "
                                f"{display_key('Space')} 실행"))
        self.state_filter = QComboBox()
        self.state_filter.setAccessibleName("대기열 상태 필터")
        self.state_filter.addItem("모든 상태", None)
        for state, label in STATES.items():
            self.state_filter.addItem(label, state)
        layout.addWidget(self.state_filter)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["영상", "상태", "진행률", "안내"])
        self.list.setRootIsDecorated(False)
        self.list.setAccessibleName("자막 대기열")
        self.list.setColumnWidth(0, 250)
        self.list.setColumnWidth(1, 110)
        self.list.setColumnWidth(2, 110)
        self.list.setWordWrap(True)
        layout.addWidget(self.list)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        buttons = QGridLayout()
        for index, (label, callback) in enumerate((("앞당기기", self.promote), ("빼기", self.remove),
                                ("실패 항목 모두 재시도", self.retry),
                                ("선택한 번역 보류 재시도", self.retry_held))):
            button = QPushButton(label)
            button.clicked.connect(callback)
            if index == 2:
                primary_button(button)
            buttons.addWidget(button, index // 2, index % 2)
        layout.addLayout(buttons)
        self.retry_status = QLabel()
        self.retry_status.setWordWrap(True)
        layout.addWidget(self.retry_status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.state_filter.currentIndexChanged.connect(self.filter_changed)

    def filter_changed(self):
        self.snapshot = None
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start(500)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def selected(self):
        item = self.list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def refresh(self):
        selected = self.selected()
        items = self.core.subtitle_queue_items()
        # 선택·스크롤·포커스가 주기마다 튀지 않도록 값이 바뀔 때만 갱신한다.
        if getattr(self, "snapshot", None) == items:
            return
        self.snapshot = items
        counts = {state: sum(entry.state == state for entry in items) for state in STATES}
        self.summary.setText(" · ".join(f"{label} {counts[state]}개" for state, label in STATES.items()))
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for entry in items:
            if self.state_filter.currentData() not in (None, entry.state):
                continue
            item = QTreeWidgetItem([entry.title, STATES[entry.state], f"{entry.progress:.0%}", entry.error or ""])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.video_id)
            item.setToolTip(3, entry.error or "")
            self.list.addTopLevelItem(item)
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(round(entry.progress * 100))
            progress.setAccessibleName(f"{entry.title} 진행률")
            self.list.setItemWidget(item, 2, progress)
            if entry.video_id == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self.list.verticalScrollBar().setValue(scroll)

    def act(self, callback):
        try:
            callback()
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "자막 대기열", str(error))

    def promote(self):
        if self.selected() is not None:
            self.act(lambda: self.core.promote_subtitle(self.selected()))

    def remove(self):
        if self.selected() is not None:
            self.act(lambda: self.core.remove_from_subtitle_queue(self.selected()))

    def retry(self):
        def retry_all():
            result = self.core.retry_failed_subtitles()
            details = []
            for item in result.skipped:
                try:
                    title = self.core.video(item.video_id).title or str(item.video_id)
                except (ValueError, OSError, sqlite3.Error):
                    title = str(item.video_id)
                details.append(f"영상 {title}: {item.reason}")
            details = "\n".join(details)
            self.retry_status.setText(f"재시도 {result.retried}개 · 건너뜀 {result.skipped_count}개" +
                                      (f"\n{details}" if details else ""))
        self.act(retry_all)

    def retry_held(self):
        if any(e.video_id == self.selected() and e.state == "held" for e in self.core.translation_queue()):
            self.act(lambda: self.core.request_translation(self.selected()))


class AutoSubtitleRulesPage(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        layout = space_layout(QVBoxLayout(self))
        hint = QLabel("감시 폴더나 태그에 새로 등록되는 영상의 자막을 자동으로 만듭니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setAccessibleName("저장된 자동 자막 규칙")
        layout.addWidget(self.list)
        layout.addWidget(QLabel("감시 폴더 또는 영상 태그"))
        self.target = QComboBox()
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(24)
        self.target.setAccessibleName("자동 자막 대상")
        layout.addWidget(self.target)
        layout.addWidget(QLabel("원어 (선택하지 않으면 자동 감지)"))
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItems(["자동 감지", "ko", "en", "ja", "zh", "de", "fr", "es"])
        self.language.setAccessibleName("원어")
        layout.addWidget(self.language)
        buttons = QHBoxLayout()
        for text, callback in (("규칙 저장", self.save), ("선택 규칙 해제", self.remove)):
            button = QPushButton(text)
            if text == "규칙 저장":
                self.save_button = primary_button(button)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.list.currentItemChanged.connect(self.select_rule)

    def showEvent(self, event):
        super().showEvent(event)
        target = self.target.currentData()
        self.target.clear()
        for folder in self.core.watched_folders():
            self.target.addItem(f"폴더: {folder.path}", {"folder": folder.path})
        for tag in self.core.tags():
            self.target.addItem(f"태그: {tag.name}", {"tag_id": tag.id})
        index = next((i for i in range(self.target.count()) if self.target.itemData(i) == target), 0)
        self.target.setCurrentIndex(index)
        self.save_button.setEnabled(self.target.count() > 0)
        self.refresh()

    def refresh(self):
        self.list.clear()
        tags = {t.id: t.name for t in self.core.tags()}
        for rule in self.core.auto_subtitle_rules():
            target = str(rule.folder) if rule.folder else f"태그: {tags.get(rule.tag_id, rule.tag_id)}"
            item = QListWidgetItem(f"{target} · {rule.spoken_language or '자동 감지'}")
            item.setData(Qt.ItemDataRole.UserRole, rule)
            self.list.addItem(item)

    def select_rule(self, item):
        if item is None:
            return
        rule = item.data(Qt.ItemDataRole.UserRole)
        target = {"folder": rule.folder} if rule.folder else {"tag_id": rule.tag_id}
        # Path가 들어 있는 Python 객체는 QVariant의 findData 동등 비교 대상이 아니다.
        index = next((i for i in range(self.target.count()) if self.target.itemData(i) == target), -1)
        self.target.setCurrentIndex(index)
        self.language.setCurrentText(rule.spoken_language or "자동 감지")

    def save(self):
        target = self.target.currentData()
        if not target:
            return
        try:
            count = len(self.core.auto_subtitle_candidates(**target))
            include = count > 0 and QMessageBox.question(
                self, "기존 영상도 추가", f"기존 영상 {count}개도 대기열에 넣을까요?\n원어 자막이 있거나 이미 대기 중인 영상은 제외합니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            language = self.language.currentText().strip()
            self.core.set_auto_subtitle_rule(**target, spoken_language=None if language == "자동 감지" else language,
                                            include_existing=include)
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "자동 자막 규칙", str(error))

    def remove(self):
        if item := self.list.currentItem():
            self.core.remove_auto_subtitle_rule(item.data(Qt.ItemDataRole.UserRole).id)
            self.refresh()
