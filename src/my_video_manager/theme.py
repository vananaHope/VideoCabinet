"""앱 전체의 고정 다크 테마. 페이지와 직접 그리는 위젯도 같은 색을 쓴다."""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QLabel, QStyledItemDelegate

BACKGROUND = "#181818"
SURFACE = "#242424"
BORDER = "#454b54"
# 입력·버튼처럼 조작할 수 있는 요소의 경계. 장식용 BORDER보다 밝고 포커스 강조색과는 구분된다.
CONTROL_BORDER = "#5c636e"
# 빈 입력 칸은 경계로만 구분되므로 배경·표면 모두와 3:1 이상이 되게 한다(포커스는 ACCENT 2px로 따로 표시).
INPUT_BORDER = "#6b7280"
TEXT = "#eeeeee"
MUTED_TEXT = "#aaaaaa"
ACCENT = "#79b8ff"
ACCENT_TINT = "#1e3a5f"
INACTIVE_SELECTION = "#2a3440"
DISABLED_TEXT = "#777777"
DISABLED_BORDER = "#333333"
PROGRESS_PLAYED = "#355d87"
WARNING = "#f69b50"
HIGHLIGHT_POINT = "#ffd166"
HIGHLIGHT_RANGE = "#70d6a3"
HIGHLIGHT_OPEN = WARNING
VIDEO_BACKGROUND = "#000000"

_ICONS = (Path(__file__).parent / "theme_icons").as_posix()

STYLE_SHEET = f"""
QWidget {{ color: {TEXT}; background-color: {BACKGROUND}; }}
QWidget:disabled {{ color: {DISABLED_TEXT}; }}
QLabel {{ background: transparent; }}
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox,
QAbstractItemView {{
    background: {SURFACE}; border: 2px solid {BORDER};
    border-radius: 3px; selection-background-color: {ACCENT_TINT};
    selection-color: {TEXT};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox {{ border-color: {INPUT_BORDER}; }}
QLineEdit, QAbstractSpinBox, QComboBox {{ padding: 4px; }}
QPushButton, QToolButton {{
    background: {SURFACE}; border: 2px solid {CONTROL_BORDER};
    border-radius: 4px; padding: 5px 10px;
}}
QLabel[role="pageTitle"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="sectionTitle"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="hint"], QLabel[role="emptyBody"] {{ color: {MUTED_TEXT}; }}
QLabel[role="emptyTitle"] {{ font-size: 16px; font-weight: 600; }}
QPushButton[role="danger"] {{ color: {WARNING}; }}
QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame[role="card"] QLabel {{ background: transparent; }}
QPushButton:hover, QToolButton:hover {{ border-color: {MUTED_TEXT}; }}
QPushButton:checked {{ background: {ACCENT_TINT}; border-color: {BORDER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QCheckBox, QRadioButton {{ border: 2px solid transparent; padding: 2px; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus,
QComboBox:focus, QAbstractItemView:focus, QPushButton:focus, QToolButton:focus,
QCheckBox:focus, QRadioButton:focus, QSlider:focus, QTabBar:focus {{
    border: 2px solid {ACCENT};
}}
QAbstractItemView::item {{ border: 1px solid transparent; }}
QAbstractItemView::item:selected {{ background: {INACTIVE_SELECTION}; color: {TEXT}; }}
QAbstractItemView[keyboardFocus="true"]::item:selected {{ background: {ACCENT_TINT}; }}
QAbstractItemView::item:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView::item {{ border-left: 3px solid transparent; }}
QComboBox QAbstractItemView::item:selected {{ border-left-color: {ACCENT}; }}
QHeaderView::section, QTableCornerButton::section {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px;
}}
QTableView {{ gridline-color: {BORDER}; }}
QMenuBar, QMenu {{ background: {SURFACE}; }}
QMenu {{ border: 1px solid {BORDER}; }}
QMenu::item {{ padding: 5px 20px; border-left: 3px solid transparent; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: {ACCENT_TINT}; color: {TEXT}; }}
QMenu::item:selected {{ border-left-color: {ACCENT}; }}
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
QTabBar::tab:selected {{ background: {ACCENT_TINT}; }}
QTabBar::tab:focus {{ border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; margin-top: 12px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }}
QProgressBar {{ border: 1px solid {BORDER}; background: {SURFACE}; text-align: center; }}
QProgressBar::chunk {{ background: {PROGRESS_PLAYED}; }}
QWidget#videoSurface {{ background: {VIDEO_BACKGROUND}; border: 2px solid {VIDEO_BACKGROUND}; }}
QWidget#videoSurface:focus {{ border-color: {ACCENT}; }}
QListWidget#navigation {{ border: 2px solid transparent; }}
QListWidget#navigation:focus {{ border-color: {ACCENT}; }}
QListWidget#navigation::item {{ padding: 10px 6px; border-left: 3px solid transparent; }}
QListWidget#navigation::item:selected {{ border-left-color: {ACCENT}; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 2px solid {MUTED_TEXT};
    background: {SURFACE}; border-radius: 2px;
}}
QCheckBox::indicator:checked {{ background: {MUTED_TEXT}; image: url("{_ICONS}/check.svg"); }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    background: {MUTED_TEXT}; border: 1px solid {BORDER}; width: 18px;
}}
QAbstractSpinBox::up-arrow {{ image: url("{_ICONS}/up.svg"); width: 8px; height: 5px; }}
QAbstractSpinBox::down-arrow {{ image: url("{_ICONS}/down.svg"); width: 8px; height: 5px; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QAbstractSpinBox:disabled, QComboBox:disabled, QAbstractItemView:disabled,
QPushButton:disabled, QToolButton:disabled, QCheckBox::indicator:disabled {{
    color: {DISABLED_TEXT}; border-color: {DISABLED_BORDER};
}}
QCheckBox::indicator:checked:disabled {{ background: {DISABLED_TEXT}; }}
QAbstractItemView::item:disabled {{ color: {DISABLED_TEXT}; }}
QAbstractSpinBox::up-button:disabled, QAbstractSpinBox::down-button:disabled {{
    background: {DISABLED_BORDER}; border-color: {DISABLED_BORDER};
}}
"""


