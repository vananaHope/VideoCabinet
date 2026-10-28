"""창·트레이·웹 셸·앱 수명 경고가 같은 표시 이름을 보인다."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys

from PySide6.QtCore import QLockFile

import my_video_manager
from my_video_manager.app_version import DISPLAY_NAME, current_version
from my_video_manager.single_instance import SingleInstance
from qt_wait import wait_for
from test_emergency_hide_ui import app, window
from test_emergency_hide_dialogs_ui import js


def test_display_name_is_fixed():
    # 상수가 엉뚱한 값으로 바뀌어도 아래 단언들이 함께 통과하지 않게 정한 이름을 한 번 고정한다.
    assert DISPLAY_NAME == '상영실'


def test_window_tray_and_web_shell_show_display_name(window):
    assert window.windowTitle() == '상영실'
    assert window.tray.icon.toolTip() == f'{DISPLAY_NAME} · 자막 대기열'
    wait_for(lambda: window.loaded)
    assert js(window, 'document.title') == DISPLAY_NAME
    wait_for(lambda: js(window, "document.querySelector('header span')?.textContent ?? ''") == DISPLAY_NAME)
    window.navigate_web_tab('settings')
    headings = """JSON.stringify([...document.querySelectorAll('[data-page="settings"] h3')].map(e => e.textContent))"""
    wait_for(lambda: f'{DISPLAY_NAME} · {current_version()}' in json.loads(js(window, headings)))


def test_served_document_title_is_display_name_before_scripts_run():
    # 웹 셸이 여는 빌드 결과의 정적 제목이다. 스크립트가 바꾸기 전 첫 화면에도 옛 이름이 보이지 않는다.
    html = (Path(my_video_manager.__file__).parent / 'web/index.html').read_text(encoding='utf-8')
    assert f'<title>{DISPLAY_NAME}</title>' in html


def test_tray_notifications_use_display_name(window):
    window.close()
    assert window.balloons[-1][0] == DISPLAY_NAME
    assert '트레이에서 계속 처리' in window.balloons[-1][1]
    window.tray.notify('검사를 마쳤습니다.')
    assert window.balloons[-1] == (DISPLAY_NAME, '검사를 마쳤습니다.')


def test_single_instance_failure_guidance_names_display_name(tmp_path):
    # 잠금은 다른 프로세스가 가졌지만 활성화 서버가 없는 상태: 연결 실패 안내가 작업 관리자의 앱 이름을 가리킨다.
    lock = QLockFile(str(tmp_path / 'instance.lock'))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    instance = SingleInstance(tmp_path)
    try:
        instance.start()
    except RuntimeError as error:
        assert f'작업 관리자에서 {DISPLAY_NAME} 프로세스가' in str(error)
    else:
        raise AssertionError('연결 실패 안내가 없습니다')
    finally:
        lock.unlock()
        instance.deleteLater()


class _Application:
    def __init__(self, *args):
        self.aboutToQuit = SimpleNamespace(connect=lambda callback: None)

    def setWindowIcon(self, icon):
        pass

    def setQuitOnLastWindowClosed(self, value):
        pass

    def property(self, name):
        return name == 'backupRestartRequested'

    def exec(self):
        return 0


def _patch_startup(monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    from my_video_manager import theme
    monkeypatch.setattr(sys, 'argv', ['my-video-manager', '--data-dir', str(tmp_path)])
    monkeypatch.setattr(QtWidgets, 'QApplication', _Application)
    monkeypatch.setattr(theme, 'apply_theme', lambda app: None)
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'critical', lambda *args: errors.append(args[1:]))
    return errors


def test_startup_failure_warning_title_is_display_name(monkeypatch, tmp_path):
    from my_video_manager import __main__, single_instance
    errors = _patch_startup(monkeypatch, tmp_path)

    class Instance:
        def __init__(self, directory, parent):
            pass

        def start(self):
            raise RuntimeError('잠금 파일을 열 수 없습니다.')

        def close(self):
            pass
    monkeypatch.setattr(single_instance, 'SingleInstance', Instance)
    assert __main__.main() == 1
    assert errors == [(DISPLAY_NAME, '시작하지 못했습니다.\n잠금 파일을 열 수 없습니다.')]


def test_restart_failure_warning_title_is_display_name(monkeypatch, tmp_path):
    from PySide6 import QtCore
    from my_video_manager import __main__, app_logging, backup_recovery, single_instance, ui
    errors = _patch_startup(monkeypatch, tmp_path)
    instance = SimpleNamespace(start=lambda: True, close=lambda: None, activated=SimpleNamespace(connect=lambda slot: None))
    monkeypatch.setattr(single_instance, 'SingleInstance', lambda directory, parent: instance)
    monkeypatch.setattr(app_logging, 'configure_app_logging', lambda directory: None)
    monkeypatch.setattr(backup_recovery, 'open_with_backup_recovery', lambda *args: object())
    monkeypatch.setattr(ui, 'MainWindow', lambda core: SimpleNamespace(tray=SimpleNamespace(open=None), show=lambda: None))
    monkeypatch.setattr(QtCore, 'QProcess', SimpleNamespace(startDetached=lambda program, arguments: (False, 0)))
    assert __main__.main() == 1
    title, message = errors[0]
    assert title == DISPLAY_NAME and message.startswith('다시 시작하지 못했습니다.')
