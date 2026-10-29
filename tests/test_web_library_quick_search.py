"""#266 라이브러리 빠른 검색·정렬·필터 반응. 실제 웹 셸(offscreen)과 가짜 플레이어로 검증한다.

입력란은 친 글자를 결과를 기다리지 않고 곧바로 그리고, 결과·칩은 마지막 조건의 응답만 반영한다. 늦은 응답은
#265의 공용 세대 가드와 보기 요청 번호가 거른다. 응답 지연은 WebChannel 전송에서 메시지를 붙잡았다가 넘겨 재현한다.
"""
import json

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from qt_wait import wait_for
from test_web_library_loading import click, js
from test_web_tab_reshow import COUNT, GRID, QUERY, SELECTED, active_element, held, hold, library, open_window, release, view

# 보기 요청(정렬·필터·빠른 검색)의 응답과, 다른 원인으로 밀어 보낸 전체 목록.
VIEW_REPLY = "(kind, object, state) => kind === 'reply' && 'visibleIds' in state && !('videos' in state)"
LIBRARY_PUSH = "(kind, object, state) => kind === 'signal' && object === 'library' && 'videos' in state"
CHIPS = '[...document.querySelectorAll(\'[aria-label="적용한 검색 조건"] button[title]\')].map(button => button.title)'
NOTICES = 'document.querySelector(\'[aria-label="라이브러리 안내"]\').textContent'
SORT_DIRECTION = 'document.querySelector(\'[aria-label="정렬 방향"]\').textContent'
CHIP_STATUS = 'document.querySelector(\'[aria-label="적용한 검색 조건"] [data-slot=pending-status]\').textContent'
# 웹이 받은 보기 응답 수. 붙잡기 전에 세므로 붙잡은 응답도 센다.
COUNT_VIEW_REPLIES = """(() => {
  window.mvmViewReplies = 0;
  const transport = qt.webChannelTransport, receive = transport.onmessage;
  transport.onmessage = function(event) {
    const data = JSON.parse(event.data);
    let state = null;
    try { state = data.type === 10 && typeof data.data === 'string' ? JSON.parse(data.data) : null } catch (error) { state = null }
    if (state !== null && typeof state === 'object' && 'visibleIds' in state && !('videos' in state)) window.mvmViewReplies++;
    receive.call(transport, event);
  };
})()"""


def chips(window):
    return json.loads(js(window, f'JSON.stringify({CHIPS})'))


def focus_search(window):
    click(window, '[aria-label="영상 제목 빠른 검색"]')
    wait_for(lambda: active_element(window) == '영상 제목 빠른 검색')


def shows(window, count, chip_titles):
    return js(window, COUNT) == f'등록 영상 60개 · 표시 {count}개' and chips(window) == chip_titles


def test_typed_text_shows_at_once_and_results_follow_the_last_query(open_window):
    window = open_window()
    page = window.library_page
    js(window, f'{GRID}.scrollTop = 600; true')
    wait_for(lambda: js(window, f'{GRID}.scrollTop') == 600)
    focus_search(window)
    # 글자마다 보낸 보기 응답을 모두 붙잡아 결과가 늦는 상황을 만든다.
    text = 'clip 01'
    replies = [hold(window, VIEW_REPLY) for _ in text]
    QTest.keyClicks(view(window), text)
    # 입력란은 결과를 기다리지 않고 친 글자를 모두 보인다. 결과·칩은 아직 이전 조건의 것이고 카드도 그대로 있다.
    wait_for(lambda: js(window, f'{QUERY}.value') == text)
    wait_for(lambda: all(held(window, reply) for reply in replies))
    assert shows(window, 60, [])
    # 기다림이 길어지면 칩 줄 끝에 공용 기다림 표시가 보인다.
    wait_for(lambda: js(window, CHIP_STATUS) == '불러오는 중…')
    assert shows(window, 60, [])
    # 앞선 글자의 응답이 차례로 늦게 도착해도 중간 검색어의 결과는 한 번도 보이지 않고 마지막 검색어의 결과만 보인다.
    js(window, f"""window.mvmShown = new Set(); new MutationObserver(() => window.mvmShown.add(({COUNT}) + ' / ' + {CHIPS}.join('|')))
      .observe(document.querySelector('main[aria-label="라이브러리"]'), {{ subtree: true, childList: true, characterData: true }}); true""")
    for reply in replies:
        release(window, reply)
    wait_for(lambda: shows(window, 10, [f'제목: {text}']))
    shown = set(json.loads(js(window, 'JSON.stringify([...window.mvmShown])')))
    assert shown <= {'등록 영상 60개 · 표시 60개 / ', f'등록 영상 60개 · 표시 10개 / 제목: {text}'}, shown
    assert js(window, f'{QUERY}.value') == text
    assert js(window, CHIP_STATUS) == ''
    # 결과가 바뀌었으므로 목록은 맨 위로 가고 첫 결과를 고른다.
    assert js(window, f'{GRID}.scrollTop') == 0
    assert js(window, SELECTED) == f'video-{page.visible_ids[0]}'

    # 결과에서 고른 영상을 재생하고 돌아오면 같은 검색어·결과·선택이 그대로다.
    target = page.visible_ids[3]
    click(window, f'#video-{target}')
    wait_for(lambda: page.selected_id == target)
    window.play(target)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    wait_for(lambda: active_element(window) == 'library-grid')
    assert js(window, SELECTED) == f'video-{target}'
    assert js(window, f'{QUERY}.value') == text
    assert shows(window, 10, [f'제목: {text}'])


