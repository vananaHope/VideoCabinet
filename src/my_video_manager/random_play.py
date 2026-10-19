"""후보와 직전 선택을 받아 재생할 영상 ID를 고르는 계산."""

import random
from typing import Callable, Iterable, Mapping

# 후보가 없을 때의 정보 안내. 라이브러리 버튼·단축키·트레이가 같은 문구를 쓴다.
NO_CANDIDATE_MESSAGE = "재생할 영상이 없습니다."


def is_candidate(video) -> bool:
    """파일 없음·제외 영상은 후보가 아니다. 다 본 영상은 후보다."""
    return not video.missing and not video.excluded


def tag_candidates(videos: Iterable, video_tags: Mapping[int, Iterable]) -> dict[int, frozenset[int]]:
    """태그 ID별 후보 영상 ID. 영상에 붙은 태그만 보며 후보가 없는 태그는 싣지 않는다.

    고른 태그들(OR)의 후보는 이 집합들의 합집합이다.
    """
    grouped: dict[int, set[int]] = {}
    for video in videos:
        if is_candidate(video):
            for tag in video_tags.get(video.id, ()):
                grouped.setdefault(tag.id, set()).add(video.id)
    return {tag_id: frozenset(ids) for tag_id, ids in grouped.items()}


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
