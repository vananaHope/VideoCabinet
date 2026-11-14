"""영상 중심 재생 페이지. 창 상태는 셸, 도메인 상태는 AppCore가 소유한다."""

from dataclasses import replace
import math
import time
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from .core import Command, CommandType
from .highlight_ui import HighlightProgress, PlaybackHighlights
from .onscreen_playback import OnScreenTranslationDisplay
from .time_display import timestamp
from .key_display import display_keys
from .qt_keys import key_name
from .playback_help import REEL_MEANINGS, PlaybackHelp
from .translation_kind import translation_task
from .theme import playback_stylesheet, playback_font, set_type_role
from .video_click import VideoClick, VideoClickJudge

# 속도 단추 목록. ↑/↓ 키는 이 목록과 관계없이 MIN~MAX_PLAYBACK_SPEED를 0.25씩 움직인다.
SPEED_CHOICES = (0.5, 0.75, 1, 1.25, 1.5, 1.75, 2)
# 조작 줄 위젯 사이 간격. 글자를 모두 줄여도 넘치면(최소 창의 전체 화면 모아보기 줄) 좁은 간격을 쓴다.
CONTROL_SPACING, TIGHT_CONTROL_SPACING = 8, 4
# 재생 상태 표시가 영상 위에 머무는 시간(초).
STATUS_SECONDS = 1.5
# 화면 번역 자막이 없는 영상에서 켜기/끄기를 누를 때의 안내. 켬·끔은 바뀌지 않아 재생 상태 표시가 아니다.
NO_ONSCREEN_TRANSLATION = "이 영상에는 화면 번역 자막이 없습니다"


def tool_button_menu_point(button, menu):
    """QToolButton이 자기 메뉴를 여는 자리(Qt positionMenu와 같은 규칙, 왼쪽에서 오른쪽 배치).

    아래에 들어갈 자리가 있으면 단추 아래, 없으면 단추 위에 열고, 가로는 화면 안으로 맞춘다.
    """
    size, rect = menu.sizeHint(), button.rect()
    screen = button.screen().availableGeometry()
    if button.mapToGlobal(QPoint(0, rect.bottom())).y() + size.height() <= screen.bottom():
        point = button.mapToGlobal(rect.bottomLeft())
    else:
        point = button.mapToGlobal(rect.topLeft() - QPoint(0, size.height()))
    return QPoint(max(screen.left(), min(point.x(), screen.right() - size.width())), point.y() + 1)


class CompactText:
    """조작 줄에서 좁은 창이면 짧은 글자(compact)로 바꿀 수 있는 위젯. fit_controls가 줄인다."""

    compact = False
    _labels = ("", "")

    @property
    def label(self):
        """좁은 창에서 줄이기 전의 글자."""
        return self._labels[0]

    def compact_saving(self):
        """짧은 글자로 바꾸면 줄어드는 폭. 글자를 바꿔 보지 않고 계산한다."""
        metrics = self.fontMetrics()
        return max(0, metrics.horizontalAdvance(self._labels[0]) - metrics.horizontalAdvance(self._labels[1]))

    def set_label(self, text, compact=None):
        self._labels = (text, compact or text)
        self._show_label()

    def set_compact(self, compact):
        self.compact = compact
        self._show_label()

    def _show_label(self):
        text = self._labels[self.compact]
        if text != self.text():
            self.setText(text)


class ControlButton(CompactText, QToolButton):
    """조작 줄 단추. 마우스로 눌러도 초점을 가져가지 않아 영상의 키 입력이 그대로 이어진다.

    Tab으로만 초점을 받는다.
    """

    def __init__(self, text, name):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(name)
        self.set_label(text)


