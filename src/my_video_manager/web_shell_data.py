"""셸이 소유하는 웹 경계 데이터."""

from typing import TypedDict


class ShellData(TypedDict):
    tab: str
    status: str


class KeyGuideEntryData(TypedDict):
    keys: list[str]
    label: str
    detail: str


class KeyGuideData(TypedDict):
    app: list[KeyGuideEntryData]
