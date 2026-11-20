"""각 pytest 프로세스에서 Qt를 불러오기 전에 테스트 환경을 준비한다."""
import os
import logging
import sys

import pytest

# xdist 작업자도 테스트 수집 전에 이 모듈을 읽는다. 일부 UI 모듈의
# import 순서에 기대지 않고 offscreen과 GPU 비활성 기본값을 적용한다.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# 컨테이너처럼 root로 실행하면 Chromium은 sandbox를 끄지 않으면 시작하지 않는다.
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS',
                      '--disable-gpu --no-sandbox' if getattr(os, 'geteuid', lambda: -1)() == 0 else '--disable-gpu')


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
def skip_web_shell_off_windows(monkeypatch):
    """Windows가 아닌 offscreen 환경에서는 웹 셸을 만드는 테스트를 건너뛴다.

    Linux 컨테이너에서는 QWebEngineView 내부 QQuick 객체의 hover 이벤트가 앱 전역
    이벤트 필터로 들어오면서 PySide6가 세그폴트한다. 실제 확인은 Windows에서 한다.
    """
    if sys.platform == 'win32':
        return
    from my_video_manager import web_shell

    def skip(*args, **kwargs):
        pytest.skip('Windows가 아닌 offscreen 환경에서는 웹 셸이 PySide6 세그폴트를 일으킨다')

    monkeypatch.setattr(web_shell.WebShellHost, '__init__', skip)


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


def pytest_collection_modifyitems(config, items):
    """CI 조각 실행: MVM_TEST_SHARD=i/n이면 수집한 테스트 중 i번째 조각(1부터)만 남긴다.

    nodeid 순서대로 번갈아 나눠 느린 파일이 한 조각에 몰리지 않게 한다.
    """
    shard = os.environ.get('MVM_TEST_SHARD')
    if not shard:
        return
    index, count = (int(part) for part in shard.split('/'))
    if not 1 <= index <= count:
        raise pytest.UsageError(f'MVM_TEST_SHARD는 1/n~n/n 이어야 합니다: {shard}')
    ordered = sorted(items, key=lambda item: item.nodeid)
    keep = {id(item) for position, item in enumerate(ordered) if position % count == index - 1}
    deselected = [item for item in items if id(item) not in keep]
    items[:] = [item for item in items if id(item) in keep]
    config.hook.pytest_deselected(items=deselected)