def test_list_push_while_waiting_for_a_view_reply_keeps_typed_text(open_window):
    window = open_window()
    page = window.library_page
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: page.options['query'] == 'clip 0' and shows(window, 60, ['제목: clip 0']))
    # 검사 결과 반영 같은 다른 원인의 전체 목록이 지금 검색어(clip 0)로 나간 뒤 늦게 도착한다.
    late = hold(window, LIBRARY_PUSH)
    window.refresh()
    wait_for(lambda: held(window, late))
    reply = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: page.options['query'] == 'clip 00' and held(window, reply))
    release(window, late)
    # 응답을 기다리는 동안 도착한 목록이 앞선 검색어로 입력란을 되돌리지 않으므로 이어 친 글자를 잃지 않는다.
    assert js(window, f'{QUERY}.value') == 'clip 00'
    QTest.keyClicks(view(window), '1')
    wait_for(lambda: page.options['query'] == 'clip 001')
    release(window, reply)
    wait_for(lambda: shows(window, 1, ['제목: clip 001']))
    assert js(window, f'{QUERY}.value') == 'clip 001'


def test_fast_search_and_sort_changes_show_only_the_last_condition(open_window):
    window = open_window()
    page = window.library_page
    focus_search(window)
    replies = [hold(window, VIEW_REPLY) for _ in range(8)]
    # 검색어를 치다가 정렬 방향을 바꾸고 다시 검색어를 잇는다. 응답은 모두 늦는다.
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: page.options['query'] == 'clip 0')
    click(window, '[aria-label="정렬 방향"]')
    wait_for(lambda: page.options['descending'])
    focus_search(window)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: page.options['query'] == 'clip 00' and all(held(window, reply) for reply in replies))
    assert js(window, f'{QUERY}.value') == 'clip 00'
    assert shows(window, 60, [])
    for reply in reversed(replies):
        release(window, reply)
    # 마지막 조건(내림차순 + clip 00)의 결과만 보인다.
    wait_for(lambda: shows(window, 10, ['제목: clip 00']))
    assert js(window, 'document.querySelector(\'[aria-label="정렬 방향"]\').textContent') == '내림차순 ↓'
    first = js(window, f'{GRID}.querySelector("[role=gridcell]").textContent')
    assert 'clip 009' in first, first


def test_composition_requests_the_list_once_for_the_final_text(open_window, library):
    library.rename_video(library.videos()[5].id, '한글 영상')
    window = open_window()
    js(window, COUNT_VIEW_REPLIES)
    focus_search(window)
    # 실제 DOM의 조합 이벤트로 여러 글자를 조합한다. 조합 중에는 입력란만 바뀌고 목록은 요청하지 않는다.
    js(window, """(() => {
      const input = document.activeElement;
      input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true, data: ''}));
      for (const value of ['ㅎ', '하', '한', '한ㄱ', '한그', '한글']) {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
        input.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertCompositionText', isComposing: true}));
        input.dispatchEvent(new CompositionEvent('compositionupdate', {bubbles: true, data: value}));
      }
    })()""")
    wait_for(lambda: js(window, f'{QUERY}.value') == '한글')
    js(window, "document.activeElement.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true, data: '한글'}))")
    wait_for(lambda: shows(window, 1, ['제목: 한글']))
    assert js(window, 'window.mvmViewReplies') == 1
    assert js(window, f'{QUERY}.value') == '한글'


