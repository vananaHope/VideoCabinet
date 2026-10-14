"""검색 입력과 결과 선택. 조회와 재생 규칙은 AppCore가 담당한다."""

from concurrent.futures import ThreadPoolExecutor
from html import escape

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal, QTextBoundaryFinder
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from .highlight_ui import timestamp
from .key_display import display_key
from .search import search_key
from .dialog_ui import space_layout
from .theme import ACCENT, BORDER, MUTED_TEXT, TEXT


SOURCE_LABELS = {"title": "제목", "filename": "파일 이름", "tag": "태그", "note": "메모",
                 "transcript": "원어 자막", "translation": "번역 자막"}


def highlighted_text(text, query):
    """검색과 같은 정규화로 찾되 원문 표기·공백을 보존해 그린다."""
    needle = search_key(query)
    if not needle:
        return escape(text)
    # Qt 경계는 UTF-16 단위다. 결합 문자·한글 자모를 한 묶음으로 정규화한다.
    encoded = text.encode("utf-16-le")
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    normalized, positions = "", []
    start = 0
    while (end := finder.toNextBoundary()) != -1:
        cluster = encoded[start * 2:end * 2].decode("utf-16-le")
        key = search_key(cluster)
        normalized += key
        positions.extend([(start, end)] * len(key))
        start = end
    spans, offset = [], 0
    while (index := normalized.find(needle, offset)) >= 0:
        spans.append((positions[index][0], positions[index + len(needle) - 1][1]))
        offset = index + len(needle)
    parts, previous = [], 0
    for start, end in spans:
        if start < previous:  # ß → ss처럼 같은 원문 문자가 여러 번 대응할 수 있다.
            continue
        parts.append(escape(encoded[previous * 2:start * 2].decode("utf-16-le")))
        parts.append(f'<span style="color:{ACCENT}; font-weight:600">'
                     + escape(encoded[start * 2:end * 2].decode("utf-16-le")) + '</span>')
        previous = end
    parts.append(escape(encoded[previous * 2:].decode("utf-16-le")))
    return "".join(parts)


class SearchResultDelegate(QStyledItemDelegate):
    def __init__(self, page):
        super().__init__(page.results)
        self.page = page

    def document(self, index, width):
        result = index.data(Qt.ItemDataRole.UserRole)
        document = QTextDocument()
        document.setDefaultFont(self.page.font())
        document.setDocumentMargin(0)
        time = f" · {timestamp(result.start)}" if result.start is not None else ""
        missing = " · 파일 없음" if result.missing else ""
        document.setHtml(
            f'<div style="color:{TEXT}; font-size:11pt; font-weight:600">'
            f'{highlighted_text(result.title, self.page.query.text())}</div>'
            f'<div style="color:{MUTED_TEXT}; margin-top:5px">'
            f'<span style="background-color:{BORDER}; color:{TEXT}">'
            f'&nbsp;{SOURCE_LABELS[result.source]}&nbsp;</span>{time}{missing}</div>'
            f'<div style="color:{TEXT}; margin-top:7px">'
            f'{highlighted_text(result.text, self.page.query.text())}</div>')
        document.setTextWidth(max(1, width - 28))
        return document

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.save()
        painter.setClipRect(option.rect)
        painter.translate(option.rect.left() + 14, option.rect.top() + 12)
        self.document(index, option.rect.width()).drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):
        width = self.page.results.viewport().width()
        return QSize(max(1, width - 12), int(self.document(index, width - 12).size().height()) + 24)


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


class SearchPage(QWidget):
    result_chosen = Signal(object)

    def __init__(self, core, parent=None, *, preparation=None):
        super().__init__(parent)
        self.core = core
        self.preparation = preparation or SearchPreparation(core, self)
        self.video_ids = ()
        layout = space_layout(QVBoxLayout(self))
        title = QLabel("검색")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        layout.addWidget(title)
        self.query = QLineEdit()
        self.query.setPlaceholderText("제목 · 파일 이름 · 태그 · 메모 · 자막 내용")
        self.query.setAccessibleName("검색어")
        self.query.setMinimumHeight(48)
        self.query.setStyleSheet("font-size: 16px; padding: 8px")
        layout.addWidget(self.query)
        # 입력·목록 탐색은 재생 명령의 키 배치와 독립된 Qt 기본 조작이다.
        hint = QLabel("띄어쓰기와 대소문자를 구분하지 않습니다. "
                      f"{display_key('Down')} 결과 선택 · {display_key('Enter')} 또는 클릭으로 재생")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.results = QListWidget()
        self.results.setAccessibleName("검색 결과")
        self.results.setWordWrap(True)
        self.results.setSpacing(4)
        self.results.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setStyleSheet(f"QListWidget::item {{ border-bottom: 1px solid {BORDER}; }}")
        self.results.setItemDelegate(SearchResultDelegate(self))
        layout.addWidget(self.results)
        self.status = QLabel("검색어를 입력하세요.")
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.query.textChanged.connect(self.schedule_search)
        # 같은 Enter가 부모로 전파되며 결과 재생까지 실행되지 않도록 포커스 이동을 미룬다.
        self.query.returnPressed.connect(lambda: QTimer.singleShot(0, self.focus_results))
        self.query.installEventFilter(self)
        self.results.installEventFilter(self)
        self.results.itemClicked.connect(self.choose)
        self.results.itemActivated.connect(self.choose)
        self.query.setFocus()
        self.dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if self.dirty:
            self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def focus_content(self):
        (self.results if self.results.count() else self.query).setFocus()

    def handle_key(self, event) -> bool:
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            # Enter는 QLineEdit의 returnPressed에 맡겨 IME 입력 확정을 보존한다.
            if self.query.hasFocus() and event.key() == Qt.Key.Key_Down:
                self.focus_results()
                return True
            if self.results.hasFocus() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if item := self.results.currentItem():
                    self.choose(item)
                return True
        return False

    def schedule_search(self):
        # 새 입력에 이전 결과가 잠깐 남아 잘못 재생되는 일을 막는다.
        self.results.clear()
        self.video_ids = ()
        self.dirty = True
        self.status.setText("검색 중…")
        if self.isVisible():
            self.timer.start()

    def refresh(self):
        self.timer.stop()
        self.results.clear()
        try:
            if not self.preparation.ready():
                self.status.setText("검색 색인 준비 중…")
                if self.isVisible():
                    self.timer.start()
                return
            response = self.core.search(self.query.text())
            results = response.results
        except Exception as error:
            self.status.setText(f"검색 실패: {error}")
            return
        self.video_ids = tuple(dict.fromkeys(result.video_id for result in results))
        self.dirty = False
        for result in results:
            time = f" · {timestamp(result.start)}" if result.start is not None else ""
            missing = " · 파일 없음" if result.missing else ""
            item = QListWidgetItem(f"{result.title}{missing} · {SOURCE_LABELS[result.source]}{time}\n{result.text}")
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.results.addItem(item)
        if results:
            self.results.setCurrentRow(0)
        self.status.setText(f"검색 결과 {len(results)}개" if self.query.text().strip() else "검색어를 입력하세요.")
        if response.truncated:
            self.status.setText(f"검색 결과 {len(results)}개 · 결과가 많습니다. 더 길게 입력하세요.")

    def focus_results(self):
        if self.dirty:
            self.refresh()
        if self.results.count():
            self.results.setFocus()

    def choose(self, item):
        result = item.data(Qt.ItemDataRole.UserRole)
        if result.missing:
            self.status.setText("파일 없음: 영상의 위치를 다시 연결한 뒤 재생하세요.")
            return
        self.result_chosen.emit(result)

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
