"""재생 수명주기 공용 계약 v2 (#4·#5·#7 공용).

관리자가 정한 파일이다. 내용을 바꾸지 말고 그대로 `src/my_video_manager/playback.py`로 복사한다.
바꿔야 할 이유가 생기면 관리자에게 ask로 묻는다.

사용법:
- AppCore는 `self.playback = PlaybackHub()`를 갖는다.
- 각 기능(시청 #4, 하이라이트 #5, ...)은 PlaybackListener를 구현해 `core.playback.subscribe(...)`로 붙는다.
- 화면은 재생을 시작할 때 `core.playback.start(video_id, 시작 위치)`, mpv 재생 위치가 바뀔 때
  `core.playback.report(위치)`, 재생 화면을 떠나거나 다른 영상으로 넘어갈 때 `core.playback.end()`를 부른다.
- 탐색(seek) 직후 처음 보고하는 위치는 `report(위치, seeked=True)`로 알린다. 직전 위치와 이 위치 사이는
  재생된 것이 아니라 건너뛴 것이다.
- 시청으로 기록하지 않는 재생(예: #12 하이라이트 모아보기)은 `start(..., record_viewing=False)`로 시작한다.
- 위치는 모두 영상 시간 기준 초(float)다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlaybackSession:
    video_id: int
    record_viewing: bool = True


class PlaybackListener(Protocol):
    def playback_started(self, session: PlaybackSession, position: float) -> None: ...

    def playback_position(self, session: PlaybackSession, position: float, seeked: bool) -> None: ...

    def playback_ended(self, session: PlaybackSession, position: float) -> None: ...


class PlaybackHub:
    def __init__(self) -> None:
        self._listeners: list[PlaybackListener] = []
        self._session: PlaybackSession | None = None
        self._position = 0.0

    def subscribe(self, listener: PlaybackListener) -> None:
        self._listeners.append(listener)

    @property
    def session(self) -> PlaybackSession | None:
        return self._session

    @property
    def position(self) -> float:
        return self._position

    def start(self, video_id: int, position: float, *, record_viewing: bool = True) -> PlaybackSession:
        if self._session is not None:
            self.end()
        session = PlaybackSession(video_id, record_viewing)
        self._session = session
        self._position = position
        for listener in self._listeners:
            listener.playback_started(session, position)
        return session

    def report(self, position: float, *, seeked: bool = False) -> None:
        session = self._session
        if session is None:
            return
        self._position = position
        for listener in self._listeners:
            listener.playback_position(session, position, seeked)

    def end(self) -> None:
        session = self._session
        if session is None:
            return
        position = self._position
        self._session = None
        for listener in self._listeners:
            listener.playback_ended(session, position)
