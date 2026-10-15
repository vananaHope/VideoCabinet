"""외부 자막의 언어 표시를 상세와 검색에서 공유한다."""
from collections import Counter
from pathlib import Path

from .external_subtitles import WARNING_PREFIX


def language_label(language: str | None) -> str:
    return {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어"}.get(
        language, language or "언어 모름")


def subtitle_file_data(file):
    """상세 절의 문구만 다듬고 저장된 경고와 언어 클래스는 보존한다."""
    languages = Counter(track.language for track in file.subtitles)
    return dict(id=file.id, name=file.name,
                folderLabel=str(Path(*file.parent_parts)) if file.parent_parts else None,
                warning=file.warning.removeprefix(WARNING_PREFIX) if file.warning else None,
                subtitles=[dict(language=track.language, languageLabel=language_label(track.language),
                                languageClass=track.language_class.upper() if languages[track.language] > 1 else "",
                                lineCount=track.line_count) for track in file.subtitles])
