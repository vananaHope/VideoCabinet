"""기본 진입점과 데이터 폴더별 중복 실행의 웹 셸 복원."""
import os
import subprocess
import sys

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from my_video_manager.single_instance import SingleInstance
from test_web_library_data import core
from test_web_library_page import window_factory


def test_second_default_process_activates_existing_web_window(window_factory, core):
    window = window_factory()
    instance = SingleInstance(core.database.parent)
    assert instance.start()
    instance.activated.connect(window.tray.open)
    activated = []
    instance.activated.connect(lambda: activated.append(True))
    window.hide()
    try:
        result = subprocess.run([sys.executable, '-m', 'my_video_manager', '--data-dir', str(core.database.parent)],
                                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        for _ in range(100):
            if activated:
                break
            QTest.qWait(20)
        assert activated and window.isVisible()
        assert window.pages.currentWidget() is window.web_host
        assert window.web_host.active_tab == 'library'
    finally:
        instance.close()
        instance.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
