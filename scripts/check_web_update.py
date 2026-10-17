"""설정의 업데이트 구역과 셸 새 버전 알림의 상태별 화면, 실제 Qt/WebEngine 포커스 검사 (독립 임시 라이브러리, 네트워크 없음).

스크린샷: python scripts/check_web_update.py --offscreen --output <폴더>
실창: desktop_lock.py run --owner issue-142 -- python scripts/check_web_update.py
확인 전·확인 중·없음·패치·전체·실패·공개 키 미설정·이전 버전에서 확인함과
새 버전 알림(패치·전체, 노트 있음·없음·긴 노트)·건너뛴 버전,
업데이트 내려받기(패치·전체)·취소 뒤·검증 실패·설치 전 확인·설치 준비 중·설정의 진행 상태와
다음 실행의 결과 안내(성공·전체 다시 시도·시간 초과)를 1100×720으로 남긴다.
내려받기는 이 실행에서만 만든 서명 키와 가짜 http, 보조 프로세스와 앱 종료는 가짜로 바꾼다.
네트워크·실제 설치 파일·브라우저를 쓰지 않고, 끝나면 .local의 임시 라이브러리를 지운다.
"""
import argparse
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-140')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from my_video_manager import update_manifest
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.update_check import LAST_CHECK_KEY, InstalledUpdateInfo, release_notes_summary
from my_video_manager.update_http import UpdateCheckError
from my_video_manager.update_install import UpdateBusyState, update_busy_state
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        pass


class Player:
    def __init__(self, surface):
        pass

    def close(self):
        pass


app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
(ROOT / '.local').mkdir(exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='update-', dir=ROOT / '.local'))
core = AppCore(database=workspace / 'data.sqlite3', media=Media(), clock=lambda: datetime.now(timezone.utc),
               update_installation=lambda: InstalledUpdateInfo('0.5.0', 'a' * 64))
gate = threading.Event()
started = []
failures = []


def gated_check():
    started.append(threading.get_ident())
    # 네트워크 대기를 흉내 낸다. 실제 서명 키가 없으므로 요청 없이 공개 키 미설정 실패로 끝난다.
    gate.wait(30)
    if failures:
        raise failures[0]
    return core.check_for_update()


SIGNING_KEY = Ed25519PrivateKey.generate()
FINGERPRINT = 'a' * 64
MB = 1024 * 1024


