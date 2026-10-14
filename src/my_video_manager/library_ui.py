"""라이브러리 관리 입력을 AppCore 공개 API에 전달한다."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QFileDialog,
)


class LibraryControls(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.core = window.core
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for title, action in (
            ("감시 폴더 해제", self.remove_folder), ("파일 직접 추가", self.add_file),
            ("제목 변경", self.rename), ("파일 다시 연결", self.reconnect),
            ("제외", self.exclude), ("제외 목록", self.show_excluded),
            ("최소 길이 설정", self.settings),
        ):
            button = QPushButton(title)
            button.clicked.connect(action)
            layout.addWidget(button)
        layout.addStretch()

    def selected_video(self):
        video_id = self.window.library_page.selected_video_id()
        if video_id is not None:
            return next((v for v in self.core.videos() if v.id == video_id), None)
        QMessageBox.information(self.window, "영상 선택", "목록에서 영상을 먼저 선택하세요.")
        return None

    def apply(self, action):
        try:
            action()
            self.window.refresh()
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self.window, "라이브러리", str(error))

    def remove_folder(self):
        folders = [str(folder.path) for folder in self.core.watched_folders()]
        if not folders:
            QMessageBox.information(self.window, "감시 폴더", "해제할 감시 폴더가 없습니다.")
            return
        folder, ok = QInputDialog.getItem(self.window, "감시 폴더 해제", "해제할 폴더", folders, editable=False)
        if ok and QMessageBox.question(
            self.window, "감시 폴더 해제",
            "이 폴더 아래의 모든 위치를 해제합니다. 다른 위치가 없는 영상은 파일 없음으로 남습니다.\n"
            "실제 파일과 영상 기록은 유지합니다. 다른 감시 폴더에 겹치는 위치는 다음 검사에서 복귀합니다.",
        ) == QMessageBox.StandardButton.Yes:
            self.apply(lambda: self.core.remove_watched_folder(folder))

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "감시 폴더 밖 영상도 직접 추가할 수 있습니다")
        if path:
            self.window.scan(operation=lambda: self.core.add_file(path))

    def rename(self):
        video = self.selected_video()
        if video:
            title, ok = QInputDialog.getText(self.window, "제목 변경", "영상 제목", text=video.title)
            if ok:
                self.apply(lambda: self.core.rename_video(video.id, title))

    def reconnect(self):
        video = self.selected_video()
        if video:
            path, _ = QFileDialog.getOpenFileName(self.window, "원래 영상과 같은 내용의 파일 선택")
            if path:
                def reconnect():
                    self.core.reconnect_video(video.id, path)
                    # 공통 작업자 완료 표시를 사용한다. 전체 폴더 검사는 필요 없다.
                    from .core import ScanResult
                    return ScanResult(0, ())
                self.window.scan(operation=reconnect)

    def exclude(self):
        video = self.selected_video()
        if video and QMessageBox.question(
            self.window, "영상 제외", f"'{video.title}'을 제외할까요?\n실제 파일과 기록은 남으며 제외 목록에서 되돌릴 수 있습니다."
        ) == QMessageBox.StandardButton.Yes:
            self.apply(lambda: self.core.exclude_video(video.id))

    def show_excluded(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("제외 목록")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("제외한 영상의 파일과 기록은 그대로 남아 있습니다."))
        items = QListWidget()
        layout.addWidget(items)
        def refresh():
            items.clear()
            for video in self.core.excluded_videos():
                item = QListWidgetItem(video.title + (" · 파일 없음" if video.missing else ""))
                item.setData(Qt.ItemDataRole.UserRole, video.id)
                items.addItem(item)
            if items.count():
                items.setCurrentRow(0)
        def restore():
            item = items.currentItem()
            if item:
                self.apply(lambda: self.core.restore_video(item.data(Qt.ItemDataRole.UserRole)))
                refresh()
        button = QPushButton("선택 영상 되돌리기")
        button.clicked.connect(restore)
        layout.addWidget(button)
        refresh()
        dialog.exec()

    def settings(self):
        seconds, ok = QInputDialog.getDouble(
            self.window, "최소 길이 설정", "새로 등록할 영상의 최소 길이(초) · 기본값 60 · 0이면 길이 제한 없음",
            self.core.minimum_duration, 0, 86400 * 365, 2,
        )
        if ok:
            self.apply(lambda: self.core.set_minimum_duration(seconds))
            self.window.library_page.show_status("최소 길이를 저장했습니다. 다시 검사하면 새 기준을 적용합니다. 기존 영상은 유지합니다.")
