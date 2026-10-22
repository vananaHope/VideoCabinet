"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QStackedWidget, QWidget, QVBoxLayout

from .adapters import MpvPlayer
from .core import AppCore, Command, CommandType
from .random_continuous_play import RandomPlayScope
from .subtitle_controls import SubtitleControls
from .translation_controls import TranslationControls
from .web_dialogs_entries import HighlightList
from .key_display import display_keys
from .native_dialogs import native_dialog_escape
from .tray import TrayControls
from .web_dialogs_entries import ReviewDialog
from .playback_page import PlaybackPage
from .player_shutdown import PlayerShutdown
from .qt_keys import key_name
from .theme import apply_theme


@dataclass
class TransitionHold:
    """긴급 탈출로 멈춘 엔진·재생 항목에 묶인 모아보기·무작위 이어 재생 전환 보류.

    끝 도달은 코어가 항목별로 기억하고, EOF와 진행 중인 사용자 탐색은 여기서 기억한다.
    엔진이나 재생 세션(모아보기 항목)이 바뀌면 보류는 그 항목과 함께 버린다.
    """
    player: object
    session: object
    eof: bool = False
    seeking: bool = False


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, *, player_factory=MpvPlayer, folder_watch_options=None,
                 update_check_options=None, native_dialogs_factory=native_dialog_escape):
        apply_theme(QApplication.instance())
        super().__init__()
        self.core = core
        self.player = None
        self._player_surface = None
        self.player_shutdown = PlayerShutdown(self)
        self.player_factory = player_factory
        self.playback_list = ()
        self._composing_widget = None
        # 긴급 탈출로 멈춘 엔진. 사용자가 재개하기 전까지 영상·항목 끝 전환을 미룬다.
        self._hold = None
        self._pending_random_eof = None
        self._stopping_player = False
        # 긴급 탈출로 닫은 메뉴와 그때의 화면. 복귀 때 같은 화면이면 메뉴를 다시 연다.
        self._emergency_popups = []
        self._emergency_view = None
        self._reopen_when_active = False
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
        # Windows 기본 파일 창은 Qt 이벤트 필터를 거치지 않으므로 따로 받는다.
        self.native_dialogs = native_dialogs_factory(self, self.is_emergency_key, self.emergency_hide)
        self.native_dialogs.install()
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

    def logical_page(self):
        """복귀 준비의 재생 표면은 덮개일 뿐, 명령 대상은 이미 웹 페이지다."""
        return self.web_host if self.web_host.return_pending else self.pages.currentWidget()

    def set_playback_fullscreen(self, enabled):
        enabled = enabled and self.logical_page() is self.playback_page
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
        if (event.type() == QEvent.Type.ActivationChange and getattr(self, "_reopen_when_active", False)
                and self.isActiveWindow()):
            # 활성화 처리가 끝난 뒤 메뉴를 연다.
            QTimer.singleShot(0, self.reopen_emergency_popups)

    def show_fullscreen_settings_menu(self):
        if self.web_host.dialogs.blocks_shell_actions:
            return
        self.playback_page.close_help()
        if self.logical_page() is self.playback_page:
            self.web_host.popup_settings_menu()
        else:
            self.navigate_web_tab('settings')

    def navigate_web_tab(self, tab):
        self.web_host.navigate(tab)

    def emergency_hide(self):
        """긴급 탈출: 확인 없이 일시정지하고 전체 화면을 푼 뒤 창을 트레이로 숨긴다.

        재생 세션과 현재 화면은 그대로 두므로 트레이 열기로 같은 장면의 일시정지 상태로 돌아온다.
        """
        # 조합 중인 글자는 초점이 옮겨 가기 전에 지금 입력란에 확정한다.
        QGuiApplication.inputMethod().reset()
        # 공용 경고처럼 exec 중인 Qt 대화상자는 닫기(취소·Esc와 같은 결과)로 끝내고 복귀 때 다시 띄우지 않는다.
        # 호출부는 이 처리가 끝나 창이 숨은 뒤 exec가 반환되면 이어서 실행된다.
        container = self.web_host.dialogs.container
        while (modal := QApplication.activeModalWidget()) not in (None, container):
            if not modal.close():
                modal.reject()  # 닫기 버튼이 없는 QMessageBox는 close를 거부한다.
            if QApplication.activeModalWidget() is modal:
                break
        focus = QApplication.focusWidget()
        # Qt 메뉴 팝업은 창과 함께 닫고 복귀 때 같은 자리에 다시 연다. 웹 목록·메뉴는 닫힌 채 둔다.
        self.web_host.close_popups()
        self._emergency_view = self._view()
        self._emergency_popups = []
        self._reopen_when_active = False
        while (popup := QApplication.activePopupWidget()) is not None:
            if isinstance(popup, QMenu):
                self._emergency_popups.append((popup, self.mapFromGlobal(popup.pos()), popup.activeAction()))
            if not popup.close():
                break
        if self.player:
            try:
                # 이미 엔진이 보낸 구간 끝·EOF 보고가 다음 항목을 자동 재생하지 않게 먼저 보류한다.
                if self._current_hold() is None:
                    self._hold = TransitionHold(self.player, self.core.playback.session)
                self.player.pause()
                self.sync_position()
            except Exception as error:
                # 숨기기가 먼저다. 실패는 복귀한 화면에 보인다.
                self.playback_page.show_error(f"일시정지 실패: {error}")
        self.set_playback_fullscreen(False)
        self.tray.hide_for_emergency(focus)

    def _view(self):
        return self.pages.currentWidget(), self.web_host.active_tab, self.core.playback.session

    def reopen_emergency_popups(self):
        """긴급 탈출 전에 열려 있던 Qt 메뉴(설정·재생 메뉴)를 다시 연다.

        창이 활성화된 뒤에 연다. 먼저 열면 메뉴가 전경 창이 되어 앱 창이 활성 창이 아니게 되고
        다시 연 메뉴 위에서 긴급 탈출 키를 받지 못한다. 그사이 화면이 바뀌었으면(트레이 대기열 보기 등) 열지 않는다.
        """
        if not self.isActiveWindow():
            self._reopen_when_active = bool(self._emergency_popups)
            return
        self._reopen_when_active = False
        popups, self._emergency_popups = self._emergency_popups, []
        if self._emergency_view != self._view():
            return
        for menu, offset, action in reversed(popups):
            if menu is self.settings_menu:
                point = self.web_host.settings_menu_point()
            else:
                # 조작 줄 단추에 딸린 메뉴(재생 메뉴·속도 목록)는 지금 단추 위치를 기준으로 다시 놓는다.
                point = self.playback_page.menu_anchor_point(menu)
                if point is None:
                    point = self.mapToGlobal(offset)
            menu.popup(point)
            if action is not None and action in menu.actions():
                menu.setActiveAction(action)

    def is_emergency_key(self, name):
        return self.core.command_for_key(name or "") == Command(CommandType.EMERGENCY_HIDE)

    def has_emergency_focus(self):
        """앱 창이나 이 창이 띄운 대화상자·경고가 활성 창이다. 메뉴·드롭다운 팝업은 활성 창을 바꾸지 않는다."""
        active = QApplication.activeWindow()
        while active is not None and active is not self:
            active = active.parentWidget()
        return active is self

    @property
    def worker(self):
        return self.library_page.worker

    def refresh(self):
        self.library_page.refresh()

    def show_status(self, text):
        """현재 페이지와 관계없이 창 아래에 작업 결과를 표시한다."""
        self.statusBar().showMessage(text)

    def scan(self, checked=False, *, operation=None):
        self.library_page.scan(checked, operation=operation)

    @property
    def playback_list(self):
        """다음에 시작할 재생의 목록. 출처 이름(playback_list_name)은 set_playback_list로 함께 정한다."""
        return self._playback_list

    @playback_list.setter
    def playback_list(self, video_ids):
        # 이름 없이 목록만 바꾸면 이전 목록의 이름이 새 목록에 남지 않게 지운다.
        self._playback_list, self.playback_list_name = video_ids, None

    def set_playback_list(self, video_ids, name=None):
        """재생을 시작할 목록과 출처 이름(예: 현재 결과). 이름은 무작위 이어 재생 범위 표시에 쓴다."""
        self.playback_list = video_ids
        self.playback_list_name = name

    def play(self, video_id, *, random_scope=None):
        self.set_playback_list(random_scope.video_ids if random_scope is not None and random_scope.kind == "list"
                               else self.library_page.visible_video_ids(), "현재 결과")
        self.play_video(video_id, random_scope=random_scope, new_playback=True)

    def random_play(self):
        """단축키·트레이의 범위는 항상 영상 전체이며 일반 재생 전환으로 기록을 마감한다."""
        from .random_play import NO_CANDIDATE_MESSAGE
        try:
            video_id = self.core.pick_random_video()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "무작위 재생 실패", str(error))
            return
        if video_id is None:
            self.show_status(NO_CANDIDATE_MESSAGE)
            if self.isFullScreen():
                self.playback_page.show_notice(NO_CANDIDATE_MESSAGE, reveal=True)
            return
        self.play_random_video(video_id)

    def play_random_video(self, video_id):
        """영상 전체 범위에서 고른 영상을 재생한다. 라이브러리 ▾ '영상 전체에서'도 같은 재생 목록을 쓴다."""
        self.set_playback_list(tuple(video.id for video in self.core.videos()), "영상 전체")
        self.play_video(video_id, random_scope=RandomPlayScope())

    def show_search(self):
        self.navigate_web_tab('search')

    def play_video(self, video_id, *, start=None, random_scope=None, new_playback=False):
        if self.tray.quitting:
            return
        page = self.logical_page()
        from_list = page is not self.playback_page
        if from_list:
            self._return_page = page
            # 취소 뒤에는 재생 덮개만 currentWidget으로 남는다. 출발 탭을 먼저 기억한다.
            if page is self.web_host:
                self.web_host.remember_playback_tab()
        self.web_host.cancel_return()
        try:
            self.stop_player()
            begins_playback = from_list or new_playback or self.core.playback.session is None
            source = self.playback_list if begins_playback or random_scope is not None else None
            self.load_player(video_id, self.core.switch_to(
                video_id, start=start, playback_video_ids=source, random_scope=random_scope,
                playback_source_name=self.playback_list_name if source is not None else None))
        except Exception as error:
            self.end_playback()
            self.pages.setCurrentWidget(self._return_page)
            QMessageBox.critical(self, "재생 실패", str(error))

    def load_player(self, video_id, start):
        location = self.core.playback_location(video_id)
        if self.logical_page() is self.web_host:
            self.web_host.remember_playback_tab()
        self.pages.setCurrentIndex(1)
        if self.player is None:
            self.player = self.create_player()
        self.player.play(location.path, start, subtitle=self.core.playback_subtitle(video_id))
        self.progress.duration = next(v.duration for v in self.core.videos() if v.id == video_id)
        self.refresh_highlights()
        self.position_timer.start()
        self.surface.setFocus()

    def end_playback(self):
        session = self.core.playback.session
        if session is not None and self.core.random_continuous_enabled:
            self.library_page.selected_id = session.video_id
        self.stop_player()
        self.core.end_playback()
        self.reel.shown = None
        self.playback_page.show_reel(None, False, {})

    def create_player(self):
        self.web_host.cancel_return()
        # 종료 중인 mpv와 새 mpv가 같은 HWND를 그리거나 해제하지 않게
        # 재생 표면 안에 엔진마다 별도 native 자식을 둔다.
        if self.surface.layout() is None:
            layout = QVBoxLayout(self.surface)
            layout.setContentsMargins(0, 0, 0, 0)
        surface = QWidget(self.surface)
        # 기본 QWidget이 처리하지 않은 마우스 이벤트는 ignore되어 부모 surface로 전파된다.
        surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.surface.layout().addWidget(surface)
        surface.show()
        try:
            player = self.player_factory(int(surface.winId()))
        except Exception:
            surface.deleteLater()
            raise
        self._player_surface = surface
        self.player_shutdown.release()
        return player

    def stop_player(self, *, report=True):
        self.position_timer.stop()
        # 닫는 엔진의 일시정지 상태는 읽지 않는다. 남은 보고는 기존처럼 처리한다.
        self._hold = None
        self._pending_random_eof = None
        if self.player:
            player, surface = self.player, self._player_surface
            prepare = getattr(player, 'prepare_close', None)
            self._stopping_player = True
            try:
                if prepare is not None:
                    prepare()
                else:
                    # prepare_close 없는 기존 주입 어댑터와의 호환 경로.
                    # 제품 및 공용 테스트 플레이어는 위 비동기 종료 경로를 쓴다.
                    player.close()
                if report:
                    self.sync_position()
            finally:
                self.player = None
                self._player_surface = None
                self._stopping_player = False
                if surface is not None:
                    self.surface.layout().removeWidget(surface)
                    if prepare is not None:
                        self.player_shutdown.retire(player, surface, deferred=self.web_host.return_pending)
                    else:
                        surface.hide()
                        surface.deleteLater()

    def _current_hold(self):
        """지금 엔진·재생 항목의 보류. 엔진이나 항목이 바뀌었으면 버린다."""
        hold = self._hold
        if hold is not None and (hold.player is not self.player
                                 or hold.session is not self.core.playback.session):
            hold = self._hold = None
        return hold

    def user_seeking(self):
        """사용자가 같은 항목 안에서 탐색을 시작했다.

        보류한 EOF는 탐색 전 위치의 것이므로 버리고, 탐색 완료 보고가 오기 전에는 보류 전환을 적용하지 않는다.
        엔진의 정지 해제가 탐색 완료 보고보다 먼저 관측될 수 있기 때문이다.
        """
        self._pending_random_eof = None
        if (hold := self._current_hold()) is not None:
            hold.eof, hold.seeking = False, True

    def sync_position(self):
        if self.player and self.core.playback.session is not None:
            player = self.player
            # 긴급 탈출로 멈춘 엔진은 사용자가 재개하기 전까지 영상·항목 끝 전환을 미룬다.
            # 위치·복습 보고는 그대로 반영한다.
            hold = self._current_hold()
            resumed = hold is not None and not self.player.paused
            # 상대 탐색과 Home/End 절대 탐색 모두 mpv 이벤트의 seeked 표시를 쓴다.
            session = self.core.playback.session
            for position, seeked in player.take_positions():
                self.core.playback.report(position, seeked=seeked)
                if seeked:
                    self._pending_random_eof = None
                if self.core.playback.session is not session:
                    break
                if self._stopping_player:
                    continue
                if hold is not None:
                    if seeked:
                        hold.eof = hold.seeking = False
                    continue
                self.core.advance_reel_if_due()
                if self.core.playback.session is not session:
                    break  # 자동 전환 뒤 이전 엔진의 나머지 보고는 버린다.
            eof = player.take_eof()
            if self._stopping_player:
                pass  # 마감 보고만 반영한다. 종료 중 EOF로 다음 영상을 열지 않는다.
            elif hold is not None and self.core.playback.session is session:
                if not hold.seeking:
                    hold.eof = hold.eof or eof
                if resumed and not hold.seeking:
                    # 남은 보고를 모두 반영한 뒤 미룬 전환을 이 항목에 적용한다.
                    self._hold = None
                    self.core.advance_reel_if_due(eof=hold.eof)
                    if hold.eof:
                        self._queue_random_eof(session)
            elif self.core.playback.session is session and eof:
                self.core.advance_reel_if_due(eof=True)
                self._queue_random_eof(session)
            self.core.save_viewings()
            position = self.core.playback.position
            opened = self.core.open_highlight_start
            range_keys = next((display_keys(row.keys) for row in self.core.key_bindings()
                               if row.command.kind == CommandType.RANGE_HIGHLIGHT), "키 미할당")
            self.playback_page.show_position(position, self.progress.duration, opened, range_keys)
            self._show_random_notice()
            return position
        return None

    def _show_random_notice(self):
        if (notice := self.core.take_random_continuous_notice()) is not None:
            self.show_status(notice)
            self.playback_page.show_notice(notice, reveal=True)

    def _queue_random_eof(self, session):
        if not self.core.random_continuous_enabled or self.core.playback.session is not session:
            return
        pending = (self.player, session)
        if self._pending_random_eof is not None:
            return
        self._pending_random_eof = pending

        def advance():
            if self._pending_random_eof is not pending:
                return
            self._pending_random_eof = None
            if self.player is not pending[0] or self.core.playback.session is not session:
                return
            if (hold := self._current_hold()) is not None:
                if not hold.seeking:
                    hold.eof = True
                return
            try:
                target = self.core.advance_random_if_due(session, eof=True)
                if target is not None:
                    self.play_video(target)
                self._show_random_notice()
            except Exception as error:
                self.playback_page.show_error(f"무작위 이어 재생 실패: {error}")

        # PgDn·목록 복귀가 위치를 먼저 동기화해도 같은 이벤트에서 EOF와 중복 전환하지 않는다.
        QTimer.singleShot(0, self, advance)

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
        self.web_host.show_page('library', returning=True)

    def back_to_list(self):
        if self.reel.shown is not None or self.core.reel_playback is not None:
            self.reel.open()
        else:
            self.web_host.return_from_playback()

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
        page = self.logical_page()
        if page is not self.playback_page:
            self._return_page = page
        self.sync_position()
        source = self.library_page.visible_video_ids()
        target = self.core.play_review_line(video_id, line_id, playback_video_ids=source,
                                            playback_source_name="현재 결과")
        try:
            if self.player and target.action == "seek":
                self.player.seek_to(target.start, resume=True)
            else:
                # 코어는 이미 새 시청을 시작했다. 이전 엔진의 남은 보고를 새 시청에 보내지 않는다.
                self.stop_player(report=False)
                self.reel.shown = None
                self.reel.update_label()
                self.set_playback_list(source, "현재 결과")
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
        # Qt 입력 이벤트는 WebEngine 입력란에도 전달된다. 조합 종료·초점 이동 때만 해제한다.
        if event.type() == QEvent.Type.InputMethod:
            self._composing_widget = watched if event.preeditString() else None
        elif event.type() == QEvent.Type.FocusOut and watched is self._composing_widget:
            self._composing_widget = None
        if (self.isActiveWindow() and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            settings = self.web_host.controllers.get('settings')
            if settings is not None and settings.capture_event(event):
                return True
        if (event.type() == QEvent.Type.KeyPress and self.has_emergency_focus()
                and self.is_emergency_key(key_name(event))):
            # 재생 화면, 웹 셸의 모든 탭, 열린 대화상자·메뉴·팝업, 입력·IME 조합 중에도 이 필터 한 곳에서 받는다.
            # 키 배치 화면의 키 캡처는 위에서 먼저 소비한다.
            if not event.isAutoRepeat():
                self.emergency_hide()
            return True
        if (event.type() != QEvent.Type.KeyPress or not self.isActiveWindow()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return super().eventFilter(watched, event)
        if self.core.command_for_key(key_name(event) or "") == Command(CommandType.RANDOM_PLAY):
            if not (self.web_host.dialogs.blocks_shell_actions or self._composing_widget is not None
                    or event.isAutoRepeat()):
                self.random_play()
            return True
        if (self.logical_page() is self.web_host and event.key() == Qt.Key.Key_F1
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            # 대화상자가 열려 있으면 웹에 넘긴다. 열린 키 안내는 F1로 닫히고 다른 대화상자에는 F1 동작이 없다.
            if self.web_host.dialogs.blocks_shell_actions:
                return super().eventFilter(watched, event)
            if not (self._composing_widget is not None or event.isAutoRepeat()):
                self.web_host.open_key_guide()
            return True
        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_8):
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
        handle_key = getattr(self.logical_page(), "handle_key", None)
        return handle_key(event) if callable(handle_key) else False

    def closeEvent(self, event):
        self.tray.close_window(event)
        if event.isAccepted():
            self._startup_scan_timer.stop()
