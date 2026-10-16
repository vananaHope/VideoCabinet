"""watchdog의 OS 이벤트를 코어의 폴더 묶음으로 바꾸는 어댑터."""

from pathlib import Path
import logging
import os
import sys
from threading import Lock, RLock

from watchdog.events import DirCreatedEvent, FileSystemEventHandler

from .folder_watch import STABLE_SUFFIXES, minimal_folders

logger = logging.getLogger(__name__)


class _Overflow(DirCreatedEvent):
    """OS 이벤트 버퍼가 넘쳐 버려진 변경. 감시 루트 전체를 다시 확인한다."""


if sys.platform == "win32":
    from watchdog.observers.api import BaseObserver
    from watchdog.observers.read_directory_changes import WindowsApiEmitter
    from watchdog.observers.winapi import close_directory_handle, read_events

    class _Emitter(WindowsApiEmitter):
        """WindowsApiEmitter에 연결 끊김과 버퍼 넘침 처리를 더한다.

        루트 삭제 뒤 스스로 멈춘 emitter를 unschedule해도 핸들을 두 번 닫지 않는다.
        드라이브 분리 등의 읽기 오류는 스레드 밖 traceback 대신 error에 남긴다.
        """

        error = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._handle_lock = Lock()

        def on_thread_stop(self):
            with self._handle_lock:
                handle, self._whandle = self._whandle, None
            if handle:
                close_directory_handle(handle)

        def _read_events(self):
            handle = self._whandle
            if not handle:
                return []
            events = read_events(handle, self.watch.path, recursive=self.watch.is_recursive)
            # 동기 ReadDirectoryChangesW는 변경이나 오류가 있을 때만 돌아온다.
            # 중지 중이 아닌 0바이트는 버퍼 넘침이다.
            if not events and self.should_keep_running():
                self.queue_event(_Overflow(self.watch.path))
            return events

        def run(self):
            try:
                super().run()
            except OSError as error:
                if self.should_keep_running():
                    self.error = error

    def Observer():
        # WindowsApiObserver와 같은 emitter 구현을 쓰며 import 실패를 polling으로 대체하지 않는다.
        return BaseObserver(_Emitter)
else:
    from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change
        self.overflows = 0

    def on_any_event(self, event):
        if isinstance(event, _Overflow):
            self.overflows += 1
            if self.overflows == 1:
                logger.warning("감시 이벤트 버퍼가 넘쳐 감시 폴더 전체를 다시 확인합니다: %s", event.src_path)
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

    start/update/stop은 소유 스레드에서 호출한다. reconnect는 타이머 스레드에서
    호출할 수 있다. 생성만으로는 스레드나 OS 감시 핸들을 만들지 않는다.
    """

    def __init__(self):
        # 소유 스레드의 수명 메서드와 타이머 스레드의 reconnect를 직렬화한다.
        # 이벤트 전달(dispatcher) 스레드는 이 잠금을 쓰지 않는다.
        self._lock = RLock()
        self._observer = None
        self._handler = None
        self._watches = {}
        self._failed = set()

    @property
    def failed_folders(self):
        with self._lock:
            return tuple(sorted(self._failed))

    def start(self, folders, on_change):
        self.stop()
        with self._lock:
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
        with self._lock:
            if self._observer is None:
                return
            folders = minimal_folders(folders)
            # 새 구독을 먼저 설치해 상하위 루트 교체 중 감시 공백을 줄인다.
            # 이미 실패한 루트는 느린 드라이브에서 소유 스레드를 막지 않도록 reconnect에 맡긴다.
            self._failed.intersection_update(folders)
            for folder in folders:
                if folder not in self._watches and folder not in self._failed:
                    self._install(folder)
            for folder in tuple(self._watches):
                if folder not in folders:
                    self._observer.unschedule(self._watches.pop(folder))

    def reconnect(self):
        """멈춘 감시를 실패로 옮기고, 다시 나타난 실패 루트를 재설치해 반환한다.

        emitter 스레드는 루트 삭제(DirDeletedEvent) 뒤 스스로 끝나거나 드라이브 분리 같은
        읽기 오류로 끝난다. 어느 경우든 스레드 생존 여부만 메모리에서 확인한다.
        존재 확인은 느린 드라이브에서 오래 걸릴 수 있어 잠금 밖에서 한다.
        """
        with self._lock:
            observer = self._observer
            if observer is None:
                return ()
            emitters = {emitter.watch: emitter for emitter in list(observer.emitters)}
            for folder, watch in tuple(self._watches.items()):
                emitter = emitters.get(watch)
                if emitter is not None and emitter.is_alive():
                    continue
                del self._watches[folder]
                try:
                    observer.unschedule(watch)
                except Exception:
                    pass  # 이미 멈춘 emitter의 정리 실패가 재연결을 막지 않는다.
                self._failed.add(folder)
                logger.warning("감시 폴더 연결이 끊겼습니다; 다른 폴더는 계속 감시하며 다시 연결을 시도합니다: %s (%s)",
                               folder, getattr(emitter, "error", None) or "폴더 없음")
            candidates = tuple(self._failed)
        present = [folder for folder in candidates if os.path.isdir(folder)]
        recovered = []
        with self._lock:
            if self._observer is not observer:
                return ()
            for folder in present:
                if folder in self._failed and self._install(folder):
                    logger.info("감시 폴더를 다시 연결했습니다: %s", folder)
                    recovered.append(folder)
        return tuple(recovered)

    def _install(self, folder):
        try:
            self._watches[folder] = self._observer.schedule(self._handler, str(folder), recursive=True)
        except Exception as error:
            if folder not in self._failed:
                logger.warning("감시 폴더 설치 실패; 다른 폴더는 계속 감시합니다: %s (%s)", folder, error)
            self._failed.add(folder)
            return False
        self._failed.discard(folder)
        return True

    def stop(self):
        with self._lock:
            observer, self._observer = self._observer, None
            handler, self._handler = self._handler, None
            self._watches.clear()
            self._failed.clear()
        # 이벤트 콜백이 컨트롤러 잠금을 쓰므로 join은 이 잠금 밖에서 한다.
        if observer is not None:
            observer.stop()
            if observer.ident is not None:
                observer.join()
        if handler is not None and handler.overflows > 1:
            logger.warning("감시 중 이벤트 버퍼 넘침이 %d번 있었습니다.", handler.overflows)
