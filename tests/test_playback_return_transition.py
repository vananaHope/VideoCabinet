"""목록 복귀의 위치 보고 경계와 엔진 종료 중 UI 응답을 검사한다."""
from threading import Event
from time import perf_counter
import json
import pytest

from PySide6.QtCore import QTimer, QObject, QEvent, QPoint
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QImage, QColor, QGuiApplication, QBackingStore
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtQuickWidgets import QQuickWidget

from test_playback_page_ui import app, window, Player, mouse, PRESS, RELEASE, wait_past_click_interval
from test_random_continuous_play_ui import review_window
from qt_wait import wait_for
from my_video_manager.core import Command, CommandType
from my_video_manager.random_continuous_play import RandomPlayScope


def patch_method_for(monkeypatch, target, name, replacement):
    """Qt 소유 인스턴스를 undo에서 만지지 않고 대상의 클래스 메서드를 바꾼다."""
    cls = type(target)
    original = getattr(cls, name)
    def method(self, *args, **kwargs):
        if self is target:
            return replacement(*args, **kwargs)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(cls, name, method)


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


@pytest.mark.parametrize('return_during_command', [False, True])
def test_return_does_not_send_status_to_asynchronously_closing_player(window, return_during_command):
    class ReturningPlayer(SlowPlayer):
        def execute(self, command):
            super().execute(command)
            if return_during_command:
                window.back_to_list()

    window.player_factory = ReturningPlayer
    window.play_video(window.core.videos()[0].id, start=0)
    old = window.player
    command = Command(CommandType.TOGGLE_PAUSE)
    try:
        if return_during_command:
            assert window.playback_page.run_command(command)
        else:
            window.back_to_list()
        wait_for(old.started.is_set)
        assert old.prepared and not old.finished.is_set()
        assert window.core.playback.session is None
        assert not window.playback_page.run_command(command)
        assert old.commands == ([command] if return_during_command else [])
        # show_status가 기록만 하는 가짜이므로 잘못된 호출을 어댑터 가드가 가려 주지 않는다.
        assert old.statuses == []
    finally:
        old.release.set()
        window.player_shutdown.finish()


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
    # 열 수는 카드 크기 토큰에 따라 바뀌니 줄 수 대신 1800px까지 내릴 수 있는지를 기다린다.
    wait_for(lambda: javascript(window, "(g => Number(g.getAttribute('aria-rowcount')) > 10 && g.scrollHeight - g.clientHeight > 1800)(document.getElementById('library-grid'))"))
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


def test_return_keeps_playback_current_until_web_frame_is_ready(window, monkeypatch):
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    tokens = []
    patch_method_for(monkeypatch, host, 'finish_return', tokens.append)
    window.back_to_list()
    wait_for(lambda: bool(tokens))
    assert window.pages.currentWidget() is window.playback_page
    assert host.isVisible()
    assert window.playback_page.isVisible()
    assert not window.playback_page.isEnabled()


def return_frame(window, monkeypatch):
    wait_for(lambda: window.web_host._frontend_ready and 'library' in window.web_host._ready_pages)
    renderer = window.web_host.view.findChild(QQuickWidget)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('black'))
    reads = []
    patch_method_for(monkeypatch, renderer, 'grabFramebuffer', lambda: reads.append(True) or image.copy())
    return renderer, image, reads


def test_dialog_return_waits_for_content_and_saves_viewing_once(window, monkeypatch):
    renderer, image, reads = return_frame(window, monkeypatch)
    video = window.core.playback.session.video_id
    dialogs = window.web_host.dialogs
    dialogs.push('highlights', video_id=video)
    dialogs.sync_container()
    wait_for(lambda: dialogs.container is not None)
    window.player.positions += [(0, True), (40, False)]
    dialogs.pop()
    window.back_to_list()
    wait_for(lambda: bool(reads))
    assert window.playback_page.isVisible()
    assert window.pages.currentWidget() is window.playback_page
    assert window.web_host.return_pending
    assert window.core.playback.session is None
    assert window.core.viewings(video)[-1].last_position == 40
    count = len(window.core.viewings(video))
    image.setPixelColor(3, 3, QColor('white'))
    renderer.update()
    wait_for(lambda: not window.web_host.return_pending)
    assert window.pages.currentWidget() is window.web_host
    assert not window.playback_page.isVisible()
    assert len(window.core.viewings(video)) == count


