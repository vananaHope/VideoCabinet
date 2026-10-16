"""AppCore 공개 시나리오와 실제 페이지 브리지로 대기열 전환을 검증한다."""
import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from test_subtitles import setup
from test_web_library_page import window_factory
from test_web_library_data import core
from my_video_manager.web_queue_page import WebQueuePage


@pytest.fixture
def queue_page(setup):
    app = QApplication.instance() or QApplication([])

    class Host(QWidget):
        active_tab = 'queue'

        def register_page(self, page):
            pass

        def page_ready(self, tab):
            self.ready_tab = tab

    host = Host()
    host.window = host
    host.core = setup[0]
    from my_video_manager.subtitle_controls import SubtitleControls
    host.subtitles = SubtitleControls(host)
    host.subtitles.timer.stop()  # 큐 도메인은 각 테스트에서 명시적으로 처리한다.
    host.show()
    page = WebQueuePage(host)
    page.activated()
    yield page
    page.deactivated()
    host.close()
    host.deleteLater()
    app.processEvents()


def reply(value):
    data = json.loads(value)
    assert 'error' not in data, data
    return data


def test_queue_initial_add_promote_remove_and_counts(queue_page, setup):
    core, _, (a, b) = setup
    page = queue_page
    assert reply(page.bridge.snapshot())['rows'] == []
    core.request_subtitles(a.id)
    core.request_subtitles(b.id)
    page.refresh()
    snapshot = reply(page.bridge.snapshot())
    assert snapshot['order'] == [a.id, b.id]
    assert snapshot['counts'][0]['count'] == 2
    reply(page.bridge.action('promote', b.id))
    assert reply(page.bridge.snapshot())['order'] == [b.id, a.id]
    reply(page.bridge.action('remove', b.id))
    assert reply(page.bridge.snapshot())['order'] == [a.id]
    assert [row.video_id for row in core.subtitle_queue_items()] == [a.id]


def test_progress_delta_contains_only_changed_row_and_no_order(queue_page, setup, monkeypatch):
    core, _, (a, b) = setup
    for video in (a, b):
        core.request_subtitles(video.id)
    page = queue_page
    page.refresh()
    changes = []
    page.bridge.queueChanged.connect(lambda value: changes.append(json.loads(value)))
    page.refresh()
    assert changes == []
    # 공개 조회 경계의 진행률만 교체해 전송량을 관찰한다. 도메인 상태를 조작하지 않는다.
    entries = core.subtitle_queue_items()
    monkeypatch.setattr(core, 'subtitle_queue_items', lambda: (replace(entries[0], progress=.5), entries[1]))
    page.refresh()
    assert changes == [dict(rows=[dict(videoId=a.id, title=a.title, state='queued', progress=.5, message='', taskLabel='받아쓰기', stateLabel='받아쓰기 · 대기')],
                            removed=[], order=None, counts=None, canRetryFailed=False)]


def test_queue_delta_reports_promoted_order_and_removed_ids(queue_page, setup):
    core, _, (a, b) = setup
    for video in (a, b):
        core.request_subtitles(video.id)
    page = queue_page
    page.refresh()
    changes = []
    page.bridge.queueChanged.connect(lambda value: changes.append(json.loads(value)))

    reply(page.bridge.action('promote', b.id))
    assert changes.pop() == dict(rows=[], removed=[], order=[b.id, a.id], counts=None, canRetryFailed=False)

    for removed_id, remaining in ((b.id, [a.id]), (a.id, [])):
        reply(page.bridge.action('remove', removed_id))
        delta = changes.pop()
        assert delta['rows'] == []
        assert delta['removed'] == [removed_id]
        assert delta['order'] == remaining
        assert {entry['state']: entry['count'] for entry in delta['counts']} == {
            'queued': len(remaining), 'transcribing': 0, 'translating': 0,
            'held': 0, 'completed': 0, 'failed': 0,
        }
    page.refresh()
    assert changes == []


