"""대기열과 자동 자막 규칙 화면. 데이터 접근은 AppCore 공개 API만 사용한다."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)


STATES = {"queued": "대기", "transcribing": "받아쓰는 중", "translating": "번역 중",
          "held": "보류", "completed": "완료", "failed": "실패"}


class SubtitleQueueDialog(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("자막 대기열")
        self.resize(800, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("방향키로 선택 · Tab으로 버튼 이동 · Space로 실행 · Esc로 닫기"))
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["영상", "상태", "진행률", "안내"])
        self.list.setRootIsDecorated(False)
        self.list.setAccessibleName("자막 대기열")
        self.list.setColumnWidth(0, 250)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        for label, callback in (("앞당기기", self.promote), ("빼기", self.remove),
                                ("실패 항목 모두 재시도", self.retry),
                                ("선택한 번역 보류 재시도", self.retry_held),
                                ("자동 자막 규칙", self.rules), ("닫기", self.close)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

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
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for entry in items:
            item = QTreeWidgetItem([entry.title, STATES[entry.state], f"{entry.progress:.0%}", entry.error or ""])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.video_id)
            item.setToolTip(3, entry.error or "")
            self.list.addTopLevelItem(item)
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
        self.act(self.core.retry_failed_subtitles)

    def retry_held(self):
        if any(e.video_id == self.selected() and e.state == "held" for e in self.core.translation_queue()):
            self.act(lambda: self.core.request_translation(self.selected()))

    def rules(self):
        AutoSubtitleRulesDialog(self.core, self).exec()


class AutoSubtitleRulesDialog(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("자동 자막 규칙")
        self.resize(650, 400)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setAccessibleName("저장된 자동 자막 규칙")
        layout.addWidget(self.list)
        layout.addWidget(QLabel("감시 폴더 또는 영상 태그"))
        self.target = QComboBox()
        self.target.setAccessibleName("자동 자막 대상")
        for folder in core.watched_folders():
            self.target.addItem(f"폴더: {folder.path}", {"folder": folder.path})
        for tag in core.tags():
            self.target.addItem(f"태그: {tag.name}", {"tag_id": tag.id})
        layout.addWidget(self.target)
        layout.addWidget(QLabel("원어 (선택하지 않으면 자동 감지)"))
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItems(["자동 감지", "ko", "en", "ja", "zh", "de", "fr", "es"])
        self.language.setAccessibleName("원어")
        layout.addWidget(self.language)
        buttons = QHBoxLayout()
        for text, callback in (("규칙 저장", self.save), ("선택 규칙 해제", self.remove), ("닫기", self.close)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.list.currentItemChanged.connect(self.select_rule)
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
        self.target.setCurrentIndex(self.target.findData(target))
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
