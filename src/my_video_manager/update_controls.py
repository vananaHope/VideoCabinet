"""업데이트 확인을 앱 수명에 연결한다. 확인과 결과 저장은 코어가, 작업자와 중복 방지는 여기서 맡는다."""
import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    finished = Signal(str)


class UpdateControls(QObject):
    """시작 확인과 "지금 확인"을 작업자 하나로 직렬화한다.

    check_for_update는 최악 약 2분 걸리는 동기 호출이라 데몬 스레드에서 돌리고 결과는 queued signal로 받는다.
    완전 종료는 진행 중인 확인을 기다리지 않는다. 프로세스와 함께 끝나며 저장 전이었다면 이전 기록이 남는다.
    """
    changed = Signal()

    def __init__(self, window, *, startup_delay_ms=5000, check=None):
        super().__init__(window)
        self.core = window.core
        self.checking = False
        self.error = ''
        self.closed = False
        self._check = check or self.core.check_for_update
        # 작업자가 늦게 끝나도 지워진 객체로 보내지 않게 신호는 부모 없는 객체가 따로 쥔다.
        self._signals = _Signals()
        self._signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        self._startup.setInterval(startup_delay_ms)
        self._startup.timeout.connect(self.check_on_startup)

    def schedule_startup(self):
        """시작 검사(#131)를 띄운 뒤 부른다. 첫 화면과 시작 검사가 자리 잡을 때까지 조금 미룬다."""
        if not self.closed:
            self._startup.start()

    def check_on_startup(self):
        if self.closed:
            return
        try:
            due = self.core.should_check_for_update()
        except Exception as error:
            log.warning("업데이트 확인 시기를 읽지 못했습니다: %s", error)
            return
        if due:
            self.start()

    def start(self):
        """확인을 시작했으면 True. 이미 확인 중이면 그 결과를 기다린다."""
        if self.checking or self.closed:
            return False
        signals, check = self._signals, self._check

        def run():
            error = ''
            try:
                check()
            except Exception as exc:
                # 확인 실패는 결과로 저장된다. 여기로 오는 것은 설정 DB 쓰기 같은 저장 실패다.
                log.warning("업데이트 확인 결과를 저장하지 못했습니다: %s", exc)
                error = f'업데이트 확인 결과를 저장하지 못했습니다: {exc}'
            try:
                signals.finished.emit(error)
            except RuntimeError:
                pass  # 종료 중 Qt 객체가 먼저 지워졌다.

        threading.Thread(target=run, name='update-check', daemon=True).start()
        self.checking = True
        self.error = ''
        self.changed.emit()
        return True

    def _finished(self, error):
        if self.closed:
            return
        self.checking = False
        self.error = error
        self.changed.emit()

    def shutdown(self):
        self.closed = True
        self._startup.stop()