def test_inactive_page_does_not_read_or_send(queue_page, setup, monkeypatch):
    page = queue_page
    deactivated = []
    page.bridge.queueDeactivated.connect(deactivated.append)
    page.deactivated()
    assert deactivated == ['']
    page.host.active_tab = 'library'

    def unexpected():
        raise AssertionError('숨겨진 페이지가 조회함')

    monkeypatch.setattr(setup[0], 'subtitle_queue_items', unexpected)
    page.refresh()
    assert not page.timer.isActive()
    assert 'error' in json.loads(page.bridge.action('retryFailed', -1))


def test_rules_folder_and_tag_save_include_existing_and_remove(queue_page, setup):
    core, _, (a, b) = setup
    page = queue_page
    tag = core.add_video_tag(a.id, '영어 공부')
    targets = reply(page.bridge.rulesSnapshot())['targets']
    folder = targets[0]['key']
    assert reply(page.bridge.candidates(folder))['count'] == 2
    reply(page.bridge.saveRule(folder, '자동 감지', False))
    assert core.subtitle_queue() == ()
    reply(page.bridge.saveRule(f'tag:{tag.id}', ' en ', True))
    assert [entry.video_id for entry in core.subtitle_queue()] == [a.id]
    rules = reply(page.bridge.rulesSnapshot())['rules']
    assert rules[-1]['language'] == 'en'
    reply(page.bridge.removeRule(rules[-1]['id']))
    assert len(core.auto_subtitle_rules()) == 1
    assert reply(page.bridge.candidates(folder))['count'] == 1


@pytest.mark.parametrize('target', ['folder:Z:/not-watched', 'tag:999999', 'tag:not-a-number', 'bad'])
def test_rules_reject_stale_or_invalid_targets(queue_page, target):
    assert 'error' in json.loads(queue_page.bridge.saveRule(target, 'en', True))
    assert queue_page.core.auto_subtitle_rules() == ()


def test_retry_failed_reports_missing_video_title(queue_page, setup):
    core, transcriber, (a, b) = setup
    transcriber.error = RuntimeError('GPU 오류')
    for video in (a, b):
        core.request_subtitles(video.id)
        core.process_next_subtitle()
    core.rename_video(a.id, '다시 찾을 영상')
    a.locations[0].path.unlink()
    core.scan()
    result = reply(queue_page.bridge.action('retryFailed', -1))
    assert '재시도 1개 · 건너뜀 1개' in result['message']
    assert '영상 다시 찾을 영상:' in result['message']


def test_retry_held_translation_uses_existing_public_request(queue_page, setup):
    from test_subtitle_queue import translation_core
    from test_translation import Translator
    from my_video_manager.translation import TranslationError
    core, transcriber, (video, _) = setup
    translator = Translator()
    core = translation_core(core, transcriber, translator)
    queue_page.core = core
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    translator.error = TranslationError('usage_limit', '한도')
    core.process_next_translation()
    assert core.translation_queue()[0].state == 'held'
    reply(queue_page.bridge.action('retryHeld', video.id))
    assert core.translation_queue()[0].state == 'queued'


def test_tray_opens_web_queue(window_factory):
    window = window_factory()
    window.hide()
    window.tray.show_queue()
    assert window.isVisible()
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == 'queue'
    assert window.web_host.controllers['queue'].timer.isActive()
    window.navigate_web_tab('library')
    assert not window.web_host.controllers['queue'].timer.isActive()


def test_bulk_confirmation_then_background_result_keeps_ui_responsive(queue_page, setup, monkeypatch):
    from threading import Event
    from PySide6.QtCore import QTimer
    from test_web_statistics import wait_for as wait
    core, _, _ = setup
    page = queue_page
    entered, release = Event(), Event()
    monkeypatch.setattr(core, 'existing_refinement_candidates', lambda: (3, 2))
    def request_bulk():
        entered.set()
        assert release.wait(10)
        return 3, 2
    monkeypatch.setattr(core, 'request_existing_refinements', request_bulk)
    preview = reply(page.bridge.action('previewRefineExisting', -1))
    assert '3개' in preview['confirmation'] and '2개' in preview['confirmation']
    assert not entered.is_set()
    results = []
    page.bridge.bulkFinished.connect(lambda value: results.append(json.loads(value)))
    try:
        assert reply(page.bridge.action('refineExisting', -1))['pending']
        assert entered.wait(5)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait(lambda: bool(ticks))
        assert page.bridge.bulk_running
        assert 'error' in json.loads(page.bridge.action('refineExisting', -1))
    finally:
        release.set()
        wait(lambda: not page.bridge.bulk_running)
    assert '3개' in results[0]['message'] and '2개' in results[0]['message']


