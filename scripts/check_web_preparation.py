"""가짜 준비 어댑터로 배너·요청 대화상자를 검사한다. 실제 다운로드는 하지 않는다.

python scripts/check_web_preparation.py --offscreen
실창 입력 검사는 desktop_lock.py run 안에서 --verify로 실행한다(실창 캡처 없음).
데이터는 worktree 밖의 OS 임시 폴더만 사용한다.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--source', type=Path, help='실창 mpv 왕복에 사용할 읽기 전용 테스트 영상')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-92')
args = parser.parse_args()
if not (args.offscreen or args.verify):
    parser.error('--offscreen 또는 --verify를 지정하세요')
if args.verify and (not args.source or not args.source.is_file()):
    parser.error('--verify에는 실제 영상 --source가 필요합니다')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.cuda_runtime import PreparationError, PreparationProgress, SubtitlePreparation
from my_video_manager.runtime_assets import preparation_download_label
from my_video_manager.ui import MainWindow


class Media:
    def read(self, path):
        return MediaInfo(100, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(32, 18, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


class Adapter:
    fail = False

    def require_space(self, *args):
        pass

    def verify(self, *args):
        pass

    def extract(self, asset, wheel, target, cancellation, progress):
        (target / 'fixture.dll').write_bytes(b'fake DLL')

    def download(self, asset, target, cancellation, progress):
        if asset.name == 'model.bin':
            if self.fail:
                raise PreparationError('server', 'model.bin: HTTP Error 503 Service Unavailable\n'
                                       'https://example.invalid/model?token=hidden ' + '응답 지연 ' * 80)
            # 실제 청크 간격처럼 UI의 0.1초 신호 제한 뒤에 진행을 보낸다.
            time.sleep(0.15)
            progress(PreparationProgress('download', asset.name, asset.size // 3, asset.size))
            if not cancellation.wait(60):
                raise RuntimeError('검사에서 취소 입력을 받지 못했습니다.')
            raise PreparationError(getattr(cancellation, 'reason', 'cancelled'))
        target.write_bytes(b'fixture')
        progress(PreparationProgress('download', asset.name, asset.size, asset.size))


app = QApplication([])
if args.offscreen:
    for font in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / font))
args.output.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory(prefix='mvm-preparation-92-')
directory = Path(temporary.name)
core = AppCore(media=Media(), clock=datetime.now, database=directory / 'data/library.sqlite3')
for i in range(300):
    path = directory / f'영상 {i:03}.mkv'
    path.write_bytes(f'fixture {i}'.encode())
    core.add_file(path)
videos = core.videos()
core.rename_video(videos[0].id, '긴 제목으로 보는 자막 준비 화면 ' * 18)
adapter = Adapter()
service = SubtitlePreparation(core.database.parent, adapter=adapter, gpu_available=lambda: True)
original_prepare = core.prepare_subtitle_support
core.prepare_subtitle_support = lambda **kwargs: original_prepare(preparation=service, **kwargs)
window = MainWindow(core)
window.resize(1100, 720)
window.show()
controls = window.subtitles
controls.timer.stop()
window.translations.timer.stop()
window.tray.timer.stop()
controls.support_ready = False
window.navigate_web_tab('queue')
host = window.web_host
page = host.controllers['queue']
metrics = {'checks': [], 'screenshots': [], 'size': [1100, 720], 'realDownloads': False}


def wait(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('화면 조건 대기 시간 초과')


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def click(text):
    assert js(f"(() => {{ const b = [...document.querySelectorAll('button')].find(b => b.textContent === {json.dumps(text)} && b.getClientRects().length); if (!b) return false; b.click(); return true }})()"), text
    QTest.qWait(150)


def capture(name):
    assert js('document.documentElement.scrollWidth <= window.innerWidth')
    if not args.offscreen:
        return
    marker = f'capture-{time.monotonic_ns()}'
    js('requestAnimationFrame(() => requestAnimationFrame(() => '
       f'setTimeout(() => document.title = {json.dumps(marker)}, 150)))')
    wait(lambda: host.engine_page.title() == marker)
    # 배너 높이가 바뀐 프레임은 Windows offscreen 합성이 DOM보다 늦을 수 있다.
    host.view.update()
    QTest.qWait(350)
    path = args.output / f'{name}.png'
    assert window.grab().save(str(path))
    metrics['screenshots'].append(str(path))


try:
    wait(lambda: js("document.getElementById('queue-list') !== null"))
    page.timer.stop()
    QTest.qWait(200)
    capture('01-empty')
    # 실제 Python 안내가 웹 대화상자에 렌더되고 Esc로 취소되는지 확인한다.
    with patch.object(sys, 'frozen', True, create=True):
        host.dialogs.push('subtitles', video_id=videos[0].id)
        wait(lambda: js("document.querySelector('[role=dialog]') !== null"))
        wait(lambda: js(f'document.body.innerText.includes({json.dumps(preparation_download_label())})'))
        capture('02-first-request')
        QTest.keyClick(host.view.focusProxy() or host.view, Qt.Key.Key_Escape)
        wait(lambda: not host.dialogs.active)
    assert not core.subtitle_queue()
    metrics['checks'].append('첫 요청 크기 안내와 Esc 취소, 대기열 미변경')
    core.request_subtitles(videos[0].id)
    page.refresh()
    controls.process_queue()
    wait(lambda: controls.preparation['phase'] == 'download' and controls.preparation['asset'] == 'model.bin')
    wait(lambda: js("document.body.innerText.includes('파일 4/7')"))
    # 대기열 행에도 진행 막대가 있어 첫 [role=progressbar]는 그 행 막대다. 준비 막대를 접근 이름으로 집는다.
    bars = json.loads(js("JSON.stringify([...document.querySelectorAll('[role=progressbar]')].map(e => [e.getAttribute('aria-label'), e.getAttribute('aria-valuenow')]))"))
    metrics['progressbars'] = bars
    preparing = [value for label, value in bars if label == '자막 기능 준비 진행률']
    assert preparing == [str(controls.preparation['percent'])], (bars, controls.preparation['percent'])
    rows = [value for label, value in bars if label != '자막 기능 준비 진행률']
    assert rows and all(value == '0' for value in rows), bars
    capture('03-preparing-one')
    metrics['checks'].append('파일 4/7·전체 크기·누적 진행률과 progressbar aria 값')
    for video in videos[1:]:
        core.request_subtitles(video.id)
    page.refresh()
    wait(lambda: js("document.body.innerText.includes('대기 300개')"))
    capture('04-preparing-300-long-title')
    click('취소')
    wait(lambda: controls.preparation_worker is None)
    wait(lambda: js("document.body.innerText.includes('자막 기능 준비를 취소했습니다')"))
    capture('05-cancelled')
    assert len(core.subtitle_queue()) == 300
    assert service.status()['kind'] == 'cancelled'
    metrics['checks'].append('배너 취소와 queued 300개 보존, 영속 취소 결과')
    adapter.fail = True
    click('다시 시도')
    wait(lambda: controls.preparation_worker is None and controls.preparation['kind'] == 'server')
    wait(lambda: js("document.body.innerText.includes('HTTP Error 503')"))
    assert not js("document.body.innerText.includes('token=hidden')")
    capture('06-failed-detail')
    assert js("document.body.innerText.includes('서버가 일시적으로 응답하지 않습니다')")
    metrics['checks'].append('웹 다시 시도·HTTP 503 상세·민감 값 가림·긴 상세 말줄임')
    adapter.fail = False
    click('다시 시도')
    wait(lambda: controls.preparation['asset'] == 'model.bin')
    assert controls.shutdown()
    wait(lambda: controls.preparation_worker is None)
    previous = service.status()
    assert previous['kind'] == 'interrupted'
    from my_video_manager.subtitle_preparation_ui import failure_message
    controls.preparation_result(previous['kind'], failure_message(**previous))
    wait(lambda: js("document.body.innerText.includes('준비가 끝나기 전에 중단되었습니다')"))
    capture('08-interrupted')
    metrics['checks'].append('준비 중 종료·영속 중단 결과·중단됨 배너')
    controls.stopping = False
    for video in videos:
        core.remove_from_subtitle_queue(video.id)
    controls.process_queue()
    page.refresh()
    wait(lambda: js("document.querySelector('section[aria-label=\"자막 기능 준비\"]') === null"))
    capture('07-empty-after-failure')
    page.bridge.preparationAction('retry')
    assert controls.preparation_worker is None
    metrics['checks'].append('빈 대기열 배너 정리·오래된 다시 시도 호출 차단')
    if args.verify:
        window.activateWindow()
        window.raise_()
        assert QTest.qWaitForWindowActive(window, 5000)
        host.view.setFocus()
        from my_video_manager.web_contract import TABS
        for index, (tab, _) in enumerate(TABS):
            QTest.keyClick(host.view.focusProxy() or host.view, Qt.Key.Key_1 + index,
                           Qt.KeyboardModifier.ControlModifier)
            wait(lambda: host.active_tab == tab)
            QTest.qWait(100)
        metrics['checks'].append('실창 Ctrl+1~8 탭 이동')
        window.navigate_web_tab('queue')
        core.add_file(args.source)
        playable = next(video for video in core.videos()
                        if any(location.path == args.source.resolve() for location in video.locations))
        window.play_video(playable.id)
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(800)
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host and host.active_tab == 'queue')
        metrics['checks'].append('읽기 전용 테스트 영상 실제 mpv 재생·Esc 대기열 복귀')
        window.close()
        assert not window.isVisible()
        window.tray.show_queue()
        wait(lambda: js("document.activeElement.id === 'queue-list'"))
        metrics['checks'].append('실창 닫기·트레이 대기열 복귀·목록 포커스')
    (args.output / ('live-results.json' if args.verify else 'offscreen-results.json')).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
finally:
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    temporary.cleanup()
