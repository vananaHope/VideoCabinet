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


@pytest.fixture(autouse=True)
def offline_update_check(monkeypatch):
    """앱 창의 시작 업데이트 확인을 포함해 어떤 테스트도 실제 GitHub에 요청하지 않게 기본 전송을 막는다.

    업데이트 테스트는 가짜 http 어댑터를 직접 넘긴다. 전송 자체의 테스트는 update_http를 직접 쓴다.
    """
    from my_video_manager import update_check

    class Offline:
        def get(self, url, *, max_bytes):
            raise OSError('tests must not access the network')

    monkeypatch.setattr(update_check, 'UrllibUpdateHttp', Offline)


@pytest.fixture(scope="session")
def qapp():
    """단독 실행에서도 QWidget보다 먼저 QApplication을 만들고 정리를 마친다."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