def test_bulk_failure_releases_busy_state(queue_page, monkeypatch):
    from test_web_statistics import wait_for as wait
    def fail():
        raise ValueError('등록 실패')
    monkeypatch.setattr(queue_page.core, 'request_existing_refinements', fail)
    results = []
    queue_page.bridge.bulkFinished.connect(lambda value: results.append(json.loads(value)))
    assert reply(queue_page.bridge.action('refineExisting', -1))['pending']
    wait(lambda: bool(results))
    assert results == [{'error': '등록 실패'}]
    assert not queue_page.bridge.bulk_running


def test_retry_failed_availability_tracks_failure_retry_and_empty(queue_page, setup):
    core, transcriber, (video, _) = setup
    page = queue_page
    assert reply(page.bridge.snapshot())['canRetryFailed'] is False
    core.request_subtitles(video.id)
    page.refresh()
    assert reply(page.bridge.snapshot())['canRetryFailed'] is False
    transcriber.error = RuntimeError('failure')
    core.process_next_subtitle()
    changes = []
    page.bridge.queueChanged.connect(lambda value: changes.append(json.loads(value)))
    page.refresh()
    assert changes[-1]['canRetryFailed'] is True
    assert reply(page.bridge.snapshot())['canRetryFailed'] is True
    reply(page.bridge.action('retryFailed', -1))
    assert changes[-1]['canRetryFailed'] is False
    reply(page.bridge.action('remove', video.id))
    assert reply(page.bridge.snapshot())['canRetryFailed'] is False


def test_open_target_list_tab_commits_cursor_and_moves_like_native_select(window_factory, core):
    # main의 native select: 열린 목록의 Tab·Shift+Tab은 커서 항목을 확정하고 목록만 닫으며,
    # 포커스는 셀렉트에 남고 다음 Tab·Shift+Tab이 다음·이전 요소로 간다(#120).
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from test_web_dialogs import wait_for
    videos = core.videos()
    tags = [core.add_video_tag(videos[0].id, '가'), core.add_video_tag(videos[1].id, '나')]
    window = window_factory()
    window.activateWindow()
    host = window.web_host
    host.view.setFocus()
    view = host.view.focusProxy() or host.view

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait_for(lambda: bool(result))
        return result[0]

    def key(value, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(view, value, modifiers)
        QTest.qWait(150)

    target = "document.getElementById('queue-target')"
    is_open = "!!document.querySelector('[data-slot=select-content]')"
    wait_for(lambda: js("document.getElementById('library-grid') !== null"))
    window.navigate_web_tab('queue')
    wait_for(lambda: js("!!document.querySelector('[data-tab=rules]')"))
    # offscreen 문서는 실제 마우스 입력이 있어야 포커스를 얻는다.
    point = json.loads(js("JSON.stringify((() => { const r = document.querySelector('[data-tab=rules]').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] })())"))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(point[0]), int(point[1])))
    wait_for(lambda: js(f"!!{target} && document.hasFocus()"))
    assert js(f"{target}.dataset.value") == f'tag:{tags[0].id}'

    for modifiers, next_focus, expected in ((Qt.KeyboardModifier.NoModifier, 'queue-language', tags[1]),
                                            (Qt.KeyboardModifier.ShiftModifier, 'queue-rules', tags[0])):
        js(f"{target}.focus()")
        key(Qt.Key.Key_Space)
        wait_for(lambda: js(is_open))
        key(Qt.Key.Key_Down if expected is tags[1] else Qt.Key.Key_Up)
        tab = Qt.Key.Key_Tab if modifiers == Qt.KeyboardModifier.NoModifier else Qt.Key.Key_Backtab
        key(tab, modifiers)
        wait_for(lambda: not js(is_open) and js('document.activeElement.id') == 'queue-target')
        assert js(f"{target}.dataset.value") == f'tag:{expected.id}'
        key(tab, modifiers)
        wait_for(lambda: js('document.activeElement.id') == next_focus)
        assert not js(is_open)


