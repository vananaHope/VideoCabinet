"""활성 통계 페이지의 지연 갱신과 최신 요청만 반영하는 작업자."""
from dataclasses import asdict
from weakref import ref

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .web_json import encode
from .web_page import WebPageController
from .web_statistics_bridge import StatisticsBridge


class _Result(QObject):
    completed = Signal(int, object, str)
    viewingEnded = Signal()


class _ViewingChanges:
    def __init__(self, signals):
        self.signals = ref(signals)

    def playback_started(self, session, position):
        pass

    def playback_position(self, session, position, seeked):
        pass

    def playback_ended(self, session, position):
        signals = self.signals()
        if signals is not None and session.record_viewing:
            signals.viewingEnded.emit()


class _Calculation(QRunnable):
    def __init__(self, core, days, generation, result):
        super().__init__()
        self.core, self.days, self.generation, self.result = core, days, generation, result

    def run(self):
        try:
            data = asdict(self.core.statistics_dashboard(self.days))
        except Exception as error:
            data, message = None, str(error)
        else:
            message = ''
        try:
            self.result.completed.emit(self.generation, data, message)
        except RuntimeError:
            # QApplication 종료는 실행 중인 작업자의 신호 객체를 먼저 지울 수 있다.
            # 계산 결과를 기다리며 UI 종료를 막지 않고 더 이상 받을 수 없는 결과를 버린다.
            pass


class WebStatisticsPage(WebPageController):
    tab = 'statistics'
    default_focus = 'statistics-period'

    def __init__(self, host):
        super().__init__(host)
        self.days, self.result, self.message = 30, None, ''
        self.loading, self._running, self._generation = False, False, 0
        self._pending = False
        self._signals = _Result()
        self._signals.completed.connect(self._completed)
        self._signals.viewingEnded.connect(self.refresh)
        self.core.playback.subscribe(_ViewingChanges(self._signals))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._start)
        self.bridge = StatisticsBridge(self)
        self.focus_requested = self.bridge.statisticsFocusRequested
        host.register_page(self)

    def payload(self):
        return dict(days=self.days, loading=self.loading, message=self.message, result=self.result)

    def _publish(self):
        self.bridge.statisticsChanged.emit(encode(self.payload()))

    def activated(self):
        self.refresh()

    def deactivated(self):
        self._generation += 1
        self._pending = False
        self._timer.stop()
        self.loading = False

    def refresh(self):
        self._generation += 1
        self._pending = self.is_active()
        if not self._pending:
            return
        self.loading, self.message = True, ''
        self._publish()
        self._timer.start()

    def _start(self):
        if self._running or not self._pending or not self.is_active():
            return
        self._pending, self._running = False, True
        QThreadPool.globalInstance().start(_Calculation(self.core, self.days, self._generation, self._signals))

    @Slot(int, object, str)
    def _completed(self, generation, result, message):
        self._running = False
        if generation == self._generation and self.is_active():
            if result is not None:
                self.result = result
            self.message, self.loading = message, False
            self._publish()
        if self._pending and self.is_active():
            self._timer.start()
