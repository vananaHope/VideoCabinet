"""폴더 관리 화면의 공개 JSON 데이터."""
from typing import TypedDict


class RestorableVideoData(TypedDict):
    id: int
    title: str
    missing: bool
    excluded: bool


class FoldersData(TypedDict):
    folders: list[str]
    excluded: list[RestorableVideoData]
    dismissed: list[RestorableVideoData]
    minimum: float
    scanning: bool
    report: str
    automaticDetection: bool
    unwatched: list[str]
    watchStartFailed: bool
