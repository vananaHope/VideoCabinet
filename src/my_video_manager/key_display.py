"""저장용 키 이름을 사용자에게 보여 주는 이름으로 바꾸는 순수 함수."""

from collections.abc import Iterable

# 한 글자 기호는 화면에서 알아보기 어려워 이름을 함께 보여 준다.
_SYMBOL_NAMES = {"'": "작은따옴표", ",": "쉼표", ".": "마침표", "/": "빗금", ";": "쌍반점",
                 # 맑은 고딕과 한국어 키보드는 역빗금을 ₩로 보여 준다.
                 "\\": "원화 기호", "₩": "원화 기호", "[": "여는 대괄호", "]": "닫는 대괄호",
                 "-": "빼기", "=": "등호", "`": "억음 부호"}


def display_key(key: str) -> str:
    names = {"Left": "←", "Right": "→", "Up": "↑", "Down": "↓",
             "PgUp": "Page Up", "PgDn": "Page Down", "Space": "Space", "Meta": "Win"}
    text = "+".join(names.get(part, part) for part in key.split("+"))
    last = key.rsplit("+", 1)[-1]
    return f"{text} ({_SYMBOL_NAMES[last]})" if last in _SYMBOL_NAMES else text


def display_keys(keys: Iterable[str]) -> str:
    return " / ".join(display_key(key) for key in keys) or "키 미할당"
