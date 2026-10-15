"""검색 결과의 원문과 정규화 일치 구간을 웹에 전달한다."""
from typing import TypedDict

from .search import SOURCE_LABELS
from .search_matching import match_spans
from .web_external_subtitle_data import language_label


class SearchTextData(TypedDict):
    text: str
    matched: bool


class SearchResultData(TypedDict):
    videoId: int
    title: list[SearchTextData]
    source: str
    language: str | None
    languageLabel: str | None
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
    limit: int


def matched_parts(text, query) -> list[SearchTextData]:
    parts, previous = [], 0
    for start, end in match_spans(text, query):
        parts.append(dict(text=text[previous:start], matched=False))
        parts.append(dict(text=text[start:end], matched=True))
        previous = end
    parts.append(dict(text=text[previous:], matched=False))
    return parts


def result_data(result, query) -> SearchResultData:
    return dict(videoId=result.video_id, title=matched_parts(result.title, query),
                source=SOURCE_LABELS[result.source], text=matched_parts(result.text, query),
                language=result.language,
                languageLabel=language_label(result.language) if result.source == 'external' else None,
                start=result.start, missing=result.missing)
