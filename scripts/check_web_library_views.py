"""#114: 임시 앱 데이터로 폴더/조건/크기 화면, 5,000개 응답, 실제 mpv 복귀 검사.

--offscreen은 화면/키보드, --verify는 데스크톱 잠금 안에서 실제 mpv까지 검사한다.
--source 원본은 읽기만 한다. 합성 위치와 DB는 임시 폴더에만 기록한다.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import median
import sqlite3
import tempfile
from time import perf_counter

parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--playback-only', action='store_true', help='승인된 추가 실창 검사: 크기 변경과 mpv 왕복만 실행')
parser.add_argument('--review-fixes', action='store_true')
parser.add_argument('--count', type=int, default=5000)
parser.add_argument('--source', type=Path)
parser.add_argument('--output', type=Path, default=Path('.local/screens-114'))
args = parser.parse_args()
if args.playback_only and not args.verify:
    parser.error('--playback-only는 --verify와 함께 사용하세요.')
if args.verify and (args.offscreen or not args.source):
    parser.error('--verify는 실창과 --source 영상이 필요합니다.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen' if args.offscreen else 'windows'
if args.offscreen:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QImage, QColor, QPainter, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from my_video_manager.web_thumbnail import register_thumbnail_scheme
register_thumbnail_scheme()
from my_video_manager.adapters import FFmpegMediaReader
from my_video_manager.core import AppCore
from my_video_manager.library_views import default_options
from my_video_manager.ui import MainWindow

app = QApplication([])
temporary = tempfile.TemporaryDirectory(prefix='mvm-114-')
directory = Path(temporary.name)
args.output.mkdir(parents=True, exist_ok=True)
media = FFmpegMediaReader()
core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), database=directory / 'library.sqlite3')
core.set_minimum_duration(0)
# 합성 위치에는 실제 파일이 없다. 시작 검사가 돌면 위치를 지워 폴더 계층이 사라지고,
# 검사가 끝나기 전에 종료하면 quit_blocker 경고 대화상자에서 멈추므로 자동 감지(시작 검사 포함)를 끈다.
core.set_automatic_detection_enabled(False)
metrics = {'count': args.count, 'checks': [], 'screenshots': [], 'app_data': str(directory)}
playable = None
if args.source and args.count:
    core.add_file(args.source)
    playable = core.videos()[0]
    core.rename_video(playable.id, '영상 0200 실제 재생')
    old = directory / 'old-320.jpg'
    result = media._run([media.ffmpeg, '-v', 'error', '-nostdin', '-y', '-ss', str(min(10, playable.duration / 10)),
                         '-i', str(args.source), '-map', '0:V:0', '-frames:v', '1', '-vf', 'scale=320:-2', '-update', '1', str(old)])
    assert result.returncode == 0, result.stderr
    before, after = old.stat().st_size, playable.thumbnail.stat().st_size
    metrics['thumbnail'] = {'source': str(args.source), 'width_before': QImage(str(old)).width(),
                            'width_after': QImage(str(playable.thumbnail)).width(), 'bytes_before': before,
                            'bytes_after': after, 'ratio': round(after / before, 3), 'delta': after - before}
root = args.source.parent if args.source else directory / '아주 긴 감시 폴더 이름으로 말줄임을 확인하는 라이브러리'
root.mkdir(exist_ok=True)
core.add_watched_folder(root)
image = QImage(640, 360, QImage.Format.Format_RGB32)
image.fill(QColor('#24354a'))
painter = QPainter(image)
painter.fillRect(320, 0, 320, 360, QColor('#576c48'))
painter.setPen(QColor('#ffffff'))
painter.setFont(QFont('Malgun Gothic', 24))
painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, '640 × 360 · Library')
painter.end()
image.save(str(directory / 'thumbnails/demo.640.jpg'))
with closing(sqlite3.connect(core.database)) as db, db:
    for i in range(args.count - (1 if playable else 0)):
        title = f'영상 {i:04d} ' + ('아주 긴 한글과 EnglishTitle' * 8 if i == 0 else '라이브러리 검증')
        vid = db.execute('''INSERT INTO videos(fingerprint,title,duration,format,thumbnail,registered_at,width,height,resolution_checked)
            VALUES (?,?,?,?,?,?,?,?,1)''', (f'synthetic-{i}', title, 100 + i, 'mp4', 'thumbnails/demo.640.jpg',
                                         '2026-08-01T12:00:00+00:00', 1920, 1080)).lastrowid
        relative = Path('긴 하위 폴더 이름과 공백 없는 LongFolderName' * 2) / '두번째' / '세번째' / '네번째' / '다섯번째' / '여섯번째' if i % 20 == 0 else Path(f'분류 {i % 40:02d}')
        db.execute('INSERT INTO locations(path,video_id) VALUES (?,?)', (str(root / relative / f'{i}.mp4'), vid))
if args.count:
    first = core.videos()[0]
    core.add_video_tag(first.id, '함께 고른 태그')
    core.add_video_tag(first.id, '긴 태그 이름 ' * 5)
window = MainWindow(core)
window.resize(1100, 720)
window.show()
window.raise_()
window.activateWindow()
page, host = window.library_page, window.web_host


def wait(predicate, seconds=30):
    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError('조건 대기 시간 초과')


def js(code):
    values = []
    host.engine_page.runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def settle():
    loop = QEventLoop()
    QTimer.singleShot(180, loop.quit)
    loop.exec()


def view(**changes):
    value = {**default_options(), **changes}
    result = json.loads(page.bridge.view(json.dumps(value)))
    assert 'error' not in result, result
    page.selection_changed()
    settle()


def capture(name):
    settle()
    path = args.output / f'{name}.png'
    assert window.grab().save(str(path))
    assert QImage(str(path)).size().width() == 1100
    metrics['screenshots'].append(str(path.resolve()))


def key(value):
    QTest.keyClick(host.view.focusProxy(), value)
    settle()


TOGGLE = "document.querySelector('button[aria-label=\"폴더 패널\"]')"


def layout(name):
    """#194: 검색줄·격자·폴더 패널이 1100px 창 폭을 넘지 않는지 잰다."""
    value = json.loads(js("""JSON.stringify((() => {
      const row = document.querySelector('[aria-label="영상 제목 빠른 검색"]').parentElement.parentElement, bounds = row.getBoundingClientRect()
      const grid = document.getElementById('library-grid'), panel = document.getElementById('library-folder-panel')
      return {rowOverflow: row.scrollWidth - row.clientWidth, outside: [...row.children].filter(c => c.getBoundingClientRect().right > bounds.right + 0.5).length,
        searchWidth: document.querySelector('[aria-label="영상 제목 빠른 검색"]').clientWidth,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        gridWidth: grid.clientWidth, columns: Number(grid.getAttribute('aria-colcount')), panelWidth: panel ? panel.offsetWidth : 0,
        panelOverflow: panel ? panel.scrollWidth - panel.clientWidth : 0,
        truncatedFolders: panel ? [...panel.querySelectorAll('[role=treeitem] .truncate')].filter(e => e.scrollWidth > e.clientWidth).length : 0}
    })())"""))
    assert value['rowOverflow'] <= 0 and value['outside'] == 0 and value['pageOverflow'] <= 0, (name, value)
    assert value['panelOverflow'] <= 0 and value['gridWidth'] > 0 and value['columns'] >= 1, (name, value)
    metrics.setdefault('layout', {})[name] = value


