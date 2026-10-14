"""재생 페이지의 영상 영역·진행 표시·키 안내 구성."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
from .core import CommandType
from .highlight_ui import HighlightProgress
from .key_display import display_keys
from .review_ui import review_button


class PlaybackPage(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.core = window.core
        playback_layout = QVBoxLayout(self)
        self.back_button = QPushButton("목록으로 (Esc)")
        self.back_button.clicked.connect(window.back_to_list)
        playback_layout.addWidget(self.back_button)
        self.reel_label = QLabel()
        self.reel_label.setWordWrap(True)
        self.reel_label.hide()
        playback_layout.addWidget(self.reel_label)
        playback_layout.addWidget(window.subtitles.button())
        playback_layout.addWidget(window.translations.button())
        playback_layout.addWidget(review_button(window))
        self.surface = QWidget()
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.surface.setObjectName("videoSurface")
        self.surface.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        playback_layout.addWidget(self.surface, 1)
        self.progress = HighlightProgress()
        playback_layout.addWidget(self.progress)
        self.position_label = QLabel()
        playback_layout.addWidget(self.position_label)
        self.highlights_button = QPushButton("하이라이트 목록 · 시각·메모 편집")
        self.highlights_button.clicked.connect(window.show_highlights)
        playback_layout.addWidget(self.highlights_button)
        self.video_navigation_label = QLabel()
        self.video_navigation_label.setWordWrap(True)
        playback_layout.addWidget(self.video_navigation_label)
        self.key_help = QLabel()
        self.key_help.setWordWrap(True)
        playback_layout.addWidget(self.key_help)
        playback_layout.addWidget(QLabel("노랑 지점 / 초록 구간 / 주황 열린 구간"))
        self.refresh_key_help()

    def refresh_key_help(self):
        navigation = (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO)
        rows = self.core.key_bindings()
        self.video_navigation_label.setText(" · ".join(f"{display_keys(row.keys)} {row.label}"
                                                      for row in rows if row.command.kind in navigation))
        self.key_help.setText(" · ".join(f"{display_keys(row.keys)} {row.label}"
                                        for row in rows if row.keys and row.command.kind not in
                                        (*navigation, CommandType.TOGGLE_REEL_REPEAT)))
