"""watchdog의 OS 이벤트를 코어의 폴더 묶음으로 바꾸는 어댑터."""

from pathlib import Path
import logging
import sys

from watchdog.events import FileSystemEventHandler
if sys.platform == "win32":
    from watchdog.observers.read_directory_changes import WindowsApiObserver as Observer
else:
    from watchdog.observers import Observer

from .folder_watch import STABLE_SUFFIXES, minimal_folders

logger = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change

    def on_any_event(self, event):
        if event.event_type not in ("created", "deleted", "modified", "moved"):
            return
        # 자식 변경마다 오는 DirModified는 상위 전체 검사로 넓히지 않는다.
        if event.is_directory and event.event_type == "modified":
            return
        if event.event_type == "modified" and Path(event.src_path).suffix.casefold() not in STABLE_SUFFIXES:
            return  # .part 등의 지속적인 쓰기가 디바운스를 무한 연장하지 않게 한다.
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
        self._failed = set()

    @property
    def failed_folders(self):
        return tuple(sorted(self._failed))

    def start(self, folders, on_change):
        self.stop()
        self._observer = Observer()
        self._handler = _Handler(on_change)
        try:
            # dispatcher를 먼저 시작하면 schedule마다 emitter 시작 실패를 격리할 수 있다.
            self._observer.start()
            self.update(folders)
        except Exception:
            self.stop()
            raise

    def update(self, folders):
        if self._observer is None:
            return
        folders = minimal_folders(folders)
        # 새 구독을 먼저 설치해 상하위 루트 교체 중 감시 공백을 줄인다.
        self._failed.intersection_update(folders)
        for folder in folders:
            if folder not in self._watches:
                try:
                    self._watches[folder] = self._observer.schedule(self._handler, str(folder), recursive=True)
                    self._failed.discard(folder)
                except Exception as error:
                    if folder not in self._failed:
                        logger.warning("감시 폴더 설치 실패; 다른 폴더는 계속 감시합니다: %s (%s)", folder, error)
                    self._failed.add(folder)
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
        self._failed.clear()
        self._handler = None
