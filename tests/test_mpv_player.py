"""MpvPlayer 어댑터의 공개 동작. libmpv 대신 해제된 핸들을 흉내 내는 가짜 mpv 모듈을 쓴다."""

import sys
from types import SimpleNamespace

import pytest

from my_video_manager.adapters import MpvPlayer


class FakeMpv:
    created = []

    def __init__(self, **options):
        self.created.append(self)
        self.options = options
        self.commands = []
        self.terminated = False

    def event_callback(self, *names):
        return lambda callback: callback

    def property_observer(self, name):
        return lambda callback: callback

    def command(self, *arguments):
        if self.terminated:
            # 실제 python-mpv는 terminate 뒤 해제된 핸들을 넘겨 access violation이 난다.
            raise OSError("exception: access violation")
        self.commands.append(arguments)

    def terminate(self):
        self.terminated = True


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setitem(sys.modules, "mpv", SimpleNamespace(MPV=FakeMpv))
    monkeypatch.setattr(FakeMpv, "created", [])
    return MpvPlayer(1)


def engine():
    [created] = FakeMpv.created
    return created


def test_status_uses_korean_osd_font_and_milliseconds(player):
    player.show_status("⏸ 일시정지", 1.5)
    assert engine().options["osd_font"] == "Malgun Gothic"
    assert engine().commands == [("show-text", "⏸ 일시정지", 1500)]


def test_status_after_close_is_skipped(player):
    player.show_status("1.25×", 1.5)
    player.close()
    player.show_status("자막 꺼짐", 1.5)
    assert engine().commands == [("show-text", "1.25×", 1500)]


def test_status_after_prepare_close_is_skipped_before_native_termination(player):
    player.show_status("1.25×", 1.5)
    player.prepare_close()
    assert not engine().terminated
    player.show_status("자막 꺼짐", 1.5)
    assert engine().commands == [("show-text", "1.25×", 1500)]
    player.close()
    assert engine().terminated
