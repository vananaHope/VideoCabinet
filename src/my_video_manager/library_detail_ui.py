"""선택 영상 상세. 데이터는 LibraryPage의 일괄 스냅숏으로 받는다."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .dialog_ui import primary_button
from .library_grid import duration_text, viewing_text
from .theme import with_role

# 두 칸을 차지하는 작업. 나머지 짧은 작업은 두 개씩 한 줄에 놓는다.
WIDE_ACTIONS = {"재생", "자막 만들기 / 원어 지정", "자막 검수 / SRT 내보내기"}

QUEUE_LABELS = {"queued": "대기", "transcribing": "받아쓰는 중", "translating": "번역 중",
                "completed": "완료", "failed": "실패", "held": "보류"}


class LibraryDetailPanel(QScrollArea):
    def __init__(self, icons, actions, parent=None):
        super().__init__(parent)
        self.icons = icons
        self.setAccessibleName("선택 영상 상세")
        self.setWidgetResizable(True)
        self.setMinimumWidth(288)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        self.empty = with_role(QLabel("영상을 선택하면\n상세 정보와 작업이 여기에 표시됩니다."), "emptyBody")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.info = QWidget()
        info_layout = QVBoxLayout(self.info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)
        self.thumbnail = QLabel()
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.thumbnail)
        self.title = with_role(QLabel(), "sectionTitle")
        self.metadata = QLabel()
        for label in (self.title, self.metadata):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.title)
        # 작업 버튼을 정보보다 먼저 두어 기본 창 크기에서도 스크롤 없이 닿게 한다.
        grid = QGridLayout()
        grid.setSpacing(6)
        self.buttons = []  # 우클릭 메뉴와 같은 순서
        for action in actions:
            button = QPushButton(action.text())
            button.setToolTip(action.text())
            button.clicked.connect(action.trigger)
            action.changed.connect(lambda a=action, b=button: b.setEnabled(a.isEnabled()))
            button.setEnabled(action.isEnabled())
            self.buttons.append(button)
        wide = [b for b in self.buttons if b.text() in WIDE_ACTIONS]
        short = [b for b in self.buttons if b.text() not in WIDE_ACTIONS]
        for row, button in enumerate(wide):
            grid.addWidget(button, row, 0, 1, 2)
        for index, button in enumerate(short):
            grid.addWidget(button, len(wide) + index // 2, index % 2)
        visual = wide + short
        for first, second in zip(visual, visual[1:]):
            QWidget.setTabOrder(first, second)
        if wide:
            primary_button(wide[0])
        info_layout.addLayout(grid)
        info_layout.addWidget(self.metadata)
        layout.addWidget(self.info)
        layout.addStretch()
        self.show_card(None, None)

    def show_card(self, card, details):
        self.empty.setVisible(card is None)
        self.info.setVisible(card is not None)
        if card is None:
            return
        video, status = card.video, card.status
        self.thumbnail.setPixmap(self.icons.get(video.thumbnail).pixmap(QSize(224, 126)))
        self.title.setText(video.title)
        lines = [f"길이 {duration_text(video.duration)} · {viewing_text(status)}"]
        if video.missing:
            lines.append("파일 없음 · 다시 검사하거나 파일을 연결하세요.")
        elif len(video.locations) > 1:
            lines.append(f"위치 {len(video.locations)}개")
        if status.resume_point is not None:
            lines.append(f"이어볼 위치 {duration_text(status.resume_point)} ({status.stopped_percent:.0f}%)")
        lines.append("태그: " + (", ".join(t.name for t in card.tags) or "없음"))
        lines.append("시리즈: " + (card.series or "없음"))
        if details:
            lines.append(f"원어: {details.spoken_language or '알 수 없음'} · {details.original_lines}줄"
                         if details.has_transcript else "원어 자막 없음")
            lines.append(f"번역: {details.translated_lines}/{details.original_lines}줄"
                         if details.translated_lines else "번역 자막 없음")
            states = [f"{label} {QUEUE_LABELS.get(state, state)}" for label, state in
                      (("원어", details.subtitle_state), ("번역", details.translation_state)) if state]
            lines.append("대기열: " + (" · ".join(states) or "없음"))
            lines.append(f"하이라이트 {details.highlight_count}개")
        self.metadata.setText("\n".join(lines))
