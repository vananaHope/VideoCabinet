"""키 배치 목록, 충돌 검사와 변경분 저장. Qt에 의존하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from .settings import Settings

if TYPE_CHECKING:
    from .core import Command


_NAMED_KEYS = ("Enter", "Space", "Tab", "Backspace", "Left", "Right", "Up", "Down",
               "Insert", "Delete", "Home", "End", "PgUp", "PgDn", "Pause", "Print",
               *(f"F{i}" for i in range(1, 36)))
_ALIASES = {key.casefold(): key for key in _NAMED_KEYS}
_ALIASES.update(pageup="PgUp", pagedown="PgDn", pgdown="PgDn", esc="Esc", escape="Esc")
_ALIASES["return"] = "Enter"
RESERVED_KEYS = {"Alt+S": "설정 메뉴를 여는 예약 키"}


def normalize_key(key: str) -> str:
    """입력 어댑터와 저장소가 공유하는 단일 키 이름. Esc는 취소 전용이다."""
    if not isinstance(key, str) or not key:
        raise ValueError("키를 입력하세요.")
    modifiers = set()
    while "+" in key:
        prefix, rest = key.split("+", 1)
        modifier = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "meta": "Meta"}.get(prefix.casefold())
        if modifier is None:
            break
        modifiers.add(modifier)
        key = rest
    key = _ALIASES.get(key.casefold(), key)
    if key == "Esc":
        raise ValueError("Esc는 취소와 목록 복귀에 사용하므로 할당할 수 없습니다.")
    if key == " ":
        key = "Space"
    if len(key) == 1 and key.isascii() and key.isprintable():
        key = key.upper()
    elif key not in _NAMED_KEYS:
        raise ValueError("지원하지 않는 키입니다. 문자, 숫자, 방향키 또는 기능키를 눌러 주세요.")
    normalized = "".join(f"{m}+" for m in ("Ctrl", "Alt", "Shift", "Meta") if m in modifiers) + key
    if normalized in RESERVED_KEYS:
        raise ValueError(f"{normalized}는 {RESERVED_KEYS[normalized]}이므로 할당할 수 없습니다.")
    return normalized


def command_label(command: Command) -> str:
    kind = command.kind.value
    if kind == "seek":
        return f"{abs(command.amount):g}초 {'앞으로' if command.amount > 0 else '뒤로'}"
    if kind == "change_speed":
        return f"재생 속도 {abs(command.amount):g} {'올리기' if command.amount > 0 else '내리기'}"
    return {
        "toggle_pause": "재생 / 일시정지", "point_highlight": "지점 하이라이트 만들기",
        "range_highlight": "구간 하이라이트 시작 / 끝", "previous_highlight": "이전 하이라이트",
        "next_highlight": "다음 하이라이트", "toggle_subtitles": "자막 켜기 / 끄기",
        "previous_video": "이전 영상 / 시리즈 이전 화", "next_video": "다음 영상 / 시리즈 다음 화",
        "toggle_subtitle_language": "원어 / 번역 자막 전환",
    }.get(kind, kind)


@dataclass(frozen=True)
class KeyBinding:
    command: Command
    label: str
    keys: tuple[str, ...]
    default_keys: tuple[str, ...]


class KeyBindings:
    def __init__(self, settings: Settings, defaults: Mapping[str, Command], commands: tuple[Command, ...]):
        self.settings = settings
        self.defaults = {command: tuple(key for key, value in defaults.items() if value == command)
                         for command in dict.fromkeys(defaults.values())}
        for command in commands:
            if not any(existing.kind == command.kind for existing in self.defaults):
                self.defaults[command] = ()
        self.bindings = dict(self.defaults)
        stored = settings.get("keys.bindings", {})
        if isinstance(stored, dict):
            # 새 명령의 기본 키보다 기존 사용자 설정을 우선한다.
            # 겹치는 새 기본 키는 미할당으로 표시하고 다른 사용자 설정은 유지한다.
            customized = {}
            for command in self.defaults:
                keys = stored.get(self.identifier(command))
                if not isinstance(keys, list):
                    continue
                try:
                    normalized = tuple(dict.fromkeys(normalize_key(key) for key in keys))
                except ValueError:
                    continue
                customized[command] = normalized
            # 서로 다른 사용자 명령의 중복 키는 어느 쪽도 임의로 우선하지 않는다.
            owners = {}
            for command, keys in customized.items():
                for key in keys:
                    owners.setdefault(key, set()).add(command)
            conflicting = {command for commands in owners.values() if len(commands) > 1 for command in commands}
            customized = {command: keys for command, keys in customized.items() if command not in conflicting}
            claimed = {key for keys in customized.values() for key in keys}
            self.bindings = {command: customized.get(command, tuple(key for key in keys if key not in claimed))
                             for command, keys in self.defaults.items()}

    @staticmethod
    def identifier(command: Command) -> str:
        return f"{command.kind.value}:{command.amount:g}"

    def rows(self) -> tuple[KeyBinding, ...]:
        return tuple(KeyBinding(c, command_label(c), self.bindings[c], keys)
                     for c, keys in self.defaults.items())

    def validate(self, bindings: Mapping[Command, tuple[str, ...]]) -> dict[Command, tuple[str, ...]]:
        if set(bindings) != set(self.defaults):
            raise ValueError("전체 명령의 키 배치가 필요합니다. 설정 화면을 다시 열어 주세요.")
        result = {}
        owners = {}
        for command, keys in bindings.items():
            if not isinstance(keys, (list, tuple)):
                raise ValueError("명령의 키는 목록이어야 합니다.")
            normalized = tuple(dict.fromkeys(normalize_key(key) for key in keys))
            for key in normalized:
                if key in owners and owners[key] != command:
                    raise ValueError(f"{key}: ‘{command_label(owners[key])}’와 ‘{command_label(command)}’가 같은 키를 사용합니다.")
                owners[key] = command
            result[command] = normalized
        return result

    def save(self, bindings: Mapping[Command, tuple[str, ...]]) -> None:
        validated = self.validate(bindings)
        overrides = {self.identifier(command): list(keys) for command, keys in validated.items()
                     if keys != self.defaults[command]}
        self.settings.set("keys.bindings", overrides)
        self.bindings = validated

    def replace(self, bindings: Mapping[str, Command], *, persist: bool = True) -> None:
        proposed = {command: [] for command in self.defaults}
        for key, command in bindings.items():
            if command not in proposed:
                raise ValueError("설정 대상에 없는 명령입니다.")
            proposed[command].append(key)
        if persist:
            self.save(proposed)
        else:
            self.bindings = self.validate(proposed)

    def command_for_key(self, key: str) -> Command | None:
        try:
            key = normalize_key(key)
        except ValueError:
            return None
        return next((command for command, keys in self.bindings.items() if key in keys), None)

    def reset(self, command: Command | None = None) -> None:
        proposed = dict(self.bindings)
        if command is None:
            proposed = dict(self.defaults)
        elif command in self.defaults:
            proposed[command] = self.defaults[command]
        else:
            raise ValueError("설정 대상에 없는 명령입니다.")
        self.save(proposed)