def test_empty_frame_timeout_still_finishes_return(window, monkeypatch):
    _, _, reads = return_frame(window, monkeypatch)
    window.back_to_list()
    wait_for(lambda: bool(reads))
    assert window.playback_page.isVisible()
    wait_for(lambda: not window.web_host.return_pending)
    assert window.pages.currentWidget() is window.web_host
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()


def test_new_playback_cancels_wait_for_frame_content(window, monkeypatch):
    renderer, image, reads = return_frame(window, monkeypatch)
    first, second = window.core.videos()
    window.back_to_list()
    wait_for(lambda: bool(reads))
    window.play_video(second.id)
    image.setPixelColor(3, 3, QColor('white'))
    renderer.update()
    javascript(window, 'true')  # 예약된 paint 콜백을 처리한 뒤에도 새 재생을 유지한다.
    assert window.core.playback.session.video_id == second.id
    assert window.pages.currentWidget() is window.playback_page
    assert window.playback_page.isVisible() and window.playback_page.isEnabled()
    assert not window.web_host.return_pending


def test_new_playback_during_return_remembers_selected_tab(window, monkeypatch):
    host = window.web_host
    wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
    replies = []
    with monkeypatch.context() as pending:
        patch_method_for(pending, host, 'finish_return', replies.append)
        window.back_to_list()
        wait_for(lambda: bool(replies))
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
        assert host.active_tab == 'search' and host.return_pending
        window.play_video(window.core.videos()[1].id)
        assert window.core.playback.session is not None
    window.back_to_list()
    wait_for(lambda: not host.return_pending)
    assert host.active_tab == 'search'


def test_review_playback_during_return_remembers_selected_tab(review_window, monkeypatch):
    window, core = review_window, review_window.core
    wait_for(lambda: window.loaded)
    video_id = core.videos()[0].id
    core.request_subtitles(video_id)
    assert core.process_next_subtitle().state == 'completed'
    line = core.transcript(video_id).lines[1]
    window.play_video(video_id)
    host, replies = window.web_host, []
    with monkeypatch.context() as pending:
        patch_method_for(pending, host, 'finish_return', replies.append)
        window.back_to_list()
        wait_for(lambda: bool(replies))
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
        assert host.active_tab == 'search' and host.return_pending
        window.review_jump(video_id, line.id)
        assert core.playback.session.video_id == video_id
    window.back_to_list()
    wait_for(lambda: not host.return_pending)
    assert host.active_tab == 'search'


def visible_return_covers():
    return [item for item in QGuiApplication.allWindows()
            if item.objectName() == 'playback-return-cover' and item.isVisible()]


@pytest.mark.parametrize('phase', ['reply', 'frame', 'cover'])
@pytest.mark.parametrize('key', ['fullscreen', 'help', 'highlights', 'settings', 'escape'])
def test_pending_return_keys_target_web_page(window, monkeypatch, phase, key):
    host, page = window.web_host, window.playback_page
    arrived = []
    if phase == 'frame':
        renderer, image, arrived = return_frame(window, monkeypatch)
    elif phase == 'cover':
        from my_video_manager.web_return_cover import WebReturnCover
        prepare_raster_return(window, monkeypatch)
        monkeypatch.setattr(WebReturnCover, 'commit', lambda self: arrived.append(True))
    else:
        wait_for(lambda: host._frontend_ready and 'library' in host._ready_pages)
        patch_method_for(monkeypatch, host, 'finish_return', arrived.append)
    window.back_to_list()
    wait_for(lambda: bool(arrived))
    shell_help, playback_settings = [], []
    patch_method_for(monkeypatch, host, 'open_key_guide', lambda: shell_help.append(True))
    patch_method_for(monkeypatch, host, 'popup_settings_menu', lambda: playback_settings.append(True))
    panel_expanded = page.highlights_expanded
    keys = {'fullscreen': Qt.Key.Key_Apostrophe, 'help': Qt.Key.Key_F1,
            'highlights': Qt.Key.Key_Semicolon, 'settings': Qt.Key.Key_S,
            'escape': Qt.Key.Key_Escape}
    modifier = Qt.KeyboardModifier.AltModifier if key == 'settings' else Qt.KeyboardModifier.NoModifier
    QTest.keyClick(window.focusWidget() or window, keys[key], modifier)
    assert not window.isFullScreen()
    assert not page._help_requested
    assert page.highlights_expanded == panel_expanded
    assert not playback_settings
    assert shell_help == ([True] if key == 'help' else [])
    if key == 'settings':
        assert host.active_tab == 'settings'
    if phase == 'frame':
        image.setPixelColor(3, 3, QColor('white'))
        renderer.update()
    elif phase == 'reply':
        monkeypatch.undo()
        host.finish_return(host._return_token)
    wait_for(lambda: not host.return_pending)
    assert window.pages.currentWidget() is host


