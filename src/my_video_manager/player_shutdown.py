"""보고를 닫은 플레이어의 native 자원을 UI 스레드 밖에서 해제한다."""
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Thread

from PySide6.QtCore import QObject, QEventLoop, QTimer


@dataclass
class ClosingPlayer:
    player: object
    surface: object
    future: Future | None = None


class PlayerShutdown(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = []
        self.failed = []
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.collect)

    def retire(self, player, surface, *, deferred=False):
        self.pending.append(ClosingPlayer(player, surface))
        if not deferred:
            self.release()

    def release(self):
        """이전 영상 표면을 더는 표시하지 않을 때만 종료를 시작한다."""
        for item in self.pending:
            if item.future is not None:
                continue
            item.surface.hide()
            item.future = Future()
            # Qt 객체를 작업 스레드에서 접근하지 않는다. non-daemon이므로
            # 정상 종료 중 native handle 해제를 인터프리터가 중단하지 않는다.
            Thread(target=self._close, args=(item.player, item.future),
                   name='mpv-close', daemon=False).start()
        if self.pending:
            self.timer.start()

    @staticmethod
    def _close(player, future):
        try:
            player.close()
        except Exception as error:
            future.set_exception(error)
        else:
            future.set_result(None)

    def collect(self):
        for item in tuple(self.pending):
            if item.future is None or not item.future.done():
                continue
            self.pending.remove(item)
            error = item.future.exception()
            if error is not None:
                # 종료 실패한 엔진의 HWND를 새 엔진에 재사용하거나 먼저
                # 지우지 않는다. 소유 창과 함께 최종 정리한다.
                self.failed.append(item)
                self.window.statusBar().showMessage(f'플레이어 종료 실패: {error}')
            else:
                item.surface.deleteLater()
        if not self.pending:
            self.timer.stop()

    def finish(self, timeout_ms=5000):
        """앱 종료 시에도 이벤트를 처리하며 해제를 기다린다. 무응답이면 종료를 취소한다."""
        self.release()
        loop = QEventLoop(self)
        deadline = QTimer(self)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        self.timer.timeout.connect(loop.quit)
        deadline.start(timeout_ms)
        enabled = self.window.isEnabled()
        self.window.setEnabled(False)
        try:
            while self.pending and deadline.isActive():
                loop.exec()
                self.collect()
            if self.pending:
                raise RuntimeError('플레이어 종료를 기다리고 있습니다. 잠시 뒤 다시 종료해 주세요.')
        finally:
            self.window.setEnabled(enabled)
            self.timer.timeout.disconnect(loop.quit)
            deadline.stop()
            deadline.deleteLater()
            loop.deleteLater()
