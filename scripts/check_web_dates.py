"""#232: 날짜가 보이는 모든 웹 화면이 한국식 한 가지 모양인지 검사한다.

화면 언어는 Windows 표시 언어와 상관없이 한국어여야 하므로, 검사는 영어(미국) QLocale에서 시작한다.
--offscreen은 1100×720으로 라이브러리 카드·상세 정보·필터 칩과 날짜 입력 칸·모아보기·통계(30일, 해가 바뀌는 365일,
축 눈금과 툴팁)·설정의 백업·업데이트·번역 정책을 찍고, 보이는 글자에 `2026-10-21`이나 `오후 3:04` 모양이 없는지 본다.
--videos 0은 날짜가 하나도 없는 빈 화면을 찍는다.
--verify는 데스크톱 잠금 안의 실창에서 날짜 입력 칸에 연·월·일 순서로 타자해 값이 그대로 들어가는지 본다.
DB와 파일은 임시 폴더에만 만든다.
"""
import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')

parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--offscreen', action='store_true')
mode.add_argument('--verify', action='store_true')
parser.add_argument('--videos', type=int, choices=(0, 6), default=6)
parser.add_argument('--output', type=Path, default=Path('.local/screens-232'))
parser.add_argument('--now', type=datetime.fromisoformat, help='검사 시각(시간대 포함 ISO). 기본은 지금')
args = parser.parse_args()
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QEventLoop, QLocale, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.app_version import current_version
from my_video_manager.backup import create_automatic_backup
from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.library_views import default_options
from my_video_manager.translation_models import DEFAULT_MODEL, MODEL_POLICIES
from my_video_manager.update_check import LAST_CHECK_KEY
from my_video_manager.ui import MainWindow

PANEL = '[aria-label="라이브러리 필터 패널"]'
CHIPS = '[aria-label="적용한 검색 조건"]'
DATE = r'\d{4}\. \d{2}\. \d{2}\.'
DATE_TIME = DATE + r' \d{2}:\d{2}'
# 보이는 글자에 남으면 안 되는 옛 모양: ISO 날짜, 월/일/연, 12시간제. 차트 축의 `10/21`은 눈금 검사가 본다.
OLD_SHAPES = r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|오전 \d|오후 \d'


class FakeMedia:
    def read(self, path):
        return MediaInfo(120, 'matroska')

    def capture(self, path, destination, seconds):
        destination.write_bytes(b'thumbnail')


