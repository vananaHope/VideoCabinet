"""재생 중 화면 번역 자막: 그 시각 영역별로 보일 줄과 받아쓰기 자막을 비켜 둘지. Qt·mpv에 의존하지 않는다."""

from dataclasses import dataclass, replace

from .onscreen_subtitles import RegionRect
from .subtitles import TranscriptLine

# 받아쓰기 자막이 놓이는 자리(영상 프레임 세로 비율). 기본 자리는 아래, 비켜나면 위다.
TRANSCRIPT_SUBTITLE_BOTTOM = 0.75
TRANSCRIPT_SUBTITLE_TOP = 0.25


@dataclass(frozen=True)
class OnScreenTranslationRegion:
    """화면 자막 영역 하나와 그 영역의 화면 번역 줄(시각 순). 줄 id는 화면 자막 줄 id다."""
    rect: RegionRect
    lines: tuple[TranscriptLine, ...]


@dataclass(frozen=True)
class OnScreenBand:
    """그 시각에 영역 하나를 덮는 띠: 영역 사각형(영상 프레임 비율)과 그 위에 쓸 화면 번역 글자."""
    rect: RegionRect
    text: str


def onscreen_bands(regions: tuple[OnScreenTranslationRegion, ...], position: float) -> tuple[OnScreenBand, ...]:
    """그 시각에 보일 띠 묶음. 줄이 없는 영역은 띠가 없다(원래 글자가 그대로 보인다).

    한 영역에 그 시각의 줄이 여럿이면 시각 순으로 한 띠에 줄을 바꿔 쓴다.
    """
    bands = []
    for region in regions:
        texts = [line.text for line in region.lines if line.start <= position < line.end]
        if texts:
            bands.append(OnScreenBand(region.rect, "\n".join(texts)))
    return tuple(bands)


def raises_transcript_subtitles(regions: tuple[OnScreenTranslationRegion, ...]) -> bool:
    """받아쓰기 자막을 위로 비켜 둘지. 그 시각의 줄이 아니라 영역 목록으로 정해 줄마다 튀지 않는다.

    영역 하나라도 받아쓰기 자막 자리(아래 25%)와 겹치고, 위 25%와 겹치는 영역은 없을 때만 옮긴다.
    위·아래 모두에 영역이 있으면 옮겨도 겹치므로 그대로 둔다.
    """
    rects = [region.rect for region in regions]
    bottom = any(rect.y + rect.height > TRANSCRIPT_SUBTITLE_BOTTOM for rect in rects)
    top = any(rect.y < TRANSCRIPT_SUBTITLE_TOP for rect in rects)
    return bottom and not top


@dataclass(frozen=True)
class OnScreenTranslationDisplay:
    """재생 화면이 드는 화면 번역 자막 표시 상태.

    enabled는 사용자의 켬·끔(재생 화면에 들어올 때 켬)이고, regions는 지금 영상의 화면 번역 자막이다
    (화면 번역이 완성되지 않았으면 None). player·bands·subtitles_raised는 그 엔진에 지금 보낸 것이다.
    """
    enabled: bool = True
    video_id: int | None = None
    regions: tuple[OnScreenTranslationRegion, ...] | None = None
    player: object = None
    bands: tuple[OnScreenBand, ...] = ()
    subtitles_raised: bool = False

    @property
    def available(self) -> bool:
        return self.regions is not None

    @property
    def shown(self) -> bool:
        """켬이고 그릴 화면 번역 자막이 있다. 단추의 켬 표시다."""
        return self.enabled and self.regions is not None

    def target(self, position: float) -> tuple[tuple[OnScreenBand, ...], bool]:
        """그 시각에 엔진에 있어야 할 (띠 묶음, 받아쓰기 자막 비켜 둠)."""
        if not self.shown:
            return (), False
        return onscreen_bands(self.regions, position), raises_transcript_subtitles(self.regions)

    def on_player(self, player) -> "OnScreenTranslationDisplay":
        """엔진이 바뀌었으면 새 엔진에는 아무것도 보내지 않은 상태로 시작한다."""
        if player is self.player:
            return self
        return replace(self, player=player, bands=(), subtitles_raised=False)
