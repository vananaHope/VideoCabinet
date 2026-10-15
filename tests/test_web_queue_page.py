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
    assert changes == [dict(rows=[dict(videoId=a.id, title=a.title, state='queued', progress=.5, message='')],
                            removed=[], order=None, counts=None)]


def test_queue_delta_reports_promoted_order_and_removed_ids(queue_page, setup):
    core, _, (a, b) = setup
    for video in (a, b):
        core.request_subtitles(video.id)
    page = queue_page
    page.refresh()
    changes = []
    page.bridge.queueChanged.connect(lambda value: changes.append(json.loads(value)))

    reply(page.bridge.action('promote', b.id))
    assert changes.pop() == dict(rows=[], removed=[], order=[b.id, a.id], counts=None)

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
