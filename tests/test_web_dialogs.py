"""기존 진입점과 웹 공개 브리지로 도메인 저장·경고·잠금·포커스를 검증한다."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if os.environ['QT_QPA_PLATFORM'] == 'offscreen':
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')

import pytest
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from test_web_library_data import core
from test_web_library_page import window_factory
from test_review import setup, finish
from my_video_manager.tag_ui import TagEditor, TagManager
from my_video_manager.series_ui import SeriesEditor
from my_video_manager.highlight_ui import HighlightEditor, HighlightList
from my_video_manager.review_ui import ReviewDialog
from my_video_manager.web_dialogs_models import DialogModel


def state(dialogs):
    return json.loads(dialogs.bridge.snapshot())['dialog']


def act(dialogs, action, **payload):
    result = json.loads(dialogs.bridge.act(state(dialogs)['id'], action, json.dumps(payload)))
    assert 'error' not in result, result
    return result['dialog']


def within(entry, dialogs, callback):
    loaded = QSignalSpy(dialogs.host.view.loadFinished)
    if dialogs.host.engine_page.isLoading():
        assert loaded.wait(10000)
    errors = []
    def run():
        try:
            callback()
        except BaseException as error:
            errors.append(error)
        finally:
            while dialogs.active:
                dialogs.pop()
    QTimer.singleShot(50, run)
    entry()
    QTest.qWait(100)
    if errors:
        raise errors[0]


def test_tag_entry_immediate_changes_nested_manager_and_stale_frame(window_factory, core):
    window = window_factory('1')
    dialogs, video = window.web_host.dialogs, core.videos()[0]
    def check():
        assert window.web_host.view.parent() is window.web_host
        tag_state = act(dialogs, 'add', name='  한글   태그  ')
        assert [t.name for t in core.video_tags(video.id)] == ['한글 태그']
        stale = tag_state['id']
        act(dialogs, 'manage')
        assert 'error' in json.loads(dialogs.bridge.act(stale, 'close', '{}'))
        tag = core.tags()[0]
        act(dialogs, 'rename', selected=str(tag.id))
        act(dialogs, 'save', name='바뀐 이름')
        assert core.video_tags(video.id)[0].name == '바뀐 이름'
        confirmed = act(dialogs, 'delete', selected=str(tag.id))
        assert confirmed['confirmation'] and core.tags()
        act(dialogs, 'cancel-confirm')
        assert core.tags()
        act(dialogs, 'delete', selected=str(tag.id))
        act(dialogs, 'confirm')
        assert not core.tags()
        act(dialogs, 'close')
        assert state(dialogs)['kind'] == 'tags'
    within(lambda: TagEditor(core, video_id=video.id, parent=window).exec(), dialogs, check)


def test_series_entry_saves_order_without_changing_other_series(window_factory, core):
    window = window_factory('1')
    dialogs = window.web_host.dialogs
    videos = core.videos()
    def check():
        act(dialogs, 'save', name='수동 시리즈', members=[str(videos[1].id), str(videos[0].id)])
    within(lambda: SeriesEditor(core, window).exec(), dialogs, check)
    assert core.series()[0].video_ids == (videos[1].id, videos[0].id)


def test_highlight_precision_and_nested_tags(window_factory, core):
    window = window_factory('1')
    dialogs, video = window.web_host.dialogs, core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(1.234567)
    from my_video_manager.core import Command, CommandType
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    highlight = core.highlights(video.id)[0]
    def check():
        act(dialogs, 'tags', selected=str(highlight.id))
        act(dialogs, 'add', name='장면')
        act(dialogs, 'close')
        act(dialogs, 'edit', selected=str(highlight.id))
        data = state(dialogs)
        act(dialogs, 'save', **{**data['values'], 'text': '메모'})
        assert core.highlights(video.id)[0].start == highlight.start
        assert core.highlight_tags(highlight.id)[0].name == '장면'
    within(lambda: HighlightList(core, video.id, 100, window).exec(), dialogs, check)


@pytest.mark.parametrize('kind', ['tag-manager', 'translation', 'subtitles'])
def test_remaining_entry_functions_use_web_layer(window_factory, core, kind):
    window = window_factory('1')
    dialogs = window.web_host.dialogs
    entries = {'tag-manager': lambda: TagManager(core, window).exec(),
               'translation': window.translations.settings, 'subtitles': window.subtitles.request}
    def check():
        assert state(dialogs)['kind'] == kind
    within(entries[kind], dialogs, check)


def test_dialog_blocks_reserved_navigation_keys(window_factory, core):
    window = window_factory('1')
    dialogs = window.web_host.dialogs
    def check():
        window.activateWindow()
        for key in (Qt.Key.Key_2, Qt.Key.Key_7):
            QTest.keyClick(window.web_host.view, key, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(window.web_host.view, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert window.web_host.active_tab == 'library'
        assert not window.settings_menu.isVisible()
    within(lambda: TagManager(core, window).exec(), dialogs, check)


def test_common_modal_gate_clears_on_navigation_reload_and_playback(window_factory):
    window = window_factory('1')
    host = window.web_host
    host.bridge.modalState(True)
    window.activateWindow()
    QTest.keyClick(host.view, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert host.active_tab == 'library'
    host.navigate('statistics')
    assert not host.dialogs.web_modal
    host.bridge.modalState(True)
    host.view.loadStarted.emit()
    assert not host.dialogs.web_modal
    host.bridge.modalState(True)
    window.pages.setCurrentWidget(window.playback_page)
    assert not host.dialogs.web_modal
    host.bridge.modalState(True)  # 숨은 웹에서 늦게 온 상태는 차단을 되살리지 않는다.
    assert not host.dialogs.web_modal


def test_translation_choices_come_from_adapter(window_factory, monkeypatch):
    from my_video_manager import translation_cli
    monkeypatch.setattr(translation_cli, 'TRANSLATION_CLI_CHOICES', (('codex', 'Codex 표시 이름'), ('claude', 'Claude 표시 이름')))
    window = window_factory('1')
    dialogs = window.web_host.dialogs
    def check():
        assert [(r['id'], r['title']) for r in state(dialogs)['choices']] == list(translation_cli.TRANSLATION_CLI_CHOICES)
    within(window.translations.settings, dialogs, check)


@pytest.fixture
def review_window(setup, monkeypatch):
    from my_video_manager.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('MVM_WEB_UI', '1')
    core, video_id, *_ = setup
    window = MainWindow(core)
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    window.show()
    yield window, core, video_id
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_review_protected_translation_confirmation_and_queue_lock(review_window):
    window, core, video_id = review_window
    finish(core)
    line = core.review_lines(video_id)[0]
    core.edit_translation_line(video_id, line.original.id, '직접 검수한 번역')
    dialogs = window.web_host.dialogs
    def check():
        act(dialogs, 'edit-original', selected=line.original.id)
        warning = act(dialogs, 'save', text='고친 원어')
        assert '덮어' in warning['confirmation']
        assert core.review_lines(video_id)[0].original.text == line.original.text
        act(dialogs, 'confirm')
        assert core.review_lines(video_id)[0].original.text == '고친 원어'
        act(dialogs, 'range', selected=line.original.id)
        bounds = act(dialogs, 'bounds', start=0.5, end=1.5)
        assert '0.000–2.000' in bounds['description']
        act(dialogs, 'save', start=0.5, end=1.5)
        assert state(dialogs)['locked']
        act(dialogs, 'edit-translation', selected=line.original.id)
        error = json.loads(dialogs.bridge.act(state(dialogs)['id'], 'save', json.dumps({'text': '금지'})))
        assert 'error' in error
    within(lambda: ReviewDialog(core, video_id, window.review_jump, window.review_changed, window).exec(), dialogs, check)


def test_review_export_keeps_confirmed_snapshot_and_native_save(review_window, monkeypatch, tmp_path):
    window, core, video_id = review_window
    core.process_next_translation()  # 일부 번역만 완료
    dialogs = window.web_host.dialogs
    destination = tmp_path / '검수.srt'
    calls = []
    def choose(parent, title, default, filter):
        calls.append((parent, title, default, filter))
        return str(destination), filter
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    expected = core.subtitle_export(video_id, translated=True)
    def check():
        result = act(dialogs, 'export-translation')
        assert '미번역' in result['confirmation']
        finish(core)
        act(dialogs, 'confirm')
        QTest.qWait(30)
        assert destination.read_text(encoding='utf-8-sig') == expected.text
        assert destination.read_bytes().startswith(b'\xef\xbb\xbf')
        assert calls[0][1] == 'SRT 저장'
    within(lambda: ReviewDialog(core, video_id, window.review_jump, window.review_changed, window).exec(), dialogs, check)


def test_subtitle_entry_warns_before_replacing_reviewed_lines(review_window):
    window, core, video_id = review_window
    dialogs = window.web_host.dialogs
    line = core.review_lines(video_id)[0]
    core.edit_transcript_line(video_id, line.original.id, '직접 고친 원어')
    before = core.subtitle_queue()
    def check():
        warning = act(dialogs, 'save', choice='ja')
        assert '1줄' in warning['confirmation']
        act(dialogs, 'cancel-confirm')
        assert core.subtitle_queue() == before
        act(dialogs, 'save', choice='ja')
        act(dialogs, 'confirm')
        assert core.subtitle_queue()[0].state == 'queued'
    within(window.subtitles.request, dialogs, check)


def test_translation_entry_retries_held_work_with_selected_cli(review_window, setup):
    from my_video_manager.translation import TranslationError
    window, core, video_id = review_window
    translator = setup[3]
    translator.error = TranslationError('usage_limit', '한도 보류')
    assert core.process_next_translation().state == 'held'
    dialogs = window.web_host.dialogs
    def check():
        assert '1건' in state(dialogs)['description']
        act(dialogs, 'save', choice='claude')
    within(window.translations.settings, dialogs, check)
    assert core.translation_cli == 'claude'
    assert core.translation_queue()[0].state == 'queued'
