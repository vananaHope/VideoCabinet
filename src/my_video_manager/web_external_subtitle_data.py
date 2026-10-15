"""외부 자막의 언어 표시를 상세와 검색에서 공유한다."""


def language_label(language: str | None) -> str:
    return {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어"}.get(
        language, language or "언어 모름")
