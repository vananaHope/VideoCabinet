"""트레이 어댑터와 창 숨기기·완전 종료 연결."""

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QStyle, QSystemTrayIcon


class TrayControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.quitting = False
        self._confirmed = False
        self._emergency_hidden = False
        self._emergency_focus = None
        self.icon = QSystemTrayIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), self)
        self.icon.setToolTip("영상 라이브러리 · 자막 대기열")
        menu = QMenu(window)
        menu.addAction("열기", self.open)
        menu.addAction("무작위 재생", self.random_play)
        menu.addAction("대기열 보기", self.show_queue)
        menu.addSeparator()
        menu.addAction("완전 종료", self.quit)
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
            # 긴급 탈출 전 화면을 그대로 보인다. 최대화 상태를 지키고 목록도 새로 고치지 않는다.
            self.window.show()
        else:
            self.window.showNormal()
        host = self.window.web_host
        if was_hidden and not emergency and host.active_tab in ('library', 'recommend'):
            # 닫을 때 저장한 시청 상태를 복귀 시점에만 목록과 추천에 반영한다.
            host.controllers[host.active_tab].refresh()
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

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open()

    def show_queue(self):
        self.window.navigate_web_tab('queue')
        self.open()
        self.window.web_host.controllers['queue'].refresh()

    def random_play(self):
        self.open()
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
        self.icon.showMessage("영상 라이브러리", message)

    def notify_completion(self):
        counts = self.core.take_subtitle_queue_completion()
        if counts is not None:
            no_speech = f" · 말소리 없음 {counts.no_speech}개" if counts.no_speech else ""
            self.icon.showMessage("자막 대기열 처리 종료",
                                  f"이번 처리: 완료 {counts.completed}개{no_speech} · 실패 {counts.failed}개")

    def resume(self):
        self.window.subtitles.stopping = False
        self.core.resume_subtitle_processing()
        self.window.subtitles.timer.start(500)
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
                window.translations.shutdown()
            elif not QSystemTrayIcon.isSystemTrayAvailable():
                raise RuntimeError("시스템 트레이를 사용할 수 없습니다. 설정(Ctrl+8)의 완전 종료를 이용하세요.")
            window.end_playback()
        except Exception as error:
            self.quitting = False
            self.resume()
            QMessageBox.warning(window, "창 닫기 취소", str(error))
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
            was_playing = window.pages.currentWidget() is window.playback_page
            # 숨긴 뒤 page_changed가 showNormal()로 창을 다시 띄우지 않게 한다.
            window.set_playback_fullscreen(False)
            window.hide()
            if was_playing:
                window.web_host.set_tab(window.web_host.close_return_tab())
                window.web_host.focus_content()
            window.pages.setCurrentIndex(0)
            event.ignore()
            if self.core.acknowledge_tray_notice():
                self.icon.showMessage("영상 라이브러리", "트레이에서 계속 처리합니다. 트레이 메뉴에서 열거나 완전 종료할 수 있습니다.")
