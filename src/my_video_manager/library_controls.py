"""웹 라이브러리의 관리 명령과 Windows 파일 선택 연결."""
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog


class LibraryControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "감시 폴더 밖 영상도 직접 추가할 수 있습니다")
        if path:
            self.window.scan(operation=lambda: self.core.add_file(path))

    def rename(self):
        video_id = self.window.library_page.selected_video_id()
        if video_id is not None:
            self.window.web_host.dialogs.run('video-rename', video_id=video_id)
            self.window.refresh()

    def exclude(self):
        video_id = self.window.library_page.selected_video_id()
        if video_id is not None:
            self.window.web_host.dialogs.run('video-exclude', video_id=video_id)
            self.window.refresh()

    def reconnect(self):
        video_id = self.window.library_page.selected_video_id()
        if video_id is not None:
            path, _ = QFileDialog.getOpenFileName(self.window, "원래 영상과 같은 내용의 파일 선택")
            if path:
                def reconnect():
                    from .core import ScanResult
                    self.core.reconnect_video(video_id, path)
                    return ScanResult(0, ())
                self.window.scan(operation=reconnect)

    def show_excluded(self):
        self.window.web_host.controllers['folders'].open_section('excluded')