@pytest.mark.parametrize('phase', ['frame', 'cover'])
def test_reload_during_return_releases_helpers_and_restarts_preparation(window, monkeypatch, phase):
    host = window.web_host
    if phase == 'frame':
        renderer, image, arrived = return_frame(window, monkeypatch)
    else:
        from my_video_manager.web_return_cover import WebReturnCover
        prepare_raster_return(window, monkeypatch)
        arrived = []
        original_commit = WebReturnCover.commit
        monkeypatch.setattr(WebReturnCover, 'commit', lambda self: arrived.append(True))
    window.back_to_list()
    wait_for(lambda: bool(arrived))
    if phase == 'frame':
        image.setPixelColor(3, 3, QColor('white'))
    else:
        monkeypatch.setattr(WebReturnCover, 'commit', original_commit)
    started = perf_counter()
    host.view.reload()
    try:
        wait_for(lambda: not host.return_pending, timeout=2.5)
    except AssertionError:
        # 실패 재현 때도 fixture 종료가 삭제된 helper를 다시 만지지 않게 한다.
        host._return_frame = None
        host._return_cover = None
        host.cancel_return()
        raise
    assert perf_counter() - started < 2.5
    assert window.pages.currentWidget() is host
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()
    assert not visible_return_covers()
    window.play_video(window.core.videos()[1].id)
    assert window.core.playback.session is not None
    window.tray.quit()
    assert not window.isVisible()


def prepare_raster_return(window, monkeypatch):
    from types import SimpleNamespace
    from my_video_manager import web_shell
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('black'))
    image.setPixelColor(3, 3, QColor('white'))
    wait_for(lambda: window.web_host._frontend_ready and 'library' in window.web_host._ready_pages)
    monkeypatch.setattr(web_shell, 'QApplication', SimpleNamespace(platformName=lambda: 'windows'))
    finish = window.web_host.finish_return
    def ready(token):
        if window.web_host._return_cover is not None:
            finish(token)
        else:
            window.web_host.present_return(token, image)
    patch_method_for(monkeypatch, window.web_host, 'finish_return', ready)


def test_return_raster_mouse_click_reaches_visible_web_tab(window, monkeypatch):
    from my_video_manager.web_return_cover import WebReturnCover
    prepare_raster_return(window, monkeypatch)
    original_commit = WebReturnCover.commit
    exposed = []
    monkeypatch.setattr(WebReturnCover, 'commit', lambda self: exposed.append(True))
    window.back_to_list()
    wait_for(lambda: bool(exposed))
    position = json.loads(javascript(window, """JSON.stringify((()=>{
        const r=document.querySelector('nav [data-tab="settings"]').getBoundingClientRect();
        return [r.x+r.width/2,r.y+r.height/2]})())"""))
    monkeypatch.setattr(WebReturnCover, 'commit', original_commit)
    QTest.mouseClick(window.web_host.view.focusProxy(), Qt.MouseButton.LeftButton,
                     pos=QPoint(round(position[0]), round(position[1])))
    wait_for(lambda: window.web_host.active_tab == 'settings')
    wait_for(lambda: not window.web_host.return_pending)
    assert window.pages.currentWidget() is window.web_host
    assert not visible_return_covers()
    assert window.core.playback.session is None


@pytest.mark.parametrize('reply', [True, False])
def test_raster_waits_for_new_web_frame_after_switch(window, monkeypatch, reply):
    prepare_raster_return(window, monkeypatch)
    host = window.web_host
    finish = host.finish_return
    tokens, delayed = [], []
    host.bridge.shellPrepareReturn.connect(tokens.append)
    def hold_present(token):
        if host._return_cover is not None and host._return_cover.submitted:
            delayed.append(token)
        else:
            finish(token)
    patch_method_for(monkeypatch, host, 'finish_return', hold_present)
    window.back_to_list()
    wait_for(lambda: bool(delayed))
    assert tokens[-1] != tokens[0]
    assert window.pages.currentWidget() is host
    assert visible_return_covers()
    finish(tokens[0])
    javascript(window, 'true')
    assert host.return_pending and visible_return_covers()
    if reply:
        finish(delayed[-1])
    wait_for(lambda: not host.return_pending)
    assert not visible_return_covers()
    assert not window.playback_page.isVisible()