def test_list_push_while_waiting_keeps_the_sort_just_changed(open_window):
    window = open_window()
    page = window.library_page
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    # 정렬을 바꾸기 전 조건(오름차순)으로 나간 전체 목록이, 정렬 방향을 바꾼 요청의 응답을 기다리는 동안 도착한다.
    late = hold(window, LIBRARY_PUSH)
    window.refresh()
    wait_for(lambda: held(window, late))
    reply = hold(window, VIEW_REPLY)
    click(window, '[aria-label="정렬 방향"]')
    wait_for(lambda: page.options['descending'] and held(window, reply))
    release(window, late)
    # 목록 데이터는 받아도 방금 바꾼 정렬은 그대로이고, 이어 친 글자의 요청도 그 정렬을 담는다.
    assert js(window, SORT_DIRECTION) == '내림차순 ↓'
    focus_search(window)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: page.options['query'] == 'clip 00')
    assert page.options['descending']
    release(window, reply)
    wait_for(lambda: shows(window, 10, ['제목: clip 00']))
    assert js(window, SORT_DIRECTION) == '내림차순 ↓'
    first = js(window, f'{GRID}.querySelector("[role=gridcell]").textContent')
    assert 'clip 009' in first, first


def test_list_push_while_waiting_never_shows_an_intermediate_query(open_window):
    window = open_window()
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    # 중간 검색어(clip 00)의 응답과 그 조건으로 나간 전체 목록, 마지막 검색어(clip 001)의 응답을 모두 붙잡는다.
    middle = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: held(window, middle))
    late = hold(window, LIBRARY_PUSH)
    window.refresh()
    wait_for(lambda: held(window, late))
    last = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '1')
    wait_for(lambda: held(window, last))
    release(window, late)
    # 마지막 검색어의 결과가 오기 전에는 이전 결과를 그대로 보인다. 중간 검색어의 결과는 보이지 않는다.
    assert shows(window, 60, ['제목: clip 0']), (js(window, COUNT), chips(window))
    assert js(window, f'{QUERY}.value') == 'clip 001'
    release(window, middle)
    assert shows(window, 60, ['제목: clip 0']), (js(window, COUNT), chips(window))
    release(window, last)
    wait_for(lambda: shows(window, 1, ['제목: clip 001']))


def test_old_card_picked_while_waiting_is_selected_and_plays(open_window, library):
    window = open_window()
    page = window.library_page
    target = next(video.id for video in library.videos() if video.title == 'clip 001')
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    reply = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '1')
    wait_for(lambda: held(window, reply))
    # 새 결과(clip 01)를 기다리는 동안 화면에 남은 이전 결과에서 새 결과에 없는 카드를 고른다.
    assert target not in page.visible_ids
    click(window, f'#video-{target}')
    wait_for(lambda: page.selected_id == target)
    assert js(window, SELECTED) == f'video-{target}'
    wait_for(lambda: active_element(window) == 'library-grid')
    # Enter는 화면에서 고른 그 영상을 재생한다. 선택 요청은 오류 없이 받아들여졌다.
    QTest.keyClick(view(window), Qt.Key.Key_Return)
    wait_for(lambda: window.pages.currentWidget() is window.playback_page)
    assert window.core.playback.session.video_id == target
    assert js(window, NOTICES) == ''
    # 돌아와 새 결과가 반영되면 고른 영상은 결과에 없으므로 코어가 정한 첫 결과를 고르고, 화면과 코어의 선택이 같다.
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    release(window, reply)
    wait_for(lambda: shows(window, 10, ['제목: clip 01']))
    wait_for(lambda: page.selected_id == page.visible_ids[0])
    assert js(window, SELECTED) == f'video-{page.selected_id}'
    assert js(window, NOTICES) == ''


