"""watchdog의 OS 이벤트를 코어의 폴더 묶음으로 바꾸는 어댑터."""

from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .folder_watch import minimal_folders


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change

    def on_any_event(self, event):
        if event.event_type not in ("created", "deleted", "modified", "moved"):
            return
        # 자식 변경마다 오는 DirModified는 상위 전체 검사로 넓히지 않는다.
        if event.is_directory and event.event_type == "modified":
            return
        paths = [event.src_path]
        if event.event_type == "moved":
            paths.append(event.dest_path)
        folders = tuple(dict.fromkeys(
            Path(path) if event.is_directory else Path(path).parent for path in paths if path))
        if folders:
            self._on_change(folders)


class WatchdogFolderWatcher:
    """Windows에서는 ReadDirectoryChangesW, 감시 루트별 재귀 구독.

    start/update/stop은 소유 스레드에서 호출한다. 누락 루트 재접속은 #133 범위다.
    생성만으로는 스레드나 OS 감시 핸들을 만들지 않는다.
    """

    def __init__(self):
        self._observer = None
        self._handler = None
        self._watches = {}

    def start(self, folders, on_change):
        self.stop()
        self._observer = Observer()
        self._handler = _Handler(on_change)
        try:
            self.update(folders)
            self._observer.start()
        except Exception:
            self.stop()
            raise

    def update(self, folders):
        if self._observer is None:
            return
        folders = minimal_folders(folders)
        # 새 구독을 먼저 설치해 상하위 루트 교체 중 감시 공백을 줄인다.
        added = []
        try:
            for folder in folders:
                if folder not in self._watches:
                    self._watches[folder] = self._observer.schedule(self._handler, str(folder), recursive=True)
                    added.append(folder)
        except Exception:
            for folder in added:
                self._observer.unschedule(self._watches.pop(folder))
            raise
        for folder in tuple(self._watches):
            if folder not in folders:
                self._observer.unschedule(self._watches.pop(folder))

    def stop(self):
        observer, self._observer = self._observer, None
        if observer is not None:
            observer.stop()
            if observer.ident is not None:
                observer.join()
        self._watches.clear()
        self._handler = None
