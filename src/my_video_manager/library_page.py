"""라이브러리 페이지 구성·목록 갱신·검사 입력. 재생 시작과 공통 작업은 셸에 연결한다."""

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from .hidden_gems_ui import HiddenGemControls
from .library_ui import LibraryControls
from .thumbnail_ui import ThumbnailIcons
from .tag_ui import TagEditor, TagManager
from .series_ui import SeriesEditor
from .review_ui import review_button


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent, operation=None):
        super().__init__(parent)
        self.core = core
        self.operation = operation or core.scan

    def run(self):
        try:
            self.completed.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class LibraryPage(QWidget):
    scan_state_changed = Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.core = window.core
        self.worker = None
        self.thumbnail_icons = ThumbnailIcons()
        layout = QVBoxLayout(self)
        self.hidden_gems = HiddenGemControls(window)
        layout.addWidget(self.hidden_gems)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("감시 폴더 추가")
        self.scan_button = QPushButton("다시 검사")
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(window.subtitles.button())
        self.series_button = QPushButton("시리즈 편집")
        self.series_button.clicked.connect(self.show_series)
        buttons.addWidget(self.series_button)
        buttons.addWidget(window.translations.button())
        self.search_button = QPushButton("검색")
        self.search_button.clicked.connect(window.show_search)
        buttons.addWidget(self.search_button)
        self.buttons = buttons
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(review_button(window))
        self.library_controls = LibraryControls(window)
        layout.addWidget(self.library_controls)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        layout.addWidget(self.folders)
        tag_controls = QHBoxLayout()
        tag_controls.addWidget(QLabel("태그 필터"))
        self.tag_filter = QComboBox()
        self.tag_filter.setAccessibleName("라이브러리 태그 필터")
        self.tag_filter.currentIndexChanged.connect(self.filter_changed)
        tag_controls.addWidget(self.tag_filter, 1)
        self.tags_button = QPushButton("선택한 영상 태그")
        self.tags_button.clicked.connect(self.edit_video_tags)
        tag_controls.addWidget(self.tags_button)
        manage_tags = QPushButton("모든 태그 관리")
        manage_tags.clicked.connect(self.manage_tags)
        tag_controls.addWidget(manage_tags)
        layout.addLayout(tag_controls)
        layout.addWidget(QLabel("영상을 더블클릭하거나 방향키로 고른 뒤 Enter를 누르세요."))
        self.list = QListWidget()
        self.list.setIconSize(QSize(192, 108))
        self.list.setSpacing(6)
        layout.addWidget(self.list)
        self.status = QLabel("감시 폴더를 추가하면 자동으로 검사합니다.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.add_button.clicked.connect(self.add_folder)
        self.scan_button.clicked.connect(self.scan)
        self.list.itemActivated.connect(window.play)

    def refresh(self, *, focus_gems=None):
        if focus_gems is None:
            focus_gems = self.hidden_gems.list.hasFocus()
        snapshot = self.core.library_snapshot()
        self.thumbnail_icons.retain(video.thumbnail for video in snapshot.videos)
        self.hidden_gems.refresh(snapshot=snapshot)
        tag_id = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("모든 영상", None)
        for tag in self.core.tags():
            self.tag_filter.addItem(tag.name, tag.id)
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(tag_id)))
        self.tag_filter.blockSignals(False)
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        selected_row = 0
        self.folders.setText("감시 폴더: " + (", ".join(str(f.path) for f in self.core.watched_folders()) or "없음"))
        self.list.clear()
        series_labels = {vid: f"{s.name} · {index + 1}/{len(s.video_ids)}"
                         for s in snapshot.series for index, vid in enumerate(s.video_ids)}
        tag_id = self.tag_filter.currentData()
        videos = snapshot.videos
        statuses, tags_by_video = snapshot.statuses, snapshot.tags
        if tag_id is not None:
            videos = tuple(v for v in videos if any(t.id == tag_id for t in tags_by_video.get(v.id, ())))
        for row, video in enumerate(videos):
            status = statuses[video.id]
            label = "다 봄" if status.finished else f"보다 만 ({status.stopped_percent:.0f}%)" if status.abandoned else ""
            if status.favorite:
                label += " · 즐겨 보는 영상"
            if video.missing:
                label = "파일 없음" + (f" · {label}" if label else "")
            elif len(video.locations) > 1:
                label += (" · " if label else "") + f"위치 {len(video.locations)}개"
            if video.id in series_labels:
                label += ("\n" if label else "") + "시리즈: " + series_labels[video.id]
            item = QListWidgetItem(self.thumbnail_icons.get(video.thumbnail), video.title + (f"\n{label}" if label else ""))
            tags = tags_by_video.get(video.id, ())
            if tags:
                item.setText(item.text() + "\n태그: " + ", ".join(tag.name for tag in tags))
            item.setData(Qt.ItemDataRole.UserRole, video.id)
            item.setSizeHint(QSize(300, 120))
            self.list.addItem(item)
            if video.id == selected_id:
                selected_row = row
        if self.list.count():
            self.list.setCurrentRow(selected_row)
        target = self.hidden_gems.list if focus_gems and self.hidden_gems.list.count() else self.list
        if not self.isHidden():
            target.setFocus()
        self.tags_button.setEnabled(self.list.count() > 0)

    def filter_changed(self):
        self.refresh()
        self.tag_filter.setFocus()

    def edit_video_tags(self):
        if item := self.list.currentItem():
            TagEditor(self.core, video_id=item.data(Qt.ItemDataRole.UserRole), parent=self).exec()
            self.refresh()

    def manage_tags(self):
        TagManager(self.core, self).exec()
        self.refresh()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "감시 폴더 선택")
        if folder:
            try:
                self.core.add_watched_folder(folder)
                self.scan()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "감시 폴더", str(error))

    def scan(self, checked=False, *, operation=None):
        if self.worker and self.worker.isRunning():
            return
        self.add_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.library_controls.setEnabled(False)
        self.scan_state_changed.emit(True)
        self.status.setText("영상을 검사하고 썸네일을 만드는 중입니다…")
        self.worker = ScanWorker(self.core, self, operation)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(lambda error: self.status.setText(f"검사 실패: {error}"))
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def scan_completed(self, result):
        self.refresh()
        self.status.setText(f"영상 {result.added}개 등록 · 전체 {self.list.count()}개 · 안내 {len(result.issues)}개")
        if result.issues:
            icon = QMessageBox.Icon.Warning if any(issue.failed for issue in result.issues) else QMessageBox.Icon.Information
            dialog = QMessageBox(icon, "검사·추가 안내",
                                 "\n".join(f"{issue.path}: {issue.message}" for issue in result.issues[:3]), parent=self)
            dialog.setDetailedText("\n".join(f"{i.path}: {i.message}" for i in result.issues))
            dialog.exec()

    def scan_finished(self):
        self.add_button.setEnabled(True)
        self.scan_button.setEnabled(True)
        self.library_controls.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None
        self.scan_state_changed.emit(False)

    def show_series(self):
        SeriesEditor(self.core, self).exec()
        self.refresh()
