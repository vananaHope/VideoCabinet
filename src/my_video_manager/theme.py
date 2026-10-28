"""네이티브 재생·셸·트레이의 테마. 웹 토큰을 단일 원본으로 쓴다."""

from PySide6.QtGui import QColor, QFont, QPalette

from .web_tokens import web_tokens

# 웹과 네이티브 재생의 단일 원본.
_WEB = web_tokens()
PLAYBACK_COLORS = _WEB["colors"]
# 웹은 번들 글꼴(토큰의 첫 이름)을 쓰지만 Qt 글꼴 데이터베이스에는 아직 등록하지 않는다(#297).
# 토큰의 대체 글꼴인 맑은 고딕을 명시해 재생 화면·트레이 메뉴·공용 경고가 시스템 기본 글꼴로 떨어지지 않게 한다.
NATIVE_FONT = "Malgun Gothic"


def playback_pixels(group, name):
    """웹의 rem 값을 Qt 논리 픽셀로 변환한다(CSS 기본 1rem = 16px)."""
    return round(float(_WEB[group][name].removesuffix("rem")) * 16)


def playback_font(size="text-sm"):
    font = QFont(NATIVE_FONT)
    font.setPixelSize(playback_pixels("typography", size))
    return font


def playback_stylesheet():
    c = PLAYBACK_COLORS
    radius = playback_pixels("layout", "radius") // 2
    spacing = playback_pixels("layout", "spacing")
    return f"""
    QWidget {{ color: {c['foreground']}; background: {c['background']};
        font-family: "{NATIVE_FONT}";
        font-size: {playback_pixels('typography', 'text-sm')}px; }}
    QLabel {{ background: transparent; }}
    QWidget#playbackHeader, QWidget#playbackBar, QWidget#playbackHighlights,
    QWidget#playbackHelp {{ background: {c['card']}; }}
    QWidget#playbackHeader {{ border-bottom: 1px solid {c['border']}; }}
    QWidget#playbackBar {{ border-top: 1px solid {c['border']}; }}
    QWidget#playbackHighlights {{ border-left: 1px solid {c['border']}; }}
    QWidget#playbackHelp {{ border: 1px solid {c['border']}; border-radius: {radius}px; }}
    QLabel[playbackRole="muted"] {{ color: {c['muted-foreground']}; }}
    QLabel[playbackRole="warning"] {{ color: {c['highlight-open']}; }}
    QLabel[playbackRole="title"] {{ font-weight: 600; }}
    QPushButton, QToolButton {{ background: {c['secondary']}; color: {c['foreground']};
        border: 1px solid {c['border']}; border-radius: {radius}px;
        padding: {spacing}px {spacing * 2}px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {c['muted-foreground']}; }}
    /* 재생 기호(⏮ ⏸ ⏭ 등)가 컬러 이모지로 그려지지 않게 단색 기호 글꼴을 쓴다. */
    QToolButton[playbackRole="symbol"] {{ font-family: "Segoe UI Symbol";
        font-size: {playback_pixels('typography', 'text-base')}px; }}
    QPushButton:checked, QToolButton:checked {{ background: {c['secondary']}; color: {c['primary-text']}; }}
    QPushButton:focus, QToolButton:focus, QAbstractItemView:focus {{ border: 2px solid {c['ring']}; }}
    QListWidget {{ background: {c['card']}; border: 2px solid transparent; outline: none; }}
    QMenu {{ background: {c['popover']}; color: {c['popover-foreground']}; border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background: {c['secondary']}; border-left-color: {c['ring']}; }}
    QScrollBar {{ background: {c['card']}; }}
    QScrollBar::handle {{ background: {c['border']}; }}
    QScrollBar::handle:hover {{ background: {c['muted-foreground']}; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: {c['card']}; }}
    QWidget#videoSurface {{ background: {VIDEO_BACKGROUND}; border: 0; }}
    """

VIDEO_BACKGROUND = '#000000'


def apply_theme(app):
    """셸·트레이 메뉴와 공용 네이티브 경고에 웹 색과 글꼴을 적용한다."""
    if app.property('darkThemeApplied'):
        return
    app.setStyle('Fusion')
    colors = PLAYBACK_COLORS
    palette = QPalette()
    for role, token in {
        QPalette.ColorRole.Window: 'background', QPalette.ColorRole.WindowText: 'foreground',
        QPalette.ColorRole.Base: 'card', QPalette.ColorRole.Text: 'foreground',
        QPalette.ColorRole.Button: 'secondary', QPalette.ColorRole.ButtonText: 'foreground',
        QPalette.ColorRole.ToolTipBase: 'popover', QPalette.ColorRole.ToolTipText: 'popover-foreground',
        QPalette.ColorRole.Highlight: 'primary', QPalette.ColorRole.HighlightedText: 'primary-text',
    }.items():
        palette.setColor(role, QColor(colors[token]))
    app.setPalette(palette)
    app.setFont(playback_font())
    app.setStyleSheet(playback_stylesheet())
    app.setProperty('darkThemeApplied', True)
