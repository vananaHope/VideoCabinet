"""메뉴 대기 도우미가 부하에서도 앱 창의 활성 상태를 깨뜨리지 않는지."""
from time import sleep

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QToolButton, QVBoxLayout, QWidget

from qt_wait import wait_for, while_button_menu_open


@pytest.fixture
def window(qapp):
    window = QMainWindow()
    body = QWidget()
    window.setCentralWidget(body)
    layout = QVBoxLayout(body)
    window.content = QWidget()
    window.content.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    window.button = QToolButton()
    window.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    window.menu = QMenu(window.button)
    window.menu.addAction("고르기")
    # 앱의 재생 메뉴처럼 닫힌 뒤 다음 이벤트 차례에 내용으로 초점을 돌린다.
    window.menu.aboutToHide.connect(lambda: QTimer.singleShot(0, window.content.setFocus))
    window.button.setMenu(window.menu)
    layout.addWidget(window.content)
    layout.addWidget(window.button)
    window.show()
    window.activateWindow()
    window.content.setFocus()
    wait_for(window.content.hasFocus)
    yield window
    window.close()
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_menu_action_waits_until_the_menu_is_exposed_even_when_the_event_loop_starts_late(window):
    # 부하: 메뉴를 보인 뒤 exec의 이벤트 루프가 돌기까지 대기 타이머 간격보다 오래 걸린다.
    # 그러면 메뉴 창의 표시 알림보다 대기 타이머가 먼저 실행된다.
    window.menu.aboutToShow.connect(lambda: sleep(0.05))
    seen = {}

    def during():
        seen['popup'] = QApplication.activePopupWidget()
        seen['exposed'] = window.menu.windowHandle().isExposed()
        window.menu.close()

    while_button_menu_open(window.button, window.menu, during)
    assert seen == {'popup': window.menu, 'exposed': True}
    wait_for(lambda: not window.menu.isVisible())
    QApplication.processEvents()
    # 닫힌 메뉴가 활성 창으로 남지 않아 앱 창이 활성이고 초점이 내용으로 돌아온다.
    assert window.isActiveWindow()
    wait_for(window.content.hasFocus, timeout=5)


def test_menu_that_never_opens_fails_instead_of_passing_silently(window):
    window.button.setEnabled(False)
    with pytest.raises(AssertionError, match='메뉴가 열려 드러나지 않았다'):
        while_button_menu_open(window.button, window.menu, lambda: None)
