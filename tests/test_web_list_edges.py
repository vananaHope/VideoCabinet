"""추천·모아보기·검색 화면의 목록 가장자리, 추천 카드 시청 상태 배지, 결과 행 긴 제목(#382)."""
import json

import pytest

from qt_wait import wait_for
from test_library_return_ui import Player
from test_reel import mark
from test_web_library_data import core
from test_web_library_page import window_factory
from test_web_recommend_page import abandon, finish

# 파일 이름 한도(255바이트) 안에서 결과 행 제목이 세 줄을 넘는 길이.
LONG_TITLE = 'W' * 240

# 페이지 머리글 제목, 목록 요소, 첫 항목(추천은 첫 줄 제목과 첫 카드)의 왼쪽 경계와 첫 항목 제목이 몇 줄인지 잰다.
MEASURE = """JSON.stringify((() => {
  const main = document.querySelector('main[aria-label="%s"]')
  const header = main?.querySelector('h1'), list = main?.querySelector('%s'), item = list?.querySelector('%s')
  if (!header || !item || !main.getClientRects().length) return null
  const left = element => element.getBoundingClientRect().left
  const title = item.querySelector('.text-body-strong')
  const style = getComputedStyle(title)
  // 줄 제한을 푼 복제본으로 제목 전체가 몇 줄인지 잰다.
  const full = title.cloneNode(true)
  full.style.display = 'block'; full.style.webkitLineClamp = 'none'; full.style.overflow = 'visible'
  title.after(full)
  const fullLines = Math.round(full.getBoundingClientRect().height / parseFloat(style.lineHeight))
  full.remove()
  return {
    header: left(header), list: left(list), item: left(item),
    rowTitle: list.querySelector('[role=rowheader] h2') ? left(list.querySelector('[role=rowheader] h2')) : null,
    listPadding: parseFloat(getComputedStyle(list).paddingInlineStart),
    lines: Math.round(title.getBoundingClientRect().height / parseFloat(style.lineHeight)),
    fullLines, tooltip: title.title, text: title.textContent,
    badges: [...item.querySelectorAll('[data-slot=status-badge]')].map(badge => badge.textContent),
  }
})())"""


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


def measure(window, page, list_selector, item_selector):
    measured = []

    def ready():
        measured[:] = [json.loads(js(window, MEASURE % (page, list_selector, item_selector)))]
        return measured[0] is not None
    wait_for(ready)
    return measured[0]


def add_long_video(core):
    path = core.database.parent.parent / f'{LONG_TITLE}.mkv'
    path.write_bytes(b'long')
    core.add_file(path)
    return next(video for video in core.videos() if video.title == LONG_TITLE)


def assert_edges(box):
    # 목록 안쪽 여백은 선택 테두리·초점 윤곽선 자리로 남고, 첫 항목 왼쪽 가장자리는 페이지 머리글과 같다.
    assert box['listPadding'] > 0, box
    assert box['item'] == pytest.approx(box['header'], abs=0.5), box
    assert box['list'] == pytest.approx(box['header'] - box['listPadding'], abs=0.5), box


def test_recommend_card_uses_viewing_badge_and_aligns_with_header(window_factory, core):
    first, second, third = core.videos()
    abandon(core, first, second)
    finish(core, third)
    window = window_factory()
    window.player_factory = Player
    window.navigate_web_tab('recommend')
    box = measure(window, '추천', '#recommendations', '[role=gridcell]')
    assert_edges(box)
    assert box['rowTitle'] == pytest.approx(box['header'], abs=0.5), box
    # 라이브러리 카드와 같은 시청 상태 배지를 쓴다.
    assert box['badges'] == ['보다 만 40%'], box


@pytest.mark.parametrize('tab,page,list_selector', [('reel', '하이라이트 모아보기', '#reel-list'), ('search', '검색', '#search-results')])
def test_result_rows_clamp_long_titles_and_align_with_header(window_factory, core, tab, page, list_selector):
    video = add_long_video(core)
    mark(core, video, 10, 15)
    window = window_factory()
    window.player_factory = Player
    window.navigate_web_tab(tab)
    if tab == 'search':
        window.web_host.controllers['search'].bridge.find('WWWW')
    box = measure(window, page, list_selector, '[role=option]')
    assert_edges(box)
    # 긴 제목은 두 줄에서 말줄임하고, 전체 제목은 마우스 올림 제목으로 확인한다.
    assert box['lines'] == 2 and box['fullLines'] > 2, box
    assert box['tooltip'] == LONG_TITLE and box['text'] == LONG_TITLE, box
