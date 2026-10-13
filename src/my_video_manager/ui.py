"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .adapters import MpvPlayer
from .core import AppCore, CommandType
from .highlight_ui import HighlightList, HighlightProgress, timestamp


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent):
        super().__init__(parent)
        self.core = core

    def run(self):
        try:
            self.completed.emit(self.core.scan())
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, *, player_factory=MpvPlayer):
        super().__init__()
        self.core = core
        self.player = None
        self.player_factory = player_factory
        self._seek_pending = False
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(100)
        self.position_timer.timeout.connect(self.poll_position)
        self.worker = None
        self.setWindowTitle("영상 라이브러리")
        self.resize(1100, 720)
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)

        library = QWidget()
        layout = QVBoxLayout(library)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("감시 폴더 추가")
        self.scan_button = QPushButton("다시 검사")
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.scan_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        layout.addWidget(self.folders)
        layout.addWidget(QLabel("영상을 더블클릭하거나 방향키로 고른 뒤 Enter를 누르세요."))
        self.list = QListWidget()
        self.list.setIconSize(QSize(192, 108))
        self.list.setSpacing(6)
        layout.addWidget(self.list)
        self.status = QLabel("감시 폴더를 추가하면 자동으로 검사합니다.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.pages.addWidget(library)

        playback = QWidget()
        playback_layout = QVBoxLayout(playback)
        self.back_button = QPushButton("목록으로 (Esc)")
        self.back_button.clicked.connect(self.show_library)
        playback_layout.addWidget(self.back_button)
        self.surface = QWidget()
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.surface.setStyleSheet("background: black")
        self.surface.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        playback_layout.addWidget(self.surface, 1)
        self.progress = HighlightProgress()
        playback_layout.addWidget(self.progress)
        self.position_label = QLabel()
        playback_layout.addWidget(self.position_label)
        self.highlights_button = QPushButton("하이라이트 목록 · 시각·메모 편집")
        self.highlights_button.clicked.connect(self.show_highlights)
        playback_layout.addWidget(self.highlights_button)
        playback_layout.addWidget(QLabel("Enter 재생/일시정지 · ←/→ 5초 · , 3초 뒤로 · ↑/↓ 속도 ±0.25"))
        playback_layout.addWidget(QLabel("Insert 지점 · Delete 구간 시작/끝 · Home/End 이전/다음 · 노랑 지점 / 초록 구간 / 주황 열린 구간"))
        self.pages.addWidget(playback)

        self.add_button.clicked.connect(self.add_folder)
        self.scan_button.clicked.connect(self.scan)
        self.list.itemActivated.connect(self.play)
        QApplication.instance().installEventFilter(self)
        self.refresh()

    def refresh(self):
        self.folders.setText("감시 폴더: " + (", ".join(str(f.path) for f in self.core.watched_folders()) or "없음"))
        self.list.clear()
        for video in self.core.videos():
            item = QListWidgetItem(QIcon(str(video.thumbnail)), video.title)
            item.setData(Qt.ItemDataRole.UserRole, video.id)
            item.setSizeHint(QSize(300, 120))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setFocus()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "감시 폴더 선택")
        if folder:
            try:
                self.core.add_watched_folder(folder)
                self.scan()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "감시 폴더", str(error))

    def scan(self):
        if self.worker and self.worker.isRunning():
            return
        self.add_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.status.setText("영상을 검사하고 썸네일을 만드는 중입니다…")
        self.worker = ScanWorker(self.core, self)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(lambda error: self.status.setText(f"검사 실패: {error}"))
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def scan_completed(self, result):
        self.refresh()
        self.status.setText(f"영상 {result.added}개 등록 · 전체 {self.list.count()}개 · 오류 {len(result.issues)}개")
        if result.issues:
            dialog = QMessageBox(QMessageBox.Icon.Warning, "일부 파일 검사 실패",
                                 "나머지 영상은 등록했습니다. 자세히 보기에서 실패한 위치를 확인하세요.", parent=self)
            dialog.setDetailedText("\n".join(f"{i.path}: {i.message}" for i in result.issues))
            dialog.exec()

    def scan_finished(self):
        self.add_button.setEnabled(True)
        self.scan_button.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None

    def play(self, item):
        try:
            video_id = item.data(Qt.ItemDataRole.UserRole)
            location = self.core.playback_location(video_id)
            self.end_playback()
            self.pages.setCurrentIndex(1)
            if self.player is None:
                self.player = self.player_factory(int(self.surface.winId()))
            self.player.play(location.path)
            self.core.playback.start(video_id, 0)
            self._seek_pending = False
            self.progress.duration = next(v.duration for v in self.core.videos() if v.id == video_id)
            self.refresh_highlights()
            self.position_timer.start()
            self.surface.setFocus()
        except Exception as error:
            self.end_playback()
            self.pages.setCurrentIndex(0)
            QMessageBox.critical(self, "재생 실패", str(error))

    def end_playback(self):
        self.position_timer.stop()
        if self.player and self.core.playback.session is not None:
            self.sync_position()
        self.core.playback.end()
        if self.player:
            self.player.close()
            self.player = None

    def sync_position(self):
        if self.player and self.core.playback.session is not None:
            position = self.player.position()
            if position is not None:
                # mpv의 비동기 seek가 아직 이전 위치를 반환하면 표시만 유지한다.
                # 처음 바뀐 위치까지의 간격은 재생된 구간으로 세지 않는다.
                if not self._seek_pending or position != self.core.playback.position:
                    self.core.playback.report(position, seeked=self._seek_pending)
                    self._seek_pending = False
                self.progress.position = position
                self.progress.open_start = self.core.open_highlight_start
                self.progress.update()
                opened = self.core.open_highlight_start
                suffix = f" · 구간 시작 {timestamp(opened)} — Delete로 끝내기" if opened is not None else ""
                self.position_label.setText(f"{timestamp(position)} / {timestamp(self.progress.duration)}{suffix}")
            return position
        return None

    def poll_position(self):
        try:
            self.sync_position()
        except Exception as error:
            self.position_timer.stop()
            self.position_label.setText(f"재생 위치 확인 실패: {error}")

    def refresh_highlights(self):
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
        self.list.setFocus()

    def eventFilter(self, watched, event):
        if (event.type() != QEvent.Type.KeyPress or not self.isActiveWindow()
                or QApplication.activeModalWidget() is not None):
            return super().eventFilter(watched, event)
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if self.pages.currentIndex() == 0:
            if self.list.hasFocus() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item:
                    self.play(item)
                # 화면을 연 Enter가 부모로 전파되어 곧바로 pause를 실행하지 않게 소비한다.
                return True
            return False
        if event.key() == Qt.Key.Key_Escape:
            self.show_library()
            return True
        key = {Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Left: "Left",
               Qt.Key.Key_Right: "Right", Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down",
               Qt.Key.Key_Comma: ",", Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete",
               Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End"}.get(event.key(), event.text())
        command = self.core.command_for_key(key)
        if command and self.player:
            try:
                if self.core.is_highlight_command(command):
                    if event.isAutoRepeat() or self.sync_position() is None:
                        return True
                    target = self.core.execute_highlight_command(command)
                    if target is not None:
                        self.player.seek_to(target)
                        self._seek_pending = True
                    self.refresh_highlights()
                    self.sync_position()
                else:
                    if command.kind == CommandType.SEEK:
                        self.sync_position()
                    self.player.execute(command)
                    if command.kind == CommandType.SEEK:
                        self._seek_pending = True
            except Exception as error:
                QMessageBox.warning(self, "재생 조작 실패", str(error))
            return True
        return False

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status.setText("검사가 끝난 뒤 창을 닫아 주세요.")
            event.ignore()
            return
        try:
            self.end_playback()
        except Exception as error:
            QMessageBox.warning(self, "재생 종료 실패", str(error))
            event.ignore()
            return
        QApplication.instance().removeEventFilter(self)
        event.accept()
