"""영상 중심 재생 페이지. 창 상태는 셸, 도메인 상태는 AppCore가 소유한다."""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from .core import CommandType
from .highlight_ui import HighlightProgress, PlaybackHighlights
from .time_display import timestamp
from .key_display import display_keys
from .qt_keys import key_name
from .playback_help import PlaybackHelp
from .translation_kind import translation_task
from .theme import playback_stylesheet, playback_font


class PlaybackPage(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.core, self.shell = window.core, window
        self.setStyleSheet(playback_stylesheet())
        self.setFont(playback_font())
        self.fullscreen = False
        self.highlights_expanded = True
        self._shown_session = None
        self._help_requested = False
        self._error = ""
        self._details = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName('playbackHeader')
        top = QHBoxLayout(self.header)
        top.setContentsMargins(8, 4, 8, 4)
        self.back_button = QPushButton("목록으로 · Esc")
        self.back_button.clicked.connect(window.back_to_list)
        top.addWidget(self.back_button)
        self.title_label = QLabel()
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setProperty('playbackRole', 'title')
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.title_label, 1)
        self.reel_label = QLabel()
        self.reel_label.setProperty('playbackRole', 'muted')
        top.addWidget(self.reel_label)
        self.highlights_button = QPushButton()
        self.highlights_button.setCheckable(True)
        self.highlights_button.setChecked(True)
        self.highlights_button.clicked.connect(self.toggle_highlights)
        top.addWidget(self.highlights_button)
        self._layout.addWidget(self.header)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.surface = QWidget()
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.surface.setObjectName("videoSurface")
        self.surface.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.surface.setMouseTracking(True)
        content.addWidget(self.surface, 1)
        self.highlights_panel = PlaybackHighlights()
        self.highlights_panel.activated.connect(self.jump_highlight)
        content.addWidget(self.highlights_panel)
        self._layout.addLayout(content, 1)
        self.bottom_bar = QWidget()
        self.bottom_bar.setObjectName("playbackBar")
        bottom = QVBoxLayout(self.bottom_bar)
        bottom.setContentsMargins(8, 0, 8, 4)
        bottom.setSpacing(0)
        self.progress = HighlightProgress()
        self.progress.setFixedHeight(30)
        bottom.addWidget(self.progress)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.position_label = QLabel("00:00:00.000 / 00:00:00.000")
        self.open_range_label = QLabel()
        self.open_range_label.hide()
        self.speed_label = QLabel("1×")
        self.subtitle_label = QLabel("자막 없음")
        self.subtitle_label.setProperty('playbackRole', 'muted')
        self.subtitle_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.position_label)
        row.addWidget(self.open_range_label)
        row.addWidget(self.speed_label)
        row.addWidget(self.subtitle_label, 1)
        self.menu_button = QToolButton()
        self.menu_button.setText("메뉴 ⋯")
        self.menu_button.setAccessibleName("재생 작업 메뉴")
        self.menu_button.setToolTip("재생 작업 메뉴 · 키 안내는 F1")
        self.menu_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.menu_button)
        for label, callback in (
            ("하이라이트 목록 · 시각·메모 편집", window.show_highlights),
            ("자막 만들기 / 원어 지정", window.subtitles.request),
            ("번역 CLI / 재시도", window.translations.settings),
            ("자막 검수 / SRT 내보내기", window.show_review),
        ):
            self.menu.addAction(label, lambda checked=False, action=callback: self.run_action(action))
        self.menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.focus_content))
        self.menu_button.setMenu(self.menu)
        row.addWidget(self.menu_button)
        bottom.addLayout(row)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setProperty('playbackRole', 'warning')
        self.message_label.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.setInterval(5000)
        self.notice_timer.timeout.connect(lambda: self.show_notice(""))
        bottom.addWidget(self.message_label)
        self._layout.addWidget(self.bottom_bar)
        self.help_panel = PlaybackHelp(window)
        self.bar_timer = QTimer(self)
        self.bar_timer.setSingleShot(True)
        self.bar_timer.setInterval(2500)
        self.bar_timer.timeout.connect(self.hide_temporary_bar)
        self.pointer_timer = QTimer(self)
        self.pointer_timer.setInterval(150)
        self.pointer_timer.timeout.connect(self.check_pointer)
        self._pointer_position = QCursor.pos()
        self.details_timer = QTimer(self)
        self.details_timer.setInterval(1000)
        self.details_timer.timeout.connect(self.refresh_details)
        self.details_timer.start()
        window.statusBar().messageChanged.connect(self.show_notice)
        QApplication.instance().installEventFilter(self)
        QWidget.setTabOrder(self.surface, self.menu_button)
        QWidget.setTabOrder(self.menu_button, self.back_button)
        QWidget.setTabOrder(self.back_button, self.highlights_button)
        QWidget.setTabOrder(self.highlights_button, self.highlights_panel.list)
        QWidget.setTabOrder(self.highlights_panel.list, self.surface)
        self.refresh_key_help()

    def focus_content(self):
        if self.isVisible() and QApplication.activeModalWidget() is None:
            self.surface.setFocus()

    def run_action(self, action):
        self.close_help()
        try:
            action()
        finally:
            self.refresh_details()
            self.focus_content()

    def refresh_key_help(self):
        self.help_panel.refresh(self.core)
        bindings = {row.command.kind: display_keys(row.keys) for row in self.core.key_bindings()}
        self.highlights_button.setText('하이라이트 패널 ' + ('접기' if self.highlights_expanded else '펴기'))
        self.highlights_button.setToolTip('하이라이트 패널 접기 / 펴기 · '
                                         + bindings[CommandType.TOGGLE_HIGHLIGHT_LIST])
        point_keys = next(row.keys for row in self.core.key_bindings()
                          if row.command.kind == CommandType.POINT_HIGHLIGHT)
        guidance = (f'지점 하이라이트 키({display_keys(point_keys)})로 지금 순간을 남겨 보세요.'
                    if point_keys else '키 설정에서 지점 하이라이트 키를 정하면 지금 순간을 남길 수 있습니다.')
        self.highlights_panel.empty.setText('아직 하이라이트가 없습니다.\n' + guidance)
        if self._help_requested:
            self.help_panel.place_over(self.surface)

    def toggle_highlights(self):
        # 전체 화면에서는 항상 숨기고, 창 모드의 선택은 보존한다.
        if self.fullscreen:
            return
        self.highlights_expanded = not self.highlights_expanded
        self.highlights_panel.setVisible(self.highlights_expanded)
        self.highlights_button.setChecked(self.highlights_expanded)
        self.refresh_key_help()
        self.focus_content()

    def refresh_highlights(self):
        session = self.core.playback.session
        if session:
            highlights = self.core.highlights(session.video_id)
            self.progress.highlights = highlights
            self.highlights_panel.show_highlights(highlights, self.core.playback.position, video_id=session.video_id)
            self.progress.update()

    def jump_highlight(self, highlight):
        window = self.shell
        try:
            window.sync_position()
            session = self.core.playback.session
            if session is None or session.video_id != highlight.video_id:
                return  # 위치 보고 중 자동 전환된 이전 영상의 클릭은 버린다.
            if not any(h.id == highlight.id for h in self.core.highlights(session.video_id)):
                self.refresh_highlights()
                return
            if self.core.reel_playback is not None:
                # 검수 이동과 같이 기존 복습을 닫고 새 일반 시청으로 전환한다.
                window.end_playback()
                window.playback_list = window.library_page.visible_video_ids()
                window.play_video(highlight.video_id, start=highlight.start)
            elif window.player:
                window.player.seek_to(highlight.start, resume=True)
            self.focus_content()
        except Exception as error:
            QMessageBox.warning(window, '하이라이트 이동 실패', str(error))

    def toggle_help(self):
        if self._help_requested:
            self.close_help()
        else:
            self._help_requested = True
            self.refresh_key_help()
            self.help_panel.place_over(self.surface)
            self.help_panel.show()
            self.help_panel.raise_()

    def close_help(self):
        self._help_requested = False
        self.help_panel.hide()

    def set_fullscreen(self, enabled):
        self.fullscreen = enabled
        self.header.setVisible(not enabled)
        self.highlights_panel.setVisible(not enabled and self.highlights_expanded)
        self.bar_timer.stop()
        self.bottom_bar.setVisible(not enabled)
        self.message_label.setVisible(bool(self._error or (not enabled and self.message_label.text())))
        self._pointer_position = QCursor.pos()
        if enabled:
            self.pointer_timer.start()
        else:
            self.pointer_timer.stop()
        if self._help_requested:
            QTimer.singleShot(0, lambda: self.help_panel.place_over(self.surface))

    def reveal_bar(self):
        if self.fullscreen:
            # 레이아웃 공간을 사용해 네이티브 mpv 위젯과 겹치지 않는다.
            self.bottom_bar.show()
            self.bar_timer.start()

    def check_pointer(self):
        # mpv의 네이티브 자식 창이 Qt MouseMove를 받지 않는 경우도 감지한다.
        position = QCursor.pos()
        moved = position != self._pointer_position
        self._pointer_position = position
        if (moved and self.isVisible() and self.shell.isActiveWindow()
                and self.rect().contains(self.mapFromGlobal(position))):
            self.reveal_bar()

    def hide_temporary_bar(self):
        if self.fullscreen:
            if self.menu.isVisible() or self.bottom_bar.isAncestorOf(QApplication.focusWidget()):
                self.bar_timer.start()
            elif not self._error:
                self.bottom_bar.hide()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.surface and kind == QEvent.Type.Resize and self._help_requested:
            QTimer.singleShot(0, lambda: self.help_panel.place_over(self.surface))
        if watched is self.shell:
            if kind in (QEvent.Type.Move, QEvent.Type.Resize) and self._help_requested:
                QTimer.singleShot(0, lambda: self.help_panel.place_over(self.surface))
            elif kind in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
                self.help_panel.hide()
            elif kind == QEvent.Type.WindowActivate and self._help_requested and self.isVisible():
                self.help_panel.place_over(self.surface)
                self.help_panel.show()
        if kind == QEvent.Type.MouseMove and self.isVisible() and self.shell.isActiveWindow():
            if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
                self.reveal_bar()
        return super().eventFilter(watched, event)

    def show_notice(self, text):
        self.notice_timer.stop()
        self.message_label.setText(self._error or text)
        self.message_label.setVisible(bool(self._error or (text and not self.fullscreen)))
        if text and not self._error:
            self.notice_timer.start()

    def refresh_details(self):
        if not self.isVisible() or self.core.playback.session is None:
            return
        video_id = self.core.playback.session.video_id
        self._details = self.core.library_details(video_id)
        self.refresh_highlights()
        self.update_subtitle_label()

    def update_subtitle_label(self):
        player = self.shell.player
        # stop_player는 엔진을 닫은 뒤 마지막 위치 보고를 저장한다.
        # 그 보고로 화면을 갱신할 때는 종료된 mpv 속성을 다시 읽지 않는다.
        if not player or not self.shell.position_timer.isActive():
            return
        options = getattr(player, "playback_options", None)
        speed, visible = options() if options else (1, True)
        self.speed_label.setText(f"{speed:g}×")
        details = self._details
        if details is None:
            return
        task = translation_task(details.spoken_language)
        state = task.subtitle_label if self.core.playback_subtitle_language == "translated" else "자막 원어"
        if not visible:
            state = "자막 꺼짐"
        elif not details.original_lines:
            state = "자막 없음"
        work = {"queued": "대기", "transcribing": "만드는 중", "translating": "진행 중",
                "held": "보류", "failed": "실패"}
        labels = [state]
        if details.subtitle_state in work:
            labels.append(f"원어 {work[details.subtitle_state]}")
        if details.translation_state in work:
            labels.append(f"{task.label} {work[details.translation_state]}")
        self.subtitle_label.setText(" · ".join(labels))
        self.subtitle_label.setToolTip(self.subtitle_label.text())

    def show_position(self, position, duration, open_start, range_keys):
        session = self.core.playback.session
        if session and self._shown_session is not session:
            self._shown_session = session
            self._error = ""
            self.show_notice("")
            video = self.core.video(session.video_id)
            series = self.core.series_for_video(session.video_id)
            episode = f" · {series.video_ids.index(video.id) + 1}/{len(series.video_ids)}" if series else ""
            self.title_label.setText(video.title + episode)
            self.title_label.setToolTip(video.title + episode)
            self.refresh_details()
        self.progress.duration = duration
        self.progress.position = position
        self.progress.open_start = open_start
        self.progress.update()
        if session:
            self.highlights_panel.show_highlights(self.progress.highlights, position, video_id=session.video_id)
        self.position_label.setText(f"{timestamp(position)} / {timestamp(duration)}")
        self.open_range_label.setText(f"구간 시작 {timestamp(open_start).split('.')[0]}"
                                      if open_start is not None else "")
        self.open_range_label.setVisible(open_start is not None)
        self.position_label.setToolTip(f"구간 시작 {timestamp(open_start)} · {range_keys}: 끝내기"
                                      if open_start is not None else "")
        self.update_subtitle_label()

    def show_reel(self, current, repeat, keys):
        self.reel_label.setVisible(current is not None)
        self.back_button.setText("모아보기 목록 · Esc" if current else "목록으로 · Esc")
        if current:
            self.reel_label.setText(f"하이라이트 {current.index}/{current.total} · 반복 {'켜짐' if repeat else '꺼짐'}")
        if self._help_requested:
            self.refresh_key_help()

    def show_error(self, text):
        self._error = text
        self.show_notice(text)
        self.reveal_bar()

    def handle_key(self, event) -> bool:
        window = self.shell
        self.reveal_bar()
        if event.key() == Qt.Key.Key_F1 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not event.isAutoRepeat():
                self.toggle_help()
            return True
        if event.key() == Qt.Key.Key_Escape:
            if not event.isAutoRepeat():
                if self._help_requested:
                    self.close_help()
                elif window.isFullScreen():
                    window.set_playback_fullscreen(False)
                else:
                    window.back_to_list()
            return True
        focus = QApplication.focusWidget()
        if focus is self.highlights_panel.list:
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Up, Qt.Key.Key_Down,
                               Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                return False
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if not event.isAutoRepeat():
                    self.highlights_panel.activate(self.highlights_panel.list.currentItem())
                return True
        if focus in (self.menu_button, self.back_button, self.highlights_button) and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            return False
        if (focus in (self.back_button, self.highlights_button) and event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            return False
        if (focus is self.menu_button
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down)):
            if not event.isAutoRepeat():
                self.menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().topRight()))
            return True
        command = window.core.command_for_key(key_name(event) or "")
        if command and command.kind == CommandType.TOGGLE_HIGHLIGHT_LIST:
            if not event.isAutoRepeat():
                self.toggle_highlights()
            return True
        if command and command.kind == CommandType.TOGGLE_FULLSCREEN:
            if not event.isAutoRepeat():
                window.set_playback_fullscreen(not window.isFullScreen())
            return True
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
