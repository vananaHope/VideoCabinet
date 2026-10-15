"""Qt 조건 대기."""
from time import monotonic
from PySide6.QtCore import QEventLoop, QTimer
from wait_helpers import UI_READY_TIMEOUT


def wait_for(predicate, timeout=UI_READY_TIMEOUT):
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, 'Qt 조건 대기 시간 초과'
        # QTest의 중첩 대기 대신 실행 중인 이벤트 루프에서 WebEngine의
        # Python 요청 콜백과 완료 신호에 실행 기회를 준다.
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
