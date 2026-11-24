"""재생 화면의 화면 번역 자막: MainWindow + 실제 웹 셸(offscreen) + 오버레이 명령을 기록하는 가짜 플레이어.

띠 표시 명령(영역과 그 시각 줄), 켬·끔(키·단추·재생 상태 표시), 받아쓰기 자막 비켜나기,
보는 중 완성·검수 반영, 긴급 탈출·목록 복귀·영상 전환·모아보기 뒤 띠가 남지 않는 명령 순서를 본다.
"""

from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from my_video_manager.core import AppCore, Command, CommandType
from my_video_manager.onscreen_playback import OnScreenBand
from my_video_manager.onscreen_subtitles import RegionEdit, RegionRect
from my_video_manager.translation_source import ONSCREEN
from my_video_manager.ui import MainWindow
from qt_wait import wait_for
from test_onscreen_subtitles import FakeMedia, FakeOcr
from test_onscreen_translation import Translator
from test_playback_page_ui import Player, click, key
from test_translation import finish

BOTTOM = RegionRect(0.1, 0.78, 0.8, 0.16)
TOP = RegionRect(0.05, 0.05, 0.3, 0.1)
BOTTOM_CAPTIONS = ((10, 12, 'Jon show'), (20, 22, 'Next'))
TOP_CAPTIONS = ((11, 15, 'Sign'),)
NO_ONSCREEN = '이 영상에는 화면 번역 자막이 없습니다'


class OverlayPlayer(Player):
    """오버레이·받아쓰기 자막 위치 명령과 엔진 종료를 모든 엔진에 걸친 한 기록(events)에 남긴다."""
    events = []

    def show_onscreen_translation(self, bands):
        self.events.append((self, 'show', tuple(bands)))

    def clear_onscreen_translation(self):
        self.events.append((self, 'clear', None))

    def set_subtitles_raised(self, raised):
        self.events.append((self, 'raise', raised))

    def set_subtitle(self, path):
        pass

    def pause(self):
        self.paused = True

    def prepare_close(self):
        self.events.append((self, 'close', None))


def band(rect, text):
    return OnScreenBand(rect, '번역 ' + text)


@pytest.fixture
def setup(tmp_path, qapp, monkeypatch):
    """a: 위·아래 영역, b: 아래 영역, c: 화면 자막 없음, d: 위 영역만. 화면 번역까지 끝낸 상태로 연다."""
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(OverlayPlayer, 'events', [])
    media, ocr = FakeMedia(), FakeOcr(('en',))
    core = AppCore(media=media, clock=lambda: datetime.now(timezone.utc), ocr_engine=ocr,
                   database=tmp_path / 'data/library.sqlite3', translator=Translator())
    for name in ('a', 'b', 'c', 'd'):
        path = tmp_path / f'{name}.mkv'
        path.write_bytes(name.encode())
        core.add_file(path)
    ids = {video.title: video.id for video in core.videos()}
    read(core, media, ids['a'], {BOTTOM: BOTTOM_CAPTIONS, TOP: TOP_CAPTIONS})
    read(core, media, ids['b'], {BOTTOM: BOTTOM_CAPTIONS})
    read(core, media, ids['d'], {TOP: TOP_CAPTIONS})
    finish(core)
    window = MainWindow(core, player_factory=OverlayPlayer)
    monkeypatch.setattr(window.tray.icon, "showMessage", lambda *args: None)
    for timer in (window.translations.timer, window.onscreen_subtitles.timer, window.subtitles.timer):
        timer.stop()
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield window, ids, media
    window.tray.quit()
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def read(core, media, video_id, captions):
    media.captions_by_region = dict(captions)
    core.set_onscreen_subtitle_regions(video_id, tuple((rect, 'en') for rect in captions))
    assert core.process_next_onscreen_subtitle().state == 'completed'


def play(window, video_id):
    window.play(video_id)
    report(window, 0, seeked=True)


def report(window, position, *, seeked=False):
    window.player.positions = [(position, seeked)]
    window.sync_position()
    QApplication.processEvents()


def events(player=None, since=0):
    return [(action, value) for owner, action, value in OverlayPlayer.events[since:]
            if player is None or owner is player]


def statuses(window):
    return [text for text, _ in window.player.statuses]