class CompactLabel(CompactText, QLabel):
    pass


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
        self._reel = False
        # 화면 자막 영역을 끄는 덮개. 정하는 동안만 있다.
        self.region_selector = None
        # 화면 번역 자막의 켬·끔과 지금 엔진에 그린 띠. 재생 화면을 떠나면(end_playback) 처음 상태로 돌아간다.
        self._onscreen = OnScreenTranslationDisplay()
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
        set_type_role(self.title_label, 'section-title')
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.title_label, 1)
        self.reel_label = QLabel()
        self.reel_label.setProperty('playbackRole', 'muted')
        set_type_role(self.reel_label, 'body')
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
        self.progress.seek_requested.connect(self.seek)
        self.progress.setFixedHeight(30)
        bottom.addWidget(self.progress)
        # 조작 줄이 창 최소 너비를 넓히지 않게 하고, 좁으면 fit_controls가 단추 글자를 줄인다.
        self.controls = QWidget()
        self.controls.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(CONTROL_SPACING)
        self.list_button = ControlButton("목록으로", "목록으로")
        self.list_button.set_label("목록으로", "목록")
        self.list_button.clicked.connect(window.back_to_list)
        self.list_button.hide()  # 전체 화면에서 머리 줄 대신 쓴다.
        self.previous_button = self._command_button("⏮", "이전 영상", CommandType.PREVIOUS_VIDEO)
        self.pause_button = self._command_button("⏸", "일시정지", CommandType.TOGGLE_PAUSE)
        self.next_button = self._command_button("⏭", "다음 영상", CommandType.NEXT_VIDEO)
        self.position_label = QLabel("00:00:00.000 / 00:00:00.000")
        # 무작위 이어 재생 켜기/끄기와, 켜져 있을 때 옆에 보이는 범위 이름 단추. 모아보기 중에는 숨긴다.
        # 🔀 뒤 VS15(︎)는 색 그림 문자 대신 글자 모양으로 그리게 해, 다른 기호 단추처럼 켜짐 색이 보이게 한다.
        self.random_button = self._command_button("🔀︎", "무작위 이어 재생", CommandType.TOGGLE_RANDOM_CONTINUOUS)
        self.random_button.setCheckable(True)
        self.random_scope_button = ControlButton("", "무작위 이어 재생 범위")
        self.random_scope_button.setToolTip("무작위 이어 재생 범위 바꾸기")
        self.random_scope_button.clicked.connect(self.choose_random_scope)
        self.random_scope_button.hide()
        self._random_scope_shown = None
        # 하이라이트 모아보기 중에만 보인다(show_reel).
        self.reel_previous_button = self._command_button(
            "⇤", REEL_MEANINGS[CommandType.PREVIOUS_HIGHLIGHT], CommandType.PREVIOUS_HIGHLIGHT)
        self.reel_next_button = self._command_button(
            "⇥", REEL_MEANINGS[CommandType.NEXT_HIGHLIGHT], CommandType.NEXT_HIGHLIGHT)
        self.reel_repeat_button = self._command_button("↻ 반복 꺼짐", "모아보기 반복", CommandType.TOGGLE_REEL_REPEAT)
        self.reel_repeat_button.setCheckable(True)
        self.reel_repeat_button.set_label("↻ 반복 꺼짐", "↻")
        self.reel_buttons = (self.reel_previous_button, self.reel_next_button, self.reel_repeat_button)
        for button in self.reel_buttons:
            button.hide()
        self.point_button = self._command_button("◆ 지점", "지점 하이라이트 추가", CommandType.POINT_HIGHLIGHT)
        self.point_button.set_label("◆ 지점", "◆")
        self.range_button = self._command_button("【 구간 시작", "구간 하이라이트 시작", CommandType.RANGE_HIGHLIGHT)
        self.range_button.setCheckable(True)
        self.range_button.set_label("【 구간 시작", "【")
        self.open_range_label = CompactLabel()
        self.open_range_label.setAccessibleName("열린 구간 시작")
        self.open_range_label.hide()
        # 누르면 목록을 연다. 목록 밖 속도(↑/↓ 키)도 단추에는 그 값 그대로 보인다.
        self.speed_button = ControlButton("속도 1×", "재생 속도 1×")
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_menu = QMenu(self.speed_button)
        for speed in SPEED_CHOICES:
            action = self.speed_menu.addAction(f"{speed:g}×", lambda checked=False, value=speed: self.choose_speed(value))
            action.setCheckable(True)
        self.speed_menu.aboutToShow.connect(self.check_current_speed)
        self.speed_menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.focus_content))
        self.speed_button.setMenu(self.speed_menu)
        self.subtitles_button = self._command_button("자막 켜짐", "자막 표시", CommandType.TOGGLE_SUBTITLES)
        self.subtitles_button.setCheckable(True)
        self.subtitles_button.setChecked(True)
        # 화면 번역 자막이 없는 영상에서도 보이고 눌린다(꺼짐 모양, 누르면 안내). 영상마다 조작 줄이 밀리지 않는다.
        self.onscreen_button = self._command_button(
            "화면 번역", "화면 번역 자막", CommandType.TOGGLE_ONSCREEN_TRANSLATION)
        self.onscreen_button.setCheckable(True)
        # 가장 좁은 줄(1100 폭 전체 화면의 모아보기·무작위 범위)에도 들어가는 한 글자. 툴팁·접근성 이름은 그대로다.
        self.onscreen_button.set_label("화면 번역", "T")
        self.subtitle_language_button = self._command_button(
            "자막 없음", "자막 종류 자막 없음", CommandType.TOGGLE_SUBTITLE_LANGUAGE)
        self.subtitle_work_label = QLabel()
        self.subtitle_work_label.setProperty('playbackRole', 'muted')
        set_type_role(self.subtitle_work_label, 'body')
        self.subtitle_work_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.key_guide_button = ControlButton("⌨", "키 안내")
        self.key_guide_button.setCheckable(True)
        self.key_guide_button.setToolTip("키 안내 · F1")
        self.key_guide_button.clicked.connect(self.toggle_help)
        self.fullscreen_button = self._command_button("⛶", "전체 화면", CommandType.TOGGLE_FULLSCREEN)
        self.fullscreen_button.setCheckable(True)
        for button in (self.previous_button, self.pause_button, self.next_button, self.random_button, *self.reel_buttons,
                       self.point_button, self.range_button, self.key_guide_button, self.fullscreen_button):
            button.setProperty('playbackRole', 'symbol')
        for widget in (self.list_button, self.previous_button, self.pause_button, self.next_button,
                       self.position_label, self.random_button, self.random_scope_button, *self.reel_buttons, self.point_button, self.range_button,
                       self.open_range_label, self.speed_button, self.subtitles_button, self.onscreen_button,
                       self.subtitle_language_button):
            row.addWidget(widget)
        row.addWidget(self.subtitle_work_label, 1)
        row.addWidget(self.key_guide_button)
        row.addWidget(self.fullscreen_button)
        # 단추·Tab 순서와 같다. 이 단추에 초점이 있어도 재생 키는 그대로 동작한다.
        self.control_buttons = (self.list_button, self.previous_button, self.pause_button, self.next_button,
                                self.random_button, self.random_scope_button, *self.reel_buttons, self.point_button, self.range_button, self.speed_button,
                                self.subtitles_button, self.onscreen_button, self.subtitle_language_button,
                                self.key_guide_button, self.fullscreen_button)
        # 창이 좁을 때 이 순서대로 짧은 글자로 바꾼다. 하이라이트·속도 단추가 먼저 아이콘·값만 남기고, 다음에 범위 이름을 줄인다.
        # 모아보기 단추가 더해진 가장 넓은 줄은 열린 구간 표시·메뉴 단추와 전체 화면의 목록 단추까지 줄여야 들어간다.
        self.menu_button = ControlButton("메뉴 ⋯", "재생 작업 메뉴")
        self.menu_button.set_label("메뉴 ⋯", "⋯")
        self.compact_order = [self.point_button, self.range_button, self.speed_button, self.random_scope_button,
                              self.reel_repeat_button,
                              self.fullscreen_button, self.subtitle_language_button, self.subtitles_button,
                              self.onscreen_button, self.open_range_label, self.menu_button, self.list_button]
        self.menu_button.setToolTip("재생 작업 메뉴 · 키 안내는 F1")
        self.menu_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.menu_button)
        for label, callback in (
            ("하이라이트 목록 · 시각·메모 편집", window.show_highlights),
            ("자막 만들기 / 원어 지정", window.subtitles.request),
            ("화면 자막 영역 정하기", self.choose_onscreen_region),
            ("번역 CLI / 재시도", window.translations.settings),
            ("자막 검수 / SRT 내보내기", window.show_review),
        ):
            self.menu.addAction(label, lambda checked=False, action=callback: self.run_action(action))
        # Alt+S와 같은 설정 메뉴. 이 메뉴가 닫히고 초점이 영상으로 돌아간 다음에 연다.
        self.menu.addAction("설정 · Alt+S", lambda: QTimer.singleShot(0, window.show_fullscreen_settings_menu))
        self.menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.focus_content))
        self.menu_button.setMenu(self.menu)
        row.addWidget(self.menu_button)
        bottom.addWidget(self.controls)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setProperty('playbackRole', 'warning')
        set_type_role(self.message_label, 'body')
        self.message_label.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.setInterval(5000)
        self.notice_timer.timeout.connect(lambda: self.show_notice(""))
        bottom.addWidget(self.message_label)
        self._layout.addWidget(self.bottom_bar)
        self.help_panel = PlaybackHelp(window)
        self.help_panel.close_requested.connect(self.close_help)
        self.bar_timer = QTimer(self)
        self.bar_timer.setSingleShot(True)
        self.bar_timer.setInterval(2500)
        self.bar_timer.timeout.connect(self.hide_temporary_bar)
        self.pointer_timer = QTimer(self)
        self.pointer_timer.setInterval(150)
        self.pointer_timer.timeout.connect(self.check_pointer)
        self._pointer_position = QCursor.pos()
        # 한 번 클릭은 재생/일시정지, 두 번 클릭은 전체 화면. 한 번 클릭은 판정 시간이 지나야 실행한다.
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        # 기본 CoarseTimer는 판정 시간보다 몇 ms 일찍 깨울 수 있다. 판정기도 일찍 깨면 다시 기다린다.
        self.click_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.clicks = VideoClickJudge(
            QApplication.styleHints().mouseDoubleClickInterval() / 1000, clock=time.perf_counter,
            timer=SimpleNamespace(start=lambda seconds: self.click_timer.start(math.ceil(seconds * 1000)),
                                  stop=self.click_timer.stop),
            on_click=self.video_clicked)
        self.click_timer.timeout.connect(self.clicks.expire)
        self._surface_button_down = False
        # 메뉴 등 팝업이 마지막으로 받은 누름의 시각. Qt는 팝업 밖 누름으로 팝업을 닫은 뒤
        # 같은 시각을 단 누름을 아래 위젯에 다시 보내므로(replay), 그 누름은 클릭으로 세지 않는다.
        self._popup_press_timestamp = None
        self.details_timer = QTimer(self)
        self.details_timer.setInterval(1000)
        self.details_timer.timeout.connect(self.refresh_details)
        self.details_timer.start()
        window.statusBar().messageChanged.connect(self.show_notice)
        QApplication.instance().installEventFilter(self)
        order = (self.surface, *self.control_buttons, self.menu_button, self.back_button,
                 self.highlights_button, self.highlights_panel.list, self.surface)
        for first, second in zip(order, order[1:]):
            QWidget.setTabOrder(first, second)
        self.refresh_key_help()

    def _command_button(self, text, name, kind):
        button = ControlButton(text, name)
        button.command = Command(kind)
        button.clicked.connect(lambda: self.press(button.command))
        return button

    def press(self, command):
        """조작 줄 단추. 키와 같은 명령을 실행하고 바뀐 상태를 바로 보여 준다."""
        self.run_command(command)
        self.update_controls()

    def choose_random_scope(self):
        """범위 이름 단추. 범위 고르기 창(웹 대화상자)을 열고, 고른 범위는 다음 영상부터 쓴다."""
        from .web_dialogs_entries import RandomScopeChooser
        if self.core.random_continuous_enabled:
            self.run_action(lambda: RandomScopeChooser(self.core, self.shell).exec())

    def choose_onscreen_region(self):
        """재생 작업 메뉴의 '화면 자막 영역 정하기'. 지금 장면에서 멈추고 그 위에서 사각형을 끈다."""
        from .onscreen_region_ui import RegionSelector, frame_image
        player, session = self.shell.player, self.core.playback.session
        if player is None or session is None or self.region_selector is not None:
            return
        try:
            player.pause()
            self.shell.sync_position()
        except Exception as error:
            self.show_error(f"일시정지 실패: {error}")
            return
        self.update_controls()
        try:
            image = frame_image(player.video_frame())
        except Exception:
            image = None  # 장면을 못 받아도 영상 화면비 위에서 영역을 정할 수 있다.
        video = self.core.video(session.video_id)
        aspect = (video.width / video.height if video.width and video.height
                  else self.surface.width() / max(1, self.surface.height()))
        video_id = session.video_id
        selector = self.region_selector = RegionSelector(self.surface, image, aspect,
                                                         self.core.onscreen_subtitle_regions(video_id))
        # 대화상자는 끌기·키 입력 처리가 끝난 뒤에 연다.
        selector.selected.connect(lambda rect: QTimer.singleShot(0, lambda: self.confirm_onscreen_region(video_id, rect)))
        selector.changed.connect(lambda region, rect: QTimer.singleShot(
            0, lambda: self.confirm_onscreen_region(video_id, rect, region.id)))
        selector.delete_requested.connect(lambda region: QTimer.singleShot(
            0, lambda: self.confirm_onscreen_region_delete(video_id, region.id)))
        selector.cancelled.connect(self.close_region_selector)
        selector.show()
        selector.raise_()
        selector.setFocus()

    def confirm_onscreen_region(self, video_id, rect, region_id=None):
        """읽을 언어를 웹 업무 대화상자로 확인한다. 확인하면 자막 대기열에 화면 자막 만들기가 들어간다.

        region_id가 있으면 그 영역을 고친다(자리·크기·읽을 언어). 확인하든 취소하든 영역 정하기를 끝낸다.
        """
        from .web_dialogs_entries import OnScreenRegionDialog
        if self.region_selector is None:
            return
        try:
            OnScreenRegionDialog(self.core, video_id, rect, self.shell, region_id=region_id).exec()
        finally:
            self.close_region_selector()

    def confirm_onscreen_region_delete(self, video_id, region_id):
        """고른 영역을 지울지 웹 확인 창으로 묻는다. 확인하든 취소하든 영역 정하기를 끝낸다."""
        from .web_dialogs_entries import OnScreenRegionDeleteDialog
        if self.region_selector is None:
            return
        try:
            OnScreenRegionDeleteDialog(self.core, video_id, region_id, self.shell).exec()
        finally:
            self.close_region_selector()

    def close_region_selector(self):
        selector, self.region_selector = self.region_selector, None
        if selector is not None:
            self.surface.removeEventFilter(selector)
            selector.hide()
            selector.deleteLater()
            self.focus_content()

    def current_speed(self):
        options = getattr(self.shell.player, "playback_options", None)
        return options()[0] if options else 1

    def check_current_speed(self):
        speed = self.current_speed()
        for action, choice in zip(self.speed_menu.actions(), SPEED_CHOICES):
            action.setChecked(choice == speed)

    def choose_speed(self, speed):
        """속도 목록의 값. ↑/↓ 키와 같은 속도 바꾸기 명령으로 지금 속도와의 차이만큼 바꾼다."""
        if self.shell.player:
            self.press(Command(CommandType.CHANGE_SPEED, speed - self.current_speed()))

    def menu_anchor_point(self, menu):
        """조작 줄 단추에 딸린 메뉴를 지금 단추 위치에서 열 전역 좌표. 이 페이지의 메뉴가 아니면 None.

        긴급 탈출 뒤 메뉴를 다시 열 때 쓴다. 숨기기 전과 창 상태(전체 화면)가 달라도 새로 열 때와 같은 자리에 놓인다.
        """
        if menu is self.menu:
            # 키보드로 여는 재생 메뉴(handle_key)와 같은 기준이다.
            return self.menu_button.mapToGlobal(self.menu_button.rect().topRight())
        if menu is self.speed_menu:
            return tool_button_menu_point(self.speed_button, menu)
        return None

    def fit_controls(self):
        """조작 줄이 넘치면 compact_order 순서대로 단추 글자를 짧게 바꾸고, 그래도 넘치면 간격을 좁힌다.

        결과가 같으면 글자·간격을 건드리지 않으므로, 글자·표시가 바뀔 때마다 불러도 레이아웃 요청이 되풀이되지 않는다.
        """
        row = self.controls.layout()
        gaps = max(0, sum(1 for index in range(row.count())
                          if row.itemAt(index).widget() and not row.itemAt(index).widget().isHidden()) - 1)
        # 지금 줄인 단추와 좁힌 간격을 모두 되돌렸을 때 넘치는 폭에서 시작한다.
        excess = (row.minimumSize().width() - self.controls.width()
                  + sum(button.compact_saving() for button in self.compact_order
                        if button.compact and not button.isHidden())
                  + (CONTROL_SPACING - row.spacing()) * gaps)
        for button in self.compact_order:
            saving = 0 if button.isHidden() else button.compact_saving()
            compact = excess > 0 and saving > 0
            if compact:
                excess -= saving
            button.set_compact(compact)
        spacing = TIGHT_CONTROL_SPACING if excess > 0 else CONTROL_SPACING
        if row.spacing() != spacing:
            row.setSpacing(spacing)

    def focus_content(self):
        if self.isVisible() and QApplication.activeModalWidget() is None:
            (self.region_selector or self.surface).setFocus()

    def seek(self, position=None, *, command=None):
        """마우스와 키보드 탐색은 같은 위치 보고·모아보기 동기화를 거친다."""
        window = self.shell
        if self.region_selector is not None:
            return  # 영역을 정하는 동안 진행 막대로도 장면을 바꾸지 않는다.
        try:
            window.sync_position()
            window.reel.sync()
            if window.player:
                window.user_seeking()
                if command is not None:
                    window.player.execute(command)
                else:
                    window.player.seek_to(position)
        except Exception as error:
            QMessageBox.warning(window, "재생 조작 실패", str(error))

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
        self._keys = bindings
        for button, name in ((self.pause_button, '재생/일시정지'), (self.subtitles_button, '자막 켜기/끄기'),
                             (self.fullscreen_button, '전체 화면 켜기/끄기')):
            button.setToolTip(f'{name} · {bindings[button.command.kind]}')
        self.update_reel_buttons()
        # 기본 키가 없는 명령이라 키가 없으면 툴팁은 기능 이름만 보인다.
        random_keys = next(row.keys for row in self.core.key_bindings()
                           if row.command.kind == CommandType.TOGGLE_RANDOM_CONTINUOUS)
        self.random_button.setToolTip('무작위 이어 재생 켜기/끄기'
                                      + (f' · {display_keys(random_keys)}' if random_keys else ''))
        self.point_button.setToolTip(f'지점 하이라이트 추가 · {bindings[CommandType.POINT_HIGHLIGHT]}')
        self.update_range_button()
        # 속도는 올리기·내리기 두 명령이라 명령 종류 하나로 묶은 bindings 대신 명령마다 읽는다.
        speed_keys = {row.command.amount > 0: display_keys(row.keys) for row in self.core.key_bindings()
                      if row.command.kind == CommandType.CHANGE_SPEED}
        self.speed_button.setToolTip(f'재생 속도 · 올리기 {speed_keys.get(True, "키 미할당")}'
                                     f' / 내리기 {speed_keys.get(False, "키 미할당")}')
        # Esc는 바꿀 수 없는 목록 복귀 키다. 이름은 모아보기 중 표시('모아보기 목록')를 따른다.
        self.list_button.setToolTip(f'{self.list_button.label} · Esc')
        self.update_subtitle_language_tooltip()
        self.update_onscreen_button()
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
        if self.region_selector is not None:
            return  # 영역을 정하는 동안 하이라이트 목록으로도 장면을 바꾸지 않는다.
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
                window.set_playback_list(window.library_page.visible_video_ids(), "현재 결과")
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
            self.key_guide_button.setChecked(True)
            self.refresh_key_help()
            self.help_panel.place_over(self.surface)
            self.help_panel.show()
            self.help_panel.raise_()

    def close_help(self):
        self._help_requested = False
        self.key_guide_button.setChecked(False)
        self.help_panel.hide()

    def set_fullscreen(self, enabled):
        self.fullscreen = enabled
        self.header.setVisible(not enabled)
        self.list_button.setVisible(enabled)
        self.fullscreen_button.setChecked(enabled)
        self.fullscreen_button.set_label("⛶ 전체 화면 끄기" if enabled else "⛶", "⛶")
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
            if (self.progress.dragging or self.menu.isVisible() or self.speed_menu.isVisible()
                    or self.bottom_bar.isAncestorOf(QApplication.focusWidget())):
                self.bar_timer.start()
            elif not self._error:
                self.bottom_bar.hide()

    def _accepts_click(self, player):
        return (player is not None and player is self.shell.player and self.isVisible()
                and QApplication.activeModalWidget() is None)

    def press_video(self, timestamp):
        """영상을 누름. 키 안내·메뉴가 열려 있었으면 그것만 닫고, 아니면 클릭 판정에 넘긴다."""
        player = self.shell.player
        if not self._accepts_click(player):
            return
        if (QApplication.activePopupWidget() is not None or timestamp == self._popup_press_timestamp
                or self._help_requested):
            self.clicks.cancel()
            while (popup := QApplication.activePopupWidget()) is not None and popup.close():
                pass
            self.close_help()
            return
        self.focus_content()
        # 클릭은 누름을 받은 엔진에 속한다. 엔진이 바뀌면(다음 영상, 목록 복귀 뒤 재생) 이전 누름과 잇지 않고,
        # 판정 시간 사이에 엔진이 바뀐 클릭은 실행하지 않는다.
        self.clicks.press(time.perf_counter(), player)

    def reset_clicks(self):
        """대기 중인 한 번 클릭과 누름 상태를 버린다. 창을 숨기거나 최소화하거나 목록으로 돌아갈 때 부른다.

        숨긴 사이 남은 클릭이 복원 뒤 실행되면 긴급 탈출로 멈춘 재생을 다시 틀 수 있다.
        """
        self.clicks.cancel()
        self._surface_button_down = False
        self._popup_press_timestamp = None

    def video_clicked(self, click, player):
        if not self._accepts_click(player) or QApplication.activePopupWidget() is not None:
            return  # 판정 시간 사이에 영상이 바뀌었거나 목록·메뉴·창으로 옮겨 갔다.
        self.press(Command(CommandType.TOGGLE_FULLSCREEN if click == VideoClick.DOUBLE
                           else CommandType.TOGGLE_PAUSE))

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget)
                and watched.windowType() == Qt.WindowType.Popup):
            self._popup_press_timestamp = event.timestamp()
        if watched is self.surface and kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                                                QEvent.Type.MouseButtonRelease):
            # 비활성(WS_DISABLED) mpv 창의 입력은 엔진별 native QWidget에 도착하고,
            # 기본 QWidget의 ignore 전파로 부모 surface의 이 필터까지 온다.
            # Windows는 두 번째 누름을 DblClick으로만 보내고, 다른 플랫폼은 Press 뒤에 DblClick을 더 보낸다.
            # Press 뒤 떼기 전에 온 DblClick은 같은 누름이라 세지 않고, 한 번/두 번은 판정기가 시각으로 가른다.
            if event.button() == Qt.MouseButton.LeftButton:
                if kind == QEvent.Type.MouseButtonRelease:
                    self._surface_button_down = False
                elif kind == QEvent.Type.MouseButtonPress or not self._surface_button_down:
                    self._surface_button_down = True
                    self.press_video(event.timestamp())
        if watched is self.controls and kind in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            # 창 크기뿐 아니라 단추 글자·표시가 바뀌어도 다시 맞춘다.
            self.fit_controls()
        if watched is self.surface and kind == QEvent.Type.Resize and self._help_requested:
            QTimer.singleShot(0, lambda: self.help_panel.place_over(self.surface))
        if ((watched is self or watched is self.shell) and kind == QEvent.Type.Hide
                or watched is self.shell and kind == QEvent.Type.WindowStateChange and self.shell.isMinimized()):
            self.reset_clicks()
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

    def show_notice(self, text, *, reveal=False):
        self.notice_timer.stop()
        self.message_label.setText(self._error or text)
        self.message_label.setVisible(bool(self._error or (text and (reveal or not self.fullscreen))))
        if reveal and text:
            self.reveal_bar()
        if text and not self._error:
            self.notice_timer.start()

    def refresh_details(self):
        if not self.isVisible() or self.core.playback.session is None:
            return
        video_id = self.core.playback.session.video_id
        self._details = self.core.library_details(video_id)
        self._random_scope_shown = None  # 태그 이름이 바뀌었을 수 있어 범위 이름을 다시 읽는다.
        # 영역을 고치거나 지워 화면 번역 자막이 사라진 것도 이 주기로 읽는다.
        self.refresh_onscreen_translation()
        self.refresh_highlights()
        self.update_controls()

    def update_subtitle_language_tooltip(self):
        task = translation_task(self._details.spoken_language if self._details else None)
        self.subtitle_language_button.setToolTip(
            f'원어 / {task.subtitle_label} 전환 · {self._keys[CommandType.TOGGLE_SUBTITLE_LANGUAGE]}')

    def update_onscreen_button(self):
        """화면 번역 단추는 자막 단추처럼 눌림으로 켬을 보인다. 화면 번역 자막이 없는 영상은 꺼짐 모양이다."""
        display = self._onscreen
        self.onscreen_button.setChecked(display.shown)
        self.onscreen_button.setAccessibleName("화면 번역 자막 " + ("켜짐" if display.shown else "꺼짐"))
        keys = self._keys[CommandType.TOGGLE_ONSCREEN_TRANSLATION]
        self.onscreen_button.setToolTip(f"화면 번역 자막 켜기/끄기 · {keys}" if display.available
                                        else f"{NO_ONSCREEN_TRANSLATION} · {keys}")

    def refresh_onscreen_translation(self):
        """지금 영상의 화면 번역 자막을 다시 읽어 그린다(새 영상, 보는 중 완성·검수·영역 변경).

        보는 중에 없음에서 있음으로 바뀌면 켬 상태일 때 바로 그리고 재생 상태 표시로 알린다.
        """
        session = self.core.playback.session
        video_id = session.video_id if session else None
        regions = self.core.onscreen_translation_regions(video_id) if video_id is not None else None
        previous = self._onscreen
        self._onscreen = replace(previous, video_id=video_id, regions=regions)
        self.draw_onscreen_translation()
        self.update_onscreen_button()
        completed = video_id is not None and previous.video_id == video_id and not previous.available
        if completed and self._onscreen.shown and self.shell.player is not None:
            show_status = getattr(self.shell.player, "show_status", None)
            if show_status:
                show_status("화면 번역 자막을 켰습니다", STATUS_SECONDS)

    def onscreen_translation_changed(self, video_id):
        """화면 번역 완성·검수 수정 신호. 지금 보는 영상이면 1초 주기를 기다리지 않고 다시 읽는다."""
        session = self.core.playback.session
        if session is not None and session.video_id == video_id:
            self.refresh_onscreen_translation()

    def draw_onscreen_translation(self):
        """지금 위치에 맞는 띠 묶음과 받아쓰기 자막 자리를 엔진에 맞춘다. 바뀐 것만 보낸다.

        엔진이 바뀌었으면 새 엔진에는 아무것도 없는 것으로 보고 처음부터 그린다.
        닫는 중인 엔진(위치 타이머가 멈춤)에는 보내지 않는다.
        """
        player = self.shell.player
        if player is None or not self.shell.position_timer.isActive():
            return
        display = self._onscreen.on_player(player)
        bands, raised = display.target(self.core.playback.position)
        if raised != display.subtitles_raised:
            if setter := getattr(player, "set_subtitles_raised", None):
                setter(raised)
        if bands != display.bands:
            if bands:
                if show := getattr(player, "show_onscreen_translation", None):
                    show(bands)
            elif clear := getattr(player, "clear_onscreen_translation", None):
                clear()
        self._onscreen = replace(display, bands=bands, subtitles_raised=raised)

    def toggle_onscreen_translation(self) -> bool:
        """화면 번역 자막 켜기/끄기. 없는 영상이면 상태를 바꾸지 않고 안내하며 False를 돌려준다."""
        if not self._onscreen.available:
            self.shell.statusBar().showMessage(NO_ONSCREEN_TRANSLATION, 4000)
            return False
        self._onscreen = replace(self._onscreen, enabled=not self._onscreen.enabled)
        self.draw_onscreen_translation()
        self.update_onscreen_button()
        return True

    def retire_onscreen_translation(self, player):
        """엔진을 내리기 전에 그 엔진의 띠를 지운다. 닫히는 마지막 장면에 띠가 남지 않는다."""
        display = self._onscreen
        if display.player is not player:
            return
        if display.bands and (clear := getattr(player, "clear_onscreen_translation", None)):
            clear()
        self._onscreen = replace(display, player=None, bands=(), subtitles_raised=False)

    def reset_onscreen_translation(self):
        """재생 화면을 떠났다(목록·모아보기 목록 복귀). 다음 재생은 켬으로 시작한다."""
        self._onscreen = OnScreenTranslationDisplay()
        self.update_onscreen_button()

    def update_range_button(self):
        """열린 구간이 있으면 구간 단추가 '구간 끝내기'로 바뀌고 눌린 상태가 된다."""
        opened = self.core.open_highlight_start is not None
        self.range_button.set_label(*(("】 구간 끝내기", "】") if opened else ("【 구간 시작", "【")))
        self.range_button.setChecked(opened)
        name = "구간 하이라이트 끝내기" if opened else "구간 하이라이트 시작"
        self.range_button.setAccessibleName(name)
        self.range_button.setToolTip(f"{name} · {self._keys[CommandType.RANGE_HIGHLIGHT]}")

    def update_reel_buttons(self):
        """모아보기 중에만 모아보기 단추를 보인다. 이때 ⏮ ⏭는 PgUp/PgDn의 모아보기 뜻(키 안내와 같은 이름)이다."""
        for button in self.reel_buttons:
            button.setVisible(self._reel)
        for button, name in ((self.previous_button, '이전 영상'), (self.next_button, '다음 영상')):
            button.setAccessibleName(REEL_MEANINGS[button.command.kind] if self._reel else name)
        for button in (self.previous_button, self.next_button, self.reel_previous_button, self.reel_next_button):
            button.setToolTip(f'{button.accessibleName()} · {self._keys[button.command.kind]}')
        self.reel_repeat_button.setToolTip(f'모아보기 반복 켜기/끄기 · {self._keys[CommandType.TOGGLE_REEL_REPEAT]}')

    def update_random_buttons(self):
        """모아보기가 아니면 🔀를 보이고 켜짐을 눌림 상태로 표시한다. 켜져 있으면 옆에 범위 이름 단추를 보인다."""
        enabled = self.core.random_continuous_enabled and not self._reel
        self.random_button.setVisible(not self._reel)
        self.random_button.setChecked(enabled)
        self.random_scope_button.setVisible(enabled)
        shown = (self.core.random_continuous_scope, self.core.playback_source_name) if enabled else None
        if shown is None or shown == self._random_scope_shown:
            return
        self._random_scope_shown = shown
        label = self.core.random_continuous_scope_label()
        self.random_scope_button.set_label(label.text, label.compact)
        self.random_scope_button.setAccessibleName(f"무작위 이어 재생 범위 {label.description}")
        self.random_scope_button.setToolTip(f"무작위 이어 재생 범위 바꾸기 · 지금 {label.description}")

    def show_reel_repeat(self, repeat):
        self.reel_repeat_button.setChecked(repeat)
        self.reel_repeat_button.set_label(f"↻ 반복 {'켜짐' if repeat else '꺼짐'}", "↻")

    def update_controls(self):
        """조작 줄의 재생·자막 상태를 플레이어와 코어에서 읽어 보여 준다."""
        self.update_range_button()
        self.update_onscreen_button()
        self.update_random_buttons()
        # 명령이 실행되지 않은 단추 누름이 눌림 상태만 바꿔 두지 않게 코어 상태로 되돌린다.
        self.show_reel_repeat(self._reel and self.core.reel_repeat)
        player = self.shell.player
        # stop_player는 엔진을 닫은 뒤 마지막 위치 보고를 저장한다.
        # 그 보고로 화면을 갱신할 때는 종료된 mpv 속성을 다시 읽지 않는다.
        if not player or not self.shell.position_timer.isActive():
            return
        options = getattr(player, "playback_options", None)
        speed, visible = options() if options else (1, True)
        paused = getattr(player, "paused", False)
        self.speed_button.set_label(f"속도 {speed:g}×", f"{speed:g}×")
        self.speed_button.setAccessibleName(f"재생 속도 {speed:g}×")
        self.pause_button.set_label("▶" if paused else "⏸")
        self.pause_button.setAccessibleName("재생" if paused else "일시정지")
        self.subtitles_button.setChecked(visible)
        self.subtitles_button.set_label("자막 켜짐" if visible else "자막 꺼짐", "자막")
        details = self._details
        if details is None:
            return
        task = translation_task(details.spoken_language)
        if not details.original_lines:
            language = ("자막 없음", "없음")
        elif self.core.playback_subtitle_language == "translated":
            language = (task.subtitle_label, task.short_label)
        else:
            language = ("원어 자막", "원어")
        self.subtitle_language_button.set_label(*language)
        self.subtitle_language_button.setAccessibleName(f"자막 종류 {language[0]}")
        self.update_subtitle_language_tooltip()
        work = {"queued": "대기", "transcribing": "만드는 중", "translating": "진행 중",
                "held": "보류", "failed": "실패"}
        labels = []
        if details.subtitle_state in work:
            labels.append(f"원어 {work[details.subtitle_state]}")
        if details.translation_state in work:
            labels.append(f"{task.label} {work[details.translation_state]}")
        self.subtitle_work_label.setText(" · ".join(labels))
        self.subtitle_work_label.setToolTip(self.subtitle_work_label.text())

    def show_position(self, position, duration, open_start, range_keys):
        session = self.core.playback.session
        if session and self._shown_session is not session:
            self.progress.cancel_drag()
            self._shown_session = session
            self._error = ""
            self.show_notice("")
            video = self.core.video(session.video_id)
            series = self.core.series_for_video(session.video_id)
            episode = f" · {series.video_ids.index(video.id) + 1}/{len(series.video_ids)}" if series else ""
            self.title_label.setText(video.title + episode)
            self.title_label.setToolTip(video.title + episode)
            # 보이는 화면이면 refresh_details가 화면 번역 자막도 읽는다. 숨은 창이면 그것만 읽어 옛 영상의 줄을 그리지 않는다.
            self.refresh_details()
            if not self.isVisible():
                self.refresh_onscreen_translation()
        self.progress.duration = duration
        self.progress.position = position
        self.progress.open_start = open_start
        self.progress.update()
        if session:
            self.highlights_panel.show_highlights(self.progress.highlights, position, video_id=session.video_id)
        self.position_label.setText(f"{timestamp(position)} / {timestamp(duration)}")
        start = timestamp(open_start).split('.')[0] if open_start is not None else ""
        self.open_range_label.set_label(f"구간 시작 {start}" if start else "", f"【 {start}" if start else "")
        self.open_range_label.setVisible(open_start is not None)
        self.position_label.setToolTip(f"구간 시작 {timestamp(open_start)} · {range_keys}: 끝내기"
                                      if open_start is not None else "")
        self.open_range_label.setToolTip(self.position_label.toolTip())
        self.draw_onscreen_translation()
        self.update_controls()

    def show_reel(self, current, repeat, keys):
        self._reel = current is not None
        self.reel_label.setVisible(current is not None)
        self.back_button.setText("모아보기 목록 · Esc" if current else "목록으로 · Esc")
        self.list_button.set_label("모아보기 목록" if current else "목록으로", "목록")
        self.list_button.setAccessibleName(self.list_button.label)
        self.list_button.setToolTip(f"{self.list_button.label} · Esc")
        if current:
            self.reel_label.setText(f"하이라이트 {current.index}/{current.total} · 반복 {'켜짐' if repeat else '꺼짐'}")
        self.show_reel_repeat(bool(current and repeat))
        self.update_reel_buttons()
        self.update_random_buttons()
        if self._help_requested:
            self.refresh_key_help()

    def show_error(self, text):
        self._error = text
        self.show_notice(text)
        self.reveal_bar()

    def handle_key(self, event) -> bool:
        window = self.shell
        self.reveal_bar()
        if self.region_selector is not None:
            return self.region_selector.handle_key(event)
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
        if (focus in (self.menu_button, self.back_button, self.highlights_button, *self.control_buttons)
                and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)):
            return False
        # 초점 단추는 Space로만 누른다. Enter를 비롯한 다른 키는 아래에서 지금 키 배치의 재생 명령이 된다.
        if (focus in (self.back_button, self.highlights_button, *self.control_buttons)
                and event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            return False
        if (focus is self.menu_button
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down)):
            if not event.isAutoRepeat():
                self.menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().topRight()))
            return True
        command = window.core.command_for_key(key_name(event) or "")
        return command is not None and self.run_command(command, repeated=event.isAutoRepeat())

    def run_command(self, command, *, repeated=False) -> bool:
        """재생 명령 하나를 실행한다. 키·단추가 모두 이 경로를 써서 동작이 갈라지지 않는다.

        repeated는 키를 누르고 있어 반복된 입력이다. 처리하지 않은 명령이면 False다.
        """
        window = self.shell
        if command.kind == CommandType.TOGGLE_HIGHLIGHT_LIST:
            if not repeated:
                self.toggle_highlights()
            return True
        if command.kind == CommandType.TOGGLE_FULLSCREEN:
            if not repeated:
                window.set_playback_fullscreen(not window.isFullScreen())
            return True
        if not window.player:
            return False
        if self.region_selector is not None:
            # 화면 자막 영역을 정하는 동안은 멈춘 장면을 바꾸지 않는다. 덮개 밖 단추로 눌러도 같다.
            return True
        changed = False
        try:
            if command.kind in (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO):
                if not repeated:
                    window.sync_position()
                    target = window.core.execute_video_command(command, window.playback_list)
                    if target is not None:
                        window.play_video(target)
                    else:
                        window.reel.sync()
            elif window.core.is_highlight_command(command):
                if repeated or window.sync_position() is None:
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
                changed = True
            elif command.kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE:
                if not repeated:
                    changed = window.translations.toggle()
            elif command.kind == CommandType.TOGGLE_ONSCREEN_TRANSLATION:
                if not repeated:
                    changed = self.toggle_onscreen_translation()
            elif command.kind == CommandType.TOGGLE_RANDOM_CONTINUOUS:
                # 켜면 범위는 재생을 시작한 목록이고, 끄면 영상 끝에서 멈춘다. 모아보기 중에는 🔀가 숨어 키도 동작하지 않는다.
                if not repeated and window.core.reel_playback is None:
                    window.core.set_random_continuous_enabled(not window.core.random_continuous_enabled)
                    changed = True
            elif command.kind == CommandType.SEEK:
                self.seek(command=command)
            else:
                window.player.execute(command)
                changed = True
            # 바꾸지 못했거나 실패한 조작은 재생 상태 표시 없이 지금처럼 안내·경고로만 알린다.
            status = self.playback_status(command) if changed else None
            show_status = getattr(window.player, "show_status", None)
            if status and show_status:
                show_status(status, STATUS_SECONDS)
        except Exception as error:
            QMessageBox.warning(window, "재생 조작 실패", str(error))
        return True

    def playback_status(self, command):
        """명령으로 바뀐 지금 상태를 재생 상태 표시 문구로 읽는다. 표시하지 않는 명령이면 None."""
        player, core = self.shell.player, self.core
        if command.kind == CommandType.TOGGLE_PAUSE:
            return "▶ 재생" if not getattr(player, "paused", False) else "⏸ 일시정지"
        options = getattr(player, "playback_options", None)
        speed, visible = options() if options else (1, True)
        if command.kind == CommandType.CHANGE_SPEED:
            return f"{speed:g}×"
        if command.kind == CommandType.TOGGLE_SUBTITLES:
            return "자막 켜짐" if visible else "자막 꺼짐"
        if command.kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE:
            if core.playback_subtitle_language == "translated":
                return core.subtitle_task(core.playback.session.video_id).subtitle_label
            return "원어 자막"
        if command.kind == CommandType.POINT_HIGHLIGHT:
            return "◆ 지점 하이라이트 추가"
        if command.kind == CommandType.RANGE_HIGHLIGHT:
            return "【 구간 시작" if core.open_highlight_start is not None else "】 구간 끝"
        if command.kind == CommandType.TOGGLE_REEL_REPEAT and core.reel_playback is not None:
            return f"모아보기 반복 {'켜짐' if core.reel_repeat else '꺼짐'}"
        if command.kind == CommandType.TOGGLE_ONSCREEN_TRANSLATION:
            return "화면 번역 자막 " + ("켜짐" if self._onscreen.enabled else "꺼짐")
        if command.kind == CommandType.TOGGLE_RANDOM_CONTINUOUS:
            return f"🔀 무작위 이어 재생 {'켜짐' if core.random_continuous_enabled else '꺼짐'}"
        return None
