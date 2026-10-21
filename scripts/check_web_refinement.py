"""#73 공개 코어와 WebEngine 흐름. --real은 desktop_lock.py --owner issue-73 안에서 실행."""
import argparse
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--real', action='store_true')
args = parser.parse_args()
assert args.offscreen != args.real
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine
from my_video_manager.ui import MainWindow
from my_video_manager.adapters import MpvPlayer, executable

OUT = Path(__file__).resolve().parents[1] / '.local/screens-73'
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])
if args.offscreen:
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))


class Media:
    def read(self, path):
        return MediaInfo(60, 'matroska')

    def capture(self, path, destination, seconds):
        image = QImage(32, 18, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGray)
        image.save(str(destination), 'JPG')


class Transcriber:
    def transcribe(self, *a, **kw):
        return TranscriberResult('ko', (TranscriptSegment(0, 55, '카드로 결재 할수 있어요.'),
                                       TranscriptSegment(55, 59, '한빛에서 결제 했어요.')))


class Translator:
    def translate(self, lines, *a, **kw):
        return tuple(TranslatedLine(l.id, l.text.replace('결재', '결제').replace('할수', '할 수')) for l in lines)


class PreviewPlayer:
    """offscreen은 앱의 표시/키 경로만 검사하고 실제 mpv 확인은 --real에서 한다."""
    def __init__(self, surface):
        self.options = (1, True)
    def play(self, path, start, *, subtitle):
        self.subtitle = subtitle
    def set_subtitle(self, path):
        self.subtitle = path
    def playback_options(self):
        return self.options
    def apply_playback_options(self, options):
        self.options = options
    def take_positions(self):
        return []
    def take_eof(self):
        return False
    def close(self):
        pass


