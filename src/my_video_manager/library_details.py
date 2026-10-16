"""선택 영상의 상세 표시 결과. 조회와 원어 의미 규칙은 각 소유 모듈에 둔다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryDetails:
    has_transcript: bool = False
    spoken_language: str | None = None
    original_lines: int = 0
    translated_lines: int = 0
    subtitle_state: str | None = None
    translation_state: str | None = None
    highlight_count: int = 0
    no_speech: bool = False
    translation_skip_reason: str | None = None
