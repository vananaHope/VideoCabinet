"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QStackedWidget

from .adapters import MpvPlayer
from .core import AppCore, CommandType
from .subtitle_ui import SubtitleControls
from .translation_ui import TranslationControls
from .highlight_ui import HighlightList
from .reel_ui import ReelControls
from .key_settings_ui import SettingsDialog
from .key_display import display_keys
from .tray import TrayControls
from .review_ui import ReviewDialog
from .library_page import LibraryPage
from .playback_page import PlaybackPage
from .shell_ui import SEARCH_PAGE_INDEX, build_shell
from .theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, *, player_factory=MpvPlayer):
        apply_theme(QApplication.instance())
        super().__init__()
        self.core = core
        self.player = None
        self.player_factory = player_factory
        self.playback_list = ()
        self._return_to_gems = False
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(100)
        self.position_timer.timeout.connect(self.poll_position)
        self.subtitles = SubtitleControls(self)
        self.translations = TranslationControls(self)
        self.tray = TrayControls(self)
        self.setWindowTitle("영상 라이브러리")
        self.resize(1100, 720)
        self.pages = QStackedWidget()
        self.library_count = QLabel()
        self.library_count.setAccessibleName("라이브러리 등록·표시 개수")
        self.statusBar().addPermanentWidget(self.library_count)
        self.settings_menu = self.menuBar().addMenu("설정(&S)")
        self.settings_menu.addAction("키 배치…", self.show_settings)
        # 숨은 메뉴바의 니모닉은 동작하지 않으므로 전체 화면에서만 보완한다.
        self.fullscreen_settings_shortcut = QShortcut("Alt+S", self)
        self.fullscreen_settings_shortcut.setEnabled(False)
        self.fullscreen_settings_shortcut.activated.connect(self.show_fullscreen_settings_menu)

        self.library_page = LibraryPage(self)
        self.pages.addWidget(self.library_page)
        self.playback_page = PlaybackPage(self)
        self.settings_menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.playback_page.focus_content))
        self.pages.addWidget(self.playback_page)
        # 기존 화면 어댑터용 연결점. 위젯 구성과 갱신은 각 페이지 모듈이 소유한다.
        self.surface = self.playback_page.surface
        self.progress = self.playback_page.progress
        self.reel = ReelControls(self)
        build_shell(self)
        self._active_page = self.library_page
        self._return_page = self.library_page
        self.pages.currentChanged.connect(self.page_changed)

        QApplication.instance().installEventFilter(self)
        self.refresh()

    def page_changed(self, _index):
        page = self.pages.currentWidget()
        playing = page is self.playback_page
        if playing and self._active_page is not self.playback_page:
            self._return_page = self._active_page
        self._active_page = page
        if not playing:
            self.set_playback_fullscreen(False)
            self.playback_page.close_help()
        self.sidebar.setVisible(not playing)
        self.statusBar().setVisible(not playing)
        if page in self.navigation_pages:
            self.sidebar.select(self.navigation_pages.index(page))

    def set_playback_fullscreen(self, enabled):
        enabled = enabled and self.pages.currentWidget() is self.playback_page
        if enabled and not self.isFullScreen():
            self._playback_was_maximized = self.isMaximized()
            self.showFullScreen()
        elif not enabled and self.isFullScreen():
            self.showNormal()
            if getattr(self, "_playback_was_maximized", False):
                self.showMaximized()
        self.menuBar().setVisible(not enabled)
        self.playback_page.set_fullscreen(enabled)
        playing = self.pages.currentWidget() is self.playback_page
        self.sidebar.setVisible(not playing)
        self.statusBar().setVisible(not playing)

    def changeEvent(self, event):
        super().changeEvent(event)
        # 트레이의 showNormal 등 창 바깥 경로도 실제 창 상태와 표시를 맞춘다.
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "playback_page"):
            self.fullscreen_settings_shortcut.setEnabled(self.isFullScreen())
            self.menuBar().setVisible(not self.isFullScreen())
            self.playback_page.set_fullscreen(self.isFullScreen())

    def show_fullscreen_settings_menu(self):
        self.playback_page.close_help()
        self.settings_menu.popup(self.mapToGlobal(QPoint(12, 12)))

    def navigate(self, index):
        if not 0 <= index < len(self.navigation_pages):
            return
        focus = QApplication.focusWidget()
        from_sidebar = focus is not None and self.sidebar.isAncestorOf(focus)
        if index == 0:
            self.show_library()
        elif index == 1:
            self.reel.open()
        else:
            self.end_playback()
            self._return_to_gems = False
            self.pages.setCurrentWidget(self.navigation_pages[index])
            self.navigation_pages[index].focus_content()
        self.sidebar.select(index)
        # 방향키로 페이지를 훑는 동안에는 사이드바의 키보드 포커스를 유지한다.
        if from_sidebar:
            (self.sidebar.settings if index == 5 else self.sidebar.list).setFocus()

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
        self.navigate(SEARCH_PAGE_INDEX)

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
        if self.player:
            self.player.close()
            self.sync_position()
            self.player = None

    def sync_position(self):
        if self.player and self.core.playback.session is not None:
            # 상대 탐색과 Home/End 절대 탐색 모두 mpv 이벤트의 seeked 표시를 쓴다.
            session = self.core.playback.session
            for position, seeked in self.player.take_positions():
                self.core.playback.report(position, seeked=seeked)
                self.core.advance_reel_if_due()
                if self.core.playback.session is not session:
                    break  # 자동 전환 뒤 이전 엔진의 나머지 보고는 버린다.
            eof = self.player.take_eof()
            if self.core.playback.session is session and eof:
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

    def show_highlights(self):
        if self.core.playback.session is not None:
            HighlightList(self.core, self.core.playback.session.video_id, self.progress.duration, self).exec()
            self.refresh_highlights()
            self.surface.setFocus()

    def show_library(self):
        self.end_playback()
        self.pages.setCurrentIndex(0)
        self.refresh(focus_gems=self._return_to_gems)
        self._return_to_gems = False

    def back_to_list(self):
        if self.reel.shown is not None or self.core.reel_playback is not None:
            self.reel.open()
        elif self._return_page is self.library_page:
            self.show_library()
        else:
            self.end_playback()
            self.pages.setCurrentWidget(self._return_page)
            if self._return_page is self.reel.page:
                self.reel.refresh()
                self.reel.list.setFocus()
            else:
                self._return_page.focus_content()

    def refresh_key_help(self):
        self.playback_page.refresh_key_help()

    def show_settings(self):
        SettingsDialog(self.core, self).exec()
        self.refresh_key_help()
        self.reel.update_label()
        if self.pages.currentIndex() == 1:
            self.surface.setFocus()

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
        if (event.type() != QEvent.Type.KeyPress or not self.isActiveWindow()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return super().eventFilter(watched, event)
        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_6):
            if not event.isAutoRepeat():
                self.navigate(event.key() - Qt.Key.Key_1)
            return True
        handle_key = getattr(self.pages.currentWidget(), "handle_key", None)
        return handle_key(event) if callable(handle_key) else False

    def closeEvent(self, event):
        self.tray.close_window(event)
