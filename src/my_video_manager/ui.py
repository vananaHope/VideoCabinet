"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .adapters import MpvPlayer
from .core import AppCore, CommandType
from .subtitle_ui import SubtitleControls
from .highlight_ui import HighlightList, HighlightProgress, timestamp
from .series_ui import SeriesEditor


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
        self.playback_list = ()
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(100)
        self.position_timer.timeout.connect(self.poll_position)
        self.worker = None
        self.subtitles = SubtitleControls(self)
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
        buttons.addWidget(self.subtitles.button())
        self.series_button = QPushButton("시리즈 편집")
        self.series_button.clicked.connect(self.show_series)
        buttons.addWidget(self.series_button)
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
        playback_layout.addWidget(self.subtitles.button())
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
        playback_layout.addWidget(QLabel("Enter 재생/일시정지 · ←/→ 5초 · , 3초 뒤로 · ↑/↓ 속도 ±0.25 · / 자막 켜기/끄기"))
        playback_layout.addWidget(QLabel("PgUp/PgDn 이전/다음 영상 · 시리즈 안에서는 이전/다음 화"))
        playback_layout.addWidget(QLabel("Insert 지점 · Delete 구간 시작/끝 · Home/End 이전/다음 · 노랑 지점 / 초록 구간 / 주황 열린 구간"))
        self.pages.addWidget(playback)

        self.add_button.clicked.connect(self.add_folder)
        self.scan_button.clicked.connect(self.scan)
        self.list.itemActivated.connect(self.play)
        QApplication.instance().installEventFilter(self)
        self.refresh()

    def refresh(self):
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        selected_row = 0
        self.folders.setText("감시 폴더: " + (", ".join(str(f.path) for f in self.core.watched_folders()) or "없음"))
        self.list.clear()
        series_labels = {vid: f"{s.name} · {index + 1}/{len(s.video_ids)}"
                         for s in self.core.series() for index, vid in enumerate(s.video_ids)}
        for row, video in enumerate(self.core.videos()):
            status = self.core.viewing_status(video.id)
            label = "다 봄" if status.finished else f"보다 만 ({status.stopped_percent:.0f}%)" if status.abandoned else ""
            if status.favorite:
                label += " · 즐겨 보는 영상"
            if video.id in series_labels:
                label += ("\n" if label else "") + "시리즈: " + series_labels[video.id]
            item = QListWidgetItem(QIcon(str(video.thumbnail)), video.title + (f"\n{label}" if label else ""))
            item.setData(Qt.ItemDataRole.UserRole, video.id)
            item.setSizeHint(QSize(300, 120))
            self.list.addItem(item)
            if video.id == selected_id:
                selected_row = row
        if self.list.count():
            self.list.setCurrentRow(selected_row)
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
        self.playback_list = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()))
        self.play_video(item.data(Qt.ItemDataRole.UserRole))

    def play_video(self, video_id):
        try:
            self.end_playback()
            location = self.core.playback_location(video_id)
            start = self.core.resume_start(video_id)
            self.pages.setCurrentIndex(1)
            if self.player is None:
                self.player = self.player_factory(int(self.surface.winId()))
            self.core.playback.start(video_id, start)
            self.player.play(location.path, start, subtitle=self.core.playback_subtitle(video_id))
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
        if self.player:
            self.player.close()
            self.sync_position()
            self.player = None
        self.core.playback.end()

    def sync_position(self):
        if self.player and self.core.playback.session is not None:
            # 상대 탐색과 Home/End 절대 탐색 모두 mpv 이벤트의 seeked 표시를 쓴다.
            for position, seeked in self.player.take_positions():
                self.core.playback.report(position, seeked=seeked)
            self.core.save_viewings()
            position = self.core.playback.position
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
        self.refresh()

    def show_series(self):
        SeriesEditor(self.core, self).exec()
        self.refresh()

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
               Qt.Key.Key_Comma: ",", Qt.Key.Key_Slash: "/", Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete",
               Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End",
               Qt.Key.Key_PageUp: "PgUp", Qt.Key.Key_PageDown: "PgDn"}.get(event.key(), event.text())
        command = self.core.command_for_key(key)
        if command and self.player:
            try:
                if command.kind in (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO):
                    if not event.isAutoRepeat() and self.core.playback.session is not None:
                        target = self.core.adjacent_video(self.core.playback.session.video_id, self.playback_list,
                                                          forward=command.kind == CommandType.NEXT_VIDEO)
                        if target is not None:
                            self.play_video(target)
                elif self.core.is_highlight_command(command):
                    if event.isAutoRepeat() or self.sync_position() is None:
                        return True
                    target = self.core.execute_highlight_command(command)
                    if target is not None:
                        self.player.seek_to(target)
                    self.refresh_highlights()
                    self.sync_position()
                else:
                    if command.kind == CommandType.SEEK:
                        self.sync_position()
                    self.player.execute(command)
            except Exception as error:
                QMessageBox.warning(self, "재생 조작 실패", str(error))
            return True
        return False

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status.setText("검사가 끝난 뒤 창을 닫아 주세요.")
            event.ignore()
            return
        if not self.subtitles.shutdown():
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
