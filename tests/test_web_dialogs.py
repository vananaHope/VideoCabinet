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
from my_video_manager.web_dialogs_entries import TagEditor, TagManager
from my_video_manager.web_dialogs_entries import SeriesEditor
from my_video_manager.web_dialogs_entries import HighlightEditor, HighlightList
from my_video_manager.web_dialogs_entries import ReviewDialog
from my_video_manager.web_dialogs_models import DialogModel
from qt_wait import wait_for


def state(dialogs):
    return json.loads(dialogs.bridge.snapshot())['dialog']


def act(dialogs, action, **payload):
    result = json.loads(dialogs.bridge.act(state(dialogs)['id'], action, json.dumps(payload)))
    assert 'error' not in result, result
    return result['dialog']


def within(entry, dialogs, callback):
    loaded = QSignalSpy(dialogs.host.view.loadFinished)
    if dialogs.host.engine_page.isLoading():
        # 여러 xdist 작업자의 WebEngine 초기 로드에 CPU 시간을 허용한다.
        wait_for(lambda: loaded.count() > 0)
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


def test_library_title_entry_validates_then_saves_in_web(window_factory, core):
    window = window_factory()
    video = core.videos()[0]
    window.library_page.bridge.select(video.id)
    dialogs = window.web_host.dialogs
    def check():
        assert state(dialogs)['kind'] == 'video-rename'
        assert state(dialogs)['values']['name'] == video.title
        result = json.loads(dialogs.bridge.act(state(dialogs)['id'], 'save', json.dumps({'name': ''})))
        assert 'error' in result and core.video(video.id).title == video.title
        act(dialogs, 'save', name='변경한 한글 제목')
        assert core.video(video.id).title == '변경한 한글 제목'
    within(window.library_page.library_controls.rename, dialogs, check)
    assert next(card for card in window.library_page.cards if card['id'] == video.id)['title'] == '변경한 한글 제목'


@pytest.mark.parametrize('accept', [False, True])
def test_library_exclude_entry_uses_web_confirmation_and_preserves_file(window_factory, core, accept):
    window = window_factory()
    video = core.videos()[0]
    window.library_page.bridge.select(video.id)
    dialogs = window.web_host.dialogs
    def check():
        data = state(dialogs)
        assert data['kind'] == 'video-exclude' and data['confirm_destructive']
        act(dialogs, 'confirm' if accept else 'cancel-confirm')
    within(window.library_page.library_controls.exclude, dialogs, check)
    assert core.video(video.id).excluded is accept
    assert video.locations[0].path.exists()


def test_library_series_entry_selects_current_series(window_factory, core):
    window = window_factory()
    video = core.videos()[0]
    series = core.create_series('현재 시리즈', (video.id,))
    window.refresh()
    window.library_page.bridge.select(video.id)
    dialogs = window.web_host.dialogs
    def check():
        assert state(dialogs)['values']['choice'] == str(series.id)
        assert state(dialogs)['values']['members'] == [str(video.id)]
    within(window.library_page.show_series, dialogs, check)


def test_tag_entry_immediate_changes_nested_manager_and_stale_frame(window_factory, core):
    window = window_factory()
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
    window = window_factory()
    dialogs = window.web_host.dialogs
    videos = core.videos()
    def check():
        act(dialogs, 'save', name='수동 시리즈', members=[str(videos[1].id), str(videos[0].id)])
    within(lambda: SeriesEditor(core, window).exec(), dialogs, check)
    assert core.series()[0].video_ids == (videos[1].id, videos[0].id)


def test_highlight_precision_and_nested_tags(window_factory, core):
    window = window_factory()
    dialogs, video = window.web_host.dialogs, core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(1.234567)
    from my_video_manager.core import Command, CommandType
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    highlight = core.highlights(video.id)[0]
    def check():
        assert state(dialogs)['rows'][0]['title'] == '00:00:01.235 (지점)'
        act(dialogs, 'tags', selected=str(highlight.id))
        act(dialogs, 'add', name='장면')
        act(dialogs, 'close')
        act(dialogs, 'edit', selected=str(highlight.id))
        data = state(dialogs)
        act(dialogs, 'save', **{**data['values'], 'text': '메모'})
        assert core.highlights(video.id)[0].start == highlight.start
        assert core.highlight_tags(highlight.id)[0].name == '장면'
    within(lambda: HighlightList(core, video.id, 100, window).exec(), dialogs, check)


