"""검색 결과의 원문과 정규화 일치 구간을 웹에 전달한다."""
from typing import TypedDict

from PySide6.QtCore import QTextBoundaryFinder

from .search import search_key
from .search_ui import SOURCE_LABELS


class SearchTextData(TypedDict):
    text: str
    matched: bool


class SearchResultData(TypedDict):
    videoId: int
    title: list[SearchTextData]
    source: str
    text: list[SearchTextData]
    start: float | None
    missing: bool


class SearchData(TypedDict):
    query: str
    results: list[SearchResultData]
    selectedIndex: int
    state: str
    truncated: bool
    error: str


def matched_parts(text, query) -> list[SearchTextData]:
    needle = search_key(query)
    if not needle:
        return [dict(text=text, matched=False)]
    encoded = text.encode('utf-16-le')
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    normalized, positions, start = '', [], 0
    while (end := finder.toNextBoundary()) != -1:
        key = search_key(encoded[start * 2:end * 2].decode('utf-16-le'))
        normalized += key
        positions.extend([(start, end)] * len(key))
        start = end
    parts, previous, offset = [], 0, 0
    while (index := normalized.find(needle, offset)) >= 0:
        start, end = positions[index][0], positions[index + len(needle) - 1][1]
        offset = index + len(needle)
        if start < previous:
            continue
        parts.append(dict(text=encoded[previous * 2:start * 2].decode('utf-16-le'), matched=False))
        parts.append(dict(text=encoded[start * 2:end * 2].decode('utf-16-le'), matched=True))
        previous = end
    parts.append(dict(text=encoded[previous * 2:].decode('utf-16-le'), matched=False))
    return parts


def result_data(result, query) -> SearchResultData:
    return dict(videoId=result.video_id, title=matched_parts(result.title, query),
                source=SOURCE_LABELS[result.source], text=matched_parts(result.text, query),
                start=result.start, missing=result.missing)
