"""앱 설정 공용 계약 (#3·#8 공용, 이후 #15 등도 사용).

관리자가 정한 파일이다. 내용을 바꾸지 말고 그대로 `src/my_video_manager/settings.py`로 복사한다.
바꿔야 할 이유가 생기면 관리자에게 ask로 묻는다.

사용법:
- AppCore는 `self.settings = Settings(self._connect)`처럼 DB 연결 함수를 넘겨 만든다.
- 각 기능은 자기 설정 키를 `"기능.이름"` 형식으로 정하고 기본값을 코드에 둔다.
  예: `settings.get("library.min_duration_seconds", 60.0)`, `settings.get("translation.cli", "codex")`.
- 값은 JSON으로 저장되므로 str/int/float/bool/list/dict만 쓴다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


class Settings:
    def __init__(self, connect: Callable[[], AbstractContextManager[Any]]) -> None:
        self._connect = connect
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            # 깨진 저장값은 기본값으로 대신하고, 다음 set에서 덮어쓴다.
            return default

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        with self._connect() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )

    def reset(self, key: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM settings WHERE key = ?", (key,))
