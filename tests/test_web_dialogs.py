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
from test_onscreen_subtitles import BAND
from test_onscreen_translation import read_screen, screen
from my_video_manager.onscreen_subtitles import RegionEdit, RegionRect
from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE
from my_video_manager.translation_source import ONSCREEN
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


def test_tag_entry_lists_registered_tags_by_video_count(window_factory, core):
    window = window_factory()
    dialogs = window.web_host.dialogs
    video, other, third = core.videos()[:3]
    core.add_video_tag(other.id, '자주')
    core.add_video_tag(third.id, '자주')
    core.add_video_tag(third.id, 'SF액션')
    core.create_tag('새 태그')
    def check():
        data = state(dialogs)
        assert [(t['name'], t['videoCount']) for t in data['tags']] == [('자주', 2), ('SF액션', 1), ('새 태그', 0)]
        assert data['rows'] == []
        data = act(dialogs, 'add', name=data['tags'][1]['name'])
        assert [row['title'] for row in data['rows']] == ['SF액션']
        assert [(t['name'], t['videoCount']) for t in data['tags']] == [('SF액션', 2), ('자주', 2), ('새 태그', 0)]
        assert len(core.tags()) == 3
        act(dialogs, 'manage')
        act(dialogs, 'rename', selected=str(data['tags'][2]['id']))
        act(dialogs, 'save', name='바꾼 태그')
        data = act(dialogs, 'close')
        assert data['kind'] == 'tags' and [t['name'] for t in data['tags']] == ['SF액션', '자주', '바꾼 태그']
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
        for key in (Qt.Key.Key_2, Qt.Key.Key_8):
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
    # 셸 로드 완료 뒤의 전환을 검사한다. 로드 전 전환 경로는 범위 밖이다.
    wait_for(lambda: host._loaded_notified)
    window.pages.setCurrentWidget(window.playback_page)
    def check():
        wait_for(lambda: dialogs.container is not None)
        assert host.view.parent() is dialogs.container
        identifier = state(dialogs)['id']
        navigate()
        QTest.qWait(300)
        wait_for(lambda: not host.return_pending)
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


@pytest.fixture
def screen_window(screen):
    from my_video_manager.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    core = screen[0]
    window = MainWindow(core)
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    window.onscreen_subtitles.timer.stop()  # 화면 자막 읽기는 시험이 직접 처리한다(읽기 중 잠금을 본다)
    window.show()
    yield window, screen
    window.tray.quit()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_review_offers_onscreen_exports_only_when_saved_and_writes_them_through_native_save(
        screen_window, monkeypatch, tmp_path):
    window, (core, media, *_) = screen_window
    a, b = core.videos()
    media.captions_by_region = {BAND: ((10, 12, 'Bottom one'), (30, 32, 'Bottom two')),
                                RegionRect(0.1, 0, 0.8, 0.15): ((20, 21.5, 'Top one'),)}
    read_screen(core, media, a.id, captions=(), regions=((BAND, 'en'), (RegionRect(0.1, 0, 0.8, 0.15), 'en')))
    core.process_next_translation()  # 세 줄 중 두 줄만 화면 번역
    dialogs = window.web_host.dialogs
    chosen = []
    def choose(parent, title, default, filter):
        chosen.append(default)
        return str(tmp_path / f'저장 {len(chosen)}.srt'), filter
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    expected = core.subtitle_export(a.id, source=ONSCREEN)
    partial = core.subtitle_export(a.id, translated=True, source=ONSCREEN)

    def check():
        data = state(dialogs)
        # 원어 자막이 없어도 화면 자막 내보내기는 고를 수 있다. 원어 내보내기는 줄이 없어 막힌다.
        assert data['rows'] == []
        assert [(r['id'], r['title']) for r in data['exports']] == [
            ('export-onscreen', '화면 자막 SRT 저장'), ('export-onscreen-translation', '화면 번역 SRT 저장')]
        act(dialogs, 'export-onscreen')
        QTest.qWait(30)
        assert chosen[0] == str(expected.default_path)
        assert (tmp_path / '저장 1.srt').read_bytes().startswith(b'\xef\xbb\xbf')
        assert (tmp_path / '저장 1.srt').read_text(encoding='utf-8-sig') == expected.text
        warning = act(dialogs, 'export-onscreen-translation')
        assert '1줄 미번역' in warning['confirmation'] and '화면 번역 자막' in warning['confirmation']
        act(dialogs, 'confirm')
        QTest.qWait(30)
        assert chosen[1] == str(tmp_path / 'a.ko.onscreen.srt')
        assert (tmp_path / '저장 2.srt').read_text(encoding='utf-8-sig') == partial.text
    within(lambda: ReviewDialog(core, a.id, window.review_jump, window.review_changed, window).exec(), dialogs, check)

    def check_without_onscreen():
        assert state(dialogs)['exports'] == []
        result = json.loads(dialogs.bridge.act(state(dialogs)['id'], 'export-onscreen', '{}'))
        assert result['error'] == '내보낼 화면 자막이 없습니다'
    within(lambda: ReviewDialog(core, b.id, window.review_jump, window.review_changed, window).exec(),
           dialogs, check_without_onscreen)


