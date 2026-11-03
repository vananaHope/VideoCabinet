"""번역할 줄 묶음의 출처. 출처와 대기열 작업 종류의 대응은 여기서만 정한다."""

from dataclasses import dataclass
from typing import Callable, Protocol

from .subtitle_queue_kind import TRANSCRIPTION
from .subtitles import TranscriptLine


TRANSCRIPT = "transcript"
ONSCREEN = "onscreen_subtitle"


@dataclass(frozen=True)
class OnScreenTranslationSourceLine(TranscriptLine):
    region_id: int
    language: str


@dataclass(frozen=True)
class TranslationSourceLines:
    """한 영상·출처의 현재 세대. 읽는 함수는 전달받은 DB의 같은 스냅숏을 읽는다."""

    id: str
    video_id: int
    spoken_language: str | None
    lines: tuple[TranscriptLine, ...]
    complete: bool = True


class SourceLineReader(Protocol):
    def __call__(self, video_id: int, *, connection=None) -> TranslationSourceLines | None: ...


class TranslationSources:
    def __init__(self):
        self._kinds = {TRANSCRIPT: TRANSCRIPTION}
        self._readers: dict[str, SourceLineReader] = {}
        self._protected: dict[str, Callable] = {}

    def register(self, source, read_lines, *, queue_kind, protected_lines=None):
        if not source or not queue_kind or source in self._readers:
            raise ValueError("새 번역 출처와 대기열 작업 종류를 확인하세요.")
        if any(kind == queue_kind and name != source for name, kind in self._kinds.items()):
            raise ValueError("대기열 작업 종류에는 번역 출처 하나만 연결할 수 있습니다.")
        self._kinds[source] = queue_kind
        self._readers[source] = read_lines
        self._protected[source] = protected_lines or (lambda db: set())

    def lines(self, source, video_id, *, connection=None):
        try:
            read_lines = self._readers[source]
        except KeyError:
            raise ValueError("등록되지 않은 번역 출처입니다.") from None
        return read_lines(video_id, connection=connection)

    def protected_lines(self, source, db):
        return self._protected[source](db)

    def queue_kind(self, source):
        return self._kinds[source]

    def for_queue_kind(self, kind):
        return next((source for source, value in self._kinds.items() if value == kind), None)
