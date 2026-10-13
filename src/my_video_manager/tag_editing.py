"""위젯과 독립된 태그 입력 확정 규칙."""


def resolve_tag_input(entered: str, selected_candidate: str | None) -> str:
    """명시적으로 고른 후보가 있을 때만 입력값 대신 그 후보를 추가한다."""
    return entered if selected_candidate is None else selected_candidate


def move_tag_candidate(current: int | None, count: int, key: str, page_size: int) -> int | None:
    """방향키는 순환하고, 페이지·처음·끝 이동은 후보 범위 안에서 멈춘다."""
    if count == 0:
        return None
    if key == "Home":
        return 0
    if key == "End":
        return count - 1
    if key in ("Down", "Up"):
        if current is None:
            return 0 if key == "Down" else count - 1
        return (current + (1 if key == "Down" else -1)) % count
    step = max(1, page_size) * (1 if key == "PageDown" else -1)
    return max(0, min(count - 1, (current if current is not None else 0) + step))
