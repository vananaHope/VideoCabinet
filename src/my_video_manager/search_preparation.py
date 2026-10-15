"""Qt 화면과 웹 컨트롤러가 공유하는 비동기 검색 색인 준비."""
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer


class SearchPreparation(QObject):
    """화면이 먼저 표시된 뒤 코어의 색인 준비를 작업자에서 실행한다."""
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.future = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search-index")
        executor = self.executor
        # 창이 닫혀도 진행 중인 트랜잭션은 마친다. 작업자는 Qt 객체에 접근하지 않는다.
        self.destroyed.connect(lambda: executor.shutdown(wait=False))
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.start)
        self.start_timer.start(0)

    def start(self):
        if self.future is None and not self.core.search_index_ready:
            self.future = self.executor.submit(self.core.prepare_search)

    def ready(self):
        self.start()
        if self.future is not None and self.future.done():
            self.future.result()  # 준비 오류는 검색 창에서 표시한다.
        return self.core.search_index_ready