def page(window):
    return window.playback_page


def test_starts_on_and_sends_bands_only_when_the_visible_lines_change(setup):
    window, ids, _ = setup
    play(window, ids['a'])
    player = window.player
    assert page(window).onscreen_button.isChecked()
    assert events(player) == []  # 아래·위 영역이 모두 있어 받아쓰기 자막은 그대로, 0초에는 줄 없음
    report(window, 11)
    assert events(player) == [('show', (band(BOTTOM, 'Jon show'), band(TOP, 'Sign')))]
    report(window, 11.5)
    report(window, 11.9)
    assert len(events(player)) == 1  # 같은 줄 묶음은 다시 보내지 않는다
    report(window, 13)
    assert events(player)[1:] == [('show', (band(TOP, 'Sign'),))]  # 아래 영역은 줄이 없어 띠가 없다
    report(window, 16)
    assert events(player)[2:] == [('clear', None)]
    report(window, 17)
    report(window, 21)
    assert events(player)[3:] == [('show', (band(BOTTOM, 'Next'),))]
    # 1초마다 다시 읽어도 같은 줄 묶음이면 보내지 않는다.
    page(window).refresh_details()
    report(window, 21.5)
    assert len(events(player)) == 4


def test_seek_and_speed_pick_lines_by_reported_position(setup):
    window, ids, _ = setup
    play(window, ids['a'])
    player = window.player
    report(window, 21, seeked=True)
    assert events(player) == [('show', (band(BOTTOM, 'Next'),))]
    key(window, Qt.Key.Key_Up)  # 배속 1.25×
    key(window, Qt.Key.Key_Up)
    assert player.options[0] == 1.5
    report(window, 21.75)
    report(window, 11, seeked=True)  # 뒤로 탐색
    assert events(player)[1:] == [('show', (band(BOTTOM, 'Jon show'), band(TOP, 'Sign')))]
    report(window, 14.5)
    assert events(player)[2:] == [('show', (band(TOP, 'Sign'),))]


@pytest.mark.parametrize('method', ['key', 'button'])
def test_key_and_button_toggle_with_playback_status(setup, method):
    window, ids, _ = setup
    play(window, ids['b'])
    player = window.player
    report(window, 11)
    start = len(OverlayPlayer.events)

    def toggle():
        if method == 'key':
            key(window, Qt.Key.Key_BracketRight)
        else:
            click(page(window).onscreen_button)

    toggle()
    assert statuses(window) == ['화면 번역 자막 꺼짐']
    assert events(player, start) == [('raise', False), ('clear', None)]
    assert not page(window).onscreen_button.isChecked()
    report(window, 21)
    assert events(player, start)[2:] == []  # 꺼진 동안은 보내지 않는다
    toggle()
    assert statuses(window) == ['화면 번역 자막 꺼짐', '화면 번역 자막 켜짐']
    assert events(player, start)[2:] == [('raise', True), ('show', (band(BOTTOM, 'Next'),))]
    assert page(window).onscreen_button.isChecked()


def test_video_without_onscreen_translation_keeps_state_and_shows_notice(setup):
    window, ids, _ = setup
    play(window, ids['c'])
    button = page(window).onscreen_button
    assert button.isVisible() and button.isEnabled() and not button.isChecked()
    assert NO_ONSCREEN in button.toolTip()
    for press in (lambda: key(window, Qt.Key.Key_BracketRight), lambda: click(button)):
        window.statusBar().clearMessage()
        press()
        assert statuses(window) == []
        assert page(window).message_label.text() == NO_ONSCREEN
        assert not button.isChecked()
    assert events() == []
    # 없는 영상에서 누른 것은 켬·끔을 바꾸지 않는다: 다음 영상은 켜진 채로 그린다.
    window.play_video(ids['a'])
    report(window, 11, seeked=True)
    assert events(window.player) == [('show', (band(BOTTOM, 'Jon show'), band(TOP, 'Sign')))]


