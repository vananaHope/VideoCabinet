"""트레이 어댑터와 창 숨기기·완전 종료 연결."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .app_version import DISPLAY_NAME
from .core import CommandType
from .key_display import display_keys

# scripts/app_icon.py가 손본 원본에서 만든 16·20·24·32px 커밋 산출물. 화면 배율에 맞는 크기를 Windows가 고른다.
# 테마나 작업 상태에 따라 바꾸지 않는다(긴급 탈출로 숨겼을 때도 같다).
TRAY_ICON = Path(__file__).with_name('tray.ico')


class TrayControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.quitting = False
        self._confirmed = False
        self._emergency_hidden = False
        self._emergency_focus = None
        self.icon = QSystemTrayIcon(QIcon(str(TRAY_ICON)), self)
        self.icon.setToolTip(f"{DISPLAY_NAME} · 자막 대기열")
        menu = QMenu(window)
        menu.addAction("열기", self.open)
        self.hide_action = menu.addAction("창 숨기기", self.hide_window)
        menu.addAction("무작위 재생", self.random_play)
        menu.addAction("대기열 보기", self.show_queue)
        menu.addSeparator()
        menu.addAction("완전 종료", self.quit)
        menu.aboutToShow.connect(self.refresh_menu)
        self.refresh_menu()
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self.activated)
        self.icon.messageClicked.connect(self.show_queue)
        self.icon.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.notify_completion)
        self.timer.start(750)

    def open(self):
        was_hidden = not self.window.isVisible()
        emergency = was_hidden and self._emergency_hidden
        self._emergency_hidden = False
        if emergency:
            # 긴급 탈출 전 화면을 그대로 보인다. 최대화 상태와 선택·스크롤·초점을 지킨다.
            self.window.show()
        else:
            self.window.showNormal()
        if was_hidden:
            # 숨어 있던 동안 바뀐 것(닫을 때 저장한 시청 상태·코어가 바꾼 선택, 긴급 탈출 중 끝난 검사·자막 등)만
            # 지금 탭에 반영한다(#265). 바뀐 것이 없으면 아무것도 보내지 않는다.
            self.window.web_host.reshow_active()
        self.window.raise_()
        self.window.activateWindow()
        if emergency:
            # 창과 함께 감춘 대화상자를 입력 내용 그대로 다시 보인다.
            self.window.web_host.dialogs.show_container()
        focus, self._emergency_focus = self._emergency_focus, None
        if emergency and focus is not None:
            from shiboken6 import isValid
            # 전체 화면 풀기와 숨기기로 옮겨 간 초점을 숨기기 전 위젯으로 되돌린다.
            if isValid(focus) and focus.isVisible() and focus.window() in (self.window, self.window.web_host.dialogs.container):
                focus.setFocus()
        if emergency:
            # 설정 메뉴처럼 창과 함께 닫힌 Qt 메뉴를 같은 자리에 다시 연다.
            self.window.reopen_emergency_popups()

    def refresh_menu(self):
        """메뉴를 열 때 지금 긴급 탈출 키와 창 상태를 반영한다."""
        keys = next(row.keys for row in self.core.key_bindings() if row.command.kind == CommandType.EMERGENCY_HIDE)
        self.hide_action.setText(f"창 숨기기 · {display_keys(keys)}" if keys else "창 숨기기")
        self.hide_action.setEnabled(self.window.isVisible())

    def hide_window(self):
        """트레이의 창 숨기기. 긴급 탈출 키와 같은 결과를 낸다."""
        if self.window.isVisible():
            self.window.emergency_hide()

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open()

    def show_queue(self):
        self.window.navigate_web_tab('queue')
        self.open()
        self.window.web_host.controllers['queue'].refresh()

    def random_play(self):
        self.open()
        # 긴급 탈출 복귀도 열기와 같은 경로를 쓴다. 열린 대화상자를 재생 화면으로 덮지 않는다.
        modal = QApplication.activeModalWidget()
        if self.window.web_host.dialogs.blocks_shell_actions or modal is not None:
            if modal is not None:
                modal.raise_()
                modal.activateWindow()
            return
        self.window.random_play()

    def hide_for_emergency(self, focus=None):
        """긴급 탈출. 창 X와 달리 재생 세션과 화면을 그대로 두고 첫 트레이 안내도 쓰지 않는다.

        focus는 복귀 때 되돌릴 숨기기 전 초점 위젯이다.
        """
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # 트레이가 없으면 숨긴 창을 다시 열 곳이 없으므로 작업표시줄로 내린다.
            # 창 모달 대화상자는 운영체제가 소유 창과 함께 내리고 복원한다.
            self.window.showMinimized()
            return
        self._emergency_hidden = True
        self._emergency_focus = focus
        # 재생 중 옮겨 띄운 대화상자는 별도 창이므로 함께 감추고, 열기에서 다시 보인다.
        self.window.web_host.dialogs.hide_for_emergency()
        self.window.hide()

    def notify(self, message):
        """창이 숨었을 때 알릴 일. 트레이 풍선으로 보인다."""
        self.icon.showMessage(DISPLAY_NAME, message)

    def notify_completion(self):
        counts = self.core.take_subtitle_queue_completion()
        if counts is not None:
            no_speech = f" · 말소리 없음 {counts.no_speech}개" if counts.no_speech else ""
            no_text = f" · 읽은 글자 없음 {counts.no_text}개" if counts.no_text else ""
            self.icon.showMessage(DISPLAY_NAME, "자막 대기열 처리를 마쳤습니다. "
                                  f"이번 처리: 완료 {counts.completed}개{no_speech}{no_text} · 실패 {counts.failed}개")

    def resume(self):
        self.window.subtitles.stopping = False
        self.window.onscreen_subtitles.stopping = False
        self.core.resume_subtitle_processing()
        self.window.subtitles.timer.start(500)
        self.window.onscreen_subtitles.timer.start(500)
        self.window.translations.timer.start(500)
        # 종료를 취소하면 종료 확인 중 미뤄 둔 감시 묶음을 이어서 검사한다.
        self.window.folder_watch.flush()

    def quit(self, *, confirmed=False):
        """완전 종료. confirmed면 받아쓰기 중 종료 확인을 다시 묻지 않는다(업데이트 설치 전에 이미 물었다)."""
        self.quitting = True
        self._confirmed = confirmed
        try:
            self.window.close()
        finally:
            self._confirmed = False

    def quit_blocker(self):
        """완전 종료를 막는 작업의 안내. 막는 작업이 없으면 빈 문자열."""
        if self.window.web_host.controllers['settings'].backups.busy:
            return "백업 작업이 끝난 뒤 완전 종료해 주세요."
        if self.window.worker and self.window.worker.isRunning():
            return "검사가 끝난 뒤 완전 종료해 주세요."
        return ""

    def restart(self):
        self.quit()
        if self.quitting:
            QApplication.instance().setProperty('backupRestartRequested', True)

    def close_window(self, event):
        window = self.window
        was_playing = window.logical_page() is window.playback_page
        try:
            if self.quitting:
                if blocker := self.quit_blocker():
                    raise RuntimeError(blocker)
                # 업데이트 설치 전 확인에서 이미 물었으면 받아쓰기 중 종료를 다시 묻지 않는다.
                stopped = window.subtitles.shutdown(confirm=False) if self._confirmed else window.subtitles.shutdown()
                if not stopped:
                    event.ignore()
                    self.quitting = False
                    self.resume()
                    return
                window.onscreen_subtitles.shutdown()
                window.translations.shutdown()
            elif not QSystemTrayIcon.isSystemTrayAvailable():
                raise RuntimeError("시스템 트레이를 사용할 수 없습니다. 설정(Ctrl+8)의 완전 종료를 이용하세요.")
            window.end_playback()
            window.web_host.cancel_return()
            window.player_shutdown.release()
            if self.quitting:
                window.player_shutdown.finish()
        except Exception as error:
            self.quitting = False
            self.resume()
            QMessageBox.warning(window, DISPLAY_NAME, f"창 닫기를 취소했습니다.\n{error}")
            event.ignore()
            return
        if self.quitting:
            # 끊긴 드라이브에서 감시 정지가 잠시 기다려도 보이지 않게 창과 아이콘을 먼저 숨긴다.
            window.hide()
            self.icon.hide()
            # 감시를 먼저 멈춘 뒤 미룬 검사 요청을 정리한다. 검사 작업자는 위에서 끝난 것을 확인했다.
            window.folder_watch.stop()
            # 진행 중인 업데이트 확인은 기다리지 않고 버린다.
            window.updates.shutdown()
            window.resolutions.shutdown()
            window.thumbnails.shutdown()
            self.timer.stop()
            QApplication.instance().removeEventFilter(window)
            window.native_dialogs.uninstall()
            event.accept()
            QApplication.instance().quit()
        else:
            self._emergency_hidden = False
            # 숨긴 뒤 page_changed가 showNormal()로 창을 다시 띄우지 않게 한다.
            window.set_playback_fullscreen(False)
            window.hide()
            if was_playing:
                window.web_host.set_tab(window.web_host.close_return_tab())
                window.web_host.focus_content()
            window.pages.setCurrentIndex(0)
            event.ignore()
            if self.core.acknowledge_tray_notice():
                self.icon.showMessage(DISPLAY_NAME, "트레이에서 계속 처리합니다. 트레이 메뉴에서 열거나 완전 종료할 수 있습니다.")
