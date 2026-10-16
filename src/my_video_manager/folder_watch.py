"""Qt와 독립된 변경 묶음. 콜백은 검사 작업을 외부 실행기에 전달해야 한다."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
MAX_BATCH_WAIT_SECONDS = 60.0
FolderBatch = tuple[Path, ...]
# None은 접근할 수 없는 요청 폴더 또는 하위 항목이다. ScanIssue로 보고한다.
Snapshot = dict[Path, tuple[int, int] | None]
STABLE_SUFFIXES = VIDEO_SUFFIXES | SUBTITLE_SUFFIXES
logger = logging.getLogger(__name__)


@dataclass
class _FolderState:
    signature: Snapshot
    stable_since: float


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
    return _minimal({Path(path).resolve() for path in folders})


def _minimal(folders: Iterable[Path]) -> FolderBatch:
    """정규화된 경로 중 상위 폴더만 남긴다. 비용은 경로 수 × 깊이에 비례한다."""
    result: dict[Path, None] = {}
    for folder in sorted(set(folders), key=lambda p: (len(p.parts), str(p))):
        if _owner(folder, result) is None:
            result[folder] = None
    return tuple(result)


def _owner(path: Path, folders) -> Path | None:
    """path를 담는 폴더. 상위 경로를 따라 올라가며 folders(집합 또는 dict)를 찾는다."""
    if path in folders:
        return path
    for parent in path.parents:
        if parent in folders:
            return parent
    return None


def _group(snapshot: Snapshot, folders: FolderBatch) -> dict[Path, Snapshot]:
    groups: dict[Path, Snapshot] = {folder: {} for folder in folders}
    for path, value in snapshot.items():
        owner = _owner(path, groups)
        if owner is not None:
            groups[owner][path] = value
    return groups


def folder_snapshot(folders: FolderBatch) -> Snapshot:
    """영상·외부 자막의 서명만 읽는다. 접근 실패는 범위와 관계없이 None이다.

    디렉터리 이동 시 자식 이벤트가 누락되어도 복사 중인 자식을 기다린다.
    라이브러리 순회와 같이 정션·심볼릭 링크를 따라가지 않는다.
    """
    result = {}
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
                        # 비싼 핸들 기반 stat은 전달 직전의 변경 파일 확인에만 쓴다.
                        result[path] = (info.st_size, info.st_mtime_ns)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
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
        # tick이 잠금 밖에서 읽으므로 _confirmed와 _folder_states는 제자리에서 바꾸지 않고 교체한다.
        self._confirmed: Snapshot = {}
        self._snapshot_error_reported = False
        self._snapshot_error_since: float | None = None
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
        # 이벤트 경로별 (첫 이벤트, 마지막 이벤트) 시각.
        self._pending: dict[Path, tuple[float, float]] = {}
        self._last_event = 0.0
        self._folder_states: dict[Path, _FolderState] = {}
        self._batch_started: float | None = None

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
            self._confirmed = {}
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
            self._pending = {path: times for path, times in self._pending.items() if self._contains(path)}
            self._revision += 1
            self._folder_states = {}
            self._confirmed = {path: sig for path, sig in self._confirmed.items() if self._contains(path)}
            if self._pending:
                self._batch_started = min(first for first, _ in self._pending.values())
            else:
                self._clear()
        if self._active:
            try:
                self._watcher.update(folders)
                self._update_failed = ()
            except Exception:
                self._update_failed = minimal_folders((*previous, *folders))
                raise

    def _contains(self, path):
        return _owner(path, self._folders) is not None

    def _clear(self):
        self._timer_id += 1
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        self._pending = {}
        self._folder_states = {}
        self._batch_started = None
        self._snapshot_error_reported = False
        self._snapshot_error_since = None
        self._revision += 1

    def _schedule(self, seconds):
        epoch = self._epoch
        self._timer_id += 1
        timer_id = self._timer_id
        self._timer = self._scheduler.call_later(seconds, lambda: self._tick(epoch, timer_id))

    def _stale(self, epoch, revision):
        """잠금 안에서 호출한다. 잠금 밖 계산 중 종료·폴더 변경·새 이벤트가 있었으면 버린다."""
        if not self._active or epoch != self._epoch:
            return True
        if revision != self._revision:
            # 순회 중 새 이벤트가 들어오면 새 묶음으로 다시 확인한다.
            if self._pending and self._timer is None:
                self._schedule(self._poll)
            return True
        return False

    def _changed(self, epoch, folders):
        paths = {Path(path).resolve() for path in folders}
        with self._lock:
            if not self._active or epoch != self._epoch:
                return
            accepted = [path for path in paths if self._contains(path)]
            if not accepted:
                return
            now = self._clock()
            for path in accepted:
                first = self._pending.get(path, (now, now))[0]
                self._pending[path] = (first, now)
            self._last_event = now
            if self._batch_started is None:
                self._batch_started = now
            self._revision += 1
            if self._timer is None:
                self._schedule(self._debounce)

    def _tick(self, epoch, timer_id):
        with self._lock:
            if (not self._active or epoch != self._epoch
                    or timer_id != self._timer_id or not self._pending):
                return
            self._timer = None
            now = self._clock()
            quiet = now - self._last_event
            if quiet < self._debounce and now - self._batch_started < MAX_BATCH_WAIT_SECONDS:
                # 단조 시계의 소수점 반올림 때문에 0에 가까운 재예약을 반복하지 않는다.
                self._schedule(max(0.001, self._debounce - quiet))
                return
            revision = self._revision
            pending = dict(self._pending)
            states, confirmed = self._folder_states, self._confirmed
        # 순회·배정·서명 비교·OS 핸들 확인은 잠금 밖에서 하고, 반영 전에 revision을 다시 본다.
        folders = _minimal(pending)
        snapshot_error = None
        try:
            signature = self._snapshot(folders)
        except OSError as error:
            snapshot_error, signature = error, None
        now = self._clock()
        if signature is None:
            with self._lock:
                if self._stale(epoch, revision):
                    return
                if not self._snapshot_error_reported:
                    logger.warning("감시 폴더 안정화 확인 실패; 제한적으로 재시도합니다: %s", snapshot_error)
                    self._snapshot_error_reported = True
                if self._snapshot_error_since is None:
                    self._snapshot_error_since = now
                if now - self._snapshot_error_since < self._stable:
                    self._schedule(self._poll)
                    return
            # 주입 어댑터가 범위 전체의 오류를 던져도 무한 대기하지 않는다.
            signature = {folder: None for folder in folders}
        groups = _group(signature, folders)
        owners = {path: _owner(path, groups) for path in pending}
        first: dict[Path, float] = {}
        last: dict[Path, float] = {}
        for path, (started, latest) in pending.items():
            folder = owners[path]
            first[folder] = min(started, first.get(folder, started))
            last[folder] = max(latest, last.get(folder, latest))
        new_states = {}
        for folder, current in groups.items():
            state = states.get(folder)
            new_states[folder] = (state if state is not None and state.signature == current
                                  else _FolderState(current, now))
        stable = {folder for folder in folders
                  if now - last[folder] >= self._debounce
                  and now - new_states[folder].stable_since >= self._stable}
        # 첫 이벤트부터 60초 안인 폴더는 이동 쌍이 갈리지 않게 함께 기다린다.
        # 60초가 지난 폴더는 준비되는 대로 각자 전달한다.
        young = {folder for folder in folders if now - first[folder] < MAX_BATCH_WAIT_SECONDS}
        candidates = tuple(folder for folder in folders
                           if folder in stable and (folder not in young or young <= stable))
        blocked = set()
        for folder in candidates:
            for path, expected in groups[folder].items():
                if expected is None or expected == confirmed.get(path):
                    continue
                try:
                    if not self._ready(path):
                        blocked.add(folder)
                        break
                    info = os.stat(path, follow_symlinks=False)
                    if (info.st_size, info.st_mtime_ns) != expected:
                        blocked.add(folder)
                        break
                except (FileNotFoundError, NotADirectoryError):
                    blocked.add(folder)
                    break
                except OSError:
                    # 영구 접근 거부는 scan의 오류 보고에 맡긴다.
                    continue
        ready_folders = tuple(folder for folder in candidates if folder not in blocked
                              and (folder not in young or not blocked & young))
        if ready_folders:
            delivered = set(ready_folders)
            kept = {path: sig for path, sig in confirmed.items() if _owner(path, delivered) is None}
            for folder in ready_folders:
                kept.update(groups[folder])
            remaining = {path: times for path, times in pending.items() if owners[path] not in delivered}
        with self._lock:
            if self._stale(epoch, revision):
                return
            if snapshot_error is None:
                self._snapshot_error_since = None
            checked = self._clock()
            for folder in blocked:
                new_states[folder] = _FolderState(new_states[folder].signature, checked)
            self._folder_states = new_states
            if not ready_folders:
                self._schedule(self._poll)
                return
            try:
                self._on_batch_ready(ready_folders)
            except Exception:
                logger.exception("감시 폴더 검사 요청 전달 실패; 다시 시도합니다")
                self._schedule(self._poll)
                return
            self._confirmed = kept
            self._folder_states = {folder: state for folder, state in new_states.items()
                                   if folder not in delivered}
            if remaining:
                self._pending = remaining
                self._batch_started = min(started for started, _ in remaining.values())
                self._revision += 1
                self._schedule(self._poll)
            else:
                self._clear()
