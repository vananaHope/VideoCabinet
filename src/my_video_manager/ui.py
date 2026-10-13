"""화면은 입력을 코어에 전달하고 결과를 표시한다."""

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .adapters import MpvPlayer
from .core import AppCore, CommandType
from .subtitle_ui import SubtitleControls
from .translation_ui import TranslationControls
from .highlight_ui import HighlightList, HighlightProgress, timestamp
from .series_ui import SeriesEditor
from .search_ui import SearchDialog, SearchPreparation
from .tag_ui import TagEditor, TagManager
from .library_ui import LibraryControls
from .reel_ui import ReelControls
from .key_settings_ui import SettingsDialog, key_name
from .key_display import display_keys
from .tray import TrayControls
from .hidden_gems_ui import HiddenGemControls
from .thumbnail_ui import ThumbnailIcons

from .review_ui import ReviewDialog, review_button


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, core, parent, operation=None):
        super().__init__(parent)
        self.core = core
        self.operation = operation or core.scan

    def run(self):
        try:
            self.completed.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, *, player_factory=MpvPlayer):
        super().__init__()
        self.core = core
        self.player = None
        self.player_factory = player_factory
        self.playback_list = ()
        self._return_to_gems = False
        self.thumbnail_icons = ThumbnailIcons()
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(100)
        self.position_timer.timeout.connect(self.poll_position)
        self.worker = None
        self.subtitles = SubtitleControls(self)
        self.translations = TranslationControls(self)
        self.tray = TrayControls(self)
        self.menuBar().addAction("대기열 보기", self.tray.show_queue)
        self.menuBar().addAction("완전 종료", self.tray.quit)
        self.setWindowTitle("영상 라이브러리")
        self.resize(1100, 720)
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.settings_menu = self.menuBar().addMenu("설정(&S)")
        self.settings_menu.addAction("키 배치…", self.show_settings)

        library = QWidget()
        layout = QVBoxLayout(library)
        self.hidden_gems = HiddenGemControls(self)
        layout.addWidget(self.hidden_gems)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("감시 폴더 추가")
        self.scan_button = QPushButton("다시 검사")
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.subtitles.button())
        self.series_button = QPushButton("시리즈 편집")
        self.series_button.clicked.connect(self.show_series)
        buttons.addWidget(self.series_button)
        buttons.addWidget(self.translations.button())
        self.search_button = QPushButton("검색")
        self.search_button.clicked.connect(self.show_search)
        buttons.addWidget(self.search_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(review_button(self))
        self.library_controls = LibraryControls(self)
        layout.addWidget(self.library_controls)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        layout.addWidget(self.folders)
        tag_controls = QHBoxLayout()
        tag_controls.addWidget(QLabel("태그 필터"))
        self.tag_filter = QComboBox()
        self.tag_filter.setAccessibleName("라이브러리 태그 필터")
        self.tag_filter.currentIndexChanged.connect(self.filter_changed)
        tag_controls.addWidget(self.tag_filter, 1)
        self.tags_button = QPushButton("선택한 영상 태그")
        self.tags_button.clicked.connect(self.edit_video_tags)
        tag_controls.addWidget(self.tags_button)
        manage_tags = QPushButton("모든 태그 관리")
        manage_tags.clicked.connect(self.manage_tags)
        tag_controls.addWidget(manage_tags)
        layout.addLayout(tag_controls)
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
        self.back_button.clicked.connect(self.back_to_list)
        playback_layout.addWidget(self.back_button)
        self.reel_label = QLabel()
        self.reel_label.setWordWrap(True)
        self.reel_label.hide()
        playback_layout.addWidget(self.reel_label)
        playback_layout.addWidget(self.subtitles.button())
        playback_layout.addWidget(self.translations.button())
        playback_layout.addWidget(review_button(self))
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
        self.video_navigation_label = QLabel()
        self.video_navigation_label.setWordWrap(True)
        playback_layout.addWidget(self.video_navigation_label)
        self.key_help = QLabel()
        self.key_help.setWordWrap(True)
        playback_layout.addWidget(self.key_help)
        playback_layout.addWidget(QLabel("노랑 지점 / 초록 구간 / 주황 열린 구간"))
        self.refresh_key_help()
        self.pages.addWidget(playback)
        self.reel = ReelControls(self)
        buttons.addWidget(self.reel.button())

        self.add_button.clicked.connect(self.add_folder)
        self.scan_button.clicked.connect(self.scan)
        self.list.itemActivated.connect(self.play)
        QApplication.instance().installEventFilter(self)
        self.refresh()
        self.search_preparation = SearchPreparation(self.core, self)

    def refresh(self, *, focus_gems=None):
        if focus_gems is None:
            focus_gems = self.hidden_gems.list.hasFocus()
        snapshot = self.core.library_snapshot()
        self.thumbnail_icons.retain(video.thumbnail for video in snapshot.videos)
        self.hidden_gems.refresh(snapshot=snapshot)
        tag_id = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("모든 영상", None)
        for tag in self.core.tags():
            self.tag_filter.addItem(tag.name, tag.id)
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(tag_id)))
        self.tag_filter.blockSignals(False)
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        selected_row = 0
        self.folders.setText("감시 폴더: " + (", ".join(str(f.path) for f in self.core.watched_folders()) or "없음"))
        self.list.clear()
        series_labels = {vid: f"{s.name} · {index + 1}/{len(s.video_ids)}"
                         for s in snapshot.series for index, vid in enumerate(s.video_ids)}
        tag_id = self.tag_filter.currentData()
        videos = snapshot.videos
        statuses, tags_by_video = snapshot.statuses, snapshot.tags
        if tag_id is not None:
            videos = tuple(v for v in videos if any(t.id == tag_id for t in tags_by_video.get(v.id, ())))
        for row, video in enumerate(videos):
            status = statuses[video.id]
            label = "다 봄" if status.finished else f"보다 만 ({status.stopped_percent:.0f}%)" if status.abandoned else ""
            if status.favorite:
                label += " · 즐겨 보는 영상"
            if video.missing:
                label = "파일 없음" + (f" · {label}" if label else "")
            elif len(video.locations) > 1:
                label += (" · " if label else "") + f"위치 {len(video.locations)}개"
            if video.id in series_labels:
                label += ("\n" if label else "") + "시리즈: " + series_labels[video.id]
            item = QListWidgetItem(self.thumbnail_icons.get(video.thumbnail), video.title + (f"\n{label}" if label else ""))
            tags = tags_by_video.get(video.id, ())
            if tags:
                item.setText(item.text() + "\n태그: " + ", ".join(tag.name for tag in tags))
            item.setData(Qt.ItemDataRole.UserRole, video.id)
            item.setSizeHint(QSize(300, 120))
            self.list.addItem(item)
            if video.id == selected_id:
                selected_row = row
        if self.list.count():
            self.list.setCurrentRow(selected_row)
        target = self.hidden_gems.list if focus_gems and self.hidden_gems.list.count() else self.list
        target.setFocus()
        self.tags_button.setEnabled(self.list.count() > 0)

    def filter_changed(self):
        self.refresh()
        self.tag_filter.setFocus()

    def edit_video_tags(self):
        if item := self.list.currentItem():
            TagEditor(self.core, video_id=item.data(Qt.ItemDataRole.UserRole), parent=self).exec()
            self.refresh()

    def manage_tags(self):
        TagManager(self.core, self).exec()
        self.refresh()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "감시 폴더 선택")
        if folder:
            try:
                self.core.add_watched_folder(folder)
                self.scan()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "감시 폴더", str(error))

    def scan(self, checked=False, *, operation=None):
        if self.worker and self.worker.isRunning():
            return
        self.add_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.library_controls.setEnabled(False)
        self.status.setText("영상을 검사하고 썸네일을 만드는 중입니다…")
        self.worker = ScanWorker(self.core, self, operation)
        self.worker.completed.connect(self.scan_completed)
        self.worker.failed.connect(lambda error: self.status.setText(f"검사 실패: {error}"))
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def scan_completed(self, result):
        self.refresh()
        self.status.setText(f"영상 {result.added}개 등록 · 전체 {self.list.count()}개 · 안내 {len(result.issues)}개")
        if result.issues:
            dialog = QMessageBox(QMessageBox.Icon.Information, "검사·추가 안내",
                                 "\n".join(issue.message for issue in result.issues[:3]), parent=self)
            dialog.setDetailedText("\n".join(f"{i.path}: {i.message}" for i in result.issues))
            dialog.exec()

    def scan_finished(self):
        self.add_button.setEnabled(True)
        self.scan_button.setEnabled(True)
        self.library_controls.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None

    def play(self, item):
        self.playback_list = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()))
        self.play_video(item.data(Qt.ItemDataRole.UserRole))

    def show_search(self):
        dialog = SearchDialog(self.core, self, preparation=self.search_preparation)
        if dialog.exec() and dialog.selected_result is not None:
            self.playback_list = dialog.video_ids
            result = dialog.selected_result
            self.play_video(result.video_id, start=result.start)

    def play_video(self, video_id, *, start=None, from_gems=False):
        if self.pages.currentIndex() == 0:
            self._return_to_gems = from_gems
        try:
            self.stop_player()
            self.load_player(video_id, self.core.switch_to(video_id, start=start))
        except Exception as error:
            self.end_playback()
            self.pages.setCurrentIndex(0)
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
        self.reel_label.hide()

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
            self.progress.position = position
            self.progress.open_start = self.core.open_highlight_start
            self.progress.update()
            opened = self.core.open_highlight_start
            range_keys = next((display_keys(row.keys) for row in self.core.key_bindings()
                               if row.command.kind == CommandType.RANGE_HIGHLIGHT), "키 미할당")
            suffix = f" · 구간 시작 {timestamp(opened)} — {range_keys}: 끝내기" if opened is not None else ""
            self.position_label.setText(f"{timestamp(position)} / {timestamp(self.progress.duration)}{suffix}")
            return position
        return None

    def poll_position(self):
        try:
            self.sync_position()
            self.reel.sync()
        except Exception as error:
            self.position_timer.stop()
            self.position_label.setText(f"재생 위치 확인 실패: {error}")

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
        else:
            self.show_library()

    def show_series(self):
        SeriesEditor(self.core, self).exec()
        self.refresh()

    def refresh_key_help(self):
        navigation = (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO)
        rows = self.core.key_bindings()
        self.video_navigation_label.setText(" · ".join(f"{display_keys(row.keys)} {row.label}"
                                                      for row in rows if row.command.kind in navigation))
        self.key_help.setText(" · ".join(f"{display_keys(row.keys)} {row.label}"
                                        for row in rows if row.keys and row.command.kind not in
                                        (*navigation, CommandType.TOGGLE_REEL_REPEAT)))

    def show_settings(self):
        SettingsDialog(self.core, self).exec()
        self.refresh_key_help()
        self.reel.update_label()
        if self.pages.currentIndex() == 1:
            self.surface.setFocus()

    def show_review(self):
        session = self.core.playback.session
        item = self.list.currentItem()
        video_id = session.video_id if session else item.data(Qt.ItemDataRole.UserRole) if item else None
        if video_id is not None:
            ReviewDialog(self.core, video_id, self.review_jump, self.review_changed, self).exec()

    def review_jump(self, video_id, line_id):
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
                self.playback_list = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()))
                self.load_player(video_id, target.start)
        except Exception:
            self.end_playback()
            self.pages.setCurrentIndex(0)
            raise

    def review_changed(self, video_id):
        session = self.core.playback.session
        if self.player and session and session.video_id == video_id:
            self.player.set_subtitle(self.core.playback_subtitle(video_id))

    def eventFilter(self, watched, event):
        if (event.type() != QEvent.Type.KeyPress or not self.isActiveWindow()
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return super().eventFilter(watched, event)
        if self.pages.currentIndex() == 0:
            if event.modifiers() not in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
                return False
            if self.list.hasFocus() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item:
                    self.play(item)
                # 화면을 연 Enter가 부모로 전파되어 곧바로 pause를 실행하지 않게 소비한다.
                return True
            return False
        if self.pages.currentWidget() is self.reel.page:
            if event.key() == Qt.Key.Key_Escape:
                self.show_library()
                return True
            if self.reel.list.hasFocus() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.reel.play_selected(self.reel.list.currentItem())
                return True  # 목록을 연 Enter가 재생 화면까지 전파되어 멈추지 않게 한다.
            return False
        if event.key() == Qt.Key.Key_Escape:
            self.back_to_list()
            return True
        command = self.core.command_for_key(key_name(event) or "")
        if command and self.player:
            try:
                if command.kind in (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO):
                    if not event.isAutoRepeat():
                        self.sync_position()
                        target = self.core.execute_video_command(command, self.playback_list)
                        if target is not None:
                            self.play_video(target)
                        else:
                            self.reel.sync()
                elif self.core.is_highlight_command(command):
                    if event.isAutoRepeat() or self.sync_position() is None:
                        return True
                    self.reel.sync()
                    if self.core.playback.session is None:
                        return True
                    target = self.core.execute_highlight_command(command)
                    if target is not None:
                        self.player.seek_to(target)
                    self.reel.sync()
                    self.refresh_highlights()
                    self.sync_position()
                elif command.kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE:
                    if not event.isAutoRepeat():
                        self.translations.toggle()
                else:
                    if command.kind == CommandType.SEEK:
                        self.sync_position()
                        self.reel.sync()
                    if self.player:
                        self.player.execute(command)
            except Exception as error:
                QMessageBox.warning(self, "재생 조작 실패", str(error))
            return True
        return False

    def closeEvent(self, event):
        self.tray.close_window(event)
