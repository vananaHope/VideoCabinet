"""설정의 업데이트 구역과 셸 새 버전 알림의 상태별 화면, 실제 Qt/WebEngine 포커스 검사 (독립 임시 라이브러리, 네트워크 없음).

스크린샷: python scripts/check_web_update.py --offscreen --output <폴더>
실창: desktop_lock.py run --owner issue-141 -- python scripts/check_web_update.py
확인 전·확인 중·없음·패치·전체·실패·공개 키 미설정·이전 버전에서 확인함과
새 버전 알림(패치·전체, 노트 있음·없음·긴 노트)·건너뛴 버전을 1100×720으로 남긴다. 브라우저는 열지 않는다.
"""
import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
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
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.update_check import LAST_CHECK_KEY, InstalledUpdateInfo, release_notes_summary
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


opened = []


def open_url(url):
    # "업데이트"의 임시 동작(릴리스 페이지 열기)을 가로채 실제 브라우저를 열지 않는다.
    opened.append(url.toString())
    return True


window = MainWindow(core, player_factory=Player,
                    update_check_options=dict(startup_delay_ms=600_000, check=gated_check, open_url=open_url))
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
    # 저장값을 고쳐 HTML을 넣어도 글자로만 보인다.
    show({**patch, 'release_notes': '<img src=x onerror="document.title=1"><b>굵게</b>'})
    assert js('document.querySelector(\'[aria-label="새 버전 알림"] img, [aria-label="새 버전 알림"] b\') === null')
    assert '<img src=x' in notice_text()
    checks.append('긴 노트는 두 줄로 접고 전체 보기, 펼쳐도 안내 영역 1/4 안, HTML은 글자로만')

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

    # 업데이트: #142 전까지 그 버전의 릴리스 페이지를 연다(가로챔).
    click('#update-notice-install')
    wait(lambda: opened, '릴리스 페이지')
    assert opened == ['https://github.com/vananaHope/my-video-manager/releases/tag/v0.6.0'] and notice_text() == ''
    checks.append('업데이트: 릴리스 페이지 열기(임시)·알림 숨김')

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
