"""Qt 없는 웹 경계. TypedDict가 frontend/src/bridge-types.ts의 원본이다."""

from dataclasses import asdict
from typing import TypedDict
from urllib.parse import urlsplit


class TagData(TypedDict):
    id: int
    name: str


class ShellData(TypedDict):
    tab: str
    status: str


class VideoData(TypedDict):
    id: int
    title: str
    duration: float
    thumbnail: str | None
    missing: bool
    locationCount: int
    finished: bool
    abandoned: bool
    favorite: bool
    resumePoint: float | None
    stoppedPercent: float | None
    tags: list[TagData]
    series: str


class GemData(TypedDict):
    videoId: int
    reason: str


class DetailsData(TypedDict):
    has_transcript: bool
    spoken_language: str | None
    original_lines: int
    translated_lines: int
    subtitle_state: str | None
    translation_state: str | None
    highlight_count: int


class LibraryData(TypedDict):
    videos: list[VideoData]
    tags: list[TagData]
    gems: list[GemData]
    gemError: str
    visibleIds: list[int]
    selectedId: int | None
    scanning: bool


def snapshot_data(snapshot) -> list[VideoData]:
    series = {vid: f"{s.name} · {i + 1}/{len(s.video_ids)}"
              for s in snapshot.series for i, vid in enumerate(s.video_ids)}
    result = []
    for video in snapshot.videos:
        status = snapshot.statuses[video.id]
        result.append(VideoData(
            id=video.id, title=video.title, duration=video.duration,
            # 숫자 host는 Chromium이 IP로 정규화하므로 고정 host 아래에 ID를 둔다.
            thumbnail=f"mvm-thumb://video/{video.id}" if video.thumbnail else None,
            missing=video.missing, locationCount=len(video.locations),
            finished=status.finished, abandoned=status.abandoned, favorite=status.favorite,
            resumePoint=status.resume_point, stoppedPercent=status.stopped_percent,
            tags=[TagData(id=t.id, name=t.name) for t in snapshot.tags.get(video.id, ())],
            series=series.get(video.id, ""),
        ))
    return result


def filter_ids(videos: list[VideoData], query: str, tag_id: int | None) -> list[int]:
    query = query.strip().casefold()
    return [v['id'] for v in videos if query in v['title'].casefold()
            and (tag_id is None or any(t['id'] == tag_id for t in v['tags']))]


def details_data(details) -> DetailsData:
    return DetailsData(**asdict(details))


def thumbnail_video_id(url: str) -> int | None:
    """ID만 받는다. URL 경로·포트·인증·쿼리·인코딩으로 파일을 지정할 수 없다."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    identifier = parsed.path.removeprefix('/')
    if (parsed.scheme != 'mvm-thumb' or parsed.netloc != 'video'
            or len(identifier) > 10 or not identifier.isascii() or not identifier.isdecimal()
            or parsed.query or parsed.fragment):
        return None
    video_id = int(identifier)
    return video_id if 0 < video_id < 2**31 else None
