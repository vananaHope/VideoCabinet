"""AppCore 공개 설정 API: 저장 매체 손상만 원시 JSON 주입으로 재현한다."""

import sqlite3

import pytest

from my_video_manager.core import Command, CommandType
from test_key_bindings import open_core, draft


@pytest.mark.parametrize("damaged", ["{", "not-json", '{"value":', ""])
def test_corrupt_json_returns_each_default_until_next_set(tmp_path, damaged):
    core = open_core(tmp_path)
    # 공개 API는 올바른 JSON만 쓰므로 저장 매체 손상만 SQL로 주입한다.
    with sqlite3.connect(core.database) as db:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("keys.bindings", damaged))
    db.close()
    assert core.settings.get("keys.bindings", {"first": 1}) == {"first": 1}
    assert core.settings.get("keys.bindings", {"second": 2}) == {"second": 2}
    reopened = open_core(tmp_path)
    assert reopened.settings.get("keys.bindings", {"reopened": 3}) == {"reopened": 3}
    pause = Command(CommandType.TOGGLE_PAUSE)
    assert reopened.command_for_key("Enter") == pause
    bindings = draft(reopened)
    bindings[pause] = ("Space",)
    reopened.save_key_bindings(bindings)
    saved = open_core(tmp_path)
    assert saved.command_for_key("Space") == pause
    assert saved.command_for_key("Enter") is None
