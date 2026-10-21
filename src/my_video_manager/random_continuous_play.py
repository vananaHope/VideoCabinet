"""무작위 이어 재생의 범위와 한 번의 재생 동안 쓰는 선택·이동 기록."""

from dataclasses import dataclass, field
from typing import Callable, Literal

from .random_play import NO_CANDIDATE_MESSAGE, choose_video_id


@dataclass(frozen=True)
class RandomPlayScope:
    kind: Literal["all", "list", "tags"] = "all"
    video_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.kind not in ("all", "list", "tags"):
            raise ValueError("지원하지 않는 무작위 재생 범위입니다.")
        if (self.kind != "list" and self.video_ids) or (self.kind != "tags" and self.tag_ids):
            raise ValueError("범위 종류에 맞는 ID 목록을 지정하세요.")
        object.__setattr__(self, "video_ids", tuple(dict.fromkeys(self.video_ids)))
        object.__setattr__(self, "tag_ids", tuple(dict.fromkeys(self.tag_ids)))


@dataclass
class RandomContinuousPlay:
    source_ids: tuple[int, ...] | None = None
    enabled: bool = False
    scope: RandomPlayScope | None = None
    seen: set[int] = field(default_factory=set)
    history: list[int] = field(default_factory=list)
    index: int = 0
    notice: str | None = None

    def enable(self, video_id: int, scope: RandomPlayScope):
        self.enabled, self.scope = True, scope
        self.seen = {video_id}
        self.history, self.index = [video_id], 0
        self.notice = None

    def disable(self):
        self.enabled, self.scope = False, None
        self.seen.clear()
        self.history.clear()
        self.index, self.notice = 0, None

    def record(self, video_id: int):
        if self.enabled and (not self.history or self.history[self.index] != video_id):
            del self.history[self.index + 1:]
            self.history.append(video_id)
            self.index = len(self.history) - 1
            self.seen.add(video_id)

    def move(self, *, forward: bool, playable: set[int], candidates: tuple[int, ...],
             choice: Callable[[tuple[int, ...]], int] | None) -> tuple[int | None, bool]:
        """(대상, 새 무작위 선택 여부). 기록 이동도 이번 바퀴에 나온 영상으로 센다."""
        self.notice = None
        step = 1 if forward else -1
        for index in range(self.index + step, len(self.history) if forward else -1, step):
            if self.history[index] in playable:
                self.index = index
                self.seen.add(self.history[index])
                return self.history[index], False
        if not forward:
            self.notice = "이번 무작위 이어 재생의 첫 영상입니다."
            return None, False
        if not candidates:
            self.notice = NO_CANDIDATE_MESSAGE
            return None, False
        remaining = tuple(vid for vid in candidates if vid not in self.seen)
        restart = not remaining
        selected = choose_video_id(remaining or candidates, previous_video_id=self.history[self.index],
                                   choice=choice)
        if restart:
            self.seen.clear()
        self.seen.add(selected)
        del self.history[self.index + 1:]
        self.history.append(selected)
        self.index = len(self.history) - 1
        return selected, True