def test_frame_cancel_is_safe_after_deferred_delete(window, monkeypatch, app):
    _, _, reads = return_frame(window, monkeypatch)
    window.back_to_list()
    wait_for(lambda: bool(reads))
    frame = window.web_host._return_frame
    window.web_host.cancel_return()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    frame.cancel()
    assert not window.web_host.return_pending


@pytest.mark.parametrize('action', ['play', 'quit', 'resize', 'maximize', 'key', 'timeout'])
def test_return_raster_cover_cannot_outlive_user_action(window, monkeypatch, action):
    from my_video_manager.web_return_cover import WebReturnCover
    prepare_raster_return(window, monkeypatch)
    exposed = []
    # 실제 native raster 표면은 그리되, 웹 교체 응답을 붙잡아 수명 경합을 만든다.
    monkeypatch.setattr(WebReturnCover, 'commit', lambda self: exposed.append(True))
    window.back_to_list()
    wait_for(lambda: bool(exposed))
    assert visible_return_covers()
    if action == 'play':
        video = window.core.videos()[1]
        window.play_video(video.id)
        assert window.core.playback.session.video_id == video.id
        assert window.pages.currentWidget() is window.playback_page
    elif action == 'quit':
        window.tray.quit()
        assert not window.isVisible()
    elif action == 'resize':
        window.resize(1180, 760)
    elif action == 'maximize':
        window.showMaximized()
    elif action == 'key':
        QTest.keyClick(window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
        assert window.web_host.active_tab == 'search'
    wait_for(lambda: not window.web_host.return_pending)
    assert not visible_return_covers()
    assert window.playback_page.isEnabled()
    if action in ('resize', 'maximize', 'key', 'timeout'):
        assert window.pages.currentWidget() is window.web_host


def test_missing_web_return_reply_has_bounded_fallback(window, monkeypatch):
    tokens = []
    patch_method_for(monkeypatch, window.web_host, 'finish_return', tokens.append)
    window.back_to_list()
    wait_for(lambda: bool(tokens))
    assert window.playback_page.isVisible()
    wait_for(lambda: not window.web_host.return_pending)
    assert window.pages.currentWidget() is window.web_host
    assert not window.playback_page.isVisible()


def test_return_raster_is_flushed_before_playback_surface_is_removed(window, monkeypatch):
    from my_video_manager import web_return_cover
    prepare_raster_return(window, monkeypatch)
    events = []
    class RecordingStore(QBackingStore):
        def flush(self, *args):
            events.append('raster-flush')
            return super().flush(*args)
    monkeypatch.setattr(web_return_cover, 'QBackingStore', RecordingStore)
    window.pages.currentChanged.connect(lambda _: events.append('page-changed'))
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    assert events.index('raster-flush') < events.index('page-changed')
    assert not visible_return_covers()
    assert not window.playback_page.isVisible()


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
    patch_method_for(monkeypatch, window.web_host.view, 'findChildren', fail)
    window.back_to_list()
    wait_for(lambda: not window.web_host.return_pending)
    assert not window.playback_page.isVisible()
    assert window.playback_page.isEnabled()
    wait_for(lambda: javascript(window, "document.body.textContent.includes('return preparation failed')"))


def test_python_page_preparation_failure_releases_cover(window, monkeypatch):
    def fail():
        raise RuntimeError('page preparation failed')
    patch_method_for(monkeypatch, window.library_page, 'return_from_playback', fail)
    with pytest.raises(RuntimeError, match='page preparation failed'):
        window.back_to_list()
    assert not window.web_host.return_pending
    assert not window.playback_page.isVisible()


def test_missing_internal_renderer_returns_without_load_error(window, monkeypatch):
    patch_method_for(monkeypatch, window.web_host.view, 'findChildren', lambda *args: [])
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
    # 열 수는 카드 크기 토큰에 따라 바뀌니 줄 수 대신 1800px까지 내릴 수 있는지를 기다린다.
    wait_for(lambda: javascript(window, "(g => Number(g.getAttribute('aria-rowcount')) > 10 && g.scrollHeight - g.clientHeight > 1800)(document.getElementById('library-grid'))"))
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