def test_card_picked_while_waiting_follows_the_new_result(open_window, library):
    window = open_window()
    page = window.library_page
    ids = {video.title: video.id for video in library.videos()}
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    # 기다리는 동안 고른 영상이 새 결과에도 있으면 결과가 바뀌어도 그 선택을 지킨다.
    reply = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: held(window, reply))
    click(window, f'#video-{ids["clip 005"]}')
    wait_for(lambda: page.selected_id == ids['clip 005'])
    release(window, reply)
    wait_for(lambda: shows(window, 10, ['제목: clip 00']))
    assert js(window, SELECTED) == f'video-{ids["clip 005"]}'
    assert page.selected_id == ids['clip 005']
    # 새 결과에 없으면 새 결과의 선택(첫 결과)을 보이고 코어도 그 영상을 고른다.
    reply = hold(window, VIEW_REPLY)
    focus_search(window)
    QTest.keyClicks(view(window), '3')
    wait_for(lambda: held(window, reply))
    click(window, f'#video-{ids["clip 001"]}')
    wait_for(lambda: page.selected_id == ids['clip 001'])
    release(window, reply)
    wait_for(lambda: shows(window, 1, ['제목: clip 003']))
    assert js(window, SELECTED) == f'video-{ids["clip 003"]}'
    wait_for(lambda: page.selected_id == ids['clip 003'])
    assert js(window, NOTICES) == ''


def selects(window, video_id):
    """화면 선택과 코어 선택(selected_video_id)이 모두 video_id다. None이면 둘 다 선택이 없다."""
    screen = None if video_id is None else f'video-{video_id}'
    return json.loads(js(window, f'JSON.stringify({SELECTED})')) == screen and window.library_page.selected_video_id() == video_id


def test_card_picked_while_waiting_stays_selected_after_narrowing_and_broadening(open_window, library):
    window = open_window()
    page = window.library_page
    ids = {video.title: video.id for video in library.videos()}
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    first = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '0')
    wait_for(lambda: held(window, first))
    click(window, f'#video-{ids["clip 005"]}')
    wait_for(lambda: selects(window, ids['clip 005']))
    # 응답을 붙잡은 채 좁혔다(clip 003) 넓힌다(clip 00). 코어는 좁힐 때 선택을 clip 003으로 바꾸고 넓혀도 그대로 둔다.
    focus_search(window)
    narrow = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), '3')
    wait_for(lambda: held(window, narrow))
    assert js(window, SELECTED) == f'video-{ids["clip 005"]}'
    broad = hold(window, VIEW_REPLY)
    QTest.keyClick(view(window), Qt.Key.Key_Backspace)
    wait_for(lambda: held(window, broad))
    assert js(window, SELECTED) == f'video-{ids["clip 005"]}'
    for reply in (first, narrow):
        release(window, reply)
        assert shows(window, 60, ['제목: clip 0'])
        assert js(window, SELECTED) == f'video-{ids["clip 005"]}'
    # 마지막 결과에 고른 영상이 있으므로 화면과 코어 모두 그 영상을 고른다.
    release(window, broad)
    wait_for(lambda: shows(window, 10, ['제목: clip 00']))
    wait_for(lambda: selects(window, ids['clip 005']))
    # 정렬만 바꿔도 두 영상 모두 결과에 남으므로 선택은 그대로다.
    click(window, '[aria-label="정렬 방향"]')
    wait_for(lambda: page.options['descending'] and js(window, SORT_DIRECTION) == '내림차순 ↓')
    wait_for(lambda: js(window, f'{GRID}.querySelector("[role=gridcell]")?.id') == f'video-{ids["clip 009"]}')
    assert selects(window, ids['clip 005'])
    assert js(window, NOTICES) == ''


def test_card_picked_while_waiting_for_an_empty_result_clears_both_selections(open_window, library):
    window = open_window()
    target = next(video.id for video in library.videos() if video.title == 'clip 001')
    focus_search(window)
    QTest.keyClicks(view(window), 'clip 0')
    wait_for(lambda: shows(window, 60, ['제목: clip 0']))
    reply = hold(window, VIEW_REPLY)
    QTest.keyClicks(view(window), 'x')
    wait_for(lambda: held(window, reply))
    click(window, f'#video-{target}')
    wait_for(lambda: selects(window, target))
    # 마지막 결과가 0개면 화면도 코어도 선택이 없다.
    release(window, reply)
    wait_for(lambda: shows(window, 0, ['제목: clip 0x']))
    wait_for(lambda: selects(window, None))
    assert window.library_page.visible_ids == []
    assert js(window, NOTICES) == ''
