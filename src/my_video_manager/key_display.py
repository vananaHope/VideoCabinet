"""저장용 키 이름을 사용자에게 보여 주는 이름으로 바꾸는 순수 함수."""

from collections.abc import Iterable


def display_key(key: str) -> str:
    names = {"Left": "←", "Right": "→", "Up": "↑", "Down": "↓",
             "PgUp": "Page Up", "PgDn": "Page Down", "Space": "Space", "Meta": "Win"}
    return "+".join(names.get(part, part) for part in key.split("+"))


def display_keys(keys: Iterable[str]) -> str:
    return " / ".join(display_key(key) for key in keys) or "키 미할당"
