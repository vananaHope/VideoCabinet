"""Qt 조건 대기."""
from time import monotonic
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from wait_helpers import UI_READY_TIMEOUT


def wait_for(predicate, timeout=UI_READY_TIMEOUT):
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, 'Qt 조건 대기 시간 초과'
        # QTest의 중첩 대기 대신 실행 중인 이벤트 루프에서 WebEngine의
        # Python 요청 콜백과 완료 신호에 실행 기회를 준다.
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


def popup_shown(menu):
    """메뉴가 보이고, 그 창이 드러났다는 알림까지 앱이 처리했는지.

    offscreen은 메뉴 창을 보일 때 활성화 알림과 드러남 알림을 차례로 대기열에 넣는다. Qt는 메뉴가 열린 동안
    받은 활성화 알림만 무시하므로, 알림이 처리되기 전에 메뉴를 닫으면 닫힌 메뉴가 활성 창이 되고 앱 창은
    활성을 잃은 채 남는다(영상 초점이 돌아오지 않고, 활성 창에서만 여는 설정 메뉴가 열리지 않는다).
    isVisible은 show 직후부터 참이라 이 순간을 가리지 못한다.
    """
    handle = menu.windowHandle()
    return menu.isVisible() and handle is not None and handle.isExposed()


def while_button_menu_open(button, menu, during, timeout=UI_READY_TIMEOUT):
    """InstantPopup 단추의 메뉴는 누름 안의 exec에서 열린다. 표시가 끝난 메뉴에서 during()을 한 번 하고, 남아 있으면 닫는다."""
    deadline = monotonic() + timeout
    ran = []
    timer = QTimer()
    timer.setInterval(10)

    def run():
        if not popup_shown(menu):
            if menu.isVisible() and monotonic() >= deadline:
                timer.stop()
                menu.close()  # exec를 끝내 아래 단언이 실패하게 한다.
            return
        timer.stop()
        ran.append(True)
        try:
            during()
        finally:
            if menu.isVisible():
                menu.close()

    timer.timeout.connect(run)
    timer.start()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    timer.stop()
    assert ran, '메뉴가 열려 드러나지 않았다'
