"""#196 추천 탭 1100×720 배치와 실제 Chromium 키 입력·mpv 왕복 검사.

스크린샷: python scripts/check_web_recommend.py --offscreen
실창: desktop_lock.py run --owner issue-196 -- python scripts/check_web_recommend.py --verify --no-screenshots
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true', help='실창 Ctrl+2·mpv 왕복·긴급 탈출·창 닫기 복귀')
parser.add_argument('--no-screenshots', action='store_true')
parser.add_argument('--output', type=Path, default=ROOT / '.local/screens-196')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import executable
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.ui import MainWindow
from my_video_manager.web_tokens import web_tokens

app = QApplication([])
if args.offscreen and os.name == 'nt':
    # Windows offscreen 플러그인은 시스템 글꼴을 자동으로 열거하지 않는다.
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
args.output.mkdir(parents=True, exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix='fixture-', dir=args.output))
checks = []
layouts = {}
windows = []
# 번호가 없는 제목만 써서 자동 시리즈 묶기에 걸리지 않게 한다.
WORDS = ('바다', '숲', '음악', '도시', '과학', '역사', '여행', '요리', '그림', '언어')
KINDS = ('산책', '노트', '강의', '기록', '여행기', '실험', '수업', '이야기', '탐방', '연습')


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Media:
    def read(self, path):
        return MediaInfo(60, 'mp4')

    def capture(self, path, destination, seconds):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor.fromHsv(sum(path.stem.encode()) % 360, 90, 80))
        painter = QPainter(image)
        painter.setPen(QColor(web_tokens()['colors']['foreground']))
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, path.stem[:12])
        painter.end()
        image.save(str(destination), 'JPG')


def wait_until(predicate, timeout=20):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(window, code):
    result = []
    window.web_host.engine_page.runJavaScript(code, result.append)
    wait_until(lambda: bool(result))
    return result[0]


def read(window, expression):
    return json.loads(js(window, f'JSON.stringify({expression})'))


def key(window, value, modifiers=Qt.KeyboardModifier.NoModifier):
    if not args.offscreen and not window.isActiveWindow():
        window.raise_()
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window, 5000), '검증 창 활성화 실패'
    QTest.keyClick(window.web_host.view.focusProxy() or window.focusWidget() or window, value, modifiers)
    settle(120)


def library(name, clock=None):
    clock = clock or Clock()
    core = AppCore(media=Media(), clock=clock, database=directory / f'{name}.sqlite3')
    folder = directory / name
    folder.mkdir()
    return core, clock, folder


def add(core, folder, title, payload=None):
    path = folder / f'{title}.mp4'
    path.write_bytes((payload or title).encode())
    core.add_file(path)
    return next(v for v in core.videos() if v.title == title)


def titles(count, offset=0):
    return [f'{WORDS[(index + offset) % 10]} {KINDS[(index + offset) // 10 % 10]} {chr(0xAC00 + index + offset)}' for index in range(count)]


def watch(core, video, end):
    core.playback.start(video.id, 0)
    core.playback.report(end)
    core.playback.end()


def mark(core, video):
    core.playback.start(video.id, 5, record_viewing=False)
    core.execute_highlight_command(core.command_for_key('Insert'))
    core.playback.end()


def make_window(core):
    window = MainWindow(core)
    window.resize(1100, 720)
    windows.append(window)
    window.show()
    if not args.offscreen:
        window.raise_()
        window.activateWindow()
    wait_until(lambda: window.web_host._frontend_ready)
    settle()
    return window


def close(window):
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    windows.remove(window)


def layout(window):
    return read(window, """(() => {
      const list = document.getElementById('recommendations');
      const outer = list?.getBoundingClientRect();
      const rows = [...document.querySelectorAll('#recommendations [role=row]')].map(row => {
        const strip = row.querySelector('.recommendation-row');
        const cards = [...row.querySelectorAll('[role=gridcell]')];
        const s = strip.getBoundingClientRect();
        return {label: row.getAttribute('aria-label'), cards: cards.length, height: Math.round(row.getBoundingClientRect().height),
          cardWidth: Math.round(cards[0].getBoundingClientRect().width), cardHeights: [...new Set(cards.map(c => Math.round(c.getBoundingClientRect().height)))],
          visibleCards: cards.filter(c => { const r = c.getBoundingClientRect(); return r.left >= s.left - 1 && r.right <= s.right + 1; }).length,
          stripOverflow: strip.scrollWidth > strip.clientWidth,
          cardOverflow: cards.some(c => c.scrollWidth > c.clientWidth + 1)};
      });
      return {rows, scrollHeight: list?.scrollHeight ?? 0, clientHeight: list?.clientHeight ?? 0,
        listTop: outer ? Math.round(outer.top) : null, listBottom: outer ? Math.round(outer.bottom) : null,
        pageOverflow: document.documentElement.scrollWidth > innerWidth || document.querySelector('[data-page="recommend"]').scrollHeight > document.querySelector('[data-page="recommend"]').clientHeight,
        empty: document.querySelector('main[aria-label="추천"] section h2')?.textContent ?? null,
        notices: [...document.querySelectorAll('main[aria-label="추천"] [data-slot=notice]')].map(n => n.textContent)};
    })()""")


def capture(window, label):
    settle(400)
    if args.no_screenshots:
        return
    picture = window.grab().toImage()
    assert picture.width() == 1100 and picture.height() == 720, (picture.width(), picture.height())
    picture.save(str(args.output / f'web-{label}.png'))


def open_recommend(window):
    window.navigate_web_tab('recommend')
    wait_until(lambda: read(window, "!document.querySelector('main[aria-label=\"추천\"]').parentElement.hidden"))
    page = window.web_host.controllers['recommend']
    expected = sum(len(row['items']) for row in page.rows)
    wait_until(lambda: read(window, f"document.querySelectorAll('#recommendations [role=gridcell]').length === {expected}"))
    settle()
    return page


def active(window):
    return read(window, "document.getElementById('recommendations')?.getAttribute('aria-activedescendant')")


def card_visible(window, card_id):
    return read(window, f"""(() => {{
      const card = document.getElementById({json.dumps(card_id)}).getBoundingClientRect();
      const strip = document.getElementById({json.dumps(card_id)}).parentElement.getBoundingClientRect();
      const list = document.getElementById('recommendations').getBoundingClientRect();
      return card.left >= strip.left - 1 && card.right <= strip.right + 1 && card.top >= list.top - 1 && card.bottom <= list.bottom + 1;
    }})()""")


def screenshots():
    # 0개: 등록한 지 30일이 안 된 안 본 영상만 있다.
    core, clock, folder = library('empty')
    for title in titles(3):
        add(core, folder, title)
    window = make_window(core)
    page = open_recommend(window)
    assert page.rows == []
    capture(window, 'recommend-empty')
    layouts['empty'] = layout(window)
    assert layouts['empty']['empty'] == '지금은 추천할 영상이 없어요', layouts['empty']
    assert not layouts['empty']['pageOverflow'], layouts['empty']
    close(window)
    checks.append('추천 0개: 빈 상태 안내·관심 없음 되돌리기 버튼')

    # 적음: 보다 만 줄 하나에 세 장.
    core, clock, folder = library('few')
    videos = [add(core, folder, title) for title in titles(5)]
    for video in videos[:3]:
        watch(core, video, 25)
    window = make_window(core)
    page = open_recommend(window)
    capture(window, 'recommend-few')
    layouts['few'] = layout(window)
    rows = layouts['few']['rows']
    assert [(row['label'], row['cards']) for row in rows] == [('보다 만 · 3개', 3)], rows
    assert not rows[0]['stripOverflow'] and not layouts['few']['pageOverflow'], layouts['few']
    close(window)
    checks.append('추천 적음: 줄 하나·카드 세 장, 넘침 없음')

    # 최대: 네 줄 모두 20개, 태그 줄에서 밀려난 영상은 오래 시청 없음 줄로 내려간다.
    core, clock, folder = library('full')
    names = iter(titles(95))
    abandoned = [add(core, folder, next(names)) for _ in range(22)]
    revisit = [add(core, folder, next(names)) for _ in range(22)]
    favorite = add(core, folder, next(names))
    tagged = [add(core, folder, next(names)) for _ in range(24)]
    plain = [add(core, folder, next(names)) for _ in range(22)]
    for video in abandoned:
        watch(core, video, 25)
    for video in revisit:
        watch(core, video, 58)
        mark(core, video)
    watch(core, favorite, 58)
    watch(core, favorite, 58)
    watch(core, favorite, 58)
    core.add_video_tag(favorite.id, '자연')
    for video in tagged:
        core.add_video_tag(video.id, '자연')
    clock.now += timedelta(days=40)
    window = make_window(core)
    page = open_recommend(window)
    assert [(row['kind'], len(row['items'])) for row in page.rows] == [
        ('abandoned', 20), ('revisit', 20), ('similar_tags', 20), ('unwatched', 20)], page.rows
    overflow = {tagged[20].id, tagged[21].id}
    assert overflow <= {item['video']['id'] for item in page.rows[3]['items']}
    capture(window, 'recommend-full')
    layouts['full'] = layout(window)
    full = layouts['full']
    assert [row['cards'] for row in full['rows']] == [20] * 4, full
    assert all(row['visibleCards'] == 5 and row['stripOverflow'] for row in full['rows']), full
    assert len({row['cardWidth'] for row in full['rows']}) == 1 and all(len(row['cardHeights']) == 1 for row in full['rows']), full
    assert full['scrollHeight'] > full['clientHeight'] and not full['pageOverflow'], full
    # 키보드로 마지막 줄의 끝 카드까지 가면 세로·가로 모두 보이게 움직인다.
    js(window, "document.getElementById('recommendations').focus()")
    first = active(window)
    for _ in range(3):
        key(window, Qt.Key.Key_Down)
    key(window, Qt.Key.Key_End)
    last = f"recommendation-{page.rows[3]['items'][-1]['video']['id']}"
    wait_until(lambda: active(window) == last)
    assert card_visible(window, last)
    assert read(window, "document.getElementById('recommendations').scrollTop") > 0
    capture(window, 'recommend-full-bottom')
    key(window, Qt.Key.Key_Up)
    key(window, Qt.Key.Key_Right)
    third_row = page.rows[2]['items']
    wait_until(lambda: active(window) == f"recommendation-{third_row[1]['video']['id']}")
    for _ in range(2):
        key(window, Qt.Key.Key_Up)
    key(window, Qt.Key.Key_Home)
    wait_until(lambda: active(window) == first)
    assert card_visible(window, first) and read(window, "document.getElementById('recommendations').scrollTop") == 0
    checks.append('네 줄 × 20개: 줄마다 다섯 장 노출·가로 넘침, 세로 스크롤로 마지막 줄 끝까지 키 이동')
    # Backspace는 모든 줄에서 빼고, 안내의 되돌리기로 같은 카드에 돌아온다.
    key(window, Qt.Key.Key_Backspace)
    removed = int(first.removeprefix('recommendation-'))
    wait_until(lambda: removed in {v.id for v in core.dismissed_videos()})
    wait_until(lambda: read(window, f"!document.getElementById({json.dumps(first)})"))
    assert active(window) == f"recommendation-{page.rows[0]['items'][0]['video']['id']}"
    assert all(removed not in {item['video']['id'] for item in row['items']} for row in page.rows)
    capture(window, 'recommend-dismissed-notice')
    js(window, "[...document.querySelectorAll('main[aria-label=\"추천\"] button')].find(b => b.textContent === '되돌리기').click()")
    wait_until(lambda: not core.dismissed_videos())
    wait_until(lambda: active(window) == first and read(window, "document.activeElement.id") == 'recommendations')
    checks.append('Backspace 관심 없음(모든 줄)·되돌리기로 같은 카드 복귀')
    # 우클릭 메뉴: 재생·관심 없음.
    js(window, f"document.getElementById({json.dumps(first)}).dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, clientX: 200, clientY: 300}}))")
    wait_until(lambda: read(window, "[...document.querySelectorAll('[role=menuitem]')].map(item => item.textContent)") == ['재생', '관심 없음'])
    capture(window, 'recommend-menu')
    key(window, Qt.Key.Key_Escape)
    wait_until(lambda: read(window, "document.activeElement.id") == 'recommendations')
    checks.append('우클릭 메뉴(재생·관심 없음), Esc로 닫으면 목록에 초점')
    # 다른 탭에 다녀오면 지난 관심 없음 안내가 남지 않는다.
    js(window, "document.getElementById('recommendations').focus()")
    key(window, Qt.Key.Key_Backspace)
    wait_until(lambda: read(window, "[...document.querySelectorAll('main[aria-label=\"추천\"] button')].some(b => b.textContent === '되돌리기')"))
    window.navigate_web_tab('library')
    window.navigate_web_tab('recommend')
    wait_until(lambda: not read(window, "[...document.querySelectorAll('main[aria-label=\"추천\"] button')].some(b => b.textContent === '되돌리기')"))
    core.restore_dismissed_video(int(first.removeprefix('recommendation-')))
    checks.append('탭을 떠나면 관심 없음 안내 정리')
    # 라이브러리 탭에는 추천 영역이 없고 격자가 검색줄 바로 아래부터 시작한다.
    window.navigate_web_tab('library')
    wait_until(lambda: read(window, "!document.querySelector('main[aria-label=\"라이브러리\"]').parentElement.hidden"))
    capture(window, 'library-without-recommendations')
    layouts['library'] = read(window, """(() => ({
      recommendation: document.querySelector('[data-page="library"]').textContent.includes('숨겨진 보석'),
      gridTop: Math.round(document.getElementById('library-grid').getBoundingClientRect().top),
      gridHeight: document.getElementById('library-grid').clientHeight}))()""")
    assert not layouts['library']['recommendation'] and layouts['library']['gridTop'] < 160, layouts['library']
    close(window)
    checks.append('라이브러리 탭: 추천 영역 제거, 격자가 위로 넓어짐')

    # 긴 텍스트: 공백 없는 긴 제목과 긴 태그 이름이 든 이유.
    core, clock, folder = library('long')
    favorite = add(core, folder, '즐겨 보는 영상')
    watch(core, favorite, 58)
    watch(core, favorite, 58)
    watch(core, favorite, 58)
    target = add(core, folder, '공백없는아주긴추천영상제목' * 6)
    other = add(core, folder, '짧은 제목')
    for index in range(4):
        name = f'긴태그이름{index}' + '자연다큐멘터리' * 4
        core.add_video_tag(favorite.id, name)
        core.add_video_tag(target.id, name)
    core.add_video_tag(other.id, f'긴태그이름0' + '자연다큐멘터리' * 4)
    window = make_window(core)
    page = open_recommend(window)
    capture(window, 'recommend-long')
    layouts['long'] = layout(window)
    row, = layouts['long']['rows']
    assert row['cards'] == 2 and not row['cardOverflow'] and len(row['cardHeights']) == 1, row
    assert read(window, f"""(() => {{ const card = document.getElementById('recommendation-{target.id}');
      const [title, , reason] = card.querySelectorAll('div > span');
      return title.scrollWidth > title.clientWidth && reason.scrollHeight > reason.clientHeight; }})()"""), '긴 제목은 말줄임, 긴 이유는 두 줄로 잘린다'
    assert not layouts['long']['pageOverflow'], layouts['long']
    close(window)
    checks.append('긴 제목·긴 이유: 카드 폭·높이 유지, 말줄임과 두 줄 자름')


class FakePlayer:
    """mpv 없이 재생 왕복을 돌린다. 처음 위치 보고 한 번으로 35초까지 본 것으로 한다."""

    def __init__(self, surface):
        self.positions = [(35.0, False)]
        self.paused = False

    def play(self, path, start, *, subtitle):
        pass

    def close(self):
        pass

    def take_positions(self):
        positions, self.positions = self.positions, []
        return positions

    def take_eof(self):
        return False


def fallback_return():
    # 관심 없음으로 자동 선택된 카드를 방향키 없이 Enter로 재생하고 돌아오면, 줄 순서가 바뀌어도 그 카드로 돌아온다.
    core, clock, folder = library('fallback')
    videos = [add(core, folder, title) for title in titles(3)]
    for video in videos:
        watch(core, video, 25)
        clock.now += timedelta(days=1)
    window = make_window(core)
    window.player_factory = FakePlayer
    page = open_recommend(window)
    before = [item['video']['id'] for item in page.rows[0]['items']]
    assert before == [v.id for v in reversed(videos)], before
    js(window, "document.getElementById('recommendations').focus()")
    key(window, Qt.Key.Key_Right)
    wait_until(lambda: active(window) == f'recommendation-{before[1]}')
    key(window, Qt.Key.Key_Backspace)
    wait_until(lambda: read(window, f"!document.getElementById('recommendation-{before[1]}')"))
    chosen = f'recommendation-{before[2]}'
    assert active(window) == chosen, active(window)
    key(window, Qt.Key.Key_Return)
    wait_until(lambda: window.pages.currentWidget() is window.playback_page)
    assert core.playback.session.video_id == before[2]
    clock.now += timedelta(days=1)
    window.back_to_list()
    wait_until(lambda: [item['video']['id'] for item in page.rows[0]['items']] == [before[2], before[0]])
    wait_until(lambda: read(window, "document.activeElement.id") == 'recommendations')
    settle()
    assert active(window) == chosen, (active(window), chosen)
    close(window)
    checks.append('관심 없음 뒤 자동 선택 카드 Enter 재생 → 줄 순서가 바뀐 복귀에도 같은 카드')


def verify():
    videos = []
    core, clock, folder = library('verify', Clock())
    for index, title in enumerate(('바다 산책', '숲 노트', '음악 강의')):
        path = folder / f'{title}.mp4'
        subprocess.run([executable('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', f'testsrc2=size=160x90:rate=8', '-t', '60', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-metadata', f'title={index}', '-y', str(path)], check=True, timeout=60)
        core.add_file(path)
        videos.append(next(v for v in core.videos() if v.title == title))
    for video in videos:
        watch(core, video, 25)
    window = make_window(core)
    host = window.web_host
    try:
        key(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        wait_until(lambda: host.active_tab == 'recommend' and read(window, "document.activeElement.id") == 'recommendations')
        page = host.controllers['recommend']
        key(window, Qt.Key.Key_Right)
        chosen = active(window)
        assert chosen == f"recommendation-{page.rows[0]['items'][1]['video']['id']}", chosen
        video_id = int(chosen.removeprefix('recommendation-'))
        checks.append('실창 Ctrl+2 추천 탭·초점·→ 이동')

        def play_and_wait():
            key(window, Qt.Key.Key_Return)
            wait_until(lambda: window.pages.currentWidget() is window.playback_page)
            wait_until(lambda: core.playback.session is not None and core.playback.session.video_id == video_id)
            settle(1200)

        def returned_to_card():
            wait_until(lambda: host.active_tab == 'recommend' and window.pages.currentWidget() is host)
            wait_until(lambda: read(window, "document.activeElement.id") == 'recommendations' and active(window) == chosen)
            assert host.view.hasFocus() and window.isActiveWindow()
            assert card_visible(window, chosen)

        play_and_wait()
        key(window, Qt.Key.Key_Escape)
        returned_to_card()
        checks.append('실창 Enter 실제 mpv 재생 → Esc 복귀: 같은 탭·같은 카드 초점')

        play_and_wait()
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_H,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        wait_until(lambda: not window.isVisible())
        assert core.playback.session is not None and core.playback.session.video_id == video_id
        # OS 트레이 아이콘 클릭 대신 트레이 열기 동작을 부른다.
        window.tray.open()
        wait_until(lambda: window.isVisible() and window.pages.currentWidget() is window.playback_page)
        assert window.isActiveWindow() or QTest.qWaitForWindowActive(window, 5000)
        key(window, Qt.Key.Key_Escape)
        returned_to_card()
        checks.append('실창 긴급 탈출(Ctrl+Shift+H) → 트레이 열기: 같은 재생 장면 → Esc로 같은 카드 복귀')

        play_and_wait()
        window.close()
        wait_until(lambda: not window.isVisible())
        assert core.playback.session is None
        window.tray.open()
        if not window.isActiveWindow():
            QTest.qWaitForWindowActive(window, 5000)
        returned_to_card()
        checks.append('실창 재생 중 창 닫기 → 트레이 열기: 추천 탭·같은 카드 초점')

        js(window, f"document.getElementById({json.dumps(chosen)}).click()")
        wait_until(lambda: window.pages.currentWidget() is window.playback_page)
        key(window, Qt.Key.Key_Escape)
        returned_to_card()
        assert window.pages.count() == 2
        checks.append('실창 카드 클릭 재생 → 복귀')

        key(window, Qt.Key.Key_Backspace)
        wait_until(lambda: video_id in {v.id for v in core.dismissed_videos()})
        wait_until(lambda: active(window) not in (None, chosen))
        chosen = active(window)
        video_id = int(chosen.removeprefix('recommendation-'))
        before = [item['video']['id'] for item in page.rows[0]['items']]
        play_and_wait()
        clock.now += timedelta(days=1)
        key(window, Qt.Key.Key_Escape)
        returned_to_card()
        after = [item['video']['id'] for item in page.rows[0]['items']]
        checks.append(f'실창 관심 없음 → 자동 선택 카드 Enter mpv 재생 → Esc: 같은 카드 초점 (줄 {before} → {after})')
    finally:
        close(window)


try:
    if not args.no_screenshots or args.offscreen:
        screenshots()
    if args.offscreen:
        fallback_return()
    if args.verify:
        verify()
    result = {'checks': checks, 'offscreen': args.offscreen, 'layouts': layouts,
              'human_checks': ['OS 트레이 아이콘 클릭으로 열기', '다중 모니터·배율별 재생 왕복 포커스', '스크린 리더의 grid·activedescendant 낭독']}
    (args.output / ('verify.json' if args.verify else 'screens.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks}, ensure_ascii=False), flush=True)
finally:
    for window in list(windows):
        close(window)
