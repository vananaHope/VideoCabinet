"""업데이트 확인을 앱 수명에 연결한다. 확인과 결과 저장은 코어가, 작업자와 중복 방지·새 버전 알림의 선택은 여기서 맡는다."""
import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

log = logging.getLogger(__name__)
NOTICE_CHANGED = '업데이트 안내가 바뀌었습니다. 다시 확인해 주세요.'


class _Signals(QObject):
    finished = Signal(str)


class UpdateControls(QObject):
    """시작 확인과 "지금 확인"을 작업자 하나로 직렬화한다.

    check_for_update는 최악 약 2분 걸리는 동기 호출이라 데몬 스레드에서 돌리고 결과는 queued signal로 받는다.
    완전 종료는 진행 중인 확인을 기다리지 않는다. 프로세스와 함께 끝나며 저장 전이었다면 이전 기록이 남는다.

    새 버전 알림의 선택(업데이트·나중에·건너뛰기)도 받는다. "나중에"는 이번 실행에서 그 확인 결과만 숨기므로
    다음 확인(지금 확인·다음 시작)에서 같은 버전이 나오면 다시 알린다.
    """
    changed = Signal()
    # "업데이트"를 고른 확인 결과. 내려받기·설치(#142)가 여기에 연결한다.
    update_requested = Signal(object)

    def __init__(self, window, *, startup_delay_ms=5000, check=None, open_url=None):
        super().__init__(window)
        self.core = window.core
        self.checking = False
        self.error = ''
        self.closed = False
        self._check = check or self.core.check_for_update
        self._open_url = open_url or QDesktopServices.openUrl
        # "나중에"(또는 업데이트 선택)로 숨긴 확인 결과의 시각. 새 확인 결과는 시각이 달라 다시 알린다.
        self._postponed = None
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

    def notice(self):
        """셸에 알릴 확인 결과. 알릴 것이 없거나 이번 실행에서 숨겼으면 None."""
        result = self.core.update_to_announce()
        return None if result is None or self.hidden(result) else result

    def hidden(self, result):
        """이번 실행에서 "나중에"(또는 업데이트 선택)로 숨긴 확인 결과인가."""
        return result.checked_at == self._postponed

    def choose(self, name, version):
        """알림·설정에서 고른 선택. 화면이 보던 버전이 지금 알릴 버전과 다르면 바꾸지 않고 거절한다."""
        if name == 'unskip':
            if version != self.core.skipped_update_version():
                raise ValueError(NOTICE_CHANGED)
            self.core.clear_skipped_update_version()
        elif name in ('update', 'later', 'skip'):
            result = self.core.update_to_announce()
            if result is None or result.latest_version != version:
                raise ValueError(NOTICE_CHANGED)
            if name == 'update':
                self.request_update(result)
            elif name == 'later':
                self._postponed = result.checked_at
            else:
                self.core.skip_update_version(version)
        else:
            raise ValueError('알 수 없는 업데이트 선택입니다.')
        self.changed.emit()

    def request_update(self, result):
        """"업데이트" 선택을 다음 단계로 넘기는 자리. #142가 update_requested에 내려받기·설치를 연결한다."""
        self.update_requested.emit(result)
        # 임시 동작: #142 전까지는 사용자가 직접 받을 수 있게 그 버전의 GitHub Release 페이지를 연다.
        # #142에서 내려받기·설치로 바뀌면 이 브라우저 열기는 없앤다.
        if not self._open_url(QUrl(result.release_url)):
            raise RuntimeError('브라우저에서 GitHub Release 페이지를 열지 못했습니다.')
        # 고른 알림은 이번 실행에서 다시 띄우지 않는다. 설정의 업데이트 구역에는 남는다.
        self._postponed = result.checked_at

    def shutdown(self):
        self.closed = True
        self._startup.stop()