def check_folder_toggle():
    """#194: 아이콘 버튼은 Tab으로 닿고 Enter·Space로 패널을 여닫는다. 닫아도 고른 폴더를 저장해 둔다."""
    # 전체와 같은 결과를 내는 폴더로는 거르기 해제·복원을 구별할 수 없으므로 일부만 담은 폴더를 고른다.
    subset = next((n['id'] for n in page.index.folders if 0 < len(page.index.members.get(n['id'], ())) < args.count), '')
    assert subset or not args.count, '일부 영상만 담은 폴더가 없음'
    view(mode='folders', folder=subset, collapsed_folders=page.options['collapsed_folders'])
    assert not args.count or 0 < len(page.visible_ids) < args.count, (subset, len(page.visible_ids))
    # 폴더 패널 단추는 툴바 맨 앞이라 제목 검색 칸에서 Shift+Tab으로 닿는다(#381).
    js("document.querySelector('[aria-label=\"영상 제목 빠른 검색\"]').focus()")
    QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    settle()
    assert js('document.activeElement.getAttribute("aria-label")') == '폴더 패널'
    assert js(TOGGLE + '.getAttribute("aria-expanded")') == 'true' and js(TOGGLE + '.title') == '폴더 패널 닫기'
    folder, members = page.options['folder'], list(page.visible_ids)
    layout(f'{args.count}-panel-open')
    key(Qt.Key.Key_Return)
    wait(lambda: page.options['mode'] == 'all')
    assert page.options['folder'] == folder and core.library_view_options()['folder'] == folder
    assert len(page.visible_ids) == args.count
    assert js(TOGGLE + '.getAttribute("aria-expanded")') == 'false' and js(TOGGLE + '.title') == '폴더 패널 열기'
    assert not js("!!document.getElementById('library-folder-panel')")
    assert js('document.activeElement.getAttribute("aria-label")') == '폴더 패널'
    capture(f'{args.count}-panel-closed')
    layout(f'{args.count}-panel-closed')
    key(Qt.Key.Key_Space)
    wait(lambda: page.options['mode'] == 'folders')
    assert page.options['folder'] == folder and page.visible_ids == members
    assert js(TOGGLE + '.getAttribute("aria-expanded")') == 'true'
    reopened = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), database=core.database)
    assert reopened.library_view_options()['mode'] == 'folders' and reopened.library_view_options()['folder'] == folder
    shown = f'일부 폴더 {len(members)}/{args.count}개 → 닫기 전체 → 열기 {len(members)}개' if args.count else '폴더 없음'
    metrics['checks'].append(f'#194 폴더 패널 아이콘 검색 칸에서 Shift+Tab 도달·Enter 닫기(폴더 거르기 해제, 선택 보존)·Space 열기(폴더 복원)·설정 저장 ({shown})')


