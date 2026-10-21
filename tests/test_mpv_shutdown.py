"""mpv 공개 어댑터가 종료 경계 뒤의 이벤트를 버리는지 확인한다."""
import sys
from types import SimpleNamespace

from my_video_manager.adapters import MpvPlayer


class NativePlayer:
    def __init__(self):
        self.observers = {}
        self.events = {}
        self.time_pos = 0
        self.duration = 120
        self.pause = False
        self.terminated = False

    def property_observer(self, name):
        def register(callback):
            self.observers[name] = callback
            return callback
        return register

    def event_callback(self, *names):
        def register(callback):
            for name in names:
                self.events[name] = callback
            return callback
        return register

    def terminate(self):
        self.observers['time-pos']('time-pos', 119)
        self.observers['eof-reached']('eof-reached', True)
        self.terminated = True


def test_prepare_close_freezes_positions_before_native_shutdown(monkeypatch):
    native = NativePlayer()
    monkeypatch.setitem(sys.modules, 'mpv', SimpleNamespace(MPV=lambda **kwargs: native))
    player = MpvPlayer(1)
    native.events['playback-restart'](None)
    native.observers['time-pos']('time-pos', 40)
    player.prepare_close()
    assert native.pause and not native.terminated
    assert player.take_positions() == ((0, True), (40, False))
    native.observers['time-pos']('time-pos', 90)
    player.close()
    assert native.terminated
    assert player.take_positions() == ()
    assert not player.take_eof()