def with_role(widget, role):
    """전역 스타일시트의 역할(role) 규칙을 붙인다. 페이지마다 글자 크기를 따로 정하지 않는다."""
    widget.setProperty("role", role)
    return widget


def page_title(text):
    return with_role(QLabel(text), "pageTitle")


def hint_label(text=""):
    label = with_role(QLabel(text), "hint")
    label.setWordWrap(True)
    return label


class _ThemeWidgets(QObject):
    """목록의 실제 포커스를 표시하고 콤보 항목에도 스타일시트 테두리를 적용한다."""

    def eventFilter(self, watched, event):
        if isinstance(watched, QComboBox) and event.type() == QEvent.Type.Polish:
            # 기본 메뉴 delegate는 항목 테두리를 그리지 않는다. 사용자 delegate는 보존한다.
            if watched.itemDelegate().metaObject().className() in ("QComboMenuDelegate", "QComboBoxDelegate"):
                watched.setItemDelegate(QStyledItemDelegate(watched))
        # Qt의 item :active는 목록 포커스가 아닌 창 활성 상태다.
        if isinstance(watched, QAbstractItemView) and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            watched.setProperty("keyboardFocus", event.type() == QEvent.Type.FocusIn)
            watched.style().unpolish(watched)
            watched.style().polish(watched)
            watched.viewport().update()
        return False


def apply_theme(app):
    """QApplication 생성 직후 한 번 호출한다. 독립 창에도 같은 팔레트가 상속된다."""
    if app.property("darkThemeApplied"):
        return
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
        QPalette.ColorRole.Highlight: ACCENT_TINT,
        QPalette.ColorRole.HighlightedText: TEXT,
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
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(DISABLED_TEXT))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor(INACTIVE_SELECTION))
    app.setPalette(palette)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(STYLE_SHEET)
    app._theme_widgets = _ThemeWidgets(app)
    app.installEventFilter(app._theme_widgets)
    app.setProperty("darkThemeApplied", True)
