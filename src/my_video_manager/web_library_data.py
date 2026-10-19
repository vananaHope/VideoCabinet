"""Qt 없는 웹 경계. TypedDict가 frontend/src/bridge-types.ts의 원본이다."""

from dataclasses import asdict
from typing import TypedDict
from urllib.parse import urlsplit

from .web_external_subtitle_data import subtitle_file_data
from .translation_kind import translation_task
from .library_views import LibraryViewOptions, LibraryFolder, LibraryChip, matches_title_tags


class TagData(TypedDict):
    id: int
    name: str


class TagUsageData(TypedDict):
    """태그 고르기 목록 항목. key는 코어가 정규화한 검색용 이름이다."""
    id: int
    name: str
    key: str
    videoCount: int


class TagCandidatesData(TypedDict):
    """무작위 재생 태그 고르기용. 코어 규칙으로 거른 그 태그의 후보 영상 ID다."""
    id: int
    videoIds: list[int]


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
    viewingCount: int
    watchedSeconds: float
    lastViewedAt: str | None
    # 수정한 날짜(ISO 시각). 파일 없음이거나 수정 시각을 모르면 없다. missing으로 둘을 구별한다.
    modifiedAt: str | None
    hasSubtitles: bool


class HighlightData(TypedDict):
    id: int
    start: float
    end: float | None
    note: str
    tags: list[TagData]


class ExternalSubtitleTrackData(TypedDict):
    language: str | None
    languageLabel: str
    languageClass: str
    lineCount: int


class ExternalSubtitleFileData(TypedDict):
    id: int
    name: str
    folderLabel: str | None
    warning: str | None
    subtitles: list[ExternalSubtitleTrackData]


class DetailsData(TypedDict):
    has_transcript: bool
    spoken_language: str | None
    original_lines: int
    translated_lines: int
    taskLabel: str
    subtitleLabel: str
    subtitle_state: str | None
    translation_state: str | None
    highlight_count: int
    no_speech: bool
    translation_skip_reason: str | None
    externalSubtitles: list[ExternalSubtitleFileData]


class LibraryData(TypedDict):
    videos: list[VideoData]
    tags: list[TagUsageData]
    visibleIds: list[int]
    selectedId: int | None
    scanning: bool
    options: LibraryViewOptions
    folders: list[LibraryFolder]
    chips: list[LibraryChip]


def snapshot_data(snapshot, subtitled_ids=frozenset()) -> list[VideoData]:
    series = {vid: f"{s.name} · {i + 1}/{len(s.video_ids)}"
              for s in snapshot.series for i, vid in enumerate(s.video_ids)}
    result = []
    for video in snapshot.videos:
        status = snapshot.statuses[video.id]
        statistics = snapshot.video_statistics.get(video.id)
        modified = video.modified_at
        result.append(VideoData(
            id=video.id, title=video.title, duration=video.duration,
            # 숫자 host는 Chromium이 IP로 정규화하므로 고정 host 아래에 ID를 둔다.
            thumbnail=(f"mvm-thumb://video/{video.id}" + ('?v=640' if video.thumbnail.name.endswith('.640.jpg') else '')) if video.thumbnail else None,
            missing=video.missing, locationCount=len(video.locations),
            finished=status.finished, abandoned=status.abandoned, favorite=status.favorite,
            resumePoint=status.resume_point, stoppedPercent=status.stopped_percent,
            tags=[TagData(id=t.id, name=t.name) for t in snapshot.tags.get(video.id, ())],
            series=series.get(video.id, ""),
            viewingCount=statistics.viewing_count if statistics else 0,
            watchedSeconds=statistics.watched_seconds if statistics else 0,
            lastViewedAt=statistics.last_viewed_at if statistics else None,
            modifiedAt=modified.isoformat() if modified else None,
            hasSubtitles=video.id in subtitled_ids,
        ))
    return result


def tag_usage_data(usage) -> list[TagUsageData]:
    return [TagUsageData(id=u.tag.id, name=u.tag.name, key=u.key, videoCount=u.video_count) for u in usage]


def tag_candidates_data(candidates) -> list[TagCandidatesData]:
    return [TagCandidatesData(id=tag_id, videoIds=sorted(ids)) for tag_id, ids in sorted(candidates.items())]


def highlights_data(core, video_id) -> list[HighlightData]:
    tags = core.highlight_tags_map(video_id)
    return [HighlightData(id=h.id, start=h.start, end=h.end,
                          note=h.note.text if h.note else '',
                          tags=[TagData(id=t.id, name=t.name) for t in tags.get(h.id, ())])
            for h in core.highlights(video_id)]


def filter_ids(videos: list[VideoData], query: str, tag_id: int | None) -> list[int]:
    query = query.strip().casefold()
    return [v['id'] for v in videos if matches_title_tags(v['title'].casefold(),
            {t['id'] for t in v['tags']}, query, {tag_id} if tag_id is not None else set())]


def details_data(details, external_subtitles=()) -> DetailsData:
    task = translation_task(details.spoken_language)
    return DetailsData(**asdict(details), taskLabel=task.label, subtitleLabel=task.subtitle_label,
                       externalSubtitles=[subtitle_file_data(file) for file in external_subtitles])


def thumbnail_video_id(url: str) -> int | None:
    """ID만 받는다. URL 경로·포트·인증·쿼리·인코딩으로 파일을 지정할 수 없다."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    identifier = parsed.path.removeprefix('/')
    if (parsed.scheme != 'mvm-thumb' or parsed.netloc != 'video'
            or len(identifier) > 10 or not identifier.isascii() or not identifier.isdecimal()
            or parsed.query not in ('', 'v=640') or parsed.fragment):
        return None
    video_id = int(identifier)
    return video_id if 0 < video_id < 2**31 else None