def test_no_speech_completion_status_and_tray_notice(setup, qapp, monkeypatch):
    from PySide6.QtCore import QEvent
    from my_video_manager.subtitles import TranscriberResult
    from my_video_manager.ui import MainWindow
    core, adapter, (a, _) = setup
    adapter.result = TranscriberResult("nn", (), 0.61)
    window = MainWindow(core)
    try:
        window.subtitles.timer.stop()
        window.tray.timer.stop()
        core.request_subtitles(a.id)
        window.subtitles.completed(core.process_next_subtitle())
        assert window.statusBar().currentMessage() == "받아쓰기 완료 · 말소리를 찾지 못했습니다."
        messages = []
        monkeypatch.setattr(window.tray.icon, 'showMessage', lambda *args: messages.append(args))
        window.tray.notify_completion()
        assert messages == [("자막 대기열 처리 종료", "이번 처리: 완료 0개 · 말소리 없음 1개 · 실패 0개")]
    finally:
        window.tray.quit()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


LONG_NOTICE = ('OpenCode Go 서버가 요청을 거절했습니다. 네트워크 연결과 키 상태를 확인한 뒤 다시 시도하세요. '
               '같은 문제가 이어지면 다른 번역 방식을 고르거나 잠시 뒤 실패 항목을 다시 시도하세요. ') * 3


def open_queue(window_factory, core, width, height, *, long_notices):
    """core의 영상마다 대기열 행이 있는 실제 창을 열고, 필요하면 긴 안내 3개(셸·오류·결과)를 모두 펼친다."""
    from test_web_statistics import wait_for
    for video in core.videos():
        core.request_subtitles(video.id)
    window = window_factory()
    window.resize(width, height)
    window.subtitles.timer.stop()
    window.navigate_web_tab('queue')
    host = window.web_host

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait_for(lambda: bool(result))
        return result[0]

    def rendered():
        js('window.queueNoticeRendered = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.queueNoticeRendered = true }))')
        wait_for(lambda: js('window.queueNoticeRendered'))

    wait_for(lambda: js("document.querySelectorAll('#queue-list [data-queue-row]').length") == len(core.videos()))
    wait_for(lambda: js('innerWidth') == width and js('innerHeight') == height)
    if long_notices:
        window.show_status('번역 처리 실패: ' + LONG_NOTICE)
        host.controllers['queue'].bridge.bulkFinished.emit(json.dumps({'error': LONG_NOTICE, 'message': '재시도 결과 · ' + LONG_NOTICE}))
        expand = "[...document.querySelectorAll('button')].filter(b => b.textContent === '전체 보기' && b.getClientRects().length)"
        wait_for(lambda: js(f"{expand}.length") == 3)
        js(f"{expand}.forEach(b => b.click())")
        wait_for(lambda: js("[...document.querySelectorAll('button')].filter(b => b.textContent === '접기').length") == 3)
    rendered()
    return window, js, rendered


QUEUE_LAYOUT = """JSON.stringify((() => {
    const page = document.querySelector('[data-page=queue]')
    const grid = document.querySelector('#queue-list[role=grid]').getBoundingClientRect()
    const rows = [...document.querySelectorAll('#queue-list [data-queue-row]')].map(row => row.getBoundingClientRect().bottom)
    const button = [...document.querySelectorAll('button')].find(b => b.textContent === '실패 항목 모두 재시도').getBoundingClientRect()
    return { top: grid.top, height: grid.height, bottom: grid.bottom, rows, buttonTop: button.top, button: button.bottom,
             viewport: innerHeight, pageTop: page.getBoundingClientRect().top, scrollHeight: page.scrollHeight, clientHeight: page.clientHeight }
})())"""


def capture(window, name):
    import os
    from pathlib import Path
    if output := os.environ.get('MVM_NOTICE_SCREEN_DIR'):
        Path(output).mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(Path(output) / f'{name}.png'))


