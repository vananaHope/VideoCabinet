"""추천 페이지의 Qt 없는 공개 JSON. TypedDict가 frontend/src/bridge-types.ts의 원본이다."""

from dataclasses import replace
from typing import TypedDict

from .web_library_data import VideoData, snapshot_data


class RecommendationItemData(TypedDict):
    video: VideoData
    reason: str


class RecommendationRowData(TypedDict):
    key: str
    kind: str
    title: str
    items: list[RecommendationItemData]


class RecommendData(TypedDict):
    loaded: bool
    rows: list[RecommendationRowData]
    error: str


def rows_data(rows, snapshot, subtitled_ids=frozenset()) -> list[RecommendationRowData]:
    shown = {item.video.id for row in rows for item in row.items}
    # 카드는 추천에 나온 영상만 만든다. 라이브러리 전체를 직렬화하지 않는다.
    shown_snapshot = replace(snapshot, videos=tuple(video for video in snapshot.videos if video.id in shown))
    videos = {card['id']: card for card in snapshot_data(shown_snapshot, subtitled_ids)}
    return [RecommendationRowData(key=row.key, kind=row.kind, title=row.title, items=[
        RecommendationItemData(video=videos[item.video.id], reason=item.reason) for item in row.items])
        for row in rows]
