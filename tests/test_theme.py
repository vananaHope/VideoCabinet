"""네이티브 테마: 재생 화면·트레이 메뉴·공용 경고가 웹 토큰과 같은 면·경계 색으로 그려진다."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton

from my_video_manager.theme import PLAYBACK_COLORS
from qt_wait import wait_for
from test_emergency_hide_ui import app, play_to_twenty_seconds, window

C = PLAYBACK_COLORS


def pixel(widget, x, y):
    """위젯이 실제로 그린 색(스타일시트 적용 뒤)."""
    return widget.grab().toImage().pixelColor(x, y).name()


def token(name):
    return QColor(C[name]).name()


def test_palette_uses_web_tokens(window):
    palette = QApplication.instance().palette()
    for role, name in {
        QPalette.ColorRole.Window: 'background', QPalette.ColorRole.WindowText: 'foreground',
        QPalette.ColorRole.Base: 'card', QPalette.ColorRole.Button: 'secondary',
        QPalette.ColorRole.ToolTipBase: 'popover', QPalette.ColorRole.Highlight: 'primary',
        QPalette.ColorRole.HighlightedText: 'primary-foreground', QPalette.ColorRole.PlaceholderText: 'muted-foreground',
    }.items():
        assert palette.color(role).name() == token(name), name


def test_tray_menu_is_floating_layer_with_selection_surface(window):
    menu = window.tray.icon.contextMenu()
    menu.popup(QPoint(0, 0))
    wait_for(menu.isVisible)
    first, second = menu.actions()[:2]
    menu.setActiveAction(first)
    active, rest = menu.actionGeometry(first), menu.actionGeometry(second)
    # 항목 오른쪽 끝(글자 없는 곳)의 면: 고른 항목은 accent, 나머지는 떠 있는 층 면이다.
    assert pixel(menu, active.right() - 3, active.center().y()) == token('accent')
    assert pixel(menu, rest.right() - 3, rest.center().y()) == token('popover')
    menu.hide()


def test_shared_warning_uses_floating_surface_and_control_boundary(window):
    box = QMessageBox(QMessageBox.Icon.Warning, '재생 실패', '파일을 열지 못했습니다.', QMessageBox.StandardButton.Ok, window)
    box.show()
    wait_for(box.isVisible)
    assert pixel(box, 2, 2) == token('popover')
    button = box.button(QMessageBox.StandardButton.Ok)
    assert pixel(button, button.width() // 2, 0) == token('input')
    box.done(0)


def test_playback_controls_use_card_surface_input_boundary_and_floating_help(window):
    play_to_twenty_seconds(window)
    page = window.playback_page
    wait_for(lambda: window.pages.currentWidget() is page)
    bar = page.bottom_bar
    assert pixel(bar, bar.width() // 2, 0) == token('border')
    assert pixel(bar, 1, bar.height() - 2) == token('card')
    button = page.menu_button
    assert pixel(button, button.width() // 2, 0) == token('input')
    checkable = next(b for b in page.findChildren(QToolButton) if b.isCheckable())
    checkable.setChecked(True)
    assert pixel(checkable, checkable.width() // 2, checkable.height() - 3) == token('accent')
    help_panel = page.help_panel
    assert pixel(help_panel, 3, help_panel.height() // 2) == token('popover')