def test_expanding_every_long_notice_keeps_queue_rows_visible(window_factory, core):
    # 셸 작업 알림과 대기열 오류·결과가 모두 긴 문구이고 '전체 보기'를 전부 펼쳐도,
    # 1100×720에서 대기열 머리글과 행 세 개, 아래 버튼이 바깥 스크롤 없이 보여야 한다(#134 R1).
    window, js, _ = open_queue(window_factory, core, 1100, 720, long_notices=True)
    layout = json.loads(js(QUEUE_LAYOUT))
    assert layout['height'] >= 120, layout
    assert all(bottom <= layout['bottom'] for bottom in layout['rows']), layout
    assert layout['bottom'] <= layout['button'] <= layout['viewport'], layout
    assert (window.grab().width(), window.grab().height()) == (1100, 720)
    capture(window, 'queue-long-notices-all-expanded')


@pytest.mark.parametrize('width,height,long_notices', [(900, 600, True), (1100, 400, False)])
def test_small_window_scrolls_page_area_to_queue_actions(window_factory, core, width, height, long_notices):
    # 목록 최소 높이와 안내의 합이 창보다 크면 페이지 영역(탭 아래)이 세로로 스크롤해
    # 아래 작업 버튼에 닿을 수 있어야 한다. 목록 최소 높이는 그대로 지킨다(#134 재검토).
    window, js, rendered = open_queue(window_factory, core, width, height, long_notices=long_notices)
    before = json.loads(js(QUEUE_LAYOUT))
    assert before['scrollHeight'] > before['clientHeight'], before
    assert before['button'] > before['viewport'], before
    assert before['height'] >= 120, before
    js("document.querySelector('[data-page=queue]').scrollTop = 1e6")
    rendered()
    after = json.loads(js(QUEUE_LAYOUT))
    assert after['pageTop'] <= after['buttonTop'] and after['button'] <= after['viewport'], after
    capture(window, f'queue-{width}x{height}-{"long-notices" if long_notices else "no-notice"}-scrolled')


def test_default_window_pages_have_no_outer_scroll(window_factory, core):
    # 기본 1100×720에 안내가 없으면 어느 페이지도 바깥(페이지 영역) 스크롤이 생기지 않는다.
    window, js, rendered = open_queue(window_factory, core, 1100, 720, long_notices=False)
    capture(window, 'queue-1100x720-no-notice')
    from test_web_statistics import wait_for
    for tab in ('library', 'queue', 'reel', 'search', 'settings'):
        window.navigate_web_tab(tab)
        wait_for(lambda: not js(f"document.querySelector('[data-page={tab}]').hidden"))
        if tab == 'settings':
            js("document.querySelector('[data-category=keys]').click()")
        rendered()
        sizes = json.loads(js(f"JSON.stringify((e => [e.scrollHeight, e.clientHeight])(document.querySelector('[data-page={tab}]')))"))
        assert sizes[0] == sizes[1], (tab, sizes)


def test_small_window_reaches_bottom_of_other_list_pages(window_factory, core):
    # 목록 최소 높이를 둔 다른 페이지(라이브러리 격자, 모아보기·검색 목록, 키 배치 표)도
    # 1100×400에서 페이지 영역을 스크롤하면 페이지 맨 아래 요소가 화면 안에 들어온다.
    from test_web_statistics import wait_for
    window, js, rendered = open_queue(window_factory, core, 1100, 400, long_notices=False)
    for tab in ('library', 'reel', 'search', 'settings'):
        window.navigate_web_tab(tab)
        wait_for(lambda: not js(f"document.querySelector('[data-page={tab}]').hidden"))
        if tab == 'settings':
            js("document.querySelector('[data-category=keys]').click()")
        rendered()
        js(f"document.querySelector('[data-page={tab}]').scrollTop = 1e6")
        rendered()
        layout = json.loads(js(f"""JSON.stringify((() => {{
            const page = document.querySelector('[data-page={tab}]')
            const last = page.querySelector('main').lastElementChild.getBoundingClientRect()
            return {{ top: page.getBoundingClientRect().top, lastTop: last.top, last: last.bottom, viewport: innerHeight }}
        }})())"""))
        assert layout['top'] <= layout['lastTop'] and layout['last'] <= layout['viewport'], (tab, layout)