class ReleaseHttp:
    """서명한 0.6.0 매니페스트와 설치 파일을 256KB씩 보낸다. pause_at 바이트에서 gate가 열릴 때까지 멈춘다."""

    def __init__(self):
        self.bodies = {'MyVideoManager-Patch-0.6.0.exe': b'p' * (12 * MB),
                       'MyVideoManager-Setup-0.6.0.exe': b'f' * (48 * MB)}
        self.gate = threading.Event()
        self.gate.set()
        self.pause_at = None
        self.corrupt = False
        self.patch = True
        self.downloads = []

    def get(self, url, *, max_bytes):
        assert url.startswith('https://github.com/vananaHope/my-video-manager/releases/download/v0.6.0/')
        assets = {name: {'filename': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                  for name, body in self.bodies.items()}
        data = json.dumps({'schema_version': 1, 'version': '0.6.0', 'runtime_fingerprint': FINGERPRINT,
                           'previous_runtime_fingerprint': FINGERPRINT if self.patch else None,
                           'patch_available': self.patch,
                           'patch': assets['MyVideoManager-Patch-0.6.0.exe'] if self.patch else None,
                           'full': assets['MyVideoManager-Setup-0.6.0.exe']}).encode()
        return SIGNING_KEY.sign(data) if url.endswith('.sig') else data

    def download(self, url, *, size, write, cancellation=None):
        name = url.rsplit('/', 1)[1]
        self.downloads.append(name)
        body = self.bodies[name]
        step = 256 * 1024
        for start in range(0, len(body), step):
            if self.pause_at is not None and start >= self.pause_at:
                self.pause_at = None
                assert self.gate.wait(60), '내려받기 대기가 풀리지 않았습니다.'
            if cancellation is not None and cancellation.is_set():
                raise UpdateCheckError('cancelled')
            chunk = body[start:start + step]
            write(b'x' * len(chunk) if self.corrupt and start == 0 else chunk)


class Helper:
    def poll(self):
        return None

    def kill(self):
        pass


class GatedLauncher:
    """보조 프로세스 대신 계획만 읽고, gate가 열리면 준비 신호를 쓴다. 실제 PowerShell은 띄우지 않는다."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.starts = []

    def start(self, command, *, cwd):
        plan = json.loads(Path(command[command.index('-PlanPath') + 1]).read_text())
        self.starts.append(plan)
        assert self.gate.wait(60), '보조 프로세스 대기가 풀리지 않았습니다.'
        Path(plan['ready']).write_text('ready')
        return Helper()


http = ReleaseHttp()
launcher = GatedLauncher()
quits = []


def quit_app():
    # 실제 완전 종료 대신 기록만 한다. 보조 프로세스는 가짜라 아무것도 설치하지 않는다.
    quits.append(time.monotonic())
    return True


window = MainWindow(core, player_factory=Player, update_check_options=dict(
    startup_delay_ms=600_000, check=gated_check,
    install=dict(http=http, quit_app=quit_app,
                 prepare=dict(launcher=launcher, relaunch=('C:/Programs/MyVideoManager/my-video-manager.exe', [])))))
install = window.updates.install
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


def settle(ms=250):
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


def key(code):
    target = QApplication.focusWidget()
    assert target is not None, '실제 키보드 포커스가 없습니다'
    QTest.keyClick(target, code)
    settle()


def section_text():
    return js('document.querySelector(\'[aria-label="업데이트 설정"]\').innerText')


def notice_text():
    return js('document.querySelector(\'[aria-label="새 버전 알림"]\')?.innerText ?? ""')


def updates_text():
    return js('document.querySelector(\'[aria-label="업데이트 알림"]\')?.innerText ?? ""')


def dialog_text():
    return js('document.querySelector(\'[role="alertdialog"]\')?.innerText ?? ""')


def reset_install():
    """한 번 넘긴 설치는 이번 실행에서 다시 넘기지 않으므로, 다음 장면을 위해 처음 상태로 돌린다."""
    install.handed = False
    install._reset()
    install.result = install.result_log = None
    install.changed.emit()
    settle()


def show(record):
    if record is None:
        core.settings.reset(LAST_CHECK_KEY)
    else:
        checked = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        core.settings.set(LAST_CHECK_KEY, {'checked_at': checked, 'current_version': '0.5.0', 'latest_version': None,
                                           'download_size': None, 'failure_reason': None, **record})
    # 확인이 끝났을 때처럼 셸 알림과 설정 화면에 알린다.
    window.updates.changed.emit()
    settle()


def capture(name):
    assert js('document.documentElement.scrollWidth <= innerWidth'), f'{name}: 페이지가 가로로 넘칩니다'
    if not args.offscreen:
        return
    settle()
    image = window.grab().toImage()
    assert (image.width(), image.height()) == (1100, 720)
    image.save(str(args.output / f'update-{name}.png'))


try:
    wait(lambda: host._frontend_ready and 'settings' in host._ready_pages, 'React 초기화')
    window.navigate_web_tab('settings')
    settle()
    click('[data-category="update"]')
    show(None)
    text = section_text()
    assert '현재 버전 0.5.0' in text and '아직 확인하지 않았습니다' in text and '시작할 때 확인: 켜짐' in text
    capture('1-before')
    checks.append('확인 전: 현재 버전·확인 전 문구·자동 확인 기본 켬')

    # 키보드로 지금 확인을 누르면 진행 중에도 포커스가 버튼에 남고 두 번째 요청은 새 작업자를 만들지 않는다.
    js('document.getElementById("settings-update-check").focus()')
    host.view.setFocus()
    key(Qt.Key.Key_Return)
    wait(lambda: window.updates.checking, '확인 시작')
    wait(lambda: '확인 중' in section_text(), '확인 중 표시')
    assert js('document.activeElement.id') == 'settings-update-check'
    assert js('document.getElementById("settings-update-check").getAttribute("aria-disabled")') == 'true'
    key(Qt.Key.Key_Return)
    assert window.updates.checking and len(started) == 1 and started[0] != threading.get_ident()
    capture('2-checking')
    gate.set()
    wait(lambda: not window.updates.checking, '확인 끝')
    settle()
    assert js('document.activeElement.id') == 'settings-update-check'
    text = section_text()
    assert '서명 키가 아직 설정되지 않았습니다' in text and '확인하지 못했습니다' not in text
    capture('7-failed-no-public-key')
    checks.append('확인 중: 버튼 aria-disabled·포커스 유지·중복 없음 → 공개 키 미설정은 조용한 정보 안내')

    show({'kind': 'none', 'latest_version': '0.5.0'})
    assert '최신 버전입니다' in section_text()
    capture('3-none')
    show({'kind': 'patch', 'latest_version': '0.6.0', 'download_size': 12 * 1024 * 1024})
    text = section_text()
    assert '새 버전이 있습니다 · 0.6.0' in text and '패치 설치 파일' in text and '12.0 MB' in text
    capture('4-patch')
    show({'kind': 'full', 'latest_version': '0.6.0', 'download_size': 310 * 1024 * 1024})
    text = section_text()
    assert '새 버전이 있습니다 · 0.6.0' in text and '전체 설치 파일' in text
    capture('5-full')
    show({'kind': 'failed', 'failure_reason': 'http_429'})
    text = section_text()
    assert '업데이트를 확인하지 못했습니다' in text and 'HTTP 429' in text
    capture('6-failed')
    show({'kind': 'patch', 'current_version': '0.4.1', 'latest_version': '0.5.0', 'download_size': 1024})
    text = section_text()
    assert '이전 버전(0.4.1)에서 확인한 결과입니다' in text and '새 버전이 있습니다' not in text
    assert js('document.getElementById("settings-update-install") === null') and notice_text() == ''
    capture('8-stale')
    checks.append('없음·패치·전체·실패·이전 버전에서 확인함(업데이트 안내·셸 알림 없음) 표시')

    # 셸 새 버전 알림: 어느 탭에서나 탭 아래 안내 영역에 보인다.
    notes = release_notes_summary('## 수정\n\n- **재생 위치** 저장 문제를 고쳤습니다 (#150)\n- [자막 대기열](https://example.com) 안내 중복을 정리했습니다')
    patch = {'kind': 'patch', 'latest_version': '0.6.0', 'download_size': 12 * 1024 * 1024, 'release_notes': notes}
    window.navigate_web_tab('library')
    show(patch)
    text = notice_text()
    assert '새 버전이 있습니다 · 0.6.0' in text and '패치 설치 파일 12.0 MB' in text and '재생 위치 저장 문제를 고쳤습니다' in text
    assert all(label in text for label in ('업데이트', '나중에', '이 버전 건너뛰기')) and 'https://' not in text
    capture('notice-1-patch-notes')
    window.navigate_web_tab('statistics')
    settle()
    assert '새 버전이 있습니다 · 0.6.0' in notice_text()
    window.navigate_web_tab('library')
    show({'kind': 'full', 'latest_version': '0.6.0', 'download_size': 310 * 1024 * 1024})
    text = notice_text()
    assert '전체 설치 파일 310.0 MB' in text and '전체 보기' not in text
    capture('notice-2-full-no-notes')
    checks.append('셸 알림: 패치(노트 있음)·전체(노트 없음), 다른 탭에서도 보임, 링크 주소 없음')

    long_body = '\n'.join(f'- 긴 릴리스 노트 항목 {index}: ' + '설명이 아주 길게 이어집니다. ' * 6 for index in range(20))
    show({**patch, 'release_notes': release_notes_summary(long_body)})
    assert js('document.documentElement.scrollWidth <= innerWidth')
    assert '전체 보기' in notice_text()
    capture('notice-3-long-notes')
    click('[aria-label="새 버전 알림"] [aria-expanded="false"]')
    region = json.loads(js('JSON.stringify(document.querySelector(\'[aria-label="앱 안내"]\').getBoundingClientRect())'))
    assert region['height'] <= 720 / 4 + 1, region
    capture('notice-4-long-notes-expanded')
    # 저장값을 고쳐 HTML을 넣으면 다시 요약한 값과 달라 그 기록을 버린다(요소도 글자도 보이지 않는다).
    show({**patch, 'release_notes': '<img src=x onerror="document.title=1"><b>굵게</b>'})
    assert js('document.querySelector(\'[aria-label="업데이트 알림"] img, [aria-label="업데이트 알림"] b\') === null')
    assert notice_text() == '' and core.last_update_check() is None
    checks.append('긴 노트는 두 줄로 접고 전체 보기, 펼쳐도 안내 영역 1/4 안, 고친 저장 노트(HTML)는 기록째 버림')

    # 나중에: 키보드로 고르면 알림이 사라지고 포커스는 현재 탭으로 간다. 다음 확인 결과에서 다시 알린다.
    show(patch)
    js('document.getElementById("update-notice-later").focus()')
    host.view.setFocus()
    key(Qt.Key.Key_Return)
    wait(lambda: notice_text() == '', '나중에')
    assert js('document.activeElement.dataset.tab') == 'library'
    assert core.skipped_update_version() is None
    show(patch)
    assert '새 버전이 있습니다 · 0.6.0' in notice_text()
    checks.append('나중에: 알림 숨김·포커스 현재 탭·다음 확인에서 다시 알림')

    # 업데이트: 브라우저를 열지 않고 내려받기를 시작한다(이 실행만의 서명 키와 가짜 http).
    original_key = update_manifest.UPDATE_PUBLIC_KEY
    update_manifest.UPDATE_PUBLIC_KEY = SIGNING_KEY.public_key().public_bytes_raw()
    core.update_installation = lambda: InstalledUpdateInfo('0.5.0', FINGERPRINT)
    try:
        http.gate.clear()
        http.pause_at = 5 * MB
        click('#update-notice-install')
        wait(lambda: '5.0 MB / 12.0 MB' in updates_text(), '패치 내려받기 진행률')
        text = updates_text()
        assert '업데이트 내려받는 중 · 0.6.0' in text and '패치 설치 파일' in text and '41%' in text and notice_text() == ''
        assert js('document.activeElement.dataset.tab') == 'library'
        # 같은 업데이트를 다시 골라도(설정·다른 창 상태) 두 번째 내려받기는 없다.
        window.web_host.bridge.updateChoice('update', '0.6.0')
        settle()
        assert http.downloads == ['MyVideoManager-Patch-0.6.0.exe']
        capture('install-1-downloading-patch')
        # 설정 업데이트 구역에도 같은 진행이 보인다.
        window.navigate_web_tab('settings')
        settle()
        click('[data-category="update"]')
        section = section_text()
        assert '업데이트 내려받는 중 · 0.6.0' in section and '5.0 MB / 12.0 MB' in section and '나중에' not in section
        capture('install-2-settings-progress')
        # 취소: 키보드로 누르면 받던 파일을 지우고 새 버전 알림이 돌아온다.
        js('document.getElementById("settings-update-progress-cancel").focus()')
        host.view.setFocus()
        key(Qt.Key.Key_Return)
        wait(lambda: '취소 중' in section_text(), '취소 중')
        http.gate.set()
        wait(lambda: install.phase == 'idle', '취소 끝')
        settle()
        assert '새 버전이 있습니다 · 0.6.0' in notice_text() and '업데이트 내려받기를 취소했습니다' in js('document.body.innerText')
        assert not list((core.database.parent / 'updates' / 'download').glob('*'))
        assert js('document.activeElement.id') == 'settings-update-check'
        capture('install-3-cancelled')
        window.statusBar().clearMessage()  # 앱에서는 5초 뒤 사라지는 작업 알림이다. 다음 장면을 가리지 않게 지운다.
        checks.append('업데이트: 내려받기 시작(브라우저 없음)·진행률·두 번 눌러도 하나·설정에 같은 진행·취소 뒤 파일 정리와 알림 복귀')

        # 검증 실패: 받은 파일이 매니페스트와 다르면 지우고 다시 시도를 보인다.
        window.navigate_web_tab('library')
        settle()
        http.corrupt = True
        click('#update-notice-install')
        wait(lambda: install.phase == 'failed', '검증 실패')
        settle()
        text = updates_text()
        assert '업데이트하지 못했습니다 · 0.6.0' in text and 'SHA-256' in text and '다시 시도' in text
        capture('install-4-hash-mismatch')
        http.corrupt = False
        click('[aria-label="업데이트 알림"] [aria-label="안내 닫기"]')
        wait(lambda: install.phase == 'idle' and '새 버전이 있습니다' in notice_text(), '실패 닫기')
        checks.append('검증 실패: 이유와 다시 시도, 닫으면 새 버전 알림 복귀')

        # 전체 설치 파일 내려받기(설치본 런타임이 바뀌어 패치를 못 쓰는 릴리스).
        http.patch = False
        show({'kind': 'full', 'latest_version': '0.6.0', 'download_size': 48 * MB})
        http.gate.clear()
        http.pause_at = 20 * MB
        click('#update-notice-install')
        # 화면 값은 정수 퍼센트가 바뀔 때 오므로 멈춘 자리(20MB)의 퍼센트로 기다린다.
        wait(lambda: '/ 48.0 MB · 41%' in updates_text(), '전체 내려받기 진행률')
        assert '전체 설치 파일' in updates_text()
        capture('install-5-downloading-full')
        http.patch = True

        # 설치 전 확인: 막는 작업과 재시작 뒤 이어질 대기 항목을 보여 주고 고르게 한다.
        def entry(state, kind='translation'):
            return type('Entry', (), {'state': state, 'kind': kind})()
        core.busy_reasons_for_update = lambda: update_busy_state(
            playing=True, transcriptions=(entry('transcribing'), entry('queued'), entry('queued')),
            translations=(entry('translating'), entry('held')))
        window.subtitles.preparation_worker = object()
        launcher.gate.clear()
        http.gate.set()
        wait(lambda: install.phase == 'confirm', '설치 전 확인')
        wait(lambda: '지금 설치' in dialog_text(), '확인 대화')
        text = dialog_text()
        assert '영상 재생, 받아쓰기, 번역, 자막 기능 준비' in text and '대기 중인 받아쓰기 2개·번역·다듬기 1개' in text
        assert js('document.activeElement.innerText') == '나중에' and window.web_host.dialogs.blocks_shell_actions
        capture('install-6-confirm-busy')
        key(Qt.Key.Key_Escape)  # 닫기는 나중에와 같다
        wait(lambda: install.phase == 'ready', '나중에')
        assert '설치 파일이 준비되었습니다 · 0.6.0' in updates_text() and launcher.starts == []
        capture('install-7-ready-later')
        click('#update-progress-now')
        wait(lambda: '지금 설치' in dialog_text(), '다시 확인')
        click('[role="alertdialog"] button:last-child')
        wait(lambda: install.phase == 'preparing' and launcher.starts, '설치 준비 중')
        settle()
        assert '설치 준비 중 · 0.6.0' in updates_text() and quits == []
        capture('install-8-preparing')
        launcher.gate.set()
        wait(lambda: quits, '완전 종료')
        assert len(launcher.starts) == 1 and launcher.starts[0]['installer'].endswith('MyVideoManager-Setup-0.6.0.exe')
        window.subtitles.preparation_worker = None
        del core.busy_reasons_for_update
        checks.append('전체 내려받기·설치 전 확인(막는 작업+대기 항목, 시작 포커스 나중에, Esc=나중에)·준비됨·설치 준비 중·완전 종료 한 번')
        reset_install()

        # 다음 실행의 결과 안내: 시작할 때처럼 기록을 읽고 지운다.
        updates = core.database.parent / 'updates'

        def next_start(record, result, log=True):
            updates.mkdir(parents=True, exist_ok=True)
            (updates / 'install.json').write_text(json.dumps({'started_at': datetime.now(timezone.utc).isoformat(), **record}))
            (updates / 'install-result.json').write_text(json.dumps(result))
            if log:
                (updates / 'installer.log').write_text('log')
            else:
                (updates / 'installer.log').unlink(missing_ok=True)  # 설치 프로그램이 돌지 않아 기록이 없다
            install.load_result()
            install.changed.emit()
            settle()

        core.update_installation = lambda: InstalledUpdateInfo('0.6.0', FINGERPRINT)
        next_start({'version': '0.6.0', 'kind': 'patch'}, {'exit_code': 0})
        assert '0.6.0 버전으로 업데이트했습니다' in updates_text() and not updates.exists()
        capture('result-1-installed')
        click('[aria-label="업데이트 알림"] [aria-label="안내 닫기"]')
        wait(lambda: install.result is None, '성공 안내 닫기')
        core.update_installation = lambda: InstalledUpdateInfo('0.5.0', FINGERPRINT)
        next_start({'version': '0.6.0', 'kind': 'patch'}, {'exit_code': 7})
        text = updates_text()
        assert '패치를 적용하지 못했습니다' in text and '전체 설치 파일로 다시 시도' in text and 'installer.log' in text
        assert notice_text() == '' and sorted(path.name for path in updates.iterdir()) == ['installer.log']
        capture('result-2-retry-full')
        http.downloads.clear()
        http.gate.clear()
        http.pause_at = 4 * MB
        click('#update-result-retry')
        wait(lambda: http.downloads == ['MyVideoManager-Setup-0.6.0.exe'], '전체 다시 시도')
        install.act('cancel')
        http.gate.set()
        wait(lambda: install.phase == 'idle', '다시 시도 취소')
        next_start({'version': '0.6.0', 'kind': 'full'}, {'error': 'installer_timeout'}, log=False)
        text = updates_text()
        assert '앱을 다시 켜 보세요' in text and '다시 시도' not in text and 'installer.log' not in text
        capture('result-3-installer-timeout')
        click('[aria-label="업데이트 알림"] [aria-label="안내 닫기"]')
        wait(lambda: install.result is None and '새 버전이 있습니다' in notice_text(), '시간 초과 안내 닫기')
        checks.append('다음 실행 결과: 성공(기록 모두 지움)·패치 거부(전체 다시 시도, 로그 위치·로그만 남김)·시간 초과(다시 켜 보세요)')
    finally:
        update_manifest.UPDATE_PUBLIC_KEY = original_key
        http.gate.set()
        launcher.gate.set()
        window.subtitles.preparation_worker = None

    # 이 버전 건너뛰기 → 설정에 건너뛴 버전과 건너뛰기 취소 → 다시 선택지.
    show(patch)
    click('#update-notice-skip')
    wait(lambda: notice_text() == '', '건너뛰기')
    assert core.skipped_update_version() == '0.6.0'
    window.navigate_web_tab('settings')
    settle()
    text = section_text()
    assert '건너뛴 버전입니다 · 0.6.0' in text and '건너뛰기 취소' in text and notice_text() == ''
    capture('settings-skipped')
    js('document.getElementById("settings-update-unskip").focus()')
    host.view.setFocus()
    key(Qt.Key.Key_Return)
    wait(lambda: '새 버전이 있습니다 · 0.6.0' in notice_text(), '건너뛰기 취소')
    assert core.skipped_update_version() is None
    assert js('document.activeElement.id') == 'settings-update-skip'
    text = section_text()
    assert all(label in text for label in ('업데이트', '나중에', '이 버전 건너뛰기', '재생 위치'))
    capture('settings-available')
    click('#settings-update-later')
    wait(lambda: notice_text() == '', '설정에서 나중에')
    assert '나중에' not in section_text() and js('document.activeElement.id') == 'settings-update-install'
    checks.append('건너뛰기: 설정에 건너뛴 버전·건너뛰기 취소, 취소 뒤 선택지와 포커스, 설정에서 나중에')

    click('#settings-update-automatic-toggle')
    wait(lambda: not core.automatic_update_check_enabled(), '자동 확인 끄기')
    settle()
    assert '시작할 때 확인: 꺼짐' in section_text()
    assert js('document.activeElement.id') == 'settings-update-automatic-toggle'
    capture('9-automatic-off')
    click('#settings-update-automatic-toggle')
    wait(core.automatic_update_check_enabled, '자동 확인 켜기')
    checks.append('시작할 때 확인 끄기/켜기 저장과 포커스 유지')

    # 닫은 저장 실패 안내는 다음 확인(직접 누름·시작 확인)에서 같은 문구로 나면 다시 보인다.
    saving_error = '업데이트 확인 결과를 저장하지 못했습니다: database is locked'
    failures.append(sqlite3.OperationalError('database is locked'))
    for attempt in ('click', 'click-again', 'startup'):
        if attempt == 'startup':
            gate.clear()
            window.updates.start()
            wait(lambda: '확인 중' in section_text(), '시작 확인 표시')
            gate.set()
        else:
            click('#settings-update-check')
        wait(lambda: not window.updates.checking, '확인 끝')
        wait(lambda: saving_error in section_text(), f'{attempt}: 저장 실패 안내')
        if attempt == 'click':
            capture('10-save-error')
        click('[aria-label="업데이트 설정"] [aria-label="안내 닫기"]')
        assert saving_error not in section_text()
    failures.clear()
    checks.append('닫은 저장 실패 안내가 다음 확인에서 다시 보임(직접 누름·시작 확인)')

    click('[data-category="general"]')
    general = js('document.querySelector(\'[aria-label="일반 설정"]\').innerText')
    assert '자동 감지' in general and '완전 종료' in general and '업데이트를 확인' not in general
    checks.append('일반 구역은 그대로')
    result = {'mode': 'offscreen' if args.offscreen else 'windows', 'checks': checks, 'passed': len(checks)}
    (args.output / f'update-{result["mode"]}-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
finally:
    gate.set()
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # 이 실행이 만든 임시 라이브러리(.local/update-*)를 남기지 않는다.
    shutil.rmtree(workspace, ignore_errors=True)