def settle(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(predicate, seconds=30):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


with tempfile.TemporaryDirectory(prefix='mvm-73-ui-') as temporary:
    directory = Path(temporary)
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=directory / 'data/library.sqlite3', transcriber=Transcriber(), translator=Translator())
    path = directory / '가상 한국어 영상.mkv'
    if args.real:
        subprocess.run([executable('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=darkblue:s=640x360:r=24', '-t', '60', '-c:v', 'mpeg4', str(path)], check=True)
    else:
        path.write_bytes(b'virtual media')
    core.add_file(path)
    vid = core.videos()[0].id
    window = MainWindow(core, player_factory=MpvPlayer if args.real else PreviewPlayer)
    window.resize(1100, 720)
    window.show()
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    window.tray.timer.stop()
    host, dialogs = window.web_host, window.web_host.dialogs
    metrics = {'screens': [], 'checks': []}

    def js(code):
        values = []
        host.engine_page.runJavaScript(code, values.append)
        wait(lambda: bool(values))
        return values[0]

    def click(label):
        assert js("(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent === "
                  + json.dumps(label) + " && b.getClientRects().length); if (!b) return false; b.click(); return true; })()"), label
        settle()

    def capture(name):
        if args.real:
            return
        if window.pages.currentWidget() is host:
            js('window.refinementPainted = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.refinementPainted = true }))')
            wait(lambda: js('window.refinementPainted'))
        settle(250)
        pixmap = window.grab()
        if window.playback_page.help_panel.isVisible():
            panel = window.playback_page.help_panel
            painter = QPainter(pixmap)
            painter.drawPixmap(window.mapFromGlobal(panel.pos()), panel.grab())
            painter.end()
        assert (pixmap.width(), pixmap.height()) == (1100, 720)
        assert pixmap.save(str(OUT / f'{name}.png'))
        metrics['screens'].append(name + '.png')

    try:
        window.navigate_web_tab('queue')
        wait(lambda: js("!!document.getElementById('queue-list')"))
        queue = host.controllers['queue']
        queue.timer.stop()
        capture('queue-empty')
        core.request_subtitles(vid)
        assert core.process_next_subtitle().state == 'completed'
        queue.refresh()
        wait(lambda: js("document.body.innerText.includes('다듬기 · 대기')"))
        capture('queue-refinement')
        if args.offscreen:
            from dataclasses import replace
            original_items = core.subtitle_queue_items
            first = original_items()[0]
            rows = tuple(replace(first, video_id=i + 10000,
                title=f'{i:04} 아주 긴 가상 영상 제목 ' * 8, error='다듬기 안내 ' * 40) for i in range(5000))
            core.subtitle_queue_items = lambda: rows
            started = time.perf_counter()
            queue.refresh()
            metrics['5000_rows_refresh_ms'] = (time.perf_counter() - started) * 1000
            wait(lambda: js("document.querySelectorAll('[data-queue-row]').length === 5000"))
            capture('queue-5000-long')
            core.subtitle_queue_items = original_items
            queue.refresh()

        core.remove_from_subtitle_queue(vid)
        queue.refresh()
        # 옛 한국어 자막을 재현한다. 사용자가 뺀 세대는 별도 테스트에서 건너뛰기를 검증한다.
        with sqlite3.connect(core.database) as db:
            db.execute('DELETE FROM translation_omissions')
        db.close()
        click('기존 한국어 자막 모두 다듬기')
        wait(lambda: js("document.body.innerText.includes('한국어 영상 1개')"))
        assert not core.translation_queue()
        capture('queue-bulk-confirmation')
        click('취소')
        assert not core.translation_queue()
        click('기존 한국어 자막 모두 다듬기')
        click('다듬기 요청')
        wait(lambda: len(core.translation_queue()) == 1)
        result = core.process_next_translation()
        window.translations.completed(result)
        metrics['checks'].append('새 한국어 자동 등록과 기존 한국어 일괄 요청')
        line = core.transcript(vid).lines[0]
        core.edit_translation_line(vid, line.id, '카드로 결제할 수 있어요. 사용자가 고친 줄입니다.')
        window.navigate_web_tab('search')
        search = host.controllers['search']
        core.prepare_search()
        wait(lambda: js("!!document.getElementById('search-query')"))
        js("(() => { const e = document.getElementById('search-query'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, '결제'); e.dispatchEvent(new Event('input', {bubbles:true})); })()")
        wait(lambda: len(search.results) == 2)
        assert {r.source for r in search.results} == {'refinement'}
        wait(lambda: js("document.body.innerText.includes('다듬은 자막')"))
        capture('search-original-refined')
        metrics['checks'].append('검색 두 줄, 같은 ID 중복 없음과 다듬은 자막 우선')

        def review_scenario():
            wait(lambda: js("document.body.innerText.includes('다듬은 SRT 저장')"))
            assert js("document.body.innerText.includes('사용자가 고친 줄')")
            capture('review-export')
            click('다듬기')
            assert all(l.original.id != line.id or l.translation_reviewed for l in core.review_lines(vid))
            while core.translation_ready():
                core.process_next_translation()
            click('원어 줄 수정')
            wait(lambda: dialogs.stack[-1].kind == 'line')
            state = dialogs.snapshot()['dialog']
            dialogs.bridge.act(state['id'], 'save', json.dumps({'text': '원어를 바꿔요.'}))
            wait(lambda: js("document.body.innerText.includes('사용자 수정본 유지')"))
            capture('review-source-choice')
            click('사용자 수정본 유지')
            wait(lambda: dialogs.stack[-1].kind == 'review')
            assert core.transcript(vid).lines[0].text == '원어를 바꿔요.'
            assert core.review_lines(vid)[0].translation_reviewed
            saved = []
            original_save = dialogs.save_export
            dialogs.save_export = saved.append
            try:
                click('다듬은 SRT 저장')
                click('원어 SRT 저장')
                assert len(saved) == 2 and saved[0].text != saved[1].text
                assert saved[0].default_path != saved[1].default_path
            finally:
                dialogs.save_export = original_save
            click('닫기')

        failures = []
        def run_review():
            try:
                review_scenario()
            except BaseException as error:
                failures.append(error)
            finally:
                while dialogs.active:
                    dialogs.pop()
        QTimer.singleShot(200, run_review)
        dialogs.run('review', video_id=vid, jump=lambda *a: None, changed=lambda *a: None)
        if failures:
            raise failures[0]
        metrics['checks'].append('영상별 요청, 검수 표시, 원어 변경 시 수정본 유지, 원어/다듬은 SRT 선택')
        window.play_video(vid, start=1)
        window.activateWindow()
        window.surface.setFocus()
        wait(lambda: window.player is not None)
        if args.real:
            assert QTest.qWaitForWindowActive(window, 5000)
            wait(lambda: '결제' in (window.player._player.sub_text or ''))
            metrics['mpv_refined'] = window.player._player.sub_text
        assert core.playback_subtitle_language == 'translated'
        QTest.keyClick(window.surface, Qt.Key.Key_Period)
        wait(lambda: core.playback_subtitle_language == 'original')
        if args.real:
            wait(lambda: '원어를 바꿔요' in (window.player._player.sub_text or ''))
            metrics['mpv_original'] = window.player._player.sub_text
        QTest.keyClick(window.surface, Qt.Key.Key_Period)
        wait(lambda: core.playback_subtitle_language == 'translated')
        window.playback_page.refresh_details()
        assert '다듬은' in window.playback_page.subtitle_language_button.text()
        QTest.keyClick(window.surface, Qt.Key.Key_F1)
        capture('playback-refined-help')
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host)
        window.tray.show_queue()
        wait(lambda: host.active_tab == 'queue')
        metrics['checks'].append('마침표 키 원어/다듬은 전환, F1 안내, Esc 웹 복귀, 트레이 대기열 진입')
        (OUT / ('real.json' if args.real else 'offscreen.json')).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        window.tray.quit()
        window.deleteLater()
        app.processEvents()
        settle(300)