QUEUE_SELECTION = """JSON.stringify((() => {
    const list = document.getElementById('queue-list')
    const view = list.getBoundingClientRect()
    const header = list.querySelector(':scope > [role=row]:not([data-queue-row])').getBoundingClientRect()
    const row = document.getElementById(list.getAttribute('aria-activedescendant')).getBoundingClientRect()
    return { id: Number(list.getAttribute('aria-activedescendant').slice(10)), top: row.top, bottom: row.bottom,
             header: header.bottom, viewBottom: view.top + list.clientTop + list.clientHeight, scrollTop: list.scrollTop }
})())"""


@pytest.mark.parametrize('count,width,height,long_notices,down,up', [(300, 800, 500, True, 80, 50), (12, 1100, 400, False, None, 8)])
def test_keyboard_selection_stays_below_sticky_queue_header(window_factory, core, tmp_path, count, width, height, long_notices, down, up):
    # 키보드로 위쪽 행을 고르면 선택 행 전체가 고정 머리글 아래에 보여야 한다.
    # ↓·End 방향은 지금처럼 목록 아래 끝에 맞추고, 마우스 선택은 목록을 스크롤하지 않는다(#157).
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from test_web_statistics import wait_for
    for index in range(len(core.videos()), count):
        path = tmp_path / f'영상 {index:03}.mkv'
        path.write_bytes(str(index).encode())
        core.add_file(path)
    window, js, rendered = open_queue(window_factory, core, width, height, long_notices=long_notices)
    ids = json.loads(js("JSON.stringify([...document.querySelectorAll('#queue-list [data-queue-row]')].map(row => Number(row.dataset.queueRow)))"))
    assert len(ids) == count
    view = window.web_host.view.focusProxy() or window.web_host.view
    js("document.getElementById('queue-list').scrollIntoView({ block: 'nearest' })")
    rendered()
    # offscreen 문서는 실제 마우스 입력이 있어야 포커스를 얻는다. 첫 행을 눌러 선택한다.
    point = json.loads(js(f"JSON.stringify((r => [r.x + r.width / 2, r.y + r.height / 2])(document.getElementById('queue-row-{ids[0]}').getBoundingClientRect()))"))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(point[0]), int(point[1])))
    wait_for(lambda: js("document.activeElement.id") == 'queue-list' and js("document.getElementById('queue-list').getAttribute('aria-activedescendant')") == f'queue-row-{ids[0]}')
    assert json.loads(js(QUEUE_SELECTION))['scrollTop'] == 0
    position = 0

    def press(key, target):
        nonlocal position
        QTest.keyClick(view, key)
        position = target
        wait_for(lambda: js("document.getElementById('queue-list').getAttribute('aria-activedescendant')") == f'queue-row-{ids[target]}')

    def selection():
        rendered()
        state = json.loads(js(QUEUE_SELECTION))
        assert state['id'] == ids[position], state
        return state

    for _ in range(down or 0):
        press(Qt.Key.Key_Down, position + 1)
    if down is None:
        press(Qt.Key.Key_End, count - 1)
    state = selection()
    assert abs(state['bottom'] - state['viewBottom']) <= 1 and state['scrollTop'] > 0, state
    for _ in range(up):
        press(Qt.Key.Key_Up, position - 1)
    state = selection()
    assert state['header'] <= state['top'] and state['bottom'] <= state['viewBottom'], state
    capture(window, f'queue-{width}x{height}-{count}-rows-up')
    press(Qt.Key.Key_Home, 0)
    state = selection()
    assert state['header'] <= state['top'] and state['scrollTop'] == 0, state
    # 마우스로 일부만 보이는 아래 행을 눌러도 목록 스크롤은 그대로다.
    point = json.loads(js("JSON.stringify((l => [l.x + l.width / 2, l.bottom - 4])(document.getElementById('queue-list').getBoundingClientRect()))"))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(point[0]), int(point[1])))
    wait_for(lambda: js("document.getElementById('queue-list').getAttribute('aria-activedescendant')") != f'queue-row-{ids[0]}')
    assert json.loads(js(QUEUE_SELECTION))['scrollTop'] == 0
