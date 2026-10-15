"""성공 경로 대기 한도. 시간 초과 동작을 검사하는 짧은 한도와 구별한다."""
import os


CHILD_READY_TIMEOUT = float(os.environ.get("MVM_TEST_CHILD_TIMEOUT", "90"))
UI_READY_TIMEOUT = CHILD_READY_TIMEOUT
