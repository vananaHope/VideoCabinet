"""실행 중 폴더 감시를 Qt 메인 스레드의 검사 작업자에 연결한다."""
import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)


class FolderWatchControls(QObject):
    """감시 묶음마다 기존 ScanWorker 경로로 지정 폴더 검사를 한 번 실행한다.

    on_batch_ready는 감시 타이머 스레드에서 상태 잠금을 쥔 채 불리므로 queued signal로만 넘긴다.
    검사나 사용자 작업이 진행 중일 때 온 묶음은 합쳐 두었다가 끝나면 한 번에 실행한다.
    수명·설정·폴더 변경 호출은 모두 Qt 메인 스레드에서 직렬로 한다.
    """
    batch_ready = Signal(object)
    changed = Signal()

    def __init__(self, window, *, watcher=None, **options):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.library = window.library_page
        self.start_failed = False
        # 순서를 유지한 폴더 집합. 전체 검사가 예약되면 폴더 묶음은 그 안에 포함된다.
        self._pending = {}
        self._full_scan = False
        # 자동 검사가 이미 알린 안내. 원인이 그대로인 동안(드라이브 분리 등) 같은 실패를 반복해 알리지 않는다.
        self._reported = KnownIssues()
        self.batch_ready.connect(self.enqueue, Qt.ConnectionType.QueuedConnection)
        for tab in ('folders', 'settings'):
            self.changed.connect(window.web_host.controllers[tab].refresh)
        self.watch = self.core.create_folder_watch(self.batch_ready.emit, watcher=watcher, **options)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(500)
        self._retry.timeout.connect(self.flush)
        # scan_finished 안에서 바로 새 작업자를 만들면 같은 신호의 다른 수신자가 순서를 거꾸로 받는다.
        self.library.scan_state_changed.connect(
            lambda scanning: None if scanning else QTimer.singleShot(0, self.flush))

    @property
    def enabled(self):
        return self.core.automatic_detection_enabled()

    def start(self):
        """앱 시작 검사보다 먼저 부른다. start 직후 놓친 변경은 뒤이은 시작 검사가 덮는다."""
        try:
            self.watch.start()
            self.start_failed = False
        except Exception as error:
            log.warning("폴더 감시를 시작하지 못했습니다: %s", error)
            self.start_failed = True
        self.changed.emit()

    def stop(self):
        """완전 종료 때 감시를 먼저 멈춘 뒤 미룬 묶음을 버린다. 다음 시작 검사가 다시 확인한다."""
        self.watch.stop()
        self._retry.stop()
        self._pending.clear()
        self._full_scan = False

    def set_enabled(self, enabled):
        """끄면 감지와 미룬 묶음을 멈춘다. 다시 켜면 꺼진 동안의 변경을 전체 검사로 한 번 반영한다."""
        if not isinstance(enabled, bool):
            raise TypeError("자동 감지 설정은 bool이어야 합니다.")
        if enabled == self.enabled and not (enabled and self.start_failed):
            return
        # 시작에 실패하면 감시 수명이 시작되지 않은 상태로 남으므로 다시 켤 때 직접 시작한다.
        retry = enabled and self.start_failed
        try:
            self.core.set_automatic_detection_enabled(enabled)
            if retry:
                self.watch.start()
            if enabled:
                self.start_failed = False
        except Exception as error:
            if not enabled or self.enabled is not True:
                raise  # 설정 저장 실패는 화면의 오류 자리에 보인다.
            log.warning("폴더 감시를 시작하지 못했습니다: %s", error)
            self.start_failed = True
        self._pending.clear()
        # 시작 검사와 같이 감시 폴더가 없으면 전체 검사를 하지 않는다.
        self._full_scan = enabled and bool(self.core.watched_folders())
        self.changed.emit()
        self.flush()

    def request_full_scan(self):
        """검사 중이라 바로 돌리지 못한 전체 검사를 끝난 뒤로 미룬다."""
        self._full_scan = True
        self.flush()

    def enqueue(self, folders):
        if not self.enabled:
            return
        self._pending.update(dict.fromkeys(folders))
        self.flush()

    def unwatched_folders(self):
        """폴더 관리에 경고로 보일 감시 실패 폴더. 꺼져 있으면 감시하지 않으므로 비운다."""
        if not self.enabled:
            return ()
        if self.start_failed:
            return tuple(folder.path for folder in self.core.watched_folders())
        return self.watch.failed_folders

    def _user_busy(self):
        # 대화상자 중 검사가 시작되면 사용자가 고른 작업이 "검사 뒤 다시 시도" 안내로 거부된다.
        return (QApplication.activeModalWidget() is not None or self.library.bridge.busy
                or self.window.web_host.controllers['folders'].bridge.busy)

    def flush(self):
        if not (self._full_scan or self._pending) or self.window.tray.quitting:
            return
        if self.library.worker is not None:
            return  # 검사가 끝나면 scan_state_changed가 다시 부른다.
        if self._user_busy():
            self._retry.start()
            return
        folders = None if self._full_scan else tuple(self._pending)
        self._full_scan = False
        self._pending.clear()
        known = self._reported
        # 조용한 완료 판단의 근거. 완료 신호보다 먼저 작업자에서 채워진다.
        anchors = KnownIssues()

        def scan():
            result = self.core.scan() if folders is None else self.core.scan(folders=folders)
            # 검사한 범위의 안내만 이번 결과로 바꾼다. 작업자는 한 번에 하나라 경합하지 않는다.
            kept = () if folders is None else tuple(
                issue for issue in known.issues if not within(issue.path, folders))
            # 범위 밖 기억과 이번에 그대로 다시 나온 기억만 근거로 삼아, 재연결 직후 새 원인의 실패는 알린다.
            anchors.issues = frozenset((*kept, *(issue for issue in known.issues if issue in result.issues)))
            self._reported = KnownIssues((*kept, *result.issues))
            return result

        self.library.scan(operation=scan, quiet_if_unchanged=True, known_issues=anchors)


class KnownIssues:
    """자동 검사가 이미 알린 안내. 알린 실패 폴더 아래의 실패(끊긴 루트의 하위 폴더 등)도 같은 원인으로 본다."""

    def __init__(self, issues=()):
        self.issues = frozenset(issues)

    def __contains__(self, issue):
        return issue in self.issues or issue.failed and any(
            known.failed and within(issue.path, (known.path,)) for known in self.issues)


def within(path, folders):
    return any(path == folder or path.is_relative_to(folder) for folder in folders)
