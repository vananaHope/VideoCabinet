"""업데이트 선택 뒤의 내려받기·설치 전 확인·설치 넘기기를 앱 수명에 연결한다. 내려받기·검증·보조 프로세스는 코어가 맡는다."""
from dataclasses import replace
from datetime import datetime, timezone
import logging
import threading
from time import monotonic

from PySide6.QtCore import QObject, Qt, Signal

from .update_check import UpdateCheckResult
from .update_install import UpdateInstallError

log = logging.getLogger(__name__)
# 진행률 콜백은 64KB마다 작업자 스레드에서 불린다. 화면에는 이 간격으로 줄여 보낸다.
PROGRESS_INTERVAL = 0.1
ACTIVE = ('downloading', 'cancelling', 'confirm', 'ready', 'preparing')
# 다시 시도해도 같은 결과이거나, 이미 넘긴 보조 프로세스가 기다리고 있어 두 번째를 띄우면 안 되는 실패.
NO_RETRY = frozenset({'source_run', 'not_newer', 'no_update', 'quit_failed'})
CANCELLED = '업데이트 내려받기를 취소했습니다. 받던 파일은 지웠습니다.'
STATE_CHANGED = '업데이트 진행 상태가 바뀌었습니다. 다시 확인해 주세요.'


class _Signals(QObject):
    progress = Signal(object, object)
    downloaded = Signal(object)
    handed_off = Signal(str)


