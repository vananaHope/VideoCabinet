"""네이티브 재생·셸·트레이의 테마. 웹 토큰을 단일 원본으로 쓴다."""

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from .web_tokens import web_tokens

logger = logging.getLogger(__name__)

# 웹과 네이티브 재생의 단일 원본.
_WEB = web_tokens()
PLAYBACK_COLORS = _WEB["colors"]
# 토큰 font-sans의 첫 이름은 번들 글꼴, 둘째 이름은 대체 글꼴(맑은 고딕)이다.
BUNDLED_FONT, FALLBACK_FONT = (name.strip().strip('"') for name in _WEB["typography"]["font-sans"].split(",")[:2])
# Qt는 웹 번들의 woff2를 읽지 못해 웹 빌드가 같은 글꼴의 정적 TrueType을 굵기별로 이 폴더에 둔다(frontend/vite.config.ts).
QT_FONT_DIRECTORY = Path(__file__).with_name("web") / "qt-fonts"
QT_FONT_FILES = tuple(f"{BUNDLED_FONT}-{stem}.ttf" for stem in _WEB["bundled-font"]["weights"].values())
# 번들 글꼴을 등록하기 전과 등록에 실패했을 때는 대체 글꼴만 쓴다. 등록하면 웹처럼 번들 글꼴 뒤에 대체 글꼴을 둔다.
_font_families = [FALLBACK_FONT]


def playback_pixels(group, name):
    """웹의 rem 값을 Qt 논리 픽셀로 변환한다(CSS 기본 1rem = 16px)."""
    return round(float(_WEB[group][name].removesuffix("rem")) * 16)


def playback_font(size="text-sm"):
    font = QFont()
    font.setFamilies(_font_families)
    font.setPixelSize(playback_pixels("typography", size))
    return font


def playback_stylesheet():
    c = PLAYBACK_COLORS
    radius = playback_pixels("layout", "radius") // 2
    spacing = playback_pixels("layout", "spacing")
    return f"""
    QWidget {{ color: {c['foreground']}; background: {c['background']};
        font-family: {', '.join(f'"{name}"' for name in _font_families)};
        font-size: {playback_pixels('typography', 'text-sm')}px; }}
    QLabel {{ background: transparent; }}
    QWidget#playbackHeader, QWidget#playbackBar, QWidget#playbackHighlights {{ background: {c['card']}; }}
    QWidget#playbackHelp, QMessageBox {{ background: {c['popover']}; }}
    QWidget#playbackHeader {{ border-bottom: 1px solid {c['border']}; }}
    QWidget#playbackBar {{ border-top: 1px solid {c['border']}; }}
    QWidget#playbackHighlights {{ border-left: 1px solid {c['border']}; }}
    QWidget#playbackHelp {{ border: 1px solid {c['border']}; border-radius: {radius}px; }}
    QLabel[playbackRole="muted"] {{ color: {c['muted-foreground']}; }}
    QLabel[playbackRole="warning"] {{ color: {c['highlight-open']}; }}
    QLabel[playbackRole="title"] {{ font-weight: 600; }}
    QPushButton, QToolButton {{ background: {c['secondary']}; color: {c['foreground']};
        border: 1px solid {c['input']}; border-radius: {radius}px;
        padding: {spacing}px {spacing * 2}px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {c['muted-foreground']}; }}
    /* 재생 기호(⏮ ⏸ ⏭ 등)가 컬러 이모지로 그려지지 않게 단색 기호 글꼴을 쓴다. */
    QToolButton[playbackRole="symbol"] {{ font-family: "Segoe UI Symbol";
        font-size: {playback_pixels('typography', 'text-base')}px; }}
    QPushButton:checked, QToolButton:checked {{ background: {c['accent']}; color: {c['primary-text']}; }}
    QPushButton:focus, QToolButton:focus, QAbstractItemView:focus {{ border: 2px solid {c['ring']}; }}
    QListWidget {{ background: {c['card']}; border: 2px solid transparent; outline: none; }}
    QMenu {{ background: {c['popover']}; color: {c['popover-foreground']}; border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background: {c['accent']}; border-left-color: {c['ring']}; }}
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
        QPalette.ColorRole.Highlight: 'primary', QPalette.ColorRole.HighlightedText: 'primary-foreground',
        QPalette.ColorRole.PlaceholderText: 'muted-foreground',
    }.items():
        palette.setColor(role, QColor(colors[token]))
    app.setPalette(palette)
    app.setFont(playback_font())
    app.setStyleSheet(playback_stylesheet())
    app.setProperty('darkThemeApplied', True)


def use_bundled_font(app):
    """번들 글꼴을 Qt 글꼴 데이터베이스에 등록해 재생 화면·트레이 메뉴·공용 경고에 쓴다.

    실패가 앱 로그에 남도록 앱 로그 설정 뒤(창을 만들 때) 부른다. 굵기 하나라도 파일이 없거나
    읽지 못하면 등록한 것도 되돌리고 대체 글꼴을 유지한다. 앱 시작은 막지 않는다.
    """
    global _font_families
    if _font_families[0] == BUNDLED_FONT:
        return True
    registered = []
    for name in QT_FONT_FILES:
        path = QT_FONT_DIRECTORY / name
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            registered.append(font_id)
        if font_id < 0 or BUNDLED_FONT not in QFontDatabase.applicationFontFamilies(font_id):
            for registered_id in registered:
                QFontDatabase.removeApplicationFont(registered_id)
            reason = '파일 없음' if not path.is_file() else '읽을 수 없는 글꼴'
            logger.warning('번들 글꼴을 등록하지 못해 %s로 표시합니다(%s): %s', FALLBACK_FONT, reason, path)
            return False
    _font_families = [BUNDLED_FONT, FALLBACK_FONT]
    if app.property('darkThemeApplied'):
        app.setFont(playback_font())
        app.setStyleSheet(playback_stylesheet())
    return True
