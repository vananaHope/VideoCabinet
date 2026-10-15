"""유휴 시간에 해상도를 채우고 완료 시 활성 통계만 갱신한다."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, QTimer


class _PauseOnPlayback:
    def __init__(self, cancellation):
        self.cancellation = cancellation

    def playback_started(self, session, position):
        self.cancellation.set()

    def playback_position(self, session, position, seeked):
        pass

    def playback_ended(self, session, position):
        pass


class ResolutionControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.future = None
        self.closed = False
        self.changed = False
        self.cancellation = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='resolution')
        cancellation, executor = self.cancellation, self.executor
        self.destroyed.connect(lambda: (cancellation.set(), executor.shutdown(wait=False)))
        self.core.playback.subscribe(_PauseOnPlayback(cancellation))
        window.subtitles.timer.timeout.connect(self.pause_for_foreground)
        window.library_page.scan_state_changed.connect(lambda active: cancellation.set() if active else None)
        self.last_refresh = monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        window.library_page.refreshed.connect(self.start)
        self.start()

    def start(self):
        if not self.closed:
            self.timer.start()

    def pause_for_foreground(self):
        if self.window.subtitles.worker is not None:
            self.cancellation.set()

    def tick(self):
        if self.closed:
            return
        busy = (self.core.playback.session is not None or self.window.subtitles.worker is not None
                or self.window.worker is not None)
        if busy:
            self.cancellation.set()
        if self.future is not None:
            if not self.future.done():
                return
            try:
                result = self.future.result()
            except Exception as error:
                self.window.show_status(f'해상도 채우기 실패: {error} · 다시 검사하면 재시도합니다.')
                self.refresh_statistics()
                self.timer.stop()
                return
            finally:
                self.future = None
            if result.message and result.state == 'unknown':
                self.window.show_status(f'해상도를 읽지 못했습니다: {result.message} · 다시 검사하면 재시도합니다.')
            self.changed = self.changed or result.state == 'completed'
            if result.state == 'exhausted' or monotonic() - self.last_refresh >= 10:
                self.refresh_statistics()
            if result.state == 'exhausted':
                self.timer.stop()
                return
        if not busy:
            self.cancellation.clear()
            self.future = self.executor.submit(self.core.fill_next_resolution, cancellation=self.cancellation)

    def refresh_statistics(self):
        if self.changed:
            self.window.web_host.controllers['statistics'].refresh()
            self.changed = False
            self.last_refresh = monotonic()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self.cancellation.set()
        self.executor.shutdown(wait=True)