def test_off_state_lasts_across_video_changes_until_leaving_playback(setup):
    window, ids, _ = setup
    play(window, ids['a'])
    key(window, Qt.Key.Key_BracketRight)
    for name in ('b', 'c', 'd'):
        window.play_video(ids[name])
        report(window, 11, seeked=True)
        assert events(window.player) == []
        assert not page(window).onscreen_button.isChecked()
    window.back_to_list()
    wait_for(lambda: window.core.playback.session is None)
    play(window, ids['b'])
    report(window, 11)
    assert page(window).onscreen_button.isChecked()
    assert events(window.player) == [('raise', True), ('show', (band(BOTTOM, 'Jon show'),))]


@pytest.mark.parametrize(('name', 'raised'), [('b', True), ('a', False), ('d', False)])
def test_transcript_subtitles_move_up_only_for_bottom_regions(setup, name, raised):
    window, ids, _ = setup
    play(window, ids[name])
    player = window.player
    assert [value for action, value in events(player) if action == 'raise'] == ([True] if raised else [])
    key(window, Qt.Key.Key_BracketRight)
    key(window, Qt.Key.Key_BracketRight)
    assert [value for action, value in events(player) if action == 'raise'] == ([True, False, True] if raised else [])


def pending_translation(window, ids, media):
    """b 영역을 다시 읽어 화면 번역이 아직 없는 상태로 둔다(번역 대기)."""
    core = window.core
    region = core.onscreen_subtitle_regions(ids['b'])[0]
    media.captions_by_region = {BOTTOM: BOTTOM_CAPTIONS}
    core.update_onscreen_subtitle_region(region.id, BOTTOM, 'en', mode=RegionEdit.REBUILD)
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert core.translation(ids['b'], source=ONSCREEN) is None


def complete_translation(window):
    controls = window.translations
    controls.process_queue()
    wait_for(lambda: controls.worker is None)
    QApplication.processEvents()


def test_translation_completed_while_watching_turns_on_with_status(setup):
    window, ids, media = setup
    pending_translation(window, ids, media)
    play(window, ids['b'])
    player = window.player
    report(window, 11)
    assert events(player) == [] and not page(window).onscreen_button.isChecked()
    complete_translation(window)
    assert statuses(window) == ['화면 번역 자막을 켰습니다']
    assert events(player) == [('raise', True), ('show', (band(BOTTOM, 'Jon show'),))]
    assert page(window).onscreen_button.isChecked()


def test_translation_completed_after_user_turned_off_stays_off(setup):
    window, ids, media = setup
    pending_translation(window, ids, media)
    play(window, ids['a'])
    key(window, Qt.Key.Key_BracketRight)
    window.play_video(ids['b'])
    report(window, 11, seeked=True)
    complete_translation(window)
    assert statuses(window) == []
    assert events(window.player) == []


def test_review_edit_shows_new_text_on_next_update(setup):
    window, ids, _ = setup
    play(window, ids['b'])
    report(window, 11)
    line, = (line for subtitle in window.core.onscreen_subtitles(ids['b'])
             for line in subtitle.lines if line.text == 'Jon show')
    window.core.edit_onscreen_translation_line(line.id, '고친 번역')
    window.review_changed(ids['b'])
    report(window, 11.2)
    assert events(window.player)[-1] == ('show', (OnScreenBand(BOTTOM, '고친 번역'),))


def test_translation_removed_while_watching_clears_band_at_once(setup):
    window, ids, _ = setup
    play(window, ids['b'])
    player = window.player
    report(window, 11)
    region = window.core.onscreen_subtitle_regions(ids['b'])[0]
    window.core.delete_onscreen_subtitle_region(region.id)
    start = len(OverlayPlayer.events)
    wait_for(lambda: events(player, start))  # 1초 주기 갱신이 다시 읽는다
    assert events(player, start) == [('raise', False), ('clear', None)]
    assert not page(window).onscreen_button.isChecked()


