"""웹 공개 계약의 공통 선언. 페이지 계약 파일은 이 모듈만 import해 순환을 만들지 않는다."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypedDict


class GenerationData(TypedDict):
    """페이지 상태 메시지(밀어 보내는 changed·요청 응답)의 공용 세대(#265).

    페이지마다 단조 증가한다. 프런트는 마지막으로 반영한 세대보다 오래된 메시지를 버리므로
    늦게 도착한 이전 응답이 현재 화면을 덮지 않는다.
    """
    generation: int


@dataclass(frozen=True)
class Argument:
    name: str
    python_type: type
    typescript_type: str


@dataclass(frozen=True)
class TypeAlias:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Constant:
    name: str
    values: tuple | str
    typescript_type: str | None = None


@dataclass(frozen=True)
class BridgeContract:
    """페이지 하나의 불변 공개 표면. 이름·순서로 페이지의 역할을 추론하지 않는다."""
    name: str
    interface: str
    slots: Mapping[str, tuple[Argument, ...]] = field(default_factory=dict)
    signals: Mapping[str, type] = field(default_factory=dict)
    aliases: tuple[TypeAlias, ...] = ()
    constants: tuple[Constant, ...] = ()
    data_types: tuple[type, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'slots', MappingProxyType(dict(self.slots)))
        object.__setattr__(self, 'signals', MappingProxyType(dict(self.signals)))

    def slot(self, name):
        from PySide6.QtCore import Slot
        return Slot(*(arg.python_type for arg in self.slots[name]), result=str)

    def signal(self, name):
        from PySide6.QtCore import Signal
        return Signal(self.signals[name])
