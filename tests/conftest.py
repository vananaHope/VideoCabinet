"""각 pytest 프로세스에서 Qt를 불러오기 전에 테스트 환경을 준비한다."""
import os
import logging

import pytest

# xdist 작업자도 테스트 수집 전에 이 모듈을 읽는다. 일부 UI 모듈의
# import 순서에 기대지 않고 offscreen과 GPU 비활성 기본값을 적용한다.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')


@pytest.fixture(autouse=True)
def restore_app_logger():
    logger = logging.getLogger('my_video_manager')
    handlers, level = list(logger.handlers), logger.level
    try:
        yield
    finally:
        for handler in tuple(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.handlers[:] = handlers
        logger.setLevel(level)


@pytest.fixture(scope="session")
def qapp():
    """단독 실행에서도 QWidget보다 먼저 QApplication을 만들고 정리를 마친다."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
