"""Qt와 독립된 변경 묶음. 콜백은 검사 작업을 외부 실행기에 전달해야 한다."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
import os
from pathlib import Path
import stat
from threading import RLock, Timer
from time import monotonic
from typing import Protocol

from .settings import Settings
from .media import VIDEO_SUFFIXES
from .external_subtitles import EXTENSIONS as SUBTITLE_SUFFIXES


AUTOMATIC_DETECTION_KEY = "library.automatic_detection_enabled"
FolderBatch = tuple[Path, ...]
# None은 접근할 수 없는 하위 항목이다. 검사 단계에서 ScanIssue로 보고한다.
Snapshot = dict[Path, tuple[int, int] | None]
STABLE_SUFFIXES = VIDEO_SUFFIXES | SUBTITLE_SUFFIXES
logger = logging.getLogger(__name__)


class FolderWatcher(Protocol):
    """수명 메서드는 소유 스레드에서 직렬 호출, 이벤트는 임의 스레드에서 전달.

    이동의 원본·대상은 같은 콜백에 넣는다. stop은 이후 이벤트 전달을 끝낸다.
    이벤트 콜백에서 수명 메서드를 호출하지 않는다.
    """

    def start(self, folders: FolderBatch, on_change: Callable[[FolderBatch], None]) -> None: ...
    def update(self, folders: FolderBatch) -> None: ...
    def stop(self) -> None: ...


class ScheduledCall(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    """콜백은 call_later가 반환한 뒤 실행한다. 취소와 실행이 경합할 수 있다."""

    def call_later(self, seconds: float, callback: Callable[[], None]) -> ScheduledCall: ...


class ThreadScheduler:
    def call_later(self, seconds, callback):
        timer = Timer(seconds, callback)
        timer.daemon = True
        timer.start()
        return timer


def minimal_folders(folders: Iterable[Path]) -> FolderBatch:
    if isinstance(folders, (str, os.PathLike)):
        raise TypeError("folders에는 경로 목록을 넘겨야 합니다.")
    result: list[Path] = []
    for folder in sorted({Path(path).resolve() for path in folders}, key=lambda p: (len(p.parts), str(p))):
        if not any(folder.is_relative_to(parent) for parent in result):
            result.append(folder)
    return tuple(result)


def folder_snapshot(folders: FolderBatch) -> Snapshot:
    """영상·외부 자막의 서명만 읽는다. 요청 폴더의 접근 실패만 예외다.

    디렉터리 이동 시 자식 이벤트가 누락되어도 복사 중인 자식을 기다린다.
    라이브러리 순회와 같이 정션·심볼릭 링크를 따라가지 않는다.
    """
    result = {}
    roots = set(folders)
    pending = list(folders)
    while pending:
        directory = pending.pop()
        try:
            info = directory.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        result[path] = None
                        continue
                    if (stat.S_ISLNK(info.st_mode)
                            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode) and path.suffix.casefold() in STABLE_SUFFIXES:
                        try:
                            # Windows의 디렉터리 항목 캐시는 복사 중에도 고정될 수 있다.
                            info = os.stat(path, follow_symlinks=False)
                            result[path] = (info.st_size, info.st_mtime_ns)
                        except FileNotFoundError:
                            continue
                        except OSError:
                            result[path] = None
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            if directory in roots:
                raise
            result[directory] = None
    return result


def file_ready(path: Path) -> bool:
    """내용을 읽지 않고 쓰기 핸들과 충돌하는 읽기 열기를 확인한다.

    Windows 공유/잠금 위반은 False, 다른 접근 오류는 호출자에게 전달한다.
    비Windows의 open은 Windows 공유 모드 보장을 제공하지 않는다.
    """
    if os.name != "nt":
        with path.open("rb"):
            return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ (쓰기/삭제 공유 없음), OPEN_EXISTING.
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        if error in (32, 33):  # ERROR_SHARING_VIOLATION / ERROR_LOCK_VIOLATION
            return False
        raise ctypes.WinError(error)
    try:
        return True
    finally:
        close(handle)


def automatic_detection_enabled(settings: Settings) -> bool:
    value = settings.get(AUTOMATIC_DETECTION_KEY, True)
    return value if isinstance(value, bool) else True


class FolderWatch:
    """start/stop은 앱 수명, set_enabled는 영속 설정이며 서로 독립적이다.

    기본 디바운스 0.5초, 서명 확인 1초, 안정화 5초. 유휴 중에는 타이머가 없다.
    on_batch_ready는 짧은 enqueue/Qt queued signal이어야 한다. 이 클래스는
    scan을 호출하거나 검사 스레드를 만들지 않는다. 콜백이 예외를 던지면 재시도한다.
    start/stop/set_enabled/set_folders는 소유 스레드에서 직렬 호출한다.
    """

    def __init__(self, settings: Settings, folders: Iterable[Path],
                 on_batch_ready: Callable[[FolderBatch], None], *, watcher: FolderWatcher,
                 clock: Callable[[], float] = monotonic, scheduler: Scheduler | None = None,
                 snapshot: Callable[[FolderBatch], Snapshot] = folder_snapshot,
                 ready: Callable[[Path], bool] = file_ready,
                 debounce_seconds: float = 0.5, stable_seconds: float = 5.0,
                 poll_seconds: float = 1.0):
        if debounce_seconds <= 0 or stable_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("감지 대기 시간은 양수여야 합니다.")
        self._settings = settings
        self._folders = minimal_folders(folders)
        self._on_batch_ready = on_batch_ready
        self._watcher = watcher
        self._clock = clock
        self._scheduler = scheduler or ThreadScheduler()
        self._snapshot = snapshot
        self._ready = ready
        self._confirmed: Snapshot = {}
        self._snapshot_error_reported = False
        self._update_failed: FolderBatch = ()
        self._debounce = debounce_seconds
        self._stable = stable_seconds
        self._poll = poll_seconds
        self._lock = RLock()
        self._started = False
        self._active = False
        self._epoch = 0
        self._revision = 0
        self._timer: ScheduledCall | None = None
        self._timer_id = 0
        self._pending: set[Path] = set()
        self._last_event = 0.0
        self._signature: Snapshot | None = None
        self._stable_since = 0.0

    @property
    def enabled(self) -> bool:
        return automatic_detection_enabled(self._settings)

    @property
    def failed_folders(self) -> FolderBatch:
        """감시 설치 실패 경로. 자동 재접속은 하지 않는다."""
        return tuple(sorted(set(self._update_failed) | set(getattr(self._watcher, "failed_folders", ()))))

    def start(self) -> None:
        self._started = True
        if not self.enabled or self._active:
            return
        with self._lock:
            self._active = True
            self._epoch += 1
            epoch = self._epoch
        try:
            self._watcher.start(self._folders, lambda folders: self._changed(epoch, folders))
            self._update_failed = ()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self._started = False
        with self._lock:
            self._active = False
            self._epoch += 1
            self._clear()
            self._confirmed.clear()
        # 콜백의 state lock을 해제한 뒤 observer를 join한다.
        self._watcher.stop()

    def set_enabled(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("자동 감지 설정은 bool이어야 합니다.")
        self._settings.set(AUTOMATIC_DETECTION_KEY, enabled)
        started = self._started
        if not enabled:
            self.stop()
            self._started = started
        elif started:
            self.start()

    def set_folders(self, folders: Iterable[Path]) -> None:
        folders = minimal_folders(folders)
        with self._lock:
            if folders == self._folders and not self.failed_folders:
                return
            previous = self._folders
            self._folders = folders
            self._pending = {path for path in self._pending if self._contains(path)}
            self._revision += 1
            self._signature = None
            self._confirmed = {path: sig for path, sig in self._confirmed.items() if self._contains(path)}
            if not self._pending:
                self._clear()
        if self._active:
            try:
                self._watcher.update(folders)
                self._update_failed = ()
            except Exception:
                self._update_failed = minimal_folders((*previous, *folders))
                raise

    def _contains(self, path):
        return any(path.is_relative_to(root) for root in self._folders)

    def _clear(self):
        self._timer_id += 1
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        self._pending.clear()
        self._signature = None
        self._snapshot_error_reported = False
        self._revision += 1

    def _schedule(self, seconds):
        epoch = self._epoch
        self._timer_id += 1
        timer_id = self._timer_id
        self._timer = self._scheduler.call_later(seconds, lambda: self._tick(epoch, timer_id))

    def _changed(self, epoch, folders):
        with self._lock:
            if not self._active or epoch != self._epoch:
                return
            paths = (Path(path).resolve() for path in folders)
            accepted = {path for path in paths if self._contains(path)}
            if not accepted:
                return
            self._pending.update(accepted)
            self._last_event = self._clock()
            self._revision += 1
            if self._timer is None:
                self._schedule(self._debounce)

    def _tick(self, epoch, timer_id):
        with self._lock:
            if (not self._active or epoch != self._epoch
                    or timer_id != self._timer_id or not self._pending):
                return
            self._timer = None
            quiet = self._clock() - self._last_event
            if quiet < self._debounce:
                # 단조 시계의 소수점 반올림 때문에 0에 가까운 재예약을 반복하지 않는다.
                self._schedule(max(0.001, self._debounce - quiet))
                return
            revision = self._revision
            folders = minimal_folders(self._pending)
        try:
            signature = self._snapshot(folders)
        except OSError as error:
            if not self._snapshot_error_reported:
                logger.warning("감시 폴더 안정화 확인 실패; 재시도합니다: %s", error)
                self._snapshot_error_reported = True
            signature = None
        with self._lock:
            if not self._active or epoch != self._epoch:
                return
            # 순회 중 새 이벤트가 들어오면 새 묶음으로 다시 확인한다.
            if revision != self._revision:
                if self._pending and self._timer is None:
                    self._schedule(self._poll)
                return
            now = self._clock()
            if signature is None or signature != self._signature:
                self._signature = signature
                self._stable_since = now
            if signature is None or now - self._stable_since < self._stable:
                self._schedule(self._poll)
                return
            changed = {path: sig for path, sig in signature.items()
                       if sig is not None and sig != self._confirmed.get(path)}
        # OS 핸들 확인은 state lock 밖에서 수행한다. 종료/새 이벤트는 아래에서 재확인한다.
        ready = True
        for path, expected in changed.items():
            try:
                if not self._ready(path):
                    ready = False
                    break
                info = os.stat(path, follow_symlinks=False)
                if (info.st_size, info.st_mtime_ns) != expected:
                    ready = False
                    break
            except (FileNotFoundError, NotADirectoryError):
                ready = False
                break
            except OSError:
                # 영구 접근 거부를 복사로 오인해 기다리지 않는다. scan이 오류를 보고한다.
                continue
        with self._lock:
            if not self._active or epoch != self._epoch:
                return
            if revision != self._revision:
                if self._pending and self._timer is None:
                    self._schedule(self._poll)
                return
            if not ready:
                self._stable_since = self._clock()
                self._schedule(self._poll)
                return
            try:
                self._on_batch_ready(folders)
            except Exception:
                logger.exception("감시 폴더 검사 요청 전달 실패; 다시 시도합니다")
                self._schedule(self._poll)
            else:
                self._confirmed = {path: sig for path, sig in self._confirmed.items()
                                   if not any(path.is_relative_to(folder) for folder in folders)}
                self._confirmed.update(signature)
                self._clear()