def test_highlight_empty_input_is_rejected_and_changed_time_rounds(window_factory, core):
    window = window_factory()
    video = core.videos()[0]
    from my_video_manager.core import Command, CommandType
    core.playback.start(video.id, 0)
    core.playback.report(1.234567)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    highlight = core.highlights(video.id)[0]
    dialogs = window.web_host.dialogs
    def check():
        payload = {**state(dialogs)['values'], 'start': ''}
        assert 'error' in json.loads(dialogs.bridge.act(state(dialogs)['id'], 'save', json.dumps(payload)))
        assert core.highlights(video.id)[0].start == highlight.start
        act(dialogs, 'save', **{**payload, 'start': '2.34567'})
        assert core.highlights(video.id)[0].start == 2.346
    within(lambda: HighlightEditor(core, highlight, 100, window).exec(), dialogs, check)


@pytest.mark.parametrize('kind', ['tag-manager', 'translation', 'subtitles'])
def test_remaining_entry_functions_use_web_layer(window_factory, core, kind):
    window = window_factory()
    dialogs = window.web_host.dialogs
    entries = {'tag-manager': lambda: TagManager(core, window).exec(),
               'translation': window.translations.settings, 'subtitles': window.subtitles.request}
    def check():
        assert state(dialogs)['kind'] == kind
    within(entries[kind], dialogs, check)