class UpdateInstall(QObject):
    """업데이트 선택 뒤의 단계를 하나씩 진행한다.

    phase: idle → downloading(→ cancelling) → confirm ⇄ ready → preparing → 앱 완전 종료. 실패하면 failed.
    막는 작업(재생·받아쓰기·번역·다듬기·자막 기능 준비)이 없으면 확인 없이 바로 설치를 넘긴다.
    한 번에 하나만 진행하므로 같은 업데이트를 두 번 눌러도 내려받기나 보조 프로세스가 둘 뜨지 않는다.
    지난 실행에서 넘긴 설치의 결과(result)는 시작할 때 한 번 읽고 기록을 지운다. 실패면 installer.log는 남긴다.
    """
    # 단계가 바뀌었다. 새 버전 알림을 숨길지도 함께 바뀔 수 있다.
    changed = Signal()
    # 받은 크기만 바뀌었다(약 100ms마다).
    progressed = Signal()

    def __init__(self, window, *, http=None, prepare=None, quit_app=None):
        super().__init__(window)
        self.window, self.core = window, window.core
        self._http = http
        # prepare_update_install의 시험용 인자(launcher, relaunch, pid, ready_timeout).
        self._prepare = dict(prepare or {})
        self._quit_app = quit_app or self._quit_for_install
        self.closed = False
        # 보조 프로세스가 앱 종료를 기다리는 중이다. 이번 실행에서는 두 번째 설치를 넘기지 않는다.
        self.handed = False
        self._cancellation = None
        self._reset()
        # 작업자가 늦게 끝나도 지워진 객체로 보내지 않게 신호는 부모 없는 객체가 따로 쥔다.
        self._signals = _Signals()
        self._signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self._signals.downloaded.connect(self._downloaded, Qt.ConnectionType.QueuedConnection)
        self._signals.handed_off.connect(self._handed_off, Qt.ConnectionType.QueuedConnection)
        self.result = None
        self.result_log = None
        self.load_result()

    def _reset(self):
        self.phase = 'idle'
        self.version = self.kind = self.total = None
        self.received = 0
        self.failure, self.failure_text, self._stage = None, '', None
        self.busy = self.prepared = self._source = None
        self._full = False

    @property
    def can_retry(self):
        return self.phase == 'failed' and self.failure not in NO_RETRY

    @property
    def result_retry(self):
        """지난 설치 결과의 다시 시도: 패치가 실제로 실패했으면 'full', 아니면 같은 종류로 'same'.

        성공했거나, 설치 프로그램이 아직 돌고 있을 수 있는 시간 초과면 None.
        """
        outcome = self.result
        if outcome is None or outcome.status == 'installed' or outcome.failure_reason == 'installer_timeout':
            return None
        return 'full' if outcome.retry_full else 'same'

    def hides(self, version):
        """진행하는 동안에는(한 번에 하나) 새 버전 알림을 띄우지 않는다. 지난 설치 결과를 안내하는 동안에는
        그 버전의 알림 대신 결과 안내의 다시 시도를 쓴다."""
        return self.phase != 'idle' or (self.result is not None and self.result.version == version)

    def load_result(self):
        try:
            outcome = self.core.last_update_install()
            failed = outcome is not None and outcome.status != 'installed'
            log_path = self.core.update_installer_log()
            # 기록이 없을 때도 지난 실행이 남긴 받다 만 파일을 지운다. 실패 진단용 로그는 다음 성공 때까지 둔다.
            self.core.clear_update_install(keep_log=outcome is None or failed)
        except Exception as error:
            log.warning("업데이트 설치 결과를 읽지 못했습니다: %s", error)
            return
        self.result = outcome
        self.result_log = log_path if failed and log_path.is_file() else None

    def start(self, result, *, full=False):
        """내려받기를 시작했으면 True. 이미 진행 중이면 그 진행을 그대로 둔다."""
        if self.closed or self.handed or self.phase in ACTIVE:
            return False
        self._reset()
        # 새 시도가 시작되면 지난 실행의 결과 안내는 내린다.
        self.result = self.result_log = None
        self.phase, self.version = 'downloading', result.latest_version
        self.kind = 'full' if full else result.kind
        self._source, self._full = result, full
        self._cancellation = cancellation = threading.Event()
        signals, core, http = self._signals, self.core, self._http
        last, last_percent = 0.0, -1

        def progress(received, total):
            nonlocal last, last_percent
            # 화면에는 약 100ms마다, 또는 정수 퍼센트가 바뀔 때만 보낸다. 받기가 멈춰도 보이는 값이 1% 넘게 뒤지지 않는다.
            # 예외를 내면 내려받기가 실패로 끝나므로 여기서는 아무것도 던지지 않는다.
            try:
                now, percent = monotonic(), received * 100 // total if total else 100
                if received < total and percent == last_percent and now - last < PROGRESS_INTERVAL:
                    return
                last, last_percent = now, percent
                signals.progress.emit(received, total)
            except Exception:
                pass

        def run():
            try:
                outcome = core.download_update(result, full=full, progress=progress, cancellation=cancellation,
                                               http=http)
            except Exception:
                log.exception('업데이트 내려받기 작업 실패')
                outcome = None
            try:
                signals.downloaded.emit(outcome)
            except RuntimeError:
                pass  # 종료 중 Qt 객체가 먼저 지워졌다.

        threading.Thread(target=run, name='update-download', daemon=True).start()
        self.changed.emit()
        return True

    def _progress(self, received, total):
        if self.closed or self.phase not in ('downloading', 'cancelling'):
            return
        self.received, self.total = received, total
        self.progressed.emit()

    def _downloaded(self, outcome):
        if self.closed or self.phase not in ('downloading', 'cancelling'):
            return
        self._cancellation = None
        if self.phase == 'cancelling' or (outcome is not None and outcome.status == 'cancelled'):
            # 취소를 누른 뒤 마침 끝난 내려받기도 취소로 보고 받은 파일을 지운다.
            if outcome is not None and outcome.update is not None:
                try:
                    outcome.update.path.unlink(missing_ok=True)
                except OSError:
                    log.warning('취소한 업데이트 파일을 지우지 못했습니다: %s', outcome.update.path)
            self._reset()
            self.changed.emit()
            self.window.statusBar().showMessage(CANCELLED, 5000)
        elif outcome is None or outcome.status != 'ready':
            self._fail('download', outcome.failure_reason if outcome is not None else 'download_failed')
        else:
            update = outcome.update
            self.prepared = update
            self.kind, self.received, self.total = update.kind, update.size, update.size
            self._confirm_or_install()

    def _fail(self, stage, reason, text=''):
        self.phase, self._stage, self.failure, self.failure_text = 'failed', stage, reason, text
        self.changed.emit()

    def _busy_state(self):
        busy = self.core.busy_reasons_for_update()
        # 자막 기능 준비(CUDA·Whisper 내려받기)는 코어 밖 작업자라 화면 상태에서 더한다.
        if self.window.subtitles.preparation_worker is not None:
            busy = replace(busy, blocking=(*busy.blocking, 'preparation'))
        return busy

    def _confirm_or_install(self):
        try:
            busy = self._busy_state()
        except Exception:
            log.exception('업데이트 전 진행 중인 작업을 확인하지 못했습니다')
            self._fail('confirm', 'busy_check_failed')
            return
        if busy.blocking:
            self.phase, self.busy = 'confirm', busy
            self.changed.emit()
        else:
            self._handoff()

    def _handoff(self):
        # 앱을 닫을 수 없는 작업(백업·검사)이 있으면 보조 프로세스를 띄우기 전에 멈춘다.
        blocker = self.window.tray.quit_blocker()
        if blocker:
            self._fail('install', 'quit_blocked', blocker)
            return
        self.phase, self.busy = 'preparing', None
        self.changed.emit()
        signals, core, update, options = self._signals, self.core, self.prepared, self._prepare

        def run():
            error = ''
            try:
                core.prepare_update_install(update, **options)  # 보조 프로세스가 준비될 때까지 최대 20초
            except UpdateInstallError as exc:
                error = exc.kind
            except Exception:
                log.exception('업데이트 설치를 넘기지 못했습니다')
                error = 'handoff_failed'
            try:
                signals.handed_off.emit(error)
            except RuntimeError:
                pass

        threading.Thread(target=run, name='update-handoff', daemon=True).start()

    def _handed_off(self, error):
        if self.phase != 'preparing':
            return
        if error:
            self._fail('install', error)
            return
        # 보조 프로세스는 이 프로세스가 끝나기를 기다린다. 트레이로 숨기지 않고 완전 종료한다.
        self.handed = True
        if not self._quit_app():
            self._fail('install', 'quit_failed')

    def _quit_for_install(self):
        tray = self.window.tray
        tray.quit(confirmed=True)
        return tray.quitting

    def act(self, name):
        """알림·설정의 진행 버튼. 화면이 보던 단계와 지금 단계가 다르면 바꾸지 않고 거절한다."""
        if name == 'cancel' and self.phase == 'downloading':
            self._cancellation.set()
            self.phase = 'cancelling'
        elif name == 'install' and self.phase == 'confirm':
            self._handoff()
            return
        elif name == 'install' and self.phase == 'ready':
            self._confirm_or_install()
            return
        elif name == 'later' and self.phase == 'confirm':
            # 받은 설치 파일은 이번 실행 동안 두고 "설치"로 다시 고를 수 있다.
            self.phase, self.busy = 'ready', None
        elif name == 'retry' and self.can_retry:
            self._retry()
            return
        elif name == 'retry' and self.phase == 'idle' and self.result_retry is not None:
            self._retry_result()
            return
        elif name == 'dismiss' and self.phase == 'failed':
            self._reset()
        elif name == 'dismiss' and self.phase == 'idle' and self.result is not None:
            self.result = self.result_log = None
        else:
            raise ValueError(STATE_CHANGED)
        self.changed.emit()

    def _retry(self):
        if self._stage == 'download' or self.failure == 'installer_missing':
            self.start(self._source, full=self._full)
        elif self._stage == 'confirm':
            self._confirm_or_install()
        else:
            self._handoff()

    def _retry_result(self):
        """지난 실행의 설치 실패를 다시 시도한다. 받기는 그 버전의 서명된 매니페스트부터 다시 확인한다."""
        outcome = self.result
        try:
            installed = self.core.installed_update_info().version
        except Exception:
            installed = None
        source = UpdateCheckResult(datetime.now(timezone.utc), outcome.kind, installed, outcome.version, None)
        self.start(source, full=self.result_retry == 'full' or outcome.kind == 'full')

    def shutdown(self):
        self.closed = True
        if self._cancellation is not None:
            self._cancellation.set()
