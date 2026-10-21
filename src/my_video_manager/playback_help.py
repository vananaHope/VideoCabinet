"""네이티브 mpv 영상 위에 표시하는 키 안내 툴 창. 활성 창과 초점은 가져가지 않는다."""

from html import escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from .core import CommandType
from .key_display import display_keys
from .key_guide import SETTINGS_KEY, page_keys
from .theme import PLAYBACK_COLORS, playback_stylesheet, playback_font
from .web_tabs import TABS


# 하이라이트 모아보기 중 화면별 의미가 바뀌는 명령. 키 안내와 조작 줄 단추가 같은 이름을 쓴다.
REEL_MEANINGS = {
    CommandType.PREVIOUS_HIGHLIGHT: "이전 하이라이트 항목",
    CommandType.NEXT_HIGHLIGHT: "다음 하이라이트 항목",
    CommandType.PREVIOUS_VIDEO: "현재 영상 첫 항목 / 이전 영상",
    CommandType.NEXT_VIDEO: "다음 영상 첫 하이라이트",
}


class PlaybackHelp(QWidget):
    close_requested = Signal()

    def __init__(self, parent):
        # 마우스로 닫을 수 있게 입력은 받되, 누르더라도 앱 창의 활성 상태와 재생 키 초점은 그대로 둔다.
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.94)
        self.setObjectName("playbackHelp")
        self.setStyleSheet(playback_stylesheet())
        self.setFont(playback_font())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 12, 14)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        layout.addWidget(self.text, 1)
        self.close_button = QToolButton()
        self.close_button.setText("✕ 닫기")
        self.close_button.setAccessibleName("키 안내 닫기")
        self.close_button.setToolTip("키 안내 닫기 · F1 / Esc")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.close_requested)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

    def refresh(self, core):
        reel = core.reel_playback is not None
        meanings = dict(REEL_MEANINGS) if reel else {}
        if core.playback.session:
            task = core.subtitle_task(core.playback.session.video_id)
            meanings[CommandType.TOGGLE_SUBTITLE_LANGUAGE] = f'원어 / {task.subtitle_label} 전환'
        rows = []
        for binding in core.key_bindings():
            label = meanings.get(binding.command.kind, binding.label)
            if binding.command.kind == CommandType.TOGGLE_REEL_REPEAT and not reel:
                label += " (모아보기)"
            rows.append(f"<td style='padding:4px 12px 4px 0'><b>{escape(display_keys(binding.keys))}</b></td>"
                        f"<td style='padding-right:16px'>{escape(label)}</td>")
        split = (len(rows) + 1) // 2
        table = ''.join('<tr>' + rows[i] + (rows[i + split] if i + split < len(rows) else '') + '</tr>'
                        for i in range(split))
        c = PLAYBACK_COLORS
        legend = " &nbsp; ".join(f"<span style='color:{color}'>■ {label}</span>" for color, label in (
            (c['highlight'], "지점"), (c['highlight-range'], "구간"), (c['highlight-open'], "열린 구간")))
        self.text.setText("<b>키 안내 · " + ("하이라이트 모아보기" if reel else "일반 재생")
                          + "</b><br>F1 켜기 / 끄기 · Esc 안내 닫기"
                          + "<table>" + table + "</table><br>" + legend
                          + "<br>Tab 메뉴·목록 이동 · 목록에서 ↑↓ 선택, Enter 이동"
                          + f"<br>{SETTINGS_KEY} 설정 메뉴 · {page_keys(TABS)} 재생을 끝내고 페이지 이동"
                          + "<br>Esc: 안내 닫기 → 전체 화면 끄기 → 목록 복귀")

    def place_over(self, surface):
        width = min(900, max(360, surface.width() - 32))
        self.setFixedWidth(width)
        self.adjustSize()
        origin = surface.mapToGlobal(QPoint(0, 0))
        self.move(origin + QPoint(max(0, (surface.width() - self.width()) // 2),
                                  max(0, (surface.height() - self.height()) // 2)))
