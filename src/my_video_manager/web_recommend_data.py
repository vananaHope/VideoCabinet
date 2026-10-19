"""추천 페이지의 Qt 없는 공개 JSON. TypedDict가 frontend/src/bridge-types.ts의 원본이다."""

from typing import TypedDict

from .web_library_data import VideoData, snapshot_data


class RecommendationItemData(TypedDict):
    video: VideoData
    reason: str


class RecommendationRowData(TypedDict):
    kind: str
    title: str
    items: list[RecommendationItemData]


class RecommendData(TypedDict):
    loaded: bool
    rows: list[RecommendationRowData]
    error: str


def rows_data(rows, snapshot, subtitled_ids=frozenset()) -> list[RecommendationRowData]:
    shown = {item.video.id for row in rows for item in row.items}
    videos = {card['id']: card for card in snapshot_data(snapshot, subtitled_ids) if card['id'] in shown}
    return [RecommendationRowData(kind=row.kind, title=row.title, items=[
        RecommendationItemData(video=videos[item.video.id], reason=item.reason) for item in row.items])
        for row in rows]
