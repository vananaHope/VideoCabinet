"""목록 복귀의 위치 보고 경계와 엔진 종료 중 UI 응답을 검사한다."""
from threading import Event
from time import perf_counter
import json
import pytest

from PySide6.QtCore import QTimer, QObject, QEvent
from PySide6.QtWidgets import QWidget

from test_playback_page_ui import app, window, Player, mouse, PRESS, RELEASE, wait_past_click_interval
from qt_wait import wait_for
from my_video_manager.random_continuous_play import RandomPlayScope


class SlowPlayer(Player):
    def __init__(self, surface):
        super().__init__(surface)
        self.release = Event()
        self.started = Event()
        self.finished = Event()
        self.prepared = False
        self.surface_id = surface

    def prepare_close(self):
        self.prepared = True

    def close(self):
        self.started.set()
        self.release.wait(2)
        # 끝난 엔진에서 뒤늦게 들어온 보고는 다음 시청에 적용하면 안 된다.
        self.positions.append((110, False))
        self.closed = True
        self.finished.set()


def test_return_does_not_wait_for_player_shutdown_and_saves_once(window):
    window.player_factory = SlowPlayer
    video = window.core.videos()[0]
    window.play_video(video.id, start=0)
    player = window.player
    player.positions += [(0, True), (40, False)]
    hidden = []
    class SurfaceEvents(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Hide:
                hidden.append(True)
            return False
    events = SurfaceEvents()
    QWidget.find(player.surface_id).installEventFilter(events)
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    started = perf_counter()
    try:
        window.back_to_list()
        assert perf_counter() - started < .5
        assert hidden == []  # 웹 준비 전에 native 마지막 프레임을 지우지 않는다.
        wait_for(lambda: bool(ticks))
        assert player.prepared
        assert window.core.playback.session is None
        assert window.core.viewing_status(video.id).resume_point == 40
        count = len(window.core.viewings(video.id))
        window.back_to_list()
        assert len(window.core.viewings(video.id)) == count
        wait_for(player.started.is_set)
        assert not player.finished.is_set()
    finally:
        player.release.set()
        wait_for(player.finished.is_set)
    assert window.core.viewings(video.id)[-1].last_position == 40


def test_new_playback_isolated_from_closing_engine(window):
    window.player_factory = SlowPlayer
    first, second = window.core.videos()
    window.play_video(first.id, start=0)
    old = window.player
    old.positions += [(0, True), (40, False)]
    try:
        window.back_to_list()
        surfaces = []
        window.player_factory = lambda surface: surfaces.append(surface) or Player(surface)
        window.play_video(second.id, start=0)
        assert surfaces[-1] != old.surface_id
        new = window.player
        old.release.set()
        wait_for(old.finished.is_set)
        new.positions += [(0, True), (12, False)]
        window.sync_position()
        assert window.core.playback.session.video_id == second.id
        assert window.core.playback.position == 12
        assert window.core.viewing_status(first.id).resume_point == 40
        window.back_to_list()
        assert window.core.viewing_status(second.id).resume_point == 12
    finally:
        old.release.set()
        wait_for(old.finished.is_set)


def test_native_child_click_keeps_its_owner_while_engine_closes(window):
    window.player_factory = SlowPlayer
    first, second = window.core.videos()
    window.play_video(first.id, start=0)
    old = window.player
    old_surface = QWidget.find(old.surface_id)
    # 실제 native 자식에 전달한다. 기본 ignore 전파가 끊기면 이 단언부터 실패한다.
    mouse(window, PRESS, RELEASE, widget=old_surface)
    wait_for(lambda: old.paused)
    mouse(window, PRESS, RELEASE, widget=old_surface)
    try:
        window.player_factory = Player
        window.play_video(second.id, start=0)
        new = window.player
        wait_for(old.started.is_set)
        assert old_surface.isHidden()  # 종료 중인 표면은 새 재생 위에 입력 영역으로 남지 않는다.
        wait_past_click_interval(window)
        assert not old.finished.is_set()
        assert old.paused  # 이전 누름은 닫는 엔진에도 명령을 보내지 않는다.
        assert new.commands == []
        assert not window.isFullScreen()
        mouse(window, PRESS, RELEASE, widget=window._player_surface)
        wait_for(lambda: new.paused)
        assert len(new.commands) == 1
    finally:
        old.release.set()
        window.player_shutdown.finish()


@pytest.mark.parametrize('eof_timing', ['queued', 'closing'])
@pytest.mark.parametrize('destination', ['list', 'new_playback'])
def test_random_eof_cannot_escape_async_shutdown(window, eof_timing, destination):
    class EOFPlayer(SlowPlayer):
        eof = False

        def take_eof(self):
            eof, self.eof = self.eof, False
            return eof

        def prepare_close(self):
            super().prepare_close()
            if eof_timing == 'closing':
                self.positions.append((120, False))
                self.eof = True

        def close(self):
            super().close()
            self.eof = True

    window.end_playback()
    second, first = window.core.videos()
    before = {video.id: len(window.core.viewings(video.id)) for video in (first, second)}
    window.player_factory = EOFPlayer
    window.play(first.id, random_scope=RandomPlayScope())
    old = window.player
    old.positions += [(0, True), (40, False)]
    if eof_timing == 'queued':
        old.eof = True
        window.sync_position()  # EOF 예약 뒤 이벤트 루프 전에 목록으로 돌아간다.
    try:
        window.back_to_list()
        assert window.library_page.selected_video_id() == first.id
        assert window.core.playback.session is None
        assert not window.core.random_continuous_enabled
        wait_for(old.started.is_set)
        assert not old.finished.is_set()
        assert len(window.core.viewings(second.id)) == before[second.id]
        if destination == 'new_playback':
            window.player_factory = Player
            window.play(second.id)
        old.release.set()
        window.player_shutdown.finish()
        window.sync_position()
        if destination == 'new_playback':
            assert window.core.playback.session.video_id == second.id
            assert window.core.playback.position == 0
            assert len(window.core.viewings(second.id)) == before[second.id] + 1
        else:
            assert window.core.playback.session is None
            assert window.pages.currentWidget() is window.web_host
            assert len(window.core.viewings(second.id)) == before[second.id]
        viewing = window.core.viewings(first.id)[-1]
        assert len(window.core.viewings(first.id)) == before[first.id] + 1
        assert viewing.ended_at is not None
        assert viewing.last_position == (40 if eof_timing == 'queued' else 120)
    finally:
        old.release.set()
        window.player_shutdown.finish()


def test_quit_waits_for_closing_engine_while_processing_events(window):
    window.player_factory = SlowPlayer
    window.play_video(window.core.videos()[0].id)
    player = window.player
    window.back_to_list()
    attempted = []
    def during_quit():
        window.play_video(window.core.videos()[1].id)
        attempted.append(window.core.playback.session)
        player.release.set()
    QTimer.singleShot(0, during_quit)
    window.tray.quit()
    assert player.finished.is_set()
    assert not window.isVisible()
    assert attempted == [None]


def test_shutdown_timeout_keeps_resources_until_completion(window):
    window.player_factory = SlowPlayer
    window.play_video(window.core.videos()[0].id)
    player = window.player
    window.back_to_list()
    try:
        with pytest.raises(RuntimeError, match='플레이어 종료를 기다리고'):
            window.player_shutdown.finish(timeout_ms=20)
        assert not player.finished.is_set()
    finally:
        player.release.set()
        window.player_shutdown.finish()


def test_close_failure_is_reported_without_affecting_next_viewing(window):
    class FailingPlayer(Player):
        def prepare_close(self):
            pass

        def close(self):
            raise RuntimeError('close failed')

    first, second = window.core.videos()
    window.player_factory = FailingPlayer
    window.play_video(first.id, start=0)
    window.player.positions += [(0, True), (40, False)]
    window.back_to_list()
    window.player_factory = Player
    window.play_video(second.id, start=0)
    wait_for(lambda: 'close failed' in window.statusBar().currentMessage())
    window.player.positions += [(0, True), (12, False)]
    window.sync_position()
    assert window.core.playback.position == 12
    assert window.core.viewings(first.id)[-1].last_position == 40


def javascript(window, code):
    values = []
    window.web_host.engine_page.runJavaScript(code, values.append)
    wait_for(lambda: bool(values))
    return values[0]


def intercept_return_ready(window, *, reject=False):
    javascript(window, """(() => {
        const transport = window.qt.webChannelTransport;
        const send = transport.send.bind(transport);
        window.returnReadyFrames = [];
        transport.send = text => {
            const message = JSON.parse(text);
            if (message.object === 'shell' && message.method === 'returnReady') {
                window.returnReadyFrames.push({
                    root: getComputedStyle(document.getElementById('root')).visibility,
                    scroll: document.getElementById('library-grid').scrollTop,
                });
                if (REJECT) {
                    transport.onmessage({data: JSON.stringify({type: 10, id: message.id,
                        data: JSON.stringify({error: 'return rejected'})})});
                    return;
                }
            }
            send(text);
        };
    })()""".replace('REJECT', str(reject).lower()))


def test_web_root_is_restored_before_playback_cover_is_removed(window, tmp_path):
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    for index in range(50):
        path = tmp_path / f'return-{index:02}.mkv'
        path.write_bytes(f'return video {index}'.encode())
        window.core.add_file(path)
    window.show_library()
    wait_for(lambda: not host.return_pending)
    wait_for(lambda: javascript(window, "Number(document.getElementById('library-grid').getAttribute('aria-rowcount')) > 20"))
    javascript(window, "document.getElementById('library-grid').scrollTop=1800")
    javascript(window, "document.getElementById('library-grid').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
    wait_for(lambda: window.player is not None)
    # 페이지 변경 알림의 별도 복구가 순서 결함을 가리지 않게 복귀 경로 자체를 검사한다.
    window.pages.currentChanged.disconnect(host.dialogs.sync_container)
    intercept_return_ready(window)
    javascript(window, "window.mvmDialogRootStyle=[document.getElementById('root'), null]; document.getElementById('root').style.visibility='hidden'")
    window.back_to_list()
    assert window.playback_page.isVisible()
    assert not window.playback_page.isEnabled()
    wait_for(lambda: not window.playback_page.isVisible())
    assert json.loads(javascript(window, 'JSON.stringify(window.returnReadyFrames)')) == [
        {'root': 'visible', 'scroll': 1800}]
    assert javascript(window, "getComputedStyle(document.getElementById('root')).visibility") == 'visible'
    assert javascript(window, "document.activeElement.id") == 'library-grid'


def test_rejected_web_return_releases_cover(window):
    wait_for(lambda: window.web_host._frontend_ready and 'library' in window.web_host._ready_pages)
    intercept_return_ready(window, reject=True)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    assert javascript(window, 'window.returnReadyFrames.length') == 1
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()
    assert javascript(window, "document.body.textContent.includes('return rejected')")


def test_python_frame_preparation_failure_releases_cover(window, monkeypatch):
    def fail(*args):
        raise RuntimeError('return preparation failed')
    monkeypatch.setattr(window.web_host.view, 'findChildren', fail)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()
    wait_for(lambda: javascript(window, "document.body.textContent.includes('return preparation failed')"))


def test_python_page_preparation_failure_releases_cover(window, monkeypatch):
    def fail():
        raise RuntimeError('page preparation failed')
    monkeypatch.setattr(window.library_page, 'return_from_playback', fail)
    with pytest.raises(RuntimeError, match='page preparation failed'):
        window.back_to_list()
    assert not window.web_host.return_pending
    assert not window.playback_page.isVisible()


def test_missing_internal_renderer_returns_without_load_error(window, monkeypatch):
    monkeypatch.setattr(window.web_host.view, 'findChildren', lambda *args: [])
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    assert window.web_host.isVisible()
    assert not window.web_host.load_error.isVisible()
    assert not window.playback_page.isVisible()


def test_page_without_bridge_can_finish_return(window, monkeypatch):
    from my_video_manager.web_page import WebPageController
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    page = WebPageController(host)
    page.tab = 'library'
    monkeypatch.setitem(host.controllers, 'library', page)
    monkeypatch.setitem(host.routes, 'library', page)
    host._ready_pages.remove('library')
    window.back_to_list()
    wait_for(lambda: not host.return_pending)
    assert not window.playback_page.isVisible()


def test_late_web_return_ack_does_not_hide_new_playback(window):
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    tokens = []
    host.bridge.shellPrepareReturn.connect(tokens.append)
    window.back_to_list()
    assert tokens
    window.play_video(window.core.videos()[1].id)
    host.bridge.returnReady(tokens[-1])
    assert window.playback_page.isVisible() and window.playback_page.isEnabled()
    assert window.pages.currentWidget() is window.playback_page


def test_web_load_failure_releases_return_cover_and_shows_error(window):
    window.back_to_list()
    assert window.playback_page.isVisible()
    window.web_host.view.loadFinished.emit(False)
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()
    assert window.web_host.load_error.isVisible()


def test_sorted_library_return_never_scrolls_to_top(window, tmp_path):
    for index in range(50):
        path = tmp_path / f'scroll-{index:02}.mkv'
        path.write_bytes(f'scroll video {index}'.encode())
        window.core.add_file(path)
    window.show_library()
    wait_for(lambda: not window.playback_page.isVisible())
    library = window.library_page
    library.set_view({**library.options, 'sort': 'viewed', 'descending': True})
    selected = window.core.videos()[25].id
    library.selected_id = selected
    library.refresh()
    wait_for(lambda: javascript(window, "Number(document.getElementById('library-grid').getAttribute('aria-rowcount')) > 20"))
    javascript(window, "document.getElementById('library-grid').scrollTop=1800")
    javascript(window, "document.getElementById('library-grid').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
    wait_for(lambda: window.core.playback.session is not None)
    javascript(window, "window.scrollFrames=[]; function sample(){window.scrollFrames.push(document.getElementById('library-grid').scrollTop); if(window.scrollFrames.length<8)requestAnimationFrame(sample)} requestAnimationFrame(sample)")
    window.back_to_list()
    wait_for(lambda: not window.playback_page.isVisible())
    wait_for(lambda: javascript(window, 'window.scrollFrames.length >= 8'))
    assert json.loads(javascript(window, 'JSON.stringify(window.scrollFrames)')) == [1800] * 8
    assert library.selected_video_id() == selected
    assert javascript(window, 'document.activeElement.id') == 'library-grid'
