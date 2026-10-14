"""셸이 소유하는 웹 경계 데이터."""

from typing import TypedDict


class ShellData(TypedDict):
    tab: str
    status: str
