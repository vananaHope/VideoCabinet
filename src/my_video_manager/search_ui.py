"""검색 입력과 결과 선택. 조회와 재생 규칙은 AppCore가 담당한다."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .highlight_ui import timestamp
from .key_display import display_key


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


class SearchDialog(QDialog):
    def __init__(self, core, parent=None, *, preparation=None):
        super().__init__(parent)
        self.core = core
        self.preparation = preparation or SearchPreparation(core, self)
        self.selected_result = None
        self.video_ids = ()
        self.setWindowTitle("검색")
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("제목 · 파일 이름 · 태그 · 메모 · 자막 내용")
        self.query.setAccessibleName("검색어")
        layout.addWidget(self.query)
        # 모달 입력·목록 탐색은 재생 명령의 키 배치와 독립된 Qt 기본 조작이다.
        hint = QLabel("띄어쓰기와 대소문자를 구분하지 않습니다. "
                      f"{display_key('Down')} 결과 선택 · {display_key('Enter')} 또는 클릭으로 재생")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.results = QListWidget()
        self.results.setAccessibleName("검색 결과")
        self.results.setWordWrap(True)
        layout.addWidget(self.results)
        self.status = QLabel("검색어를 입력하세요.")
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.query.textChanged.connect(self.schedule_search)
        self.query.returnPressed.connect(self.focus_results)
        self.query.installEventFilter(self)
        self.results.installEventFilter(self)
        self.results.itemClicked.connect(self.choose)
        self.results.itemActivated.connect(self.choose)
        self.query.setFocus()
        QTimer.singleShot(0, self.refresh)

    def schedule_search(self):
        # 새 입력에 이전 결과가 잠깐 남아 잘못 재생되는 일을 막는다.
        self.results.clear()
        self.status.setText("검색 중…")
        self.timer.start()

    def refresh(self):
        self.timer.stop()
        self.results.clear()
        labels = {"title": "제목", "filename": "파일 이름", "tag": "태그", "note": "메모",
                  "transcript": "원어 자막", "translation": "번역 자막"}
        try:
            if not self.preparation.ready():
                self.status.setText("검색 색인 준비 중…")
                self.timer.start()
                return
            response = self.core.search(self.query.text())
            results = response.results
        except Exception as error:
            self.status.setText(f"검색 실패: {error}")
            return
        self.video_ids = tuple(dict.fromkeys(result.video_id for result in results))
        for result in results:
            time = f" · {timestamp(result.start)}" if result.start is not None else ""
            missing = " · 파일 없음" if result.missing else ""
            item = QListWidgetItem(f"{result.title}{missing} · {labels[result.source]}{time}\n{result.text}")
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.results.addItem(item)
        if results:
            self.results.setCurrentRow(0)
        self.status.setText(f"검색 결과 {len(results)}개" if self.query.text().strip() else "검색어를 입력하세요.")
        if response.truncated:
            self.status.setText(f"검색 결과 {len(results)}개 · 결과가 많습니다. 더 길게 입력하세요.")

    def focus_results(self):
        self.refresh()
        if self.results.count():
            self.results.setFocus()

    def choose(self, item):
        result = item.data(Qt.ItemDataRole.UserRole)
        if result.missing:
            self.status.setText("파일 없음: 영상의 위치를 다시 연결한 뒤 재생하세요.")
            return
        self.selected_result = result
        self.accept()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if watched is self.query and event.key() == Qt.Key.Key_Down:
                self.focus_results()
                return True
            if watched is self.results and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if item := self.results.currentItem():
                    self.choose(item)
                return True
        return super().eventFilter(watched, event)