def test_emergency_hide_keeps_overlay_and_return_shows_current_lines(setup):
    window, ids, _ = setup
    play(window, ids['a'])
    player = window.player
    report(window, 11)
    shown = len(events(player))
    key(window, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert not window.isVisible() and player.paused
    report(window, 11)
    window.tray.open()
    QApplication.processEvents()
    assert window.isVisible() and window.player is player
    report(window, 11)
    assert len(events(player)) == shown  # 지우지도, 같은 줄을 다시 보내지도 않는다
    key(window, Qt.Key.Key_Return)  # 재개 뒤 줄이 바뀌면 그 엔진에 새 줄 묶음
    report(window, 13)
    assert events(player)[shown:] == [('show', (band(TOP, 'Sign'),))]


def test_return_to_list_clears_before_engine_closes_and_next_playback_redraws(setup):
    window, ids, _ = setup
    play(window, ids['b'])
    first = window.player
    report(window, 11)
    window.back_to_list()
    wait_for(lambda: window.core.playback.session is None)
    assert events(first)[-2:] == [('clear', None), ('close', None)]
    play(window, ids['b'])
    second = window.player
    assert second is not first
    report(window, 11)
    assert events(second) == [('raise', True), ('show', (band(BOTTOM, 'Jon show'),))]
    assert events(first)[-1] == ('close', None)  # 닫힌 엔진에는 더 보내지 않는다


def test_video_change_clears_old_engine_then_draws_on_new_engine(setup):
    window, ids, _ = setup
    play(window, ids['a'])
    first = window.player
    report(window, 11)
    start = len(OverlayPlayer.events)
    window.play_video(ids['b'])
    second = window.player
    report(window, 11, seeked=True)
    sequence = [(owner, action) for owner, action, _ in OverlayPlayer.events[start:]]
    assert sequence == [(first, 'clear'), (first, 'close'), (second, 'raise'), (second, 'show')]


def highlight(core, video_id, start, end):
    core.switch_to(video_id)
    core.playback.report(start, seeked=True)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    made = next(h for h in core.highlights(video_id) if h.start == start)
    core.update_highlight(made.id, start=start, end=end, note='')
    core.end_playback()


def test_reel_keeps_state_across_items_and_starts_on_again(setup):
    window, ids, _ = setup
    core = window.core
    highlight(core, ids['a'], 10.5, 11.8)
    highlight(core, ids['a'], 20.5, 21.5)
    highlight(core, ids['b'], 10.5, 11.8)
    window.reel.start()
    report(window, 10.5, seeked=True)
    first = window.player
    entry = core.reel_playback
    assert entry.video_id == ids['a']
    assert events(first) == [('show', (band(BOTTOM, 'Jon show'),))]
    # 같은 영상의 다음 항목은 같은 엔진에서 탐색만 하고, 줄 묶음이 바뀌어 다시 보낸다.
    key(window, Qt.Key.Key_End)
    report(window, 20.5, seeked=True)
    assert window.player is first
    assert events(first)[1:] == [('show', (band(BOTTOM, 'Next'),))]
    key(window, Qt.Key.Key_BracketRight)
    assert statuses(window)[-1] == '화면 번역 자막 꺼짐'
    # 다른 영상 항목은 새 엔진이고, 모아보기 동안 끔이 그대로다.
    start = len(OverlayPlayer.events)
    key(window, Qt.Key.Key_End)
    report(window, 10.5, seeked=True)
    assert core.reel_playback.video_id == ids['b'] and window.player is not first
    assert events(window.player) == []
    assert events(first, start) == [('close', None)]  # 끈 동안 지운 띠는 다시 지우지 않는다
    # 모아보기 목록으로 돌아갔다가 다시 시작하면 켬으로 시작한다.
    window.back_to_list()
    wait_for(lambda: core.reel_playback is None)
    window.reel.start()
    report(window, 10.5, seeked=True)
    assert page(window).onscreen_button.isChecked()
    assert events(window.player) == [('show', (band(BOTTOM, 'Jon show'),))]


def test_rebound_key_toggles_and_old_key_does_nothing(setup):
    window, ids, _ = setup
    bindings = {row.command: row.keys for row in window.core.key_bindings()}
    bindings[Command(CommandType.TOGGLE_ONSCREEN_TRANSLATION)] = ('K',)
    window.core.save_key_bindings(bindings)
    window.refresh_key_help()
    play(window, ids['b'])
    key(window, Qt.Key.Key_BracketRight)
    assert statuses(window) == [] and page(window).onscreen_button.isChecked()
    key(window, Qt.Key.Key_K)
    assert statuses(window) == ['화면 번역 자막 꺼짐'] and not page(window).onscreen_button.isChecked()
    assert page(window).onscreen_button.toolTip() == '화면 번역 자막 켜기/끄기 · K'
