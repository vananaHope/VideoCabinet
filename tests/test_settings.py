"""공용 설정 공개 API: 저장 매체 손상은 원시 JSON 주입으로 재현한다."""

from contextlib import contextmanager
import sqlite3

import pytest

from my_video_manager.settings import Settings


@pytest.mark.parametrize("damaged", ["{", "not-json", '{"value":', ""])
def test_corrupt_json_returns_each_default_until_next_set(tmp_path, damaged):
    @contextmanager
    def connect():
        db = sqlite3.connect(tmp_path / "settings.sqlite3")
        try:
            with db:
                yield db
        finally:
            db.close()

    settings = Settings(connect)
    # set()은 올바른 JSON만 쓰므로 손상된 저장 매체만 직접 재현한다.
    with connect() as db:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("keys.bindings", damaged))
    assert settings.get("keys.bindings", {"first": 1}) == {"first": 1}
    assert settings.get("keys.bindings", {"second": 2}) == {"second": 2}
    with connect() as db:
        assert db.execute("SELECT value FROM settings WHERE key = ?", ("keys.bindings",)).fetchone()[0] == damaged
    settings.set("keys.bindings", {"toggle_pause:0": ["Space"]})
    assert Settings(connect).get("keys.bindings") == {"toggle_pause:0": ["Space"]}
