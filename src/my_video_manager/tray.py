"""트레이 어댑터와 창 숨기기·완전 종료 연결."""

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QPushButton, QStyle, QSystemTrayIcon

from .queue_ui import SubtitleQueueDialog


class TrayControls(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.core = window, window.core
        self.quitting = False
        self.dialog = None
        self.icon = QSystemTrayIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), self)
        self.icon.setToolTip("영상 라이브러리 · 자막 대기열")
        menu = QMenu(window)
        menu.addAction("열기", self.open)
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

    def button(self):
        button = QPushButton("자막 대기열 / 자동 규칙")
        button.clicked.connect(self.show_queue)
        return button

    def open(self):
        was_hidden = not self.window.isVisible()
        self.window.showNormal()
        if was_hidden:
            # 닫을 때 저장한 시청 상태를 복귀 시점에만 목록과 추천에 반영한다.
            self.window.show_library()
        self.window.raise_()
        self.window.activateWindow()

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open()

    def show_queue(self):
        self.open()
        if self.dialog is None:
            self.dialog = SubtitleQueueDialog(self.core, self.window)
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def notify_completion(self):
        counts = self.core.take_subtitle_queue_completion()
        if counts is not None:
            completed, failed = counts
            self.icon.showMessage("자막 대기열 처리 종료", f"이번 처리: 완료 {completed}개 · 실패 {failed}개")

    def resume(self):
        self.core.resume_subtitle_processing()
        self.window.subtitles.timer.start(500)
        self.window.translations.timer.start(500)

    def quit(self):
        self.quitting = True
        self.window.close()

    def close_window(self, event):
        window = self.window
        try:
            if self.quitting:
                if window.worker and window.worker.isRunning():
                    raise RuntimeError("검사가 끝난 뒤 완전 종료해 주세요.")
                if not window.subtitles.shutdown():
                    event.ignore()
                    self.quitting = False
                    self.resume()
                    return
                window.translations.shutdown()
            elif not QSystemTrayIcon.isSystemTrayAvailable():
                raise RuntimeError("시스템 트레이를 사용할 수 없습니다. 사이드바 설정(Ctrl+6)의 완전 종료를 이용하세요.")
            window.end_playback()
        except Exception as error:
            self.quitting = False
            self.resume()
            QMessageBox.warning(window, "창 닫기 취소", str(error))
            event.ignore()
            return
        if self.quitting:
            self.timer.stop()
            self.icon.hide()
            QApplication.instance().removeEventFilter(window)
            event.accept()
            QApplication.instance().quit()
        else:
            window.pages.setCurrentIndex(0)
            window.hide()
            if self.dialog:
                self.dialog.hide()
            event.ignore()
            if self.core.acknowledge_tray_notice():
                self.icon.showMessage("영상 라이브러리", "트레이에서 계속 처리합니다. 트레이 메뉴에서 열거나 완전 종료할 수 있습니다.")
