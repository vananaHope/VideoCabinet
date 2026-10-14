"""재생 페이지의 영상 영역·진행 표시·키 안내 구성."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget
from .core import CommandType
from .highlight_ui import HighlightProgress, timestamp
from .key_settings_ui import key_name
from .key_display import display_keys
from .review_ui import review_button


class PlaybackPage(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.core = window.core
        self.shell = window
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

    def show_position(self, position, duration, open_start, range_keys):
        self.progress.duration = duration
        self.progress.position = position
        self.progress.open_start = open_start
        self.progress.update()
        suffix = f" · 구간 시작 {timestamp(open_start)} — {range_keys}: 끝내기" if open_start is not None else ""
        self.position_label.setText(f"{timestamp(position)} / {timestamp(duration)}{suffix}")

    def show_reel(self, current, repeat, keys):
        self.reel_label.setVisible(current is not None)
        self.video_navigation_label.setVisible(current is None)
        self.back_button.setText("모아보기 목록으로 (Esc)" if current else "목록으로 (Esc)")
        if current:
            repeat_label = "켜짐" if repeat else "꺼짐"
            self.reel_label.setText(
                f"모아보기 · {current.entry.video_title} · {timestamp(current.start)} — {timestamp(current.end)}\n"
                f"반복 {repeat_label} ({keys[CommandType.TOGGLE_REEL_REPEAT]}) · "
                f"이전/다음 하이라이트: {keys[CommandType.PREVIOUS_HIGHLIGHT]} / {keys[CommandType.NEXT_HIGHLIGHT]} · "
                f"영상 단위 이동: {keys[CommandType.PREVIOUS_VIDEO]} / {keys[CommandType.NEXT_VIDEO]}")

    def show_error(self, text):
        self.position_label.setText(text)

    def handle_key(self, event) -> bool:
        window = self.shell
        if event.key() == Qt.Key.Key_Escape:
            window.back_to_list()
            return True
        command = window.core.command_for_key(key_name(event) or "")
        if command and window.player:
            try:
                if command.kind in (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO):
                    if not event.isAutoRepeat():
                        window.sync_position()
                        target = window.core.execute_video_command(command, window.playback_list)
                        if target is not None:
                            window.play_video(target)
                        else:
                            window.reel.sync()
                elif window.core.is_highlight_command(command):
                    if event.isAutoRepeat() or window.sync_position() is None:
                        return True
                    window.reel.sync()
                    if window.core.playback.session is None:
                        return True
                    target = window.core.execute_highlight_command(command)
                    if target is not None:
                        window.player.seek_to(target)
                    window.reel.sync()
                    window.refresh_highlights()
                    window.sync_position()
                elif command.kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE:
                    if not event.isAutoRepeat():
                        window.translations.toggle()
                else:
                    if command.kind == CommandType.SEEK:
                        window.sync_position()
                        window.reel.sync()
                    if window.player:
                        window.player.execute(command)
            except Exception as error:
                QMessageBox.warning(window, "재생 조작 실패", str(error))
            return True
        return False