def test_dialog_blocks_reserved_navigation_keys(window_factory, core):
    window = window_factory()
    dialogs = window.web_host.dialogs
    def check():
        window.activateWindow()
        for key in (Qt.Key.Key_2, Qt.Key.Key_7):
            QTest.keyClick(window.web_host.view, key, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(window.web_host.view, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert window.web_host.active_tab == 'library'
        assert not window.settings_menu.isVisible()
        window.show_fullscreen_settings_menu()
        assert window.web_host.active_tab == 'library'
        assert not window.settings_menu.isVisible()
    within(lambda: TagManager(core, window).exec(), dialogs, check)


@pytest.mark.parametrize('target', ['reel', 'queue', 'search'], ids=['H-reel-completed', 'tray-show-queue', 'show-search'])
def test_program_navigation_keeps_dialog_as_shell_overlay(window_factory, core, target):
    window = window_factory()
    host, dialogs = window.web_host, window.web_host.dialogs
    navigate = {'reel': window.reel.open, 'queue': window.tray.show_queue, 'search': window.show_search}[target]
    # 숨은 WebEngine은 초기 로드가 지연될 수 있다. 전환 계약을 검사하기 전에
    # 보이는 셸의 준비를 기다리고, 그 뒤 실제 재생 화면으로 전환한다.
    wait_for(lambda: host._loaded_notified)
    window.pages.setCurrentWidget(window.playback_page)
    def check():
        wait_for(lambda: dialogs.container is not None)
        assert host.view.parent() is dialogs.container
        identifier = state(dialogs)['id']
        navigate()
        QTest.qWait(300)
        assert window.pages.currentWidget() is host
        assert host.active_tab == target
        assert dialogs.container is None and host.view.parent() is host
        assert dialogs.active and state(dialogs)['id'] == identifier
    within(lambda: TagManager(core, window).exec(), dialogs, check)
    assert window.pages.currentWidget() is host and host.active_tab == target


def test_modal_keys_reach_other_qt_consumers(window_factory, core):
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QLineEdit
    window = window_factory()
    received = []
    class Capture(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.KeyPress:
                received.append(event.key())
            return False
    capture = Capture(window)
    field = QLineEdit(window)
    field.installEventFilter(capture)
    def check():
        QTest.keyClick(field, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(field, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        assert Qt.Key.Key_2 in received and Qt.Key.Key_S in received
        assert window.web_host.active_tab == 'library'
    within(lambda: TagManager(core, window).exec(), window.web_host.dialogs, check)


@pytest.mark.parametrize('after_detach', [False, True], ids=['A-late-callback', 'B-open-container'])
def test_shell_return_always_reattaches_live_dialog(window_factory, core, after_detach):
    window = window_factory()
    host, dialogs = window.web_host, window.web_host.dialogs
    def check():
        window.pages.setCurrentWidget(window.playback_page)
        if after_detach:
            wait_for(lambda: dialogs.container is not None)
            assert host.view.parent() is dialogs.container
        window.pages.setCurrentWidget(host)
        QTest.qWait(300)
        assert dialogs.active
        assert dialogs.container is None
        assert host.view.parent() is host
    within(lambda: TagManager(core, window).exec(), dialogs, check)


def test_dialog_snapshot_failure_cleans_run_and_allows_retry(window_factory, monkeypatch):
    window = window_factory()
    dialogs = window.web_host.dialogs
    with monkeypatch.context() as patch:
        def fail(self):
            raise ValueError('스냅샷 실패')
        patch.setattr(DialogModel, 'snapshot', fail)
        with pytest.raises(ValueError, match='스냅샷 실패'):
            dialogs.run('tag-manager')
    assert not dialogs.active and dialogs.loop is None and not dialogs.timer.isActive()
    assert dialogs.container is None
    within(lambda: dialogs.run('tag-manager'), dialogs, lambda: act(dialogs, 'close'))


def test_common_modal_gate_clears_on_navigation_reload_and_playback(window_factory):
    window = window_factory()
    host = window.web_host
    host.dialogs.bridge.modalState(1)
    window.activateWindow()
    QTest.keyClick(host.view, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert host.active_tab == 'library'
    host.navigate('statistics')
    assert not host.dialogs.web_modal
    host.dialogs.bridge.modalState(1)
    host.view.loadStarted.emit()
    assert not host.dialogs.web_modal
    host.dialogs.bridge.modalState(1)
    window.pages.setCurrentWidget(window.playback_page)
    assert not host.dialogs.web_modal
    host.dialogs.bridge.modalState(1)  # 숨은 웹에서 늦게 온 상태는 차단을 되살리지 않는다.
    assert not host.dialogs.web_modal


def test_translation_choices_come_from_adapter(window_factory, monkeypatch):
    from dataclasses import replace
    from my_video_manager import translation_options
    choices = tuple(replace(p, label=p.label + ' 검증') for p in translation_options.PROVIDERS)
    monkeypatch.setattr(translation_options, 'PROVIDERS', choices)
    window = window_factory()
    dialogs = window.web_host.dialogs
    def check():
        assert [(r['id'], r['label']) for r in state(dialogs)['translation']['providers']] == [(p.id, p.label) for p in choices]
    within(window.translations.settings, dialogs, check)


@pytest.fixture
def review_window(setup, monkeypatch):
    from my_video_manager.ui import MainWindow
    app = QApplication.instance() or QApplication([])
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


def test_review_failed_player_returns_to_shell_with_live_dialog(review_window):
    window, core, video_id = review_window
    host, dialogs = window.web_host, window.web_host.dialogs
    class BrokenPlayer:
        def play(self, *args, **kwargs):
            raise RuntimeError('mpv 시작 실패')
        def close(self):
            pass
        def position(self):
            return 0
        def take_positions(self):
            return []
        def take_eof(self):
            return False
    window.player_factory = lambda _: BrokenPlayer()
    def check():
        response = json.loads(dialogs.bridge.act(state(dialogs)['id'], 'jump', json.dumps({'selected': core.review_lines(video_id)[0].original.id})))
        assert response['error'] == 'mpv 시작 실패'
        QTest.qWait(300)
        assert window.pages.currentWidget() is host
        assert host.view.parent() is host and dialogs.container is None and dialogs.active
    within(lambda: ReviewDialog(core, video_id, window.review_jump, window.review_changed, window).exec(), dialogs, check)


def test_locked_review_can_replace_range_with_full_regeneration(review_window, setup):
    window, core, video_id = review_window
    core.request_subtitle_range(video_id, 0, 1)
    dialogs = window.web_host.dialogs
    def check():
        assert state(dialogs)['locked']
        warning = act(dialogs, 'regenerate')
        assert warning['confirmation'] and warning['confirm_destructive']
        act(dialogs, 'confirm')
        core.process_next_subtitle()
        assert 'start' not in setup[2].calls[-1] and 'duration' not in setup[2].calls[-1]
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
        assert result['confirm_title'] == '자막 검수' and not result['confirm_destructive']
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
        assert warning['confirm_title'] == '원어 자막 다시 생성' and warning['confirm_destructive']
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
