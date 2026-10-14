"""목록이 비었을 때 목록 자리에 겹쳐 보이는 안내. 레이아웃과 포커스 흐름은 바꾸지 않는다."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .theme import with_role


class EmptyState(QWidget):
    def __init__(self, view):
        super().__init__(view.viewport())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.addStretch()
        self.title = with_role(QLabel(), "emptyTitle")
        self.body = with_role(QLabel(), "emptyBody")
        for label in (self.title, self.body):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch()
        view.viewport().installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def show_message(self, title, body=""):
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()

    def clear(self):
        self.hide()

    def text(self):
        return "\n".join(filter(None, (self.title.text(), self.body.text())))
