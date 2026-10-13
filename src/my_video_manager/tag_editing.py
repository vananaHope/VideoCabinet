"""위젯과 독립된 태그 입력 확정 규칙."""


def resolve_tag_input(entered: str, selected_candidate: str | None) -> str:
    """명시적으로 고른 후보가 있을 때만 입력값 대신 그 후보를 추가한다."""
    return entered if selected_candidate is None else selected_candidate
