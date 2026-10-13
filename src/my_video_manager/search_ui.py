"""검색 입력과 결과 선택. 조회와 재생 규칙은 AppCore가 담당한다."""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .highlight_ui import timestamp


class SearchDialog(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.selected_result = None
        self.video_ids = ()
        self.setWindowTitle("검색")
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("제목 · 파일 이름 · 태그 · 메모 · 자막 내용")
        self.query.setAccessibleName("검색어")
        layout.addWidget(self.query)
        hint = QLabel("띄어쓰기와 대소문자를 구분하지 않습니다. ↓ 결과 선택 · Enter 또는 클릭으로 재생")
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
            results = self.core.search(self.query.text())
        except Exception as error:
            self.status.setText(f"검색 실패: {error}")
            return
        self.video_ids = tuple(dict.fromkeys(result.video_id for result in results))
        for result in results:
            time = f" · {timestamp(result.start)}" if result.start is not None else ""
            item = QListWidgetItem(f"{result.title} · {labels[result.source]}{time}\n{result.text}")
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.results.addItem(item)
        if results:
            self.results.setCurrentRow(0)
        self.status.setText(f"검색 결과 {len(results)}개" if self.query.text().strip() else "검색어를 입력하세요.")

    def focus_results(self):
        self.refresh()
        if self.results.count():
            self.results.setFocus()

    def choose(self, item):
        self.selected_result = item.data(Qt.ItemDataRole.UserRole)
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