class Player:
    def __init__(self, surface):
        pass

    def play(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def take_positions(self):
        return []

    def take_eof(self):
        return False

    def execute(self, command):
        pass


def local(moment):
    return moment.astimezone()


def shown_date(value):
    return f'{value.year}. {value.month:02d}. {value.day:02d}.'


QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-232-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
now = (args.now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
clock = [now]
core = AppCore(media=FakeMedia(), clock=lambda: clock[0], database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
core.set_automatic_detection_enabled(False)
root = directory / '영상'
root.mkdir()
core.add_watched_folder(root)
expected = {}
if args.videos:
    paths = []
    for i in range(args.videos):
        path = root / f'영상 {i:02d}.mkv'
        path.write_bytes(f'video {i}'.encode())
        paths.append(path)
    # 0: 오늘 수정, 1: 수정 시각 모름, 2: 해가 바뀌기 전 수정, 나머지: 최근.
    modified = [now - timedelta(hours=1), None, now.replace(month=1, day=2) - timedelta(days=7)] + \
               [now - timedelta(days=3 * i) for i in range(3, args.videos)]
    for path, moment in zip(paths, modified):
        if moment is not None:
            os.utime(path, (moment.timestamp(), moment.timestamp()))
        core.add_file(path)
    videos = {location.path: video for video in core.videos() for location in video.locations}
    ids = [videos[path].id for path in paths]
    core.rename_video(ids[3], '긴 제목도 날짜 칸을 밀지 않습니다 ' + 'LongVideoTitle' * 8)
    with closing(sqlite3.connect(core.database)) as db, db:
        db.execute('UPDATE locations SET mtime_ns=NULL WHERE path=?', (str(paths[1]),))
    # 시청: 오늘, 40일 전(30일 밖), 300일 전(대개 지난해). 나머지는 시청 기록 없음.
    for vid, days in ((ids[0], 0), (ids[1], 40), (ids[2], 300)):
        clock[0] = now - timedelta(days=days)
        core.playback.start(vid, 0)
        core.playback.report(30)
        core.playback.end()
    clock[0] = now
    for vid, start in ((ids[0], 10), (ids[1], 20)):
        core.playback.start(vid, start, record_viewing=False)
        core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
        core.playback.end()
    revisited = now - timedelta(hours=3)
    first_highlight = core.highlights(ids[0])[0]
    with closing(sqlite3.connect(core.database)) as db, db:
        db.execute('INSERT INTO revisits(highlight_id, last_revisited_at) VALUES (?, ?)',
                   (first_highlight.id, revisited.isoformat()))
    expected = {'ids': ids, 'modified': [shown_date(local(m)) if m else None for m in modified],
                'revisited': f'{shown_date(local(revisited))} {local(revisited):%H:%M}'}
    for _ in range(2):
        create_automatic_backup(core.database, reason='before_restore')
    manual = core.create_backup(directory / 'manual.zip').path
core.set_translation_cli('opencode_go')
metrics = {'videos': args.videos, 'checks': [], 'screenshots': [], 'layout': {}}

window = MainWindow(core, player_factory=Player)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page, host = window.library_page, window.web_host


def wait(predicate, seconds=30, message='조건 대기 시간 초과'):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values), message=code)
    return values[0]


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def texts(selector):
    return json.loads(js(f"JSON.stringify([...document.querySelectorAll({json.dumps(selector)})].map(e => e.textContent))"))


def capture(name):
    settle()
    path = args.output / f'{args.videos}-{name}.png'
    image = window.grab().toImage()
    assert (image.width(), image.height()) == (1100, 720), (image.width(), image.height())
    assert image.save(str(path))
    metrics['screenshots'].append(str(path.resolve()))


def no_old_shapes(name):
    """보이는 글자(숨은 페이지 제외)에 옛 날짜 모양이 없고 가로로 넘치지 않는다."""
    text = js('document.body.innerText')
    found = [m.group(0) for m in re.finditer(OLD_SHAPES, text)]
    assert not found, (name, found)
    overflow = js('document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 0, (name, overflow)


def view(**changes):
    result = json.loads(page.bridge.view(json.dumps({**default_options(), **changes})))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def navigate(tab):
    window.navigate_web_tab(tab)
    settle(400)


def click_text(selector, text):
    point = json.loads(js(f"""JSON.stringify((() => {{
      const e = [...document.querySelectorAll({json.dumps(selector)})].find(e => e.textContent === {json.dumps(text)} && e.getClientRects().length)
      if (!e) return null
      e.scrollIntoView({{block: 'nearest'}})
      const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] }})())"""))
    assert point, (selector, text)
    host.view.setFocus()
    QTest.mouseClick(host.view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(*map(int, point)))
    settle()


def open_panel():
    if not js(f"!!document.querySelector('{PANEL}')"):
        js("[...document.querySelectorAll('button')].find(b => b.textContent === '필터').click()")
        wait(lambda: js(f"!!document.querySelector('{PANEL}')"))
    settle()


def close_panel():
    js(f"document.querySelector('{PANEL} [aria-label=\"필터 닫기\"]')?.click()")
    wait(lambda: not js(f"!!document.querySelector('{PANEL}')"))


def check_language():
    order = js("new Intl.DateTimeFormat(navigator.language).formatToParts(new Date(2026, 9, 21))"
               ".filter(p => p.type !== 'literal').map(p => p.type).join(',')")
    state = {'qt': QLocale().name(), 'navigator': js('navigator.language'), 'order': order}
    metrics['language'] = state
    assert state == {'qt': 'ko_KR', 'navigator': 'ko', 'order': 'year,month,day'}, state
    metrics['checks'].append('영어(미국) QLocale에서 시작해도 Qt·웹 화면 언어 ko, 날짜 순서 연·월·일')


def check_library():
    view()
    capture('library')
    no_old_shapes('library')
    values = texts('#library-grid [aria-label="시청 통계"] > span:last-child > span:last-child')
    if args.videos:
        assert values and all(re.fullmatch(DATE, v) or v == '기록 없음' for v in values), values
        assert '기록 없음' in values and any(re.fullmatch(DATE, v) for v in values), values
    metrics['cards_last_viewed'] = values
    for index, name in ((0, 'known'), (1, 'unknown'), (2, 'previous-year')):
        if not args.videos:
            break
        result = json.loads(page.bridge.select(expected['ids'][index]))
        assert 'error' not in result, result
        page.selection_changed()
        line = lambda: js("[...document.querySelectorAll('#detail-scroll p')].map(p => p.textContent).find(t => t.startsWith('수정한 날짜')) ?? null")
        want = f"수정한 날짜: {expected['modified'][index] or '알 수 없음'}"
        wait(lambda: line() == want, message=f'{want} != {line()}')
        capture(f'detail-{name}')
        no_old_shapes(f'detail-{name}')
    metrics['checks'].append('카드 마지막 시청(날짜·기록 없음), 상세 수정한 날짜(오늘·모름·지난해)')


def check_chips():
    today = local(now).date()
    year_start = date(today.year, 1, 1)
    long_tag = core.add_video_tag(expected['ids'][0], '아주 긴 태그 이름이 칩 줄을 넓힙니다 ' * 2).id if args.videos else None
    view(query='긴 검색어 ' * 4, viewing='unwatched', external=True, highlights=True,
         added_preset='custom', added_from=(year_start - timedelta(days=10)).isoformat(), added_to=(year_start + timedelta(days=4)).isoformat(),
         modified_preset='custom', modified_from=(today - timedelta(days=30)).isoformat(),
         viewed_preset='custom', viewed_to=today.isoformat(), tags=[long_tag] if long_tag else [])
    chips = texts(f'{CHIPS} button span')
    ranged = [c for c in chips if c.startswith(('추가일', '수정한 날짜', '마지막 시청'))]
    assert len(ranged) == 3, chips
    assert ranged[0] == f'추가일: {shown_date(year_start - timedelta(days=10))} ~ {shown_date(year_start + timedelta(days=4))}', ranged
    assert ranged[1] == f'수정한 날짜: {shown_date(today - timedelta(days=30))} ~ 끝 없음', ranged
    assert ranged[2] == f'마지막 시청: 처음 ~ {shown_date(today)}', ranged
    layout = json.loads(js(f"""JSON.stringify((() => {{
      const row = document.querySelector('{CHIPS}'), r = row.getBoundingClientRect()
      const spans = [...row.querySelectorAll('button span')]
      return {{ left: r.left, right: r.right, innerWidth, scrollWidth: row.scrollWidth, clientWidth: row.clientWidth,
        truncated: spans.filter(e => e.scrollWidth > e.clientWidth).map(e => e.textContent),
        heights: [...new Set([...row.querySelectorAll('button')].map(b => Math.round(b.getBoundingClientRect().height)))] }} }})())"""))
    metrics['layout']['chips'] = layout
    assert layout['right'] <= layout['innerWidth'] and len(layout['heights']) == 1, layout
    assert not set(ranged) & set(layout['truncated']), layout
    capture('chips-many')
    no_old_shapes('chips-many')
    js(f"document.querySelector('{CHIPS}').scrollLeft = 1e6")
    capture('chips-many-scrolled')
    open_panel()
    values = json.loads(js(f"JSON.stringify([...document.querySelectorAll('{PANEL} input[type=date]')].map(i => i.value))"))
    assert len(values) == 6, values
    capture('panel-date-inputs')
    close_panel()
    view()
    metrics['checks'].append('필터 칩 직접 지정 범위 3개(해가 바뀌는 범위·처음·끝 없음)가 날짜 모양, 칩 줄 높이 한 줄·날짜 칩 말줄임 없음, 날짜 입력 칸 6개')


def check_reel():
    navigate('reel')
    wait(lambda: js("!!document.getElementById('reel-list')"))
    settle(400)
    lines = [t for t in texts('#reel-list span') if t.startswith('마지막 복습')]
    if args.videos:
        assert f"마지막 복습: {expected['revisited']}" in lines and '마지막 복습: 아직 없음' in lines, lines
        assert all(re.fullmatch(f'마지막 복습: ({DATE_TIME}|아직 없음)', t) for t in lines), lines
    metrics['reel'] = lines
    capture('reel')
    no_old_shapes('reel')
    metrics['checks'].append('모아보기 마지막 복습 날짜와 시각(24시간제)·아직 없음')


def check_statistics():
    navigate('statistics')
    for days in (30, 365):
        js(f"document.querySelector('nav[aria-label=\"통계 기간\"] button[data-tab=\"{days}\"]').click()")
        wait(lambda: not js("document.querySelector('main[aria-label=통계]').getAttribute('aria-busy') === 'true'")
             and js(f"document.querySelector('nav[aria-label=\"통계 기간\"] button[data-tab=\"{days}\"]').getAttribute('aria-current') === 'page'"))
        settle(400)
        start, end = local(now).date() - timedelta(days=days - 1), local(now).date()
        status = js("document.querySelector('main[aria-label=통계] [role=status]').textContent")
        assert status.startswith(f'{shown_date(start)} ~ {shown_date(end)}'), status
        ticks = texts("[role=figure][aria-label^='일별'] .recharts-xAxis-tick-labels .recharts-cartesian-axis-tick-value")
        assert ticks and all(re.fullmatch(r'\d{2}\. \d{2}\.', t) for t in ticks), ticks
        metrics.setdefault('statistics', {})[days] = {'status': status, 'ticks': ticks}
        capture(f'statistics-{days}')
        no_old_shapes(f'statistics-{days}')
        if args.videos and days == 30:
            # 오늘 막대에 마우스를 올려 툴팁의 날짜를 본다.
            point = json.loads(js("""JSON.stringify((() => {
              const bars = [...document.querySelectorAll("[role=figure][aria-label^='일별'] .recharts-bar-rectangle")]
              const r = bars[bars.length - 1].getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] })())"""))
            QTest.mouseMove(host.view.focusProxy(), QPoint(*map(int, point)))
            wait(lambda: bool(js("document.querySelector('[role=figure][aria-label^=일별] .recharts-tooltip-wrapper p')?.textContent")))
            label = js("document.querySelector('[role=figure][aria-label^=일별] .recharts-tooltip-wrapper p').textContent")
            assert label == shown_date(end), label
            metrics['statistics']['tooltip'] = label
            capture('statistics-tooltip')
            QTest.mouseMove(host.view.focusProxy(), QPoint(5, 5))
    metrics['checks'].append('통계 기간(30일·해가 바뀌는 365일)·축 눈금 `10. 21.`·툴팁 날짜')


def check_settings():
    navigate('settings')
    click_text('[data-category]', '백업')
    bridge = host.controllers['settings'].bridge
    finished = lambda: not json.loads(bridge.backupSnapshot())['busy']
    click_text('button', '새로고침')
    wait(finished)
    if args.videos:
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(manual), '')):
            click_text('button', '백업 파일 선택')
            wait(finished)
        wait(lambda: js("!!document.querySelector('[aria-label=\"백업 미리보기\"]')"))
        created = js("[...document.querySelectorAll('[aria-label=\"백업 미리보기\"] dt')].find(e => e.textContent === '만든 시각').nextSibling.textContent")
        assert re.fullmatch(DATE_TIME, created), created
        rows = [t.split(' · ')[0] for t in texts('[aria-label="자동 백업"] li p:first-child')]
        assert len(rows) == 2 and all(re.fullmatch(DATE_TIME, t) for t in rows), rows
        metrics['backup'] = {'created': created, 'automatic': rows}
    capture('settings-backup')
    no_old_shapes('settings-backup')
    if args.videos:
        js('document.querySelector("[aria-label=\\"자동 백업\\"]").scrollIntoView({block: "end"})')
        capture('settings-backup-automatic')
    core.settings.set(LAST_CHECK_KEY, {'checked_at': (now - timedelta(hours=2)).isoformat(), 'current_version': current_version(),
                                       'latest_version': current_version(), 'download_size': None, 'failure_reason': None, 'kind': 'none'})
    window.updates.changed.emit()
    click_text('[data-category]', '업데이트')
    checked = local(now - timedelta(hours=2))
    want = f'마지막 확인: {shown_date(checked)} {checked:%H:%M}'
    wait(lambda: want in js("document.querySelector('[aria-label=\"업데이트 설정\"]').textContent"), message=want)
    metrics['update'] = want
    capture('settings-update')
    no_old_shapes('settings-update')
    click_text('[data-category]', '번역')
    dialogs = host.dialogs
    # 만료 전날과 다음 날(주의 문구가 붙어 가장 길다) 정책 표시. 기본 OpenCode Go 모델의 만료일 기준이라 검사 날짜와 상관없다.
    # 정책은 시계의 UTC 날짜로 판정하므로 로컬 정오를 쓴다(UTC±11 안에서 같은 날짜).
    valid_until = next(p for p in MODEL_POLICIES if p.model_id == DEFAULT_MODEL).valid_until
    noon = lambda day: datetime.combine(day, time(12)).astimezone(timezone.utc)
    for name, moment in (('', noon(valid_until - timedelta(days=1))), ('-expired', noon(valid_until + timedelta(days=1)))):
        clock[0] = moment
        done = []

        def run():
            try:
                wait(lambda: js('!!document.querySelector("[data-translation-form]")'))
                settle(300)
                policy = js('document.querySelector(\'[role=note][aria-label="모델 정책"]\').textContent')
                assert f'무보존 계약 만료: {shown_date(valid_until)} (매월 갱신 확인 필요)' in policy, policy
                assert ('주의:' in policy) == bool(name), policy
                metrics[f'translation_policy{name}'] = policy
                capture(f'settings-translation-policy{name}')
                no_old_shapes(f'settings-translation-policy{name}')
            except BaseException as error:
                done.append(error)
            else:
                done.append(None)
            finally:
                while dialogs.active:
                    dialogs.pop()
        QTimer.singleShot(50, run)
        window.translations.settings()
        wait(lambda: bool(done))
        if done[0] is not None:
            raise done[0]
    clock[0] = now
    metrics['checks'].append('설정 백업(만든 시각·자동 백업 목록)·업데이트 마지막 확인·번역 정책 만료일(만료 전·뒤)')


