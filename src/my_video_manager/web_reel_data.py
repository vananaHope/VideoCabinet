"""모아보기 웹 경계 데이터. 재생 대상과 순서는 코어가 정한다."""
from typing import TypedDict

from .core import CommandType
from .key_display import display_keys
from .web_library_data import TagData


class ReelEntryData(TypedDict):
    id: int
    videoId: int
    title: str
    thumbnail: str | None
    start: float
    end: float | None
    lastRevisited: str | None
    note: str
    tags: list[TagData]
    playable: bool
    missing: bool


class ReelData(TypedDict):
    entries: list[ReelEntryData]
    tags: list[TagData]
    tagId: int
    selectedId: int | None
    emptyTitle: str
    emptyDescription: str


def guidance(core, tag_id):
    if tag_id:
        return ('이 태그가 붙은 하이라이트가 없습니다', '다른 하이라이트 태그를 골라 보세요.')
    keys = {row.command.kind: display_keys(row.keys) for row in core.key_bindings()}
    point = keys.get(CommandType.POINT_HIGHLIGHT, '키 미할당')
    span = keys.get(CommandType.RANGE_HIGHLIGHT, '키 미할당')
    return ('아직 하이라이트가 없습니다',
            f'영상을 보다가 {point}로 지점, {span}로 구간을 표시하면 여기에 모입니다.')


def entries_data(core, tag_id):
    videos = {v.id: v for v in core.videos()}
    tags = {}
    result = []
    for entry in core.reel_entries(tag_id or None):
        h = entry.highlight
        if h.video_id not in tags:
            tags[h.video_id] = core.highlight_tags_map(h.video_id)
        result.append(ReelEntryData(
            id=h.id, videoId=h.video_id, title=entry.video_title,
            thumbnail=f'mvm-thumb://video/{h.video_id}' if videos[h.video_id].thumbnail else None,
            start=h.start, end=h.end,
            lastRevisited=entry.last_revisited_at.astimezone().strftime('%Y-%m-%d %H:%M:%S') if entry.last_revisited_at else None,
            note=h.note.text if h.note else '',
            tags=[dict(id=t.id, name=t.name) for t in tags[h.video_id].get(h.id, ())],
            playable=entry.playable and h.start < entry.duration, missing=not entry.playable,
        ))
    return result