def test_onscreen_region_delete_of_an_unread_region_has_no_count_and_cancel_keeps_it(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDeleteDialog
    window, (core, *_) = screen_window
    video = core.videos()[0]
    core.add_onscreen_subtitle_region(video.id, BAND, 'en')
    region, = core.onscreen_subtitle_regions(video.id)
    dialogs = window.web_host.dialogs
    core.playback.start(video.id, 0)

    def check():
        data = state(dialogs)
        assert (data['kind'], data['confirm_title'], data['confirm_destructive']) == (
            'onscreen-region-delete', '화면 자막 영역 지우기', True)
        assert '아직 화면 자막을 만들기 전인 영역입니다' in data['confirmation']
        assert '검수로 고친 줄' not in data['confirmation']
        act(dialogs, 'cancel-confirm')
        assert not dialogs.active
    within(lambda: OnScreenRegionDeleteDialog(core, video.id, region.id, window).exec(), dialogs, check)
    assert core.onscreen_subtitle_regions(video.id) == (region,)
    assert [e.state for e in core.subtitle_queue(kind='onscreen_subtitle')] == ['queued']

    def expire():
        assert dialogs.active
        core.playback.end()  # 그 영상의 재생이 끝나면 영역 지우기 창은 쓸모가 없어 닫힌다.
        wait_for(lambda: not dialogs.active)
    core.playback.start(video.id, 0)
    within(lambda: OnScreenRegionDeleteDialog(core, video.id, region.id, window).exec(), dialogs, expire)
    assert core.onscreen_subtitle_regions(video.id) == (region,)


def test_onscreen_region_delete_closes_when_the_region_is_already_gone(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDeleteDialog
    window, (core, *_) = screen_window
    video = core.videos()[0]
    core.add_onscreen_subtitle_region(video.id, BAND, 'en')
    core.add_onscreen_subtitle_region(video.id, RegionRect(0.1, 0, 0.8, 0.15), 'en')
    region, other = core.onscreen_subtitle_regions(video.id)
    dialogs = window.web_host.dialogs
    core.playback.start(video.id, 0)

    def check():
        state(dialogs)
        core.delete_onscreen_subtitle_region(region.id)  # 창이 열린 사이 다른 경로로 지워졌다
        act(dialogs, 'confirm')
        assert not dialogs.active
        assert '영역이 바뀌었습니다' in window.statusBar().currentMessage()
    within(lambda: OnScreenRegionDeleteDialog(core, video.id, region.id, window).exec(), dialogs, check)
    assert core.onscreen_subtitle_regions(video.id) == (other,)


# #284 화면 자막 영역 시리즈 전체에 적용: 시리즈에 속한 화에만 선택지가 있고, 시리즈 영역 고치기·지우기·바꾸기는 확인 창이
# 영향받는 다른 화 수와 사라질 검수 줄 수의 합을 보인다.
CORNER = RegionRect(0.6, 0.02, 0.38, 0.1)


def series_episodes(core, media):
    """두 화를 시리즈로 묶고 첫 화에서 시리즈 전체에 적용해 둘 다 읽은 뒤, 화마다 영역의 첫 줄을 검수로 고친다."""
    a, b = (v.id for v in core.videos())
    core.create_series('주말 예능 ' + '아주 긴 시리즈 이름 ' * 6, (a, b))
    media.captions = ((10, 12, 'Jon show'), (20, 22, 'Next'))
    core.add_onscreen_subtitle_region(a, BAND, 'en', series=True)
    while core.process_next_onscreen_subtitle():
        pass
    for video in (a, b):
        core.edit_onscreen_translation_line(core.onscreen_subtitles(video)[0].lines[0].id, '고친 번역')
    return a, b


def onscreen_saved(core, videos):
    return [(core.onscreen_subtitle_regions(v), core.onscreen_subtitles(v), core.onscreen_translation_reviewed_lines(v))
            for v in videos], core.subtitle_queue(kind='onscreen_subtitle')


def test_onscreen_region_dialog_offers_the_series_option_only_inside_a_series(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = (v.id for v in core.videos())
    dialogs, seen = window.web_host.dialogs, []
    core.playback.start(a, 0)
    within(lambda: OnScreenRegionDialog(core, a, BAND, window).exec(), dialogs, lambda: seen.append(state(dialogs)))
    assert (seen[0]['series_label'], seen[0]['series_note'], seen[0]['values']['series']) == ('', '', False)
    core.create_series('예능', (a, b))
    core.add_onscreen_subtitle_region(a, BAND, 'en')  # 직접 정한 화: 꺼진 채 열린다
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window).exec(), dialogs, lambda: seen.append(state(dialogs)))
    assert (seen[1]['series_label'], seen[1]['values']['series']) == ('시리즈 전체에 적용 · 예능', False)
    assert '켜면 이 화의 영역 묶음이 시리즈 영역이 되어' in seen[1]['series_note']
    core.add_onscreen_subtitle_region(b, BAND, 'en', series=True)  # 시리즈에서 온 화: 켜진 채 열린다
    region, = core.onscreen_subtitle_regions(b)
    core.playback.start(b, 0)
    for context in ({}, {'region_id': region.id}):
        within(lambda: OnScreenRegionDialog(core, b, CORNER, window, **context).exec(), dialogs,
               lambda: seen.append(state(dialogs)))
        assert seen[-1]['values']['series'] is True
        assert seen[-1]['series_note'] == '끄면 이 화는 앞으로 시리즈 영역 변경을 따르지 않습니다.'


def test_series_apply_without_existing_series_regions_saves_without_a_confirmation(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = (v.id for v in core.videos())
    core.create_series('예능', (a, b))
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        result = act(dialogs, 'save', choice='en', series=True)
        assert result is None or not result['confirmation']
        assert not dialogs.active
    within(lambda: OnScreenRegionDialog(core, a, BAND, window).exec(), dialogs, check)
    assert [r.origin.value for v in (a, b) for r in core.onscreen_subtitle_regions(v)] == ['series', 'series']
    assert [e.video_id for e in core.subtitle_queue(kind='onscreen_subtitle')] == [a, b]


@pytest.mark.parametrize('answer', ['cancel-confirm', 'confirm'])
def test_series_region_edit_confirms_other_episodes_and_reviewed_lines_and_cancel_changes_nothing(screen_window, answer):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    region, = core.onscreen_subtitle_regions(a)
    before = onscreen_saved(core, (a, b))
    dialogs, seen = window.web_host.dialogs, {}
    core.playback.start(a, 0)

    def check():
        data = act(dialogs, 'save', choice='ja', series=True)
        seen.update(data)
        assert data['confirm_title'] == '시리즈 화면 자막 영역 고치기' and data['confirm_destructive']
        assert '이 화와 시리즈 영역을 받은 다른 화 1개에서' in data['confirmation']
        assert '검수로 고친 줄 2개의 수정이 사라집니다' in data['confirmation']
        act(dialogs, answer)
        if answer == 'cancel-confirm':
            assert dialogs.active and not state(dialogs)['confirmation']  # 고르던 창으로 돌아간다
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    if answer == 'cancel-confirm':
        assert onscreen_saved(core, (a, b)) == before
    else:
        assert [(r.rect, r.language, r.origin.value) for v in (a, b) for r in core.onscreen_subtitle_regions(v)] == [
            (CORNER, 'ja', 'series')] * 2
        assert [e.video_id for e in core.subtitle_queue(kind='onscreen_subtitle')] == [a, b]


def test_series_confirmation_follows_changes_while_open_and_asks_again_when_confirmed_on_a_stale_count(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDeleteDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    region, = core.onscreen_subtitle_regions(a)
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        data = state(dialogs)
        assert (data['kind'], data['confirm_title']) == ('onscreen-region-delete', '시리즈 화면 자막 영역 지우기')
        assert '이 화와 시리즈 영역을 받은 다른 화 1개에서' in data['confirmation']
        assert '검수로 고친 줄 2개의 수정이 사라집니다' in data['confirmation']
        # 창이 열린 동안 다른 화의 검수가 늘면 안내가 지금 수로 바뀐다.
        core.edit_onscreen_translation_line(core.onscreen_subtitles(b)[0].lines[1].id, '또 고친 번역')
        assert '검수로 고친 줄 3개의 수정이 사라집니다' in state(dialogs)['confirmation']
        # 안내를 다시 보기 전에 확인하면 지우지 않고 다시 묻는다.
        identifier = state(dialogs)['id']
        core.edit_onscreen_subtitle_line(core.onscreen_subtitles(a)[0].lines[1].id, 'Next one')
        before = onscreen_saved(core, (a, b))
        result = json.loads(dialogs.bridge.act(identifier, 'confirm', '{}'))['dialog']
        assert dialogs.active and onscreen_saved(core, (a, b)) == before
        assert '그 사이 시리즈의 화면 자막 영역이 바뀌었습니다' in result['confirmation']
        assert '검수로 고친 줄 4개의 수정이 사라집니다' in result['confirmation']
        act(dialogs, 'confirm')
        assert not dialogs.active
    within(lambda: OnScreenRegionDeleteDialog(core, a, region.id, window).exec(), dialogs, check)
    assert core.onscreen_subtitle_regions(a) == core.onscreen_subtitle_regions(b) == ()
    assert '시리즈 화면 자막 영역을 지웠습니다' in window.statusBar().currentMessage()


def test_series_region_delete_cancel_keeps_every_episode(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDeleteDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    region, = core.onscreen_subtitle_regions(b)
    before = onscreen_saved(core, (a, b))
    dialogs = window.web_host.dialogs
    core.playback.start(b, 0)

    def check():
        act(dialogs, 'cancel-confirm')
        assert not dialogs.active
    within(lambda: OnScreenRegionDeleteDialog(core, b, region.id, window).exec(), dialogs, check)
    assert onscreen_saved(core, (a, b)) == before


def test_series_apply_from_a_directly_set_episode_confirms_the_replacement(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    region, = core.onscreen_subtitle_regions(b)
    core.update_onscreen_subtitle_region(region.id, region.rect, region.language, mode=RegionEdit.REBUILD)  # 2화만 고쳐 직접 정한 화가 됐다
    dialogs, seen = window.web_host.dialogs, {}
    core.playback.start(b, 0)

    def check():
        seen.update(act(dialogs, 'save', choice='en', series=True))
        act(dialogs, 'confirm')
    within(lambda: OnScreenRegionDialog(core, b, CORNER, window).exec(), dialogs, check)
    assert seen['confirm_title'] == '시리즈 화면 자막 영역 바꾸기'
    assert '이 화와 다른 화 1개의 화면 자막 영역이 바뀝니다' in seen['confirmation']
    assert '검수로 고친 줄 1개의 수정이 사라집니다' in seen['confirmation']
    assert [(r.rect, r.origin.value) for r in core.onscreen_subtitle_regions(a)] == [(BAND, 'series'), (CORNER, 'series')]


def test_series_region_edit_information_follows_the_series_option(screen_window):
    """#365: 시리즈에서 온 영역을 고칠 때 선택지를 켜면 정보 줄이 확인 창과 같은 시리즈 범위의 숫자를 말한다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    region, = core.onscreen_subtitle_regions(a)
    dialogs, seen = window.web_host.dialogs, {}
    core.playback.start(a, 0)

    def check():
        data = state(dialogs)
        assert '이 영역만 화면 자막과 화면 번역 자막을 다시 만듭니다. 검수로 고친 줄 1개' in data['information']
        assert '이 화와 시리즈 영역을 받은 다른 화 1개에서' in data['series_information']
        assert '검수로 고친 줄 2개의 수정이 사라집니다' in data['series_information']
        seen['information'] = data['series_information']
        seen['confirmation'] = act(dialogs, 'save', choice='ja', series=True)['confirmation']
        act(dialogs, 'cancel-confirm')
        act(dialogs, 'close')
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    # 이어지는 확인 창과 같은 문구·숫자다(확인 창은 두 줄로 나눠 보인다).
    assert seen['confirmation'].replace('\n', ' ') == seen['information']


def read_region_with_review(core, media):
    """한 화에 읽기를 마친 영역 하나(두 줄)와 검수로 고친 줄 하나."""
    a = core.videos()[0].id
    media.captions = ((10, 12, 'Jon show'), (20, 22, 'Next'))
    core.add_onscreen_subtitle_region(a, BAND, 'en')
    assert core.process_next_onscreen_subtitle().state == 'completed'
    finish(core)
    region, = core.onscreen_subtitle_regions(a)
    core.edit_onscreen_translation_line(core.onscreen_subtitles(a)[0].lines[0].id, '고친 번역')
    return a, region


def test_region_edit_offers_move_only_for_a_read_region_and_keeps_everything(screen_window):
    """#426: 읽은 영역을 고치면 자리만 바꾸기를 고를 수 있고, 고르면 줄·번역·검수가 그대로이고 대기열에 넣지 않는다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, region = read_region_with_review(core, media)
    before = (core.onscreen_subtitles(a)[0].lines, core.translation(a, source=ONSCREEN),
              core.onscreen_translation_reviewed_lines(a))
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        data = state(dialogs)
        assert data['move_language'] == 'en'
        assert '자리만 바꾸기' in data['move_information'] and '다시 읽기' in data['move_information']
        assert '사라집니다' not in data['move_information']
        assert '검수로 고친 줄 1개의 수정이 사라집니다' in data['information']
        act(dialogs, 'save', choice='en', mode='move')
        assert not dialogs.active
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    assert [r.rect for r in core.onscreen_subtitle_regions(a)] == [CORNER]
    assert (core.onscreen_subtitles(a)[0].lines, core.translation(a, source=ONSCREEN),
            core.onscreen_translation_reviewed_lines(a)) == before
    assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()


@pytest.mark.parametrize('answer', ['cancel-confirm', 'confirm'])
def test_region_rebuild_from_more_confirms_the_lost_reviews(screen_window, answer):
    """#426: 자리만 바꾸기를 고를 수 있을 때 처음부터 다시 만들기는 사라질 검수 수를 확인 창으로 묻는다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, region = read_region_with_review(core, media)
    lines = core.onscreen_subtitles(a)[0].lines
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        data = act(dialogs, 'save', choice='en', mode='rebuild')
        assert data['confirm_destructive'] and '검수로 고친 줄 1개의 수정이 사라집니다' in data['confirmation']
        assert core.onscreen_subtitles(a)[0].lines == lines  # 확인 전에는 바뀌지 않는다
        act(dialogs, answer)
        if dialogs.active:
            act(dialogs, 'close')
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    if answer == 'confirm':
        assert core.onscreen_subtitles(a) == () and len(core.subtitle_queue(kind=ONSCREEN_SUBTITLE)) == 1
    else:
        assert core.onscreen_subtitles(a)[0].lines == lines and core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()


def test_region_reread_queues_only_that_region_without_a_confirmation(screen_window):
    """#427: 다시 읽기는 검수한 줄을 지키므로 확인 창 없이 그 영역만 다시 읽도록 넣고, 기존 번역은 그대로 보인다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, region = read_region_with_review(core, media)
    before = (core.onscreen_subtitles(a)[0].lines, core.translation(a, source=ONSCREEN))
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        result = act(dialogs, 'save', choice='en', mode='reread')
        assert result is None or not result['confirmation']
        assert not dialogs.active
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    assert [r.rect for r in core.onscreen_subtitle_regions(a)] == [CORNER]
    assert (core.onscreen_subtitles(a)[0].lines, core.translation(a, source=ONSCREEN)) == before
    assert len(core.subtitle_queue(kind=ONSCREEN_SUBTITLE)) == 1
    assert '다시 읽도록' in window.statusBar().currentMessage()


def test_region_edit_of_an_unread_region_offers_only_rebuild_without_a_confirmation(screen_window):
    """#426: 아직 읽지 않은 영역은 자리만 바꾸기가 없고, 화면 자막 만들기는 지금처럼 바로 대기열에 넣는다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a = core.videos()[0].id
    core.add_onscreen_subtitle_region(a, BAND, 'en')
    region, = core.onscreen_subtitle_regions(a)
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        data = state(dialogs)
        assert (data['move_language'], data['move_information']) == ('', '')
        result = act(dialogs, 'save', choice='en')
        assert result is None or not result['confirmation']
        assert not dialogs.active
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window, region_id=region.id).exec(), dialogs, check)
    assert [r.rect for r in core.onscreen_subtitle_regions(a)] == [CORNER]


def test_series_add_whose_range_changed_at_the_last_moment_saves_without_a_replace_confirmation(screen_window, monkeypatch):
    """#365: 시리즈에서 온 화에 새 영역을 더하는 일은 확인 창이 없다. 막판에 범위만 바뀌어도 바꾸기 확인 창을 띄우지 않는다."""
    from my_video_manager.web_dialogs_entries import OnScreenRegionDialog
    window, (core, media, *_) = screen_window
    a, b = series_episodes(core, media)
    series = core.series_for_video(a)
    measure = core.onscreen_subtitle_region_series_impact

    def measure_then_leave(*args, **kwargs):
        impact = measure(*args, **kwargs)
        if core.series_for_video(b) is not None:
            core.update_series(series.id, name=series.name, video_ids=(a,))  # 잰 직후 2화가 시리즈에서 빠진다
        return impact
    monkeypatch.setattr(core, 'onscreen_subtitle_region_series_impact', measure_then_leave)
    dialogs = window.web_host.dialogs
    core.playback.start(a, 0)

    def check():
        result = act(dialogs, 'save', choice='en', series=True)
        assert result is None or not result['confirmation']
        assert not dialogs.active
    within(lambda: OnScreenRegionDialog(core, a, CORNER, window).exec(), dialogs, check)
    assert [(r.rect, r.origin.value) for r in core.onscreen_subtitle_regions(a)] == [(BAND, 'series'), (CORNER, 'series')]
    assert [(r.rect, r.origin.value) for r in core.onscreen_subtitle_regions(b)] == [(BAND, 'direct')]


# #285 검수 화면의 화면 자막: 받아쓰기 자막과 구별해 영역마다 열고 원문·화면 번역 줄을 고친다.
TOP = RegionRect(0.6, 0.02, 0.38, 0.1)


def onscreen_review_video(core, media, video, *, failed=False):
    """받아쓰기 원어 자막과, 읽기를 마친 영역 둘(아래 en 두 줄, 위 ja 한 줄). failed면 읽기에 실패한 영역 하나를 더한다."""
    from test_translation import source
    source(core, video)
    media.captions_by_region = {BAND: ((10, 12, 'Jon show'), (20, 22, 'Next')), TOP: ((5, 7, 'Corner'),)}
    core.add_onscreen_subtitle_region(video, BAND, 'en')
    core.add_onscreen_subtitle_region(video, TOP, 'ja')
    assert core.process_next_onscreen_subtitle().state == 'completed'
    finish(core)
    if failed:
        media.error_at = 0
        core.add_onscreen_subtitle_region(video, RegionRect(0, 0.4, 0.5, 0.2), 'en')
        assert core.process_next_onscreen_subtitle().state == 'failed'
        media.error_at = None
    return core.onscreen_subtitles(video)


def rows(data):
    return [(r['title'], r['detail'], r['status']) for r in data['rows']]


def test_review_opens_transcript_or_each_read_onscreen_region_and_edits_its_lines(screen_window):
    window, (core, media, *_) = screen_window
    a, b = core.videos()
    bottom, top = onscreen_review_video(core, media, a.id, failed=True)
    failed = core.onscreen_subtitle_regions(a.id)[2]
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    transcript_rows = [(line.original.text, line.translation) for line in core.review_lines(a.id)]
    dialogs = window.web_host.dialogs
    jumps = []

    def check():
        data = state(dialogs)
        # 읽기를 마친 영역만 고를 수 있다. 영역 번호는 영상의 영역 순서이고 읽을 언어가 함께 보인다.
        assert [(c['id'], c['title']) for c in data['choices']] == [
            ('transcript', '받아쓰기 자막 · 원어 · 번역 자막'),
            (str(bottom.region.id), '화면 자막 영역 1 · 영어(en) · 2줄'),
            (str(top.region.id), '화면 자막 영역 2 · 일본어(ja) · 1줄')]
        assert data['values']['choice'] == 'transcript' and data['task_kind'] == 'translation'
        assert [(r['title'], r['detail']) for r in data['rows']] == transcript_rows
        # 읽지 못한 영역이 남아 있으면 고친 원문을 다시 번역할 수 없어 원문 수정을 거부한다. 그 영역을 지운다.
        core.delete_onscreen_subtitle_region(failed.id)
        data = act(dialogs, 'view', choice=str(bottom.region.id))
        assert (data['values']['choice'], data['task_kind'], data['short_label'], data['subtitle_label']) == (
            str(bottom.region.id), 'onscreen_translation', '화면 번역', '화면 번역 자막')
        assert rows(data) == [('Jon show', '번역 Jon show', 'Codex (CLI)'), ('Next', '번역 Next', 'Codex (CLI)')]
        assert [(r['start'], r['end']) for r in data['rows']] == [(10, 12), (20, 22)]
        act(dialogs, 'jump', selected=bottom.lines[1].id)
        assert jumps == [(a.id, bottom.lines[1].id)]
        # 원문 줄 수정: 원문 검수됨으로 남고 그 줄만 다시 번역을 기다린다.
        line = act(dialogs, 'edit-original', selected=bottom.lines[1].id)
        assert (line['kind'], line['title'], line['values']['text']) == ('line', '원문 줄 수정', 'Next')
        data = act(dialogs, 'save', text='Next scene')
        # 다시 번역하기 전에는 이전 번역과 그 번역의 방식이 보인다(번역 자막 검수와 같다).
        assert data['kind'] == 'review' and rows(data)[1] == ('Next scene', '번역 Next', '원문 검수됨 · Codex (CLI)')
        finish(core)
        assert rows(state(dialogs))[1] == ('Next scene', '번역 Next scene', '원문 검수됨 · Codex (CLI)')
        line = act(dialogs, 'edit-translation', selected=bottom.lines[0].id)
        assert (line['title'], line['values']['text']) == ('화면 번역 줄 수정', '번역 Jon show')
        assert rows(act(dialogs, 'save', text='존 쇼'))[0] == ('Jon show', '존 쇼', '직접 수정')
        # 직접 고친 번역이 있는 줄의 원문을 고치면 확인을 받는다. 취소하면 아무것도 바뀌지 않는다.
        data = act(dialogs, 'view', choice=str(top.region.id))
        assert rows(data) == [('Corner', '고친 코너', '직접 수정')]
        act(dialogs, 'edit-original', selected=top.lines[0].id)
        warning = act(dialogs, 'save', text='Corner title')
        assert '덮어써집니다' in warning['confirmation'] and warning['confirm_destructive']
        assert not warning['keep_reviewed']
        act(dialogs, 'cancel-confirm')
        assert core.onscreen_review_lines(top.region.id)[0].original.text == 'Corner'
        assert core.onscreen_translation_reviewed_lines(a.id) == {top.lines[0].id, bottom.lines[0].id}
        act(dialogs, 'save', text='Corner title')
        assert rows(act(dialogs, 'confirm')) == [('Corner title', '고친 코너', '원문 검수됨')]
        assert core.onscreen_translation_reviewed_lines(a.id) == {bottom.lines[0].id}
        # 받아쓰기 자막으로 돌아오면 원래 줄 목록이다.
        assert [(r['title'], r['detail']) for r in act(dialogs, 'view', choice='transcript')['rows']] == transcript_rows

    within(lambda: ReviewDialog(core, a.id, lambda *args: jumps.append(args), window.review_changed, window).exec(),
           dialogs, check)

    def check_without_onscreen():
        data = state(dialogs)
        assert data['choices'] == [] and data['task_kind'] == 'translation'
    within(lambda: ReviewDialog(core, b.id, window.review_jump, window.review_changed, window).exec(),
           dialogs, check_without_onscreen)


def test_review_regenerates_an_onscreen_range_and_locks_while_reading(screen_window):
    window, (core, media, *_) = screen_window
    a = core.videos()[0]
    bottom, top = onscreen_review_video(core, media, a.id)
    dialogs = window.web_host.dialogs

    def check():
        act(dialogs, 'view', choice=str(bottom.region.id))
        data = act(dialogs, 'range', selected=bottom.lines[1].id)
        assert (data['kind'], data['title'], data['values']['start'], data['values']['end']) == (
            'range', '구간 화면 자막 다시 생성', 20, 22)
        assert '20.000–22.000' in act(dialogs, 'bounds', start=21, end=21.5)['description']
        assert act(dialogs, 'bounds', start=21, end=200)['warning']
        data = act(dialogs, 'save', start=21, end=21.5)
        assert data['kind'] == 'review' and data['locked'] and '화면 자막 읽기' in data['warning']
        # 화면 자막 읽기 중에는 원문·화면 번역 줄 수정과 구간 다시 생성을 모두 막는다.
        before = core.onscreen_review_lines(bottom.region.id)
        for action in ('edit-original', 'edit-translation'):
            act(dialogs, action, selected=bottom.lines[0].id)
            error = json.loads(dialogs.bridge.act(state(dialogs)['id'], 'save', json.dumps({'text': '금지'})))
            assert '화면 자막' in error['error']
            act(dialogs, 'close')
        assert core.onscreen_review_lines(bottom.region.id) == before
        assert state(dialogs)['locked']
        # 받아쓰기 자막은 화면 자막 읽기와 무관하게 고칠 수 있다.
        assert not act(dialogs, 'view', choice='transcript')['locked']
        media.captions_by_region[BAND] = ((20, 22, 'Replaced'),)
        assert core.process_next_onscreen_subtitle().state == 'completed'
        data = act(dialogs, 'view', choice=str(bottom.region.id))
        assert not data['locked'] and [r['title'] for r in data['rows']] == ['Jon show', 'Replaced']
        assert rows(data)[1][1] == '미번역'

    within(lambda: ReviewDialog(core, a.id, window.review_jump, window.review_changed, window).exec(), dialogs, check)
    assert core.onscreen_subtitles(a.id)[1] == top


def test_review_of_a_no_text_region_shows_guidance_and_falls_back_when_the_region_changes(screen_window):
    window, (core, media, *_) = screen_window
    a = core.videos()[0]
    media.captions_by_region = {BAND: ()}
    core.add_onscreen_subtitle_region(a.id, BAND, 'en')
    assert core.process_next_onscreen_subtitle().state == 'completed'
    empty, = core.onscreen_subtitles(a.id)
    dialogs = window.web_host.dialogs

    def check():
        data = state(dialogs)
        assert data['choices'][1]['title'] == '화면 자막 영역 1 · 영어(en) · 읽은 글자 없음'
        assert data['rows'] == []  # 받아쓰기 원어 자막이 없어도 검수 화면은 열린다
        data = act(dialogs, 'view', choice=str(empty.region.id))
        assert data['rows'] == [] and '읽은 글자가 없습니다' in data['information']
        assert act(dialogs, 'range', selected='')['title'] == '구간 화면 자막 다시 생성'
        act(dialogs, 'close')
        core.delete_onscreen_subtitle_region(empty.region.id)
        data = state(dialogs)
        assert (data['choices'], data['values']['choice']) == ([], 'transcript')
        assert '받아쓰기 자막' in data['information']
        error = json.loads(dialogs.bridge.act(data['id'], 'view', json.dumps({'choice': str(empty.region.id)})))
        assert '영역이 바뀌었습니다' in error['error']

    within(lambda: ReviewDialog(core, a.id, window.review_jump, window.review_changed, window).exec(), dialogs, check)


def test_region_delete_confirmation_counts_original_edits_as_reviewed_lines(screen_window):
    from my_video_manager.web_dialogs_entries import OnScreenRegionDeleteDialog
    window, (core, media, *_) = screen_window
    video = core.videos()[0]
    bottom, top = onscreen_review_video(core, media, video.id)
    core.edit_onscreen_subtitle_line(bottom.lines[0].id, 'Jon shows')
    core.edit_onscreen_subtitle_line(bottom.lines[1].id, 'Next one')
    core.edit_onscreen_translation_line(bottom.lines[1].id, '다음')
    dialogs = window.web_host.dialogs
    core.playback.start(video.id, 0)

    def check():
        assert '검수로 고친 줄 2개의 수정이 사라집니다' in state(dialogs)['confirmation']
        act(dialogs, 'cancel-confirm')
    within(lambda: OnScreenRegionDeleteDialog(core, video.id, bottom.region.id, window).exec(), dialogs, check)
    core.playback.end()
