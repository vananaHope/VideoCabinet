"""셸이 소유하는 웹 경계 데이터."""

from typing import TypedDict


class ShellData(TypedDict):
    tab: str
    status: str


class ShellEntryData(TypedDict):
    """웹이 처음 그리기 전에 받는 시작 상태(#267). 페이지가 내는 진입 데이터는 pages 아래 탭 이름으로 따로 담는다."""
    tab: str


class KeyGuideEntryData(TypedDict):
    keys: list[str]
    label: str
    detail: str


class KeyGuideData(TypedDict):
    app: list[KeyGuideEntryData]