def enter_korean_date(value):
    """날짜 입력 칸을 연·월·일 순서로 친다. 칸 순서가 다르면 값이 맞지 않는다."""
    for text in (f'{value.year}', f'{value.month:02d}', f'{value.day:02d}'):
        for digit in text:
            QTest.keyClick(host.view.focusProxy(), Qt.Key(Qt.Key.Key_0.value + int(digit)))
        settle()
        if len(text) == 4:
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Right)
            settle()


def check_typing():
    view(modified_preset='custom')
    open_panel()
    js(f"document.querySelector('{PANEL} [aria-label=\"수정한 날짜 시작\"]').focus()")
    settle()
    target = date(2026, 10, 21)
    enter_korean_date(target)
    wait(lambda: page.options['modified_from'] == target.isoformat(), 10,
         f"연·월·일 순서 타자 결과가 다름: {page.options['modified_from']!r}")
    capture('verify-typed-date')
    close_panel()
    view()
    metrics['checks'].append('실창: 수정한 날짜 시작 칸에 2026 → 10 → 21 순서로 타자해 2026-10-21 저장')


try:
    wait(lambda: js("!!document.getElementById('library-grid') || !!document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]')"))
    settle(400)
    check_language()
    if args.offscreen:
        check_library()
        check_chips()
        check_reel()
        check_statistics()
        check_settings()
    else:
        assert QTest.qWaitForWindowActive(window, 5000)
        check_typing()
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = repr(error)
    raise
finally:
    name = f"metrics-{'verify' if args.verify else args.videos}.json"
    (args.output / name).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    wait(lambda: not window.tray.quit_blocker(), 120)
