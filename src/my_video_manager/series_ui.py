"""시리즈 편집 화면. 저장·검증은 AppCore 공개 메서드에 맡긴다."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)
from .dialog_ui import dialog_buttons, space_layout


class SeriesEditor(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("시리즈 편집")
        self.resize(800, 550)
        layout = space_layout(QVBoxLayout(self))
        self.selector = QComboBox()
        self.selector.addItem("새 시리즈", None)
        for series in core.series():
            self.selector.addItem(series.name, series.id)
        layout.addWidget(self.selector)
        self.name = QLineEdit()
        self.name.setPlaceholderText("시리즈 이름")
        layout.addWidget(self.name)
        hint = QLabel("왼쪽: 시리즈 순서 · 오른쪽: 넣을 영상\n다른 시리즈의 영상은 먼저 그 시리즈에서 빼 주세요.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        lists = QHBoxLayout()
        self.members, self.available = QListWidget(), QListWidget()
        self.members.setAccessibleName("시리즈 영상 순서")
        self.available.setAccessibleName("넣을 수 있는 영상")
        lists.addWidget(self.members)
        controls = QVBoxLayout()
        for label, action in (("← 넣기", self.add_video), ("빼기 →", self.remove_video),
                              ("위로", lambda: self.move_video(-1)), ("아래로", lambda: self.move_video(1))):
            button = QPushButton(label)
            button.clicked.connect(action)
            controls.addWidget(button)
        controls.addStretch()
        lists.addLayout(controls)
        lists.addWidget(self.available)
        layout.addLayout(lists)
        note = QLabel("저장 전에 시리즈를 바꾸면 편집이 취소됩니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = dialog_buttons(self.save, self.reject, save=True)
        layout.addWidget(buttons)
        self.selector.currentIndexChanged.connect(self.load)
        self.load()

    def load(self):
        series_id = self.selector.currentData()
        series = next((s for s in self.core.series() if s.id == series_id), None)
        self.name.setText(series.name if series else "")
        self.members.clear()
        self.available.clear()
        videos = {v.id: v for v in self.core.videos()}
        ids = series.video_ids if series else ()
        assigned = {vid for s in self.core.series() for vid in s.video_ids}
        for video_id in ids:
            self.append(self.members, videos[video_id])
        for video in videos.values():
            if video.id not in assigned:
                self.append(self.available, video)
        self.members.setCurrentRow(0)
        self.available.setCurrentRow(0)

    @staticmethod
    def append(widget, video):
        item = QListWidgetItem(video.title + (" · 파일 없음" if video.missing else ""))
        item.setData(Qt.ItemDataRole.UserRole, video.id)
        widget.addItem(item)

    def add_video(self):
        row = self.available.currentRow()
        if row >= 0:
            self.members.addItem(self.available.takeItem(row))
            self.members.setCurrentRow(self.members.count() - 1)

    def remove_video(self):
        row = self.members.currentRow()
        if row >= 0:
            self.available.addItem(self.members.takeItem(row))
            self.available.setCurrentRow(self.available.count() - 1)

    def move_video(self, offset):
        row = self.members.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self.members.count():
            self.members.insertItem(target, self.members.takeItem(row))
            self.members.setCurrentRow(target)

    def save(self):
        ids = tuple(self.members.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.members.count()))
        try:
            series_id = self.selector.currentData()
            if series_id is None:
                self.core.create_series(self.name.text(), ids)
            else:
                self.core.update_series(series_id, name=self.name.text(), video_ids=ids)
        except ValueError as error:
            QMessageBox.warning(self, "시리즈 편집", str(error))
            return
        self.accept()
