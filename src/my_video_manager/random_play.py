"""후보와 직전 선택을 받아 재생할 영상 ID를 고르는 계산."""

import random
from typing import Callable

# 후보가 없을 때의 정보 안내. 라이브러리 버튼·단축키·트레이가 같은 문구를 쓴다.
NO_CANDIDATE_MESSAGE = "재생할 영상이 없습니다."


def choose_video_id(
    candidates: tuple[int, ...], *, previous_video_id: int | None = None,
    choice: Callable[[tuple[int, ...]], int] | None = None,
) -> int | None:
    """중복 없는 후보에서 직전 영상을 피한다. 후보 하나뿐이면 반복을 허용한다."""
    if not candidates:
        return None
    if len(candidates) > 1:
        candidates = tuple(video_id for video_id in candidates if video_id != previous_video_id)
    selected = (random.choice if choice is None else choice)(candidates)
    if selected not in candidates:
        raise ValueError("난수 어댑터는 후보 영상 ID를 반환해야 합니다.")
    return selected
