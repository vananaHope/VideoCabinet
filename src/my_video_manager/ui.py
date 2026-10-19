"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from .adapters import MpvPlayer
from .core import AppCore, Command, CommandType
from .subtitle_controls import SubtitleControls
from .translation_controls import TranslationControls
from .web_dialogs_entries import HighlightList
from .key_display import display_keys
from .tray import TrayControls
from .web_dialogs_entries import ReviewDialog
from .playback_page import PlaybackPage
from .qt_keys import key_name
from .theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, *, player_factory=MpvPlayer, folder_watch_options=None,
                 update_check_options=None):
        apply_theme(QApplication.instance())
        super().__init__()
        self.core = core
        self.player = None
        self.player_factory = player_factory
        self.playback_list = ()
        self._return_to_gems = False
        # 긴급 탈출로 멈춘 엔진. 사용자가 재개하기 전까지 모아보기 자동 전환을 미룬다.
        self._held_player = None
        self._held_eof = False
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(100)
        self.position_timer.timeout.connect(self.poll_position)
        self.subtitles = SubtitleControls(self)
        self.translations = TranslationControls(self)
        self.tray = TrayControls(self)
        from .update_controls import UpdateControls
        self.updates = UpdateControls(self, **(update_check_options or {}))
        self.setWindowTitle("영상 라이브러리")
        self.resize(1100, 720)
        self.pages = QStackedWidget()
        self.settings_menu = self.menuBar().addMenu("설정(&S)")
        self.settings_menu.addAction("키 배치…", self.show_settings)
        # 숨은 메뉴바의 니모닉은 동작하지 않으므로 전체 화면에서만 보완한다.
        self.fullscreen_settings_shortcut = QShortcut("Alt+S", self)
        self.fullscreen_settings_shortcut.setEnabled(False)
        self.fullscreen_settings_shortcut.activated.connect(self.show_fullscreen_settings_menu)

        self.menuBar().hide()
        self.statusBar().hide()
        from .web_page_registry import create_web_shell
        self.web_host = create_web_shell(self)
        self.library_page = self.web_host.controllers['library']
        from .folder_watch_controls import FolderWatchControls
        self.folder_watch = FolderWatchControls(self, **(folder_watch_options or {}))
        self._startup_frontend_ready = False
        self._startup_scan_scheduled = False
        self._startup_scan_timer = QTimer(self)
        self._startup_scan_timer.setSingleShot(True)
        self._startup_scan_timer.setInterval(250)
        self._startup_scan_timer.timeout.connect(self.scan_on_startup)
        self.web_host.frontend_loaded.connect(self.startup_frontend_loaded)
        self.home_page = self.web_host
        self.pages.addWidget(self.home_page)
        self.playback_page = PlaybackPage(self)
        self.settings_menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.playback_page.focus_content))
        self.pages.addWidget(self.playback_page)
        # 기존 화면 어댑터용 연결점. 위젯 구성과 갱신은 각 페이지 모듈이 소유한다.
        self.surface = self.playback_page.surface
        self.progress = self.playback_page.progress
        from .web_reel_page import WebReelControls
        self.reel = WebReelControls(self)
        self.setCentralWidget(self.pages)
        self._active_page = self.home_page
        self._return_page = self.home_page
        self.pages.currentChanged.connect(self.page_changed)

        QApplication.instance().installEventFilter(self)
        self.refresh()
        from .resolution_controls import ResolutionControls
        self.resolutions = ResolutionControls(self)
        self.thumbnails = ResolutionControls(self, kind='thumbnail')

    def startup_frontend_loaded(self):
        self._startup_frontend_ready = True
        self.schedule_startup_scan()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_startup_scan()

    def schedule_startup_scan(self):
        if (self._startup_scan_scheduled or not self._startup_frontend_ready
                or not self.isVisible() or self.tray.quitting):
            return
        self._startup_scan_scheduled = True
        # React 첫 렌더와 창 표시 뒤 Chromium 합성·첫 입력에 시간을 준다.
        # 트레이 복원이나 웹 재로드에서는 다시 예약하지 않는다.
        self._startup_scan_timer.start()

    def scan_on_startup(self):
        """감시를 먼저 시작한 뒤 시작 검사를 돌려 감시 시작 직후의 틈을 덮는다.

        자동 감지를 끄면 시작 검사도 함께 끈다. 업데이트 확인은 그 뒤로 조금 미룬다.
        """
        if self.tray.quitting:
            return
        self.folder_watch.start()
        if self.folder_watch.enabled and self.core.watched_folders():
            self.library_page.scan(quiet_if_unchanged=True)
        self.updates.schedule_startup()

    def page_changed(self, _index):
        page = self.pages.currentWidget()
        playing = page is self.playback_page
        if playing and self._active_page is not self.playback_page:
            self._return_page = self._active_page
        self._active_page = page
        if not playing:
            self.set_playback_fullscreen(False)
            self.playback_page.close_help()

    def set_playback_fullscreen(self, enabled):
        enabled = enabled and self.pages.currentWidget() is self.playback_page
        if enabled and not self.isFullScreen():
            self._playback_was_maximized = self.isMaximized()
            self.showFullScreen()
        elif not enabled and self.isFullScreen():
            self.showNormal()
            if getattr(self, "_playback_was_maximized", False):
                self.showMaximized()
        self.playback_page.set_fullscreen(enabled)

    def changeEvent(self, event):
        super().changeEvent(event)
        # 트레이의 showNormal 등 창 바깥 경로도 실제 창 상태와 표시를 맞춘다.
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "playback_page"):
            self.fullscreen_settings_shortcut.setEnabled(self.isFullScreen())
            self.web_host.dialogs.sync_shortcut()
            self.playback_page.set_fullscreen(self.isFullScreen())

    def show_fullscreen_settings_menu(self):
        if self.web_host.dialogs.blocks_shell_actions:
            return
        self.playback_page.close_help()
        if self.pages.currentWidget() is self.playback_page:
            self.web_host.popup_settings_menu()
        else:
            self.navigate_web_tab('settings')

    def navigate_web_tab(self, tab):
        self.web_host.navigate(tab)

    def emergency_hide(self):
        """긴급 탈출: 확인 없이 일시정지하고 전체 화면을 푼 뒤 창을 트레이로 숨긴다.

        재생 세션과 현재 화면은 그대로 두므로 트레이 열기로 같은 장면의 일시정지 상태로 돌아온다.
        """
        focus = QApplication.focusWidget()
        if self.player:
            try:
                # 이미 엔진이 보낸 구간 끝·EOF 보고가 다음 항목을 자동 재생하지 않게 먼저 보류한다.
                if self._held_player is not self.player:
                    self._held_player, self._held_eof = self.player, False
                self.player.pause()
                self.sync_position()
            except Exception as error:
                # 숨기기가 먼저다. 실패는 복귀한 화면에 보인다.
                self.playback_page.show_error(f"일시정지 실패: {error}")
        self.set_playback_fullscreen(False)
        self.tray.hide_for_emergency(focus)

    @property
    def worker(self):
        return self.library_page.worker

    def refresh(self, *, focus_gems=None):
        self.library_page.refresh(focus_gems=focus_gems)

    def show_status(self, text):
        """현재 페이지와 관계없이 창 아래에 작업 결과를 표시한다."""
        self.statusBar().showMessage(text)

    def scan(self, checked=False, *, operation=None):
        self.library_page.scan(checked, operation=operation)

    def play(self, video_id):
        self.playback_list = self.library_page.visible_video_ids()
        self.play_video(video_id)

    def show_search(self):
        self.navigate_web_tab('search')

    def play_video(self, video_id, *, start=None, from_gems=False):
        if self.pages.currentWidget() is not self.playback_page:
            self._return_page = self.pages.currentWidget()
        if self.pages.currentIndex() == 0:
            self._return_to_gems = from_gems
        try:
            self.stop_player()
            self.load_player(video_id, self.core.switch_to(video_id, start=start))
        except Exception as error:
            self.end_playback()
            self.pages.setCurrentWidget(self._return_page)
            QMessageBox.critical(self, "재생 실패", str(error))

    def load_player(self, video_id, start):
        location = self.core.playback_location(video_id)
        if self.pages.currentWidget() is self.web_host:
            self.web_host.remember_playback_tab()
        self.pages.setCurrentIndex(1)
        if self.player is None:
            self.player = self.player_factory(int(self.surface.winId()))
        self.player.play(location.path, start, subtitle=self.core.playback_subtitle(video_id))
        self.progress.duration = next(v.duration for v in self.core.videos() if v.id == video_id)
        self.refresh_highlights()
        self.position_timer.start()
        self.surface.setFocus()

    def end_playback(self):
        self.stop_player()
        self.core.playback.end()
        self.reel.shown = None
        self.playback_page.show_reel(None, False, {})

    def stop_player(self):
        self.position_timer.stop()
        # 닫는 엔진의 일시정지 상태는 읽지 않는다. 남은 보고는 기존처럼 처리한다.
        self._held_player, self._held_eof = None, False
        if self.player:
            self.player.close()
            self.sync_position()
            self.player = None

    def sync_position(self):
        if self.player and self.core.playback.session is not None:
            # 긴급 탈출로 멈춘 엔진은 사용자가 재개하기 전까지 모아보기 자동 전환을 미룬다.
            # 위치·복습 보고는 그대로 반영하고, 끝 도달은 코어가, EOF는 여기서 기억한다.
            held = self._held_player is self.player
            if self._held_player is not None and not held:
                self._held_player, self._held_eof = None, False  # 엔진이 바뀌면 보류 대상이 없다.
            resumed = held and not self.player.paused
            # 상대 탐색과 Home/End 절대 탐색 모두 mpv 이벤트의 seeked 표시를 쓴다.
            session = self.core.playback.session
            for position, seeked in self.player.take_positions():
                self.core.playback.report(position, seeked=seeked)
                if held:
                    self._held_eof = self._held_eof and not seeked
                    continue
                self.core.advance_reel_if_due()
                if self.core.playback.session is not session:
                    break  # 자동 전환 뒤 이전 엔진의 나머지 보고는 버린다.
            eof = self.player.take_eof()
            if held:
                self._held_eof = self._held_eof or eof
                if resumed:
                    # 남은 보고를 모두 반영한 뒤 미룬 전환을 적용한다.
                    eof, self._held_player, self._held_eof = self._held_eof, None, False
                    self.core.advance_reel_if_due(eof=eof)
            elif self.core.playback.session is session and eof:
                self.core.advance_reel_if_due(eof=True)
            self.core.save_viewings()
            position = self.core.playback.position
            opened = self.core.open_highlight_start
            range_keys = next((display_keys(row.keys) for row in self.core.key_bindings()
                               if row.command.kind == CommandType.RANGE_HIGHLIGHT), "키 미할당")
            self.playback_page.show_position(position, self.progress.duration, opened, range_keys)
            return position
        return None

    def poll_position(self):
        try:
            self.sync_position()
            self.reel.sync()
        except Exception as error:
            self.position_timer.stop()
            self.playback_page.show_error(f"재생 위치 확인 실패: {error}")

    def refresh_highlights(self):
        if self.core.playback.session is None:
            return
        self.progress.highlights = self.core.highlights(self.core.playback.session.video_id)
        self.progress.open_start = self.core.open_highlight_start
        self.progress.position = self.core.playback.position
        self.progress.update()
        self.playback_page.highlights_panel.show_highlights(
            self.progress.highlights, self.progress.position, video_id=self.core.playback.session.video_id)

    def show_highlights(self):
        if self.core.playback.session is not None:
            HighlightList(self.core, self.core.playback.session.video_id, self.progress.duration, self).exec()
            self.refresh_highlights()
            self.surface.setFocus()

    def show_library(self):
        self.end_playback()
        self.web_host.set_tab("library")
        self.pages.setCurrentIndex(0)
        self.refresh(focus_gems=self._return_to_gems)
        self._return_to_gems = False

    def back_to_list(self):
        if self.reel.shown is not None or self.core.reel_playback is not None:
            self.reel.open()
        else:
            self.web_host.return_from_playback(focus_gems=self._return_to_gems)
            self._return_to_gems = False

    def refresh_key_help(self):
        self.playback_page.refresh_key_help()

    def show_settings(self):
        self.navigate_web_tab('settings')
        self.web_host.request_focus('settings-keys')

    def show_review(self):
        session = self.core.playback.session
        video_id = session.video_id if session else self.library_page.selected_video_id()
        if video_id is not None:
            ReviewDialog(self.core, video_id, self.review_jump, self.review_changed, self).exec()

    def review_jump(self, video_id, line_id):
        if self.pages.currentWidget() is not self.playback_page:
            self._return_page = self.pages.currentWidget()
        self.sync_position()
        target = self.core.play_review_line(video_id, line_id)
        try:
            if self.player and target.action == "seek":
                self.player.seek_to(target.start, resume=True)
            else:
                # 코어는 이미 새 시청을 시작했다. 이전 엔진의 남은 보고를 새 시청에 보내지 않는다.
                self.position_timer.stop()
                if self.player:
                    self.player.close()
                    self.player = None
                self.reel.shown = None
                self.reel.update_label()
                self.playback_list = self.library_page.visible_video_ids()
                self.load_player(video_id, target.start)
        except Exception:
            self.end_playback()
            self.pages.setCurrentWidget(self._return_page)
            raise

    def review_changed(self, video_id):
        session = self.core.playback.session
        if self.player and session and session.video_id == video_id:
            self.player.set_subtitle(self.core.playback_subtitle(video_id))

    def eventFilter(self, watched, event):
        if (self.isActiveWindow() and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            settings = self.web_host.controllers.get('settings')
            if settings is not None and settings.capture_event(event):
                return True
        if (event.type() != QEvent.Type.KeyPress or not self.isActiveWindow()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return super().eventFilter(watched, event)
        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_7):
            if self.web_host.dialogs.blocks_shell_actions:
                return super().eventFilter(watched, event)
            if not event.isAutoRepeat():
                from .web_contract import TABS
                self.navigate_web_tab(TABS[event.key() - Qt.Key.Key_1][0])
            return True
        if event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() == Qt.Key.Key_S:
            if self.web_host.dialogs.blocks_shell_actions:
                return super().eventFilter(watched, event)
            if not event.isAutoRepeat():
                self.show_fullscreen_settings_menu()
            return True
        if self.core.command_for_key(key_name(event) or "") == Command(CommandType.EMERGENCY_HIDE):
            # 재생 화면과 웹 셸의 모든 탭이 이 필터 한 곳에서 받는다.
            if self.web_host.dialogs.blocks_shell_actions:
                return super().eventFilter(watched, event)
            if not event.isAutoRepeat():
                self.emergency_hide()
            return True
        handle_key = getattr(self.pages.currentWidget(), "handle_key", None)
        return handle_key(event) if callable(handle_key) else False

    def closeEvent(self, event):
        self.tray.close_window(event)
        if event.isAccepted():
            self._startup_scan_timer.stop()
