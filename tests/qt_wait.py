"""Qt 조건 대기."""
from time import monotonic
from PySide6.QtTest import QTest
from wait_helpers import UI_READY_TIMEOUT


def wait_for(predicate, timeout=UI_READY_TIMEOUT):
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, 'Qt 조건 대기 시간 초과'
        QTest.qWait(10)