try:
    wait(lambda: js("!!document.getElementById('library-grid')"))
    settle()
    if args.review_fixes:
        for name, changes in (
            ('medium', {}), ('large', {'card_size': 'large'}),
            ('medium-folders', {'mode': 'folders'}),
            ('small-folders-chips', {'mode': 'folders', 'card_size': 'small', 'viewing': 'unwatched'}),
        ):
            view(**changes)
            capture(name)
            geometry = json.loads(js("JSON.stringify((()=>{const g=document.getElementById('library-grid'),c=g.querySelector('[role=gridcell]'),i=c.querySelector('img'),r=g.querySelector('[role=row]');return {columns:Number(g.getAttribute('aria-colcount')),height:g.clientHeight,cardHeight:c.offsetHeight,rowHeight:r.offsetHeight,thumbWidth:i.clientWidth,thumbHeight:i.clientHeight}})())"))
            metrics[name] = geometry
            assert abs(geometry['thumbWidth'] / geometry['thumbHeight'] - 16 / 9) < 0.03
            if name == 'medium-folders':
                assert geometry['columns'] >= 2 and geometry['height'] / geometry['rowHeight'] >= 1.5, geometry
            if name == 'large':
                assert geometry['height'] >= geometry['cardHeight'], geometry
        metrics['checks'].append('I1: 보통+폴더별 2열 및 1.5행, 크게 카드 전체, 16:9 썸네일')
    if not args.playback_only and not args.review_fixes:
        for size in ('small', 'medium', 'large'):
            view(card_size=size)
            capture(f'{args.count}-{size}')
            metrics.setdefault('card_sizes', {})[size] = json.loads(js("JSON.stringify((()=>{const g=document.getElementById('library-grid'), c=g.querySelector('[role=gridcell]'); return {columns:g.getAttribute('aria-colcount'),width:c?.clientWidth,thumbnail:c?.querySelector('img')?.clientHeight}})())"))
            if args.count > 200:
                target = page.visible_ids[200]
                js("(()=>{const g=document.getElementById('library-grid');const height=parseFloat(getComputedStyle(g).getPropertyValue('--grid-row-height'))*parseFloat(getComputedStyle(document.documentElement).fontSize);g.scrollTop=Math.floor(200/Number(g.getAttribute('aria-colcount')))*height})()")
                settle()
                assert js(f"!!document.getElementById('video-{target}')"), f'{size}: 크기 변경 후 200번째 카드의 행 위치 불일치'
                js("document.getElementById('library-grid').scrollTop=0")
                settle()
        view(mode='folders')
        capture(f'{args.count}-folders-deep-long')
        js("document.getElementById('library-folders').focus()")
        if args.count:
            # 합성 위치는 감시 루트 아래 여러 하위 폴더를 만든다. 계층이 없으면 접기/펴기를 검사할 수 없으므로 실패로 본다.
            folders = page.index.folders
            parents = {n['parent'] for n in folders if n['parent']}
            assert any(not n['parent'] and n['id'] in parents for n in folders), folders
            key(Qt.Key.Key_Down)
            root_id = page.options['folder']
            assert root_id in parents, root_id
            key(Qt.Key.Key_Left)
            assert js("document.querySelector('[role=treeitem][aria-selected=true]').getAttribute('aria-expanded')") == 'false'
            key(Qt.Key.Key_Right)
            assert js("document.querySelector('[role=treeitem][aria-selected=true]').getAttribute('aria-expanded')") == 'true'
            key(Qt.Key.Key_Down)
            assert next(n for n in folders if n['id'] == page.options['folder'])['parent'] == root_id
            metrics['checks'].append('실제 QTest 트리 ↑↓·←→ 접기/펴기(부모·자식 폴더)')
        else:
            # 감시 폴더에 영상이 없으면 트리에는 '모든 폴더'만 남는다. Enter·Tab 격자 이동은 그대로 검사한다.
            assert page.index.folders == [] and js("document.querySelectorAll('[role=treeitem]').length") == 1
        key(Qt.Key.Key_Return)
        assert js('document.activeElement.id') == 'library-grid'
        metrics['checks'].append('트리 Enter 격자 이동')
        js("document.getElementById('library-folders').focus()")
        key(Qt.Key.Key_Up)
        key(Qt.Key.Key_Tab)
        assert js('document.activeElement.id') == 'library-grid'
        metrics['checks'].append('트리 Tab 격자 이동')
        check_folder_toggle()
        if args.count:
            view(viewing='unwatched', tags=[t.id for t in core.tags()])
            capture(f'{args.count}-filter-chips')
            js("[...document.querySelectorAll('button')].find(b=>b.textContent==='필터').click()")
            wait(lambda: js("!!document.querySelector('[aria-label=\"라이브러리 필터 패널\"]')"))
            capture(f'{args.count}-filter-panel')
            key(Qt.Key.Key_Escape)
            wait(lambda: not js("!!document.querySelector('[aria-label=\"라이브러리 필터 패널\"]')"))
            assert js('document.activeElement.textContent') == '필터'
            metrics['checks'].append('필터 패널 Esc 닫기·버튼 포커스 복원')
            view(query='없는 제목 abcdef')
            capture(f'{args.count}-no-results')
            assert page.visible_ids == []
            view()
            started = perf_counter()
            index = core.library_view_index()
            metrics['index_build_ms'] = round((perf_counter() - started) * 1000, 3)
            started = perf_counter()
            page.return_from_playback()
            metrics['return_refresh_python_ms'] = round((perf_counter() - started) * 1000, 3)
            root_node = next(n for n in index.folders if n['parent'] == '')
            for label, change in (('filter', {'viewing': 'unwatched', 'query': '영상 0'}),
                                  ('folder', {'mode': 'folders', 'folder': root_node['id']}),
                                  ('sort', {'sort': 'duration', 'descending': True})):
                samples, bridge_samples = [], []
                for i in range(25):
                    options = {**default_options(), **(change if i % 2 else {})}
                    started = perf_counter()
                    core.library_view_ids(options, index=index)
                    samples.append((perf_counter() - started) * 1000)
                    started = perf_counter()
                    page.bridge.view(json.dumps(options))
                    bridge_samples.append((perf_counter() - started) * 1000)
                metrics[label + '_ms'] = {'core_median': round(median(samples), 3), 'core_max': round(max(samples), 3),
                                         'bridge_median': round(median(bridge_samples), 3), 'bridge_max': round(max(bridge_samples), 3)}
            metrics['checks'].append('코어 캐시 조건·폴더·정렬 25회와 Settings 저장·JSON 포함 브리지 25회 측정')
    if args.verify:
        assert QTest.qWaitForWindowActive(window, 5000)
        root_node = next(n for n in page.index.folders if n['path'] == str(root))
        view(mode='folders', folder=root_node['id'], card_size='large', query='영상')
        view(mode='folders', folder=root_node['id'], card_size='small', query='영상')
        # 선택 폴더와 다른 가지를 접은 상태를 함께 보존한다.
        js("(()=>{const n=[...document.querySelectorAll('[role=treeitem][aria-expanded=true]')].find(e=>e.getAttribute('aria-selected')!=='true'); if(n)n.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));})()")
        index = page.visible_ids.index(playable.id)
        columns = int(js("document.getElementById('library-grid').getAttribute('aria-colcount')"))
        height = float(js("parseFloat(getComputedStyle(document.getElementById('library-grid')).getPropertyValue('--grid-row-height'))*parseFloat(getComputedStyle(document.documentElement).fontSize)"))
        js(f"document.getElementById('library-grid').scrollTop={index // columns * height}")
        metrics['playback_scroll'] = dict(index=index, columns=columns, height=height, state=js("JSON.stringify({top:document.getElementById('library-grid').scrollTop,first:document.querySelector('[role=row]')?.getAttribute('aria-rowindex')})"))
        wait(lambda: js(f"!!document.getElementById('video-{playable.id}')"))
        js(f"document.getElementById('video-{playable.id}').click()")
        wait(lambda: page.selected_id == playable.id)
        state_code = "JSON.stringify({folder:document.querySelector('[role=treeitem][aria-selected=true]')?.id,expanded:[...document.querySelectorAll('[role=treeitem][aria-expanded=true]')].map(e=>e.id),id:document.getElementById('library-grid').getAttribute('aria-activedescendant'),top:document.getElementById('library-grid').scrollTop})"
        before = js(state_code)
        before_options = dict(page.options)
        key(Qt.Key.Key_Return)
        wait(lambda: window.pages.currentWidget() is window.playback_page)
        QTest.qWait(600)
        assert core.playback.session.video_id == playable.id
        window.playback_page.focus_content()
        QTest.keyClick(window.surface, Qt.Key.Key_Escape)
        wait(lambda: window.pages.currentWidget() is host)
        settle()
        assert js(state_code) == before, (before, js(state_code))
        assert page.options == before_options
        assert js('document.activeElement.id') == 'library-grid'
        metrics['checks'].append('실제 mpv Enter·Esc 왕복: 폴더·접힘·선택·스크롤·격자 포커스 동일')
        capture('real-playback-return')
        if not args.playback_only:
            options = dict(page.options)
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
            wait(lambda: host.active_tab == 'reel')
            QTest.keyClick(host.view.focusProxy(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
            wait(lambda: host.active_tab == 'library')
            assert page.options == options
            window.close()
            wait(lambda: not window.isVisible())
            window.tray.open()
            wait(window.isVisible)
            assert host.active_tab == 'library' and page.options == options
            metrics['checks'].append('Ctrl+2/1 탭 왕복·트레이 숨김/열기에서 라이브러리 조건 유지 (OS 트레이 클릭 제외)')
    metrics['result'] = 'passed'
except Exception as error:
    metrics['result'] = 'failed'
    metrics['failure'] = str(error)
    raise
finally:
    (args.output / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    # 검사·백업 작업이 남은 채 완전 종료하면 quit_blocker 경고 대화상자가 offscreen에서 프로세스를 멈춘다.
    wait(lambda: not window.tray.quit_blocker(), 120)
    window.tray.quit()
