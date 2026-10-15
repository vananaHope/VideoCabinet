"""Qt 조건 대기."""
from time import monotonic
from PySide6.QtTest import QTest


def wait_for(predicate, timeout=30):
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, 'Qt 조건 대기 시간 초과'
        QTest.qWait(10)
