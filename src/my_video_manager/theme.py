"""앱 전체의 고정 다크 테마. 페이지와 직접 그리는 위젯도 같은 색을 쓴다."""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtCore import Qt

BACKGROUND = "#181818"
SURFACE = "#242424"
BORDER = "#454b54"
TEXT = "#eeeeee"
MUTED_TEXT = "#aaaaaa"
ACCENT = "#79b8ff"
ACCENT_TEXT = "#121212"
WARNING = "#f69b50"
HIGHLIGHT_POINT = "#ffd166"
HIGHLIGHT_RANGE = "#70d6a3"
HIGHLIGHT_OPEN = WARNING
VIDEO_BACKGROUND = "#000000"

STYLE_SHEET = f"""
QWidget {{ color: {TEXT}; background-color: {BACKGROUND}; }}
QWidget:disabled {{ color: {MUTED_TEXT}; }}
QLabel {{ background: transparent; }}
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox,
QAbstractItemView {{
    background: {SURFACE}; border: 2px solid {BORDER};
    border-radius: 3px; selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit, QAbstractSpinBox, QComboBox {{ padding: 4px; }}
QPushButton, QToolButton {{
    background: {SURFACE}; border: 2px solid {BORDER};
    border-radius: 4px; padding: 5px 8px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {MUTED_TEXT}; }}
QPushButton:checked {{ border-color: {ACCENT}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QCheckBox, QRadioButton {{ border: 2px solid transparent; padding: 2px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus,
QComboBox:focus, QAbstractItemView:focus, QPushButton:focus, QToolButton:focus,
QCheckBox:focus, QRadioButton:focus, QSlider:focus, QTabBar:focus {{
    border: 2px solid {ACCENT};
}}
QAbstractItemView::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}
QAbstractItemView::item:focus {{ border: 1px solid {ACCENT}; }}
QHeaderView::section, QTableCornerButton::section {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px;
}}
QTableView {{ gridline-color: {BORDER}; }}
QMenuBar, QMenu {{ background: {SURFACE}; }}
QMenu {{ border: 1px solid {BORDER}; }}
QMenu::item {{ padding: 5px 20px; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {ACCENT}; padding: 4px; }}
QScrollBar {{ background: {BACKGROUND}; }}
QScrollBar:vertical {{ width: 14px; margin: 0; }}
QScrollBar:horizontal {{ height: 14px; margin: 0; }}
QScrollBar::handle {{ background: {BORDER}; border-radius: 4px; min-width: 24px; min-height: 24px; }}
QScrollBar::handle:hover {{ background: {MUTED_TEXT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: {BACKGROUND}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {SURFACE}; border: 2px solid {BORDER}; padding: 6px 12px; }}
QTabBar::tab:selected {{ border-bottom-color: {ACCENT}; }}
QTabBar::tab:focus {{ border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; margin-top: 12px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }}
QProgressBar {{ border: 1px solid {BORDER}; background: {SURFACE}; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QWidget#videoSurface {{ background: {VIDEO_BACKGROUND}; border: 2px solid {VIDEO_BACKGROUND}; }}
QWidget#videoSurface:focus {{ border-color: {ACCENT}; }}
QListWidget#navigation {{ border: 2px solid transparent; }}
QListWidget#navigation:focus {{ border-color: {ACCENT}; }}
QListWidget#navigation::item {{ padding: 10px 6px; }}
"""


def apply_theme(app):
    """QApplication 생성 직후 한 번 호출한다. 독립 창에도 같은 팔레트가 상속된다."""
    if app.property("darkThemeApplied"):
        return
    # OS 기본 스타일과 네이티브 파일 대화상자의 밝은 배경이 섞이지 않게 한다.
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BACKGROUND,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: BACKGROUND,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.ToolTipBase: SURFACE,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: ACCENT_TEXT,
        QPalette.ColorRole.PlaceholderText: MUTED_TEXT,
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.LinkVisited: ACCENT,
        QPalette.ColorRole.Light: BORDER,
        QPalette.ColorRole.Midlight: BORDER,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BACKGROUND,
        QPalette.ColorRole.Shadow: VIDEO_BACKGROUND,
        QPalette.ColorRole.BrightText: WARNING,
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(MUTED_TEXT))
    app.setPalette(palette)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(STYLE_SHEET)
    app.setProperty("darkThemeApplied", True)
