"""위젯에 의존하지 않는 하이라이트 시각 입력 변환."""

import math


def time_input_maximum(duration: float) -> float:
    """밀리초 단위 입력의 최댓값이 실제 영상 길이를 넘지 않게 한다."""
    return math.floor(duration * 1000) / 1000


def resolve_time_input(original: float | None, initial: float, current: float) -> float:
    """표시값을 수정하지 않았다면 반올림·범위 제한 전의 원래 시각을 보존한다."""
    return original if original is not None and current == initial else current
