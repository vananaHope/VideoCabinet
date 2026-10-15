"""백업 설정의 실제 WebEngine 동작·키보드·1100×720 화면 검사.

python scripts/check_web_backup.py --offscreen [--startup deferred]
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-65')
parser.add_argument('--startup', choices=('normal', 'applied', 'rejected', 'deferred', 'recovery'), default='normal')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow
from my_video_manager.backup import BackupBusyError, BackupRestoreResult, create_automatic_backup
from unittest.mock import patch


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


class Player:
    def __init__(self, surface):
        self.commands = []

    def play(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def execute(self, command):
        self.commands.append(command)


app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='backup-screen-', dir=ROOT / '.local'))
core = AppCore(database=workspace / 'data.sqlite3', media=Media(), clock=lambda: datetime.now(timezone.utc))
if args.startup == 'recovery':
    import errno
    import shutil
    import sys
    from my_video_manager.backup import apply_pending_backup_restore
    from my_video_manager.backup_recovery import BackupRecoveryDialog
    from my_video_manager.single_instance import SingleInstance
    from my_video_manager.theme import apply_theme
    apply_theme(app)
    archive = core.create_backup(workspace / 'healthy.zip').path
    core.request_backup_restore(archive)
    core.database.write_bytes(b'damaged header')
    instance = SingleInstance(workspace, app)
    assert instance.start()
    original_copy = shutil.copyfile
    def full(source, target, *args, **kwargs):
        if Path(source) == core.database:
            raise OSError(errno.ENOSPC, 'disk full')
        return original_copy(source, target, *args, **kwargs)
    with patch.object(shutil, 'copyfile', side_effect=full):
        result = apply_pending_backup_restore(core.database, instance=instance)
    assert result.status == 'deferred' and result.error_kind == 'disk_full'
    dialog = BackupRecoveryDialog(core.database, result, 'file is not a database')
    dialog.show()
    QTest.qWait(200)
    assert dialog.focusWidget() is dialog.retry
    dialog.grab().save(str(args.output / 'qt-backup-recovery.png'))
    dialog.cancel.click()
    assert not core.backup_inventory().pending
    assert core.database.read_bytes() == b'damaged header'
    dialog.grab().save(str(args.output / 'qt-backup-recovery-cancelled.png'))
    dialog.close()
    instance.close()
    print('복구 전용 Qt 화면: 실제 손상 DB + ENOSPC 결과, 초기 포커스, 예약 취소와 원본 보존 확인')
    sys.exit(0)
if args.startup != 'normal':
    archive = core.create_backup(workspace / 'startup.zip').path
    if args.startup == 'deferred':
        core.request_backup_restore(archive)
    core.set_backup_restore_startup_result(BackupRestoreResult(None, False, status=args.startup,
        error_message='저장 공간이 부족합니다. 공간을 확보한 뒤 다시 시도하세요.' if args.startup == 'deferred' else '백업 파일의 SHA-256이 일치하지 않습니다.' if args.startup == 'rejected' else None))
window = MainWindow(core, player_factory=Player)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
host = window.web_host
checks = []



def wait(predicate, message='조건 대기', timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(script):
    values = []
    host.engine_page.runJavaScript(script, values.append)
    wait(lambda: bool(values), script)
    return values[0]


def click(selector):
    window.activateWindow()
    host.view.setFocus()
    point = json.loads(js(f'JSON.stringify((() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) throw new Error("missing element"); e.scrollIntoView({{block:"nearest"}}); const r=e.getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})())'))
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle()


def key(code, modifiers=Qt.KeyboardModifier.NoModifier):
    target = QApplication.focusWidget()
    assert target is not None, '실제 키보드 포커스가 없습니다'
    if not args.offscreen:
        assert window.isActiveWindow(), '검사 창이 활성 창이 아닙니다'
    QTest.keyClick(target, code, modifiers)
    settle()


def navigate(tab):
    window.navigate_web_tab(tab)
    settle()


def category(name):
    click(f'[data-category="{name}"]')


def button(text):
    # 사용자에게 보이는 버튼만 선택한다. 다른 분류의 숨은 버튼은 제외한다.
    point = json.loads(js(f'JSON.stringify((() => {{ const e=[...document.querySelectorAll("button")].find(e=>e.textContent==={json.dumps(text)} && e.getClientRects().length); if(!e)return null; e.scrollIntoView({{block:"nearest"}}); const r=e.getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }})())'))
    if point is None:
        return False
    window.activateWindow()
    host.view.setFocus()
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle()
    return True


def content(selector):
    return js(f'document.querySelector({json.dumps(selector)}).textContent')


def capture(name):
    if not args.offscreen:
        return
    settle()
    web = window.grab().toImage()
    assert (web.width(), web.height()) == (1100, 720)
    web.save(str(args.output / f'web-{name}.png'))


def backup_state():
    return json.loads(bridge.backupSnapshot())


def finished():
    wait(lambda: not backup_state()['busy'], '백업 작업 완료')
    settle()


try:
    wait(lambda: host._frontend_ready and 'settings' in host._ready_pages, 'React 초기화')
    bridge = host.controllers['settings'].bridge
    navigate('settings')
    category('backup')
    finished()
    assert js('document.activeElement.dataset.category') == 'backup'
    if args.startup != 'normal':
        capture('backup-startup-' + args.startup)
        assert ({'applied': '적용됨', 'rejected': '거부됨', 'deferred': '미뤄짐'}[args.startup]) in content('[aria-label="마지막 시작의 백업 복원 결과"]')
        if args.startup == 'deferred':
            assert button('예약 취소')
            finished()
            assert not core.backup_inventory().pending
            assert '미뤄짐' in content('[aria-label="마지막 시작의 백업 복원 결과"]')
            assert not js('!!document.querySelector("[aria-label=\\"백업 복원 예약\\"]")')
            capture('backup-deferred-cancelled')
        checks.append('마지막 시작 결과와 현재 예약 분리: ' + args.startup)
    else:
        assert not core.automatic_backups()
        capture('backup-empty')
        path = workspace / '검사용 영상.mkv'
        path.write_bytes(b'backup UI sample')
        core.add_file(path)
        archive = workspace / '선택한 백업.zip'
        assert button('썸네일 포함: 꺼짐')
        entered, release = threading.Event(), threading.Event()
        real_create = core.create_backup
        def slow_create(*args, **kwargs):
            entered.set()
            if not release.wait(20):
                raise TimeoutError('화면 검사 제한 시간')
            return real_create(*args, **kwargs)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(archive), '')), patch.object(core, 'create_backup', side_effect=slow_create):
            try:
                assert button('백업 만들기')
                wait(entered.is_set)
                capture('backup-progress')
                assert '만드는 중' in content('[aria-label="백업 설정"] [role=status]')
                assert js('[...document.querySelectorAll("[aria-label=\\"백업 설정\\"] button")].every(e => e.disabled)')
                # 작업 중에도 다른 분류·페이지로 갔다 돌아올 수 있다.
                category('general')
                category('backup')
                assert not js('!!document.querySelector("[aria-label=\\"백업 설정\\"] [role=alert]")')
            finally:
                release.set()
                finished()
        assert archive.exists() and core.inspect_backup(archive).includes_thumbnails
        assert js('document.activeElement.hasAttribute("data-backup-create")')
        checks.append('작업자 진행·중복 동작 잠금·분류 왕복·썸네일 포함 저장')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(archive), '')), patch.object(core, 'create_backup', side_effect=BackupBusyError(3, 'source_changed')):
            assert button('백업 만들기')
            finished()
        assert '재생과 자막 처리를 멈추고 다시 시도' in content('[aria-label="백업 설정"] [role=alert]')
        capture('backup-error')
        category('general')
        category('backup')
        finished()
        assert '재생과 자막' in content('[aria-label="백업 설정"] [role=alert]')
        checks.append('쓰기 경합 실패 안내·재진입 보존·실패 후 조작 복구')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(archive), '')):
            assert button('백업 파일 선택')
            finished()
        assert '1개' in content('[aria-label="백업 미리보기"]')
        assert js('document.activeElement.hasAttribute("data-backup-preview")')
        capture('backup-preview')
        assert button('이 백업으로 복원 예약')
        wait(lambda: host.dialogs.blocks_shell_actions)
        assert js('document.activeElement.textContent') == '취소'
        capture('backup-confirm')
        reserved = [(Qt.Key(Qt.Key.Key_1 + index), Qt.KeyboardModifier.ControlModifier) for index in range(7)]
        reserved += [(Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier), (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier)]
        for code, modifier in reserved:
            key(code, modifier)
            assert host.active_tab == 'settings'
            assert js('!!document.querySelector("[role=alertdialog]")')
        key(Qt.Key.Key_Escape)
        wait(lambda: not host.dialogs.blocks_shell_actions)
        assert not core.backup_inventory().pending
        assert js('document.activeElement.textContent') == '이 백업으로 복원 예약'
        key(Qt.Key.Key_Return)
        wait(lambda: host.dialogs.blocks_shell_actions)
        key(Qt.Key.Key_Tab)
        assert js('document.activeElement.textContent') == '백업 복원 예약'
        key(Qt.Key.Key_Return)
        finished()
        assert core.backup_inventory().pending
        assert js('document.activeElement.hasAttribute("data-backup-pending")')
        capture('backup-pending')
        checks.append('미리보기·destructive 확인·시작 취소 포커스·예약 키 차단·Esc 복귀·Tab/Enter 예약')
        window.play_video(core.videos()[0].id)
        settle()
        key(Qt.Key.Key_Escape)
        assert host.active_tab == 'settings'
        assert js('document.querySelector("#settings-category [aria-current=true]").dataset.category') == 'backup'
        assert backup_state()['pending']
        window.hide()
        settle()
        window.tray.open()
        settle()
        # 공통 트레이 복원이 라이브러리로 이동하는 기존 동작은 별도 #82 범위다.
        assert backup_state()['pending']
        navigate('settings')
        assert js('document.querySelector("#settings-category [aria-current=true]").dataset.category') == 'backup'
        checks.append('재생 왕복·트레이 복원 후 다시 설정 진입에서도 백업 분류와 예약 유지 (#82 별도)')
        assert button('예약 취소')
        finished()
        assert not core.backup_inventory().pending
        assert not js('!!document.querySelector("[aria-label=\\"백업 복원 예약\\"]")')
        capture('backup-cancelled')
        checks.append('예약 취소 즉시 반영과 현재 데이터 유지')
        for index in range(5):
            create_automatic_backup(core.database, reason='before_migration' if index % 2 else 'before_restore')
        assert button('새로고침')
        finished()
        js('document.querySelector("[aria-label=\\"자동 백업\\"]").scrollIntoView({block:"end"})')
        capture('backup-many')
        assert len(backup_state()['automatic']) == 5
        assert 'DB 형식 변경 전' in content('[aria-label="자동 백업"]')
        assert button('복원 미리보기')
        finished()
        assert backup_state()['preview']
        assert button('선택 취소')
        finished()
        assert not backup_state()['preview']
        assert not core.backup_inventory().pending
        checks.append('최대 자동 백업 목록·시각/크기/이유·미리보기 선택 취소')
        assert js('document.documentElement.scrollWidth <= innerWidth')
        checks.append('긴 경로에서도 가로 넘침 없음')
    result = {'mode': 'offscreen' if args.offscreen else 'windows', 'startup': args.startup, 'checks': checks, 'passed': len(checks)}
    (args.output / f'{result["mode"]}-{args.startup}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
finally:
    if host.controllers['settings'].backups.busy:
        finished()
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

