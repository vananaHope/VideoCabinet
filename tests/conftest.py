"""각 pytest 프로세스에서 Qt를 불러오기 전에 테스트 환경을 준비한다."""
import os
import logging
import sqlite3
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


class _ReversibleDPAPI:
    """Windows 밖에서 쓰는 가역 가짜 DPAPI. 암호문에 평문이 그대로 남지 않게 바이트를 뒤섞는다."""

    _PREFIX = b'fake-dpapi:'

    def protect(self, data: bytes) -> bytes:
        return self._PREFIX + bytes(byte ^ 0x5A for byte in reversed(data))

    def unprotect(self, data: bytes) -> bytes:
        if not data.startswith(self._PREFIX):
            raise ValueError('fake DPAPI 암호문이 아니다')
        return bytes(byte ^ 0x5A for byte in reversed(data[len(self._PREFIX):]))


@pytest.fixture
def portable_dpapi(monkeypatch):
    """키 저장소를 거치는 로직 테스트를 Linux에서도 돌린다.

    Windows에서는 실제 사용자 DPAPI를 그대로 쓴다. 실제 DPAPI 동작은 test_secret_store가 Windows에서 검사한다.
    """
    if sys.platform == 'win32':
        return
    from my_video_manager import secret_store
    monkeypatch.setattr(secret_store, 'WindowsDPAPI', _ReversibleDPAPI)


@pytest.fixture
def name_ordered_scandir(monkeypatch):
    """NTFS처럼 폴더 항목을 이름순으로 돌려준다. ext4 등은 순회 순서가 정해져 있지 않다.

    Windows에서는 실제 NTFS 순서를 그대로 쓴다.
    """
    if sys.platform == 'win32':
        return
    original = os.scandir

    class Entries:
        def __init__(self, entries):
            self._entries = entries

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return iter(self._entries)

        def close(self):
            pass

    def scandir(path='.'):
        with original(path) as entries:
            return Entries(sorted(entries, key=lambda entry: entry.name.upper()))

    monkeypatch.setattr(os, 'scandir', scandir)


_sqlite_connect = sqlite3.connect


def _connect_without_sync(*args, **kwargs):
    connection = _sqlite_connect(*args, **kwargs)
    # synchronous는 스키마를 읽어 다른 연결의 쓰기 잠금을 기다릴 수 있다. 잠금 테스트의 대기 시간을 바꾸지 않게
    # 기다리지 않고 시도하고, 잠겨 있으면 이 연결만 기본 동기화로 둔다. busy_timeout 자체는 DB를 읽지 않는다.
    timeout = kwargs.get('timeout', args[1] if len(args) > 1 else 5.0)
    connection.execute('PRAGMA busy_timeout = 0')
    try:
        connection.execute('PRAGMA synchronous = OFF')
    except sqlite3.OperationalError:
        pass
    connection.execute(f'PRAGMA busy_timeout = {int(timeout * 1000)}')
    return connection


@pytest.fixture(autouse=True)
def sqlite_without_sync(monkeypatch):
    """테스트 DB는 커밋마다 디스크에 동기화하지 않는다.

    앱 DB를 새로 만들면 스키마 설치만으로 fsync가 약 270번 일어나 Windows 러너에서 준비 단계가 수십 초씩 걸린다.
    전원이 꺼질 때의 내구성만 잃고 트랜잭션·잠금·저널 동작은 그대로다. 하위 프로세스에는 적용되지 않는다.
    """
    monkeypatch.setattr(sqlite3, 'connect', _connect_without_sync)


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
    # 테스트가 띄우는 하위 pytest(단일 nodeid 실행)가 조각 설정을 물려받아 모두 제외되지 않게 지운다.
    shard = os.environ.pop('MVM_TEST_SHARD', None)
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
