"""웹 설정과 Qt 키 캡처의 연결. 기존 AppCore 저장·충돌 정책을 사용한다."""
import json
import math
import sqlite3

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from .app_version import current_version, RELEASES_URL

from .key_bindings import KeyBindings, RESERVED_KEYS, check_command_key, normalize_key
from .key_display import display_keys
from .qt_keys import key_name
from .web_settings_contract import SETTINGS
from .web_json import encode
from .web_page import WebPageController
from .web_update_data import update_status_data


class SettingsBridge(QObject):
    backupChanged = SETTINGS.signal('backupChanged')
    settingsChanged = SETTINGS.signal('settingsChanged')
    settingsFocusRequested = SETTINGS.signal('settingsFocusRequested')
    keyCaptured = SETTINGS.signal('keyCaptured')
    settingsError = SETTINGS.signal('settingsError')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @SETTINGS.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @SETTINGS.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @SETTINGS.slot('backupSnapshot')
    def backupSnapshot(self):
        return encode(self.page.backups.state)

    @SETTINGS.slot('backupAction')
    def backupAction(self, name, target, includeThumbnails):
        return self.page.backups.action(name, target, includeThumbnails)

    @SETTINGS.slot('saveKeys')
    def saveKeys(self, draft):
        try:
            proposed = json.loads(draft)
            rows = self.page.core.key_bindings()
            commands = {KeyBindings.identifier(row.command): row.command for row in rows}
            if not isinstance(proposed, dict) or set(proposed) != set(commands):
                raise ValueError('전체 명령의 키 배치가 필요합니다. 설정 화면을 다시 열어 주세요.')
            self.page.core.save_key_bindings({commands[key]: keys for key, keys in proposed.items()})
            window = self.page.window
            window.refresh_key_help()
            window.reel.update_label()
            window.reel.refresh_guidance()
            self.page.refresh()
            return self.snapshot()
        except (ValueError, TypeError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('beginCapture')
    def beginCapture(self, command):
        if not self.page.is_active():
            return encode({'error': '설정 화면에서 키를 바꿔 주세요.'})
        if command not in {KeyBindings.identifier(row.command) for row in self.page.core.key_bindings()}:
            return encode({'error': '설정 대상에 없는 명령입니다.'})
        self.page.capture_command = command
        return encode({'ok': True})

    @SETTINGS.slot('captureKey')
    def captureKey(self, key):
        return self.page.capture(key)

    @SETTINGS.slot('cancelCapture')
    def cancelCapture(self):
        self.page.cancel_capture()
        return encode({'ok': True})

    @SETTINGS.slot('setMinimum')
    def setMinimum(self, seconds):
        try:
            if self.page.library.worker is not None:
                raise ValueError('검사가 끝난 뒤 최소 길이를 바꿔 주세요.')
            if not math.isfinite(seconds) or not 0 <= seconds <= 86400 * 365:
                raise ValueError('최소 길이는 0~31536000초 사이로 입력하세요.')
            self.page.core.set_minimum_duration(seconds)
            self.page.library.refresh()
            self.page.refresh()
            return self.snapshot()
        except (ValueError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('setAutomaticDetection')
    def setAutomaticDetection(self, enabled):
        try:
            if self.page.library.worker is not None:
                raise ValueError('검사가 끝난 뒤 자동 감지를 바꿔 주세요.')
            self.page.window.folder_watch.set_enabled(enabled)
            self.page.refresh()
            return self.snapshot()
        except (ValueError, TypeError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('setRecommendationPeriod')
    def setRecommendationPeriod(self, criterion, days):
        # 글자를 수로 읽기만 하고 범위 검증은 코어가 한다. 추천 탭은 열릴 때 새 기간으로 다시 계산한다.
        try:
            try:
                value = float(days)
            except ValueError:
                raise ValueError('일수를 숫자로 입력하세요.') from None
            self.page.core.set_recommendation_period_days(criterion, value)
            self.page.refresh()
            return self.snapshot()
        except (ValueError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('resetRecommendationPeriod')
    def resetRecommendationPeriod(self, criterion):
        try:
            self.page.core.reset_recommendation_period_days(criterion)
            self.page.refresh()
            return self.snapshot()
        except (ValueError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('checkUpdate')
    def checkUpdate(self):
        try:
            # 이미 확인 중이면 새로 시작하지 않고 진행 중 상태를 돌려준다.
            self.page.window.updates.start()
            return self.snapshot()
        except (OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('setAutomaticUpdateCheck')
    def setAutomaticUpdateCheck(self, enabled):
        try:
            self.page.core.set_automatic_update_check_enabled(enabled)
            self.page.refresh()
            return self.snapshot()
        except (ValueError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @SETTINGS.slot('action')
    def action(self, name):
        if name not in ('translation', 'quit', 'releases') or self.busy:
            return encode({'error': '진행 중인 작업이 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        QTimer.singleShot(0, lambda: self.perform(name))
        return encode({'ok': True})

    def perform(self, name):
        try:
            if name == 'releases':
                if not QDesktopServices.openUrl(QUrl(RELEASES_URL)):
                    raise RuntimeError('브라우저에서 GitHub Release 페이지를 열지 못했습니다.')
            elif name == 'translation':
                self.page.window.translations.settings()
                self.page.refresh()
                self.page.focus_content()
            else:
                self.page.window.tray.quit()
        except Exception as error:
            self.settingsError.emit(str(error))
        finally:
            self.busy = False


class WebSettingsPage(WebPageController):
    tab = 'settings'
    default_focus = 'settings-category'

    def __init__(self, host):
        super().__init__(host)
        self.library = host.controllers['library']
        self.capture_command = None
        self.last_payload = None
        self.bridge = SettingsBridge(self)
        from .web_backup import BackupControls
        self.backups = BackupControls(self)
        self.focus_requested = self.bridge.settingsFocusRequested
        self.library.refreshed.connect(self.refresh)
        self.library.scan_state_changed.connect(lambda _: self.refresh())
        self.window.translations.video_changed.connect(lambda _: self.refresh())
        self.window.updates.changed.connect(self.refresh)
        # 한도 보류/실패처럼 video_changed가 없는 결과도 활성 화면에서 갱신한다.
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        host.register_page(self)

    def payload(self):
        queue = self.core.translation_queue()
        return dict(version=current_version(), releasesUrl=RELEASES_URL,
                    bindings=[dict(id=KeyBindings.identifier(row.command), label=row.label,
                    keys=list(row.keys), defaults=list(row.default_keys), display=display_keys(row.keys),
                    defaultDisplay=display_keys(row.default_keys), note=row.note) for row in self.core.key_bindings()],
                    minimum=self.core.minimum_duration, scanning=self.library.worker is not None,
                    automaticDetection=self.core.automatic_detection_enabled(),
                    recommendationPeriods=[self.recommendation_period(period) for period
                                           in self.core.recommendation_period_definitions()],
                    translationCli=self.core.translation_cli, translation=self.core.translation_settings(),
                    heldTranslations=sum(entry.state == 'held' for entry in queue),
                    failedTranslations=sum(entry.state == 'failed' for entry in queue),
                    update=update_status_data(self.core, self.window.updates))

    def recommendation_period(self, period):
        # 잘못된 저장값이 있어도 설정 화면은 열고, 그 기간 칸에서 고치게 한다.
        try:
            days, error = self.core.recommendation_period(period.criterion), ''
        except ValueError:
            days, error = None, '저장된 값이 잘못되어 이 기간으로 추천을 계산하지 못합니다. 새 값을 저장하거나 기본값으로 되돌리세요.'
        return dict(criterion=period.criterion, label=period.label, description=period.description, days=days, error=error,
                    defaultDays=period.default_days, minimumDays=period.minimum_days, maximumDays=period.maximum_days)

    def refresh(self):
        if not self.is_active():
            return
        payload = encode(self.payload())
        if payload != self.last_payload:
            self.last_payload = payload
            self.bridge.settingsChanged.emit(payload)

    def activated(self):
        # 비활성 동안 바뀐 값은 탭 진입의 refresh에서 반드시 보낸다.
        self.last_payload = None
        self.timer.start()

    def deactivated(self):
        self.timer.stop()
        self.cancel_capture()

    def cancel_capture(self):
        if self.capture_command is not None:
            result = dict(command=self.capture_command, key='', display='', cancelled=True, error='', continuing=False)
            self.capture_command = None
            self.bridge.keyCaptured.emit(encode(result))

    def capture(self, key):
        if self.capture_command is None or not self.is_active():
            return encode({'error': '먼저 키 바꾸기를 선택하세요.'})
        if key == 'Esc':
            self.cancel_capture()
            return encode({'ok': True})
        result = dict(command=self.capture_command, key='', display='', cancelled=False, error='', continuing=False)
        try:
            result['key'] = normalize_key(key)
            result['display'] = display_keys((result['key'],))
        except ValueError as error:
            if key.casefold() in {reserved.casefold() for reserved in RESERVED_KEYS}:
                result['error'] = str(error)
            else:
                result['error'] = '지원하는 키를 누르세요. 문자·숫자·방향키·기능키와 Ctrl/Alt/Shift 조합을 사용할 수 있습니다. Esc로 취소합니다.'
                result['continuing'] = True
        else:
            command = next(row.command for row in self.core.key_bindings()
                           if KeyBindings.identifier(row.command) == self.capture_command)
            try:
                check_command_key(command, result['key'])
            except ValueError as error:
                # 캡처를 이어 가 다른 조합을 바로 누를 수 있게 한다.
                result.update(key='', display='', error=f'{error} Esc로 취소합니다.', continuing=True)
        if not result['continuing']:
            self.capture_command = None
        self.bridge.keyCaptured.emit(encode(result))
        return encode({'ok': True})

    def capture_event(self, event):
        """Qt 예약 키 처리보다 먼저 호출한다. 조합키·자동 반복은 캡처하지 않는다."""
        if self.capture_command is None or not self.is_active():
            return False
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress:
            if not event.isAutoRepeat():
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel_capture()
                elif name := key_name(event):
                    self.capture(name)
                else:
                    self.capture('')
            return True
        return False
