"""화면 자막 영역 시리즈 전체 적용(#284): 시리즈에 속한 화의 영역 출처(직접 정함·시리즈에서 옴), 시리즈 영역 고치기·지우기,
나중에 시리즈에 들어온 화의 맞추기. 가짜 미디어·OCR을 끼운 실제 DB·대기열의 공개 동작만 본다."""
from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.onscreen_subtitles import OnScreenRegionChanged, RegionOrigin, RegionRect
from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE, TRANSCRIPTION
from my_video_manager.translation_source import ONSCREEN
from test_onscreen_subtitles import FakeMedia, FakeOcr
from test_onscreen_translation import Translator


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
BAND = RegionRect(0.1, 0.75, 0.8, 0.2)
TOP = RegionRect(0.05, 0.02, 0.4, 0.12)
CORNER = RegionRect(0.6, 0.05, 0.35, 0.1)
# 화마다 해상도가 다르다. 영역은 비율이라 같은 자리를 가리킨다.
RESOLUTIONS = {"드라마 01화.mkv": (1280, 720), "드라마 02화.mkv": (1920, 1080), "드라마 03화.mkv": (640, 480),
               "드라마 04화.mkv": (3840, 2160), "따로.mkv": (1280, 720)}


class SizedMedia(FakeMedia):
    def read(self, path):
        width, height = RESOLUTIONS.get(path.name, (1280, 720))
        return MediaInfo(self.duration, "matroska", width, height)


@pytest.fixture
def series(tmp_path):
    """드라마 1~3화(시리즈)와 시리즈 밖 영상 하나. 시리즈 4화는 나중에 들어온다."""
    folder = tmp_path / "드라마"
    folder.mkdir()
    for name in ("드라마 01화.mkv", "드라마 02화.mkv", "드라마 03화.mkv", "따로.mkv"):
        (folder / name).write_bytes(name.encode())
    media, ocr = SizedMedia(), FakeOcr(("en", "ja"))
    media.captions = ((1, 3, "Hello"), (5, 7, "World"))
    core = AppCore(media=media, clock=lambda: NOW, ocr_engine=ocr, translator=Translator(),
                   database=tmp_path / "data/library.sqlite3")
    core.add_watched_folder(folder)
    core.scan()
    videos = {v.title: v.id for v in core.videos()}
    episodes = tuple(videos[f"드라마 0{n}화"] for n in (1, 2, 3))
    assert core.series_for_video(episodes[0]).video_ids == episodes
    return core, media, folder, episodes, videos["따로"]


def regions(core, video_id):
    """영역마다 (자리, 읽을 언어, 출처)."""
    return [(r.rect, r.language, r.origin) for r in core.onscreen_subtitle_regions(video_id)]


def queue(core):
    """화면 자막 대기열의 처리 순서와 (영상, 상태)."""
    return [(e.video_id, e.state) for e in core.subtitle_queue(kind=ONSCREEN_SUBTITLE)]


def read_all(core):
    while (result := core.process_next_onscreen_subtitle()) is not None:
        assert result.state == "completed"


def review(core, video_id, count=1):
    """그 화의 모든 영역에서 앞 줄 count개의 화면 번역을 직접 고친다(검수)."""
    while core.process_next_translation() is not None:
        pass
    for subtitle in core.onscreen_subtitles(video_id):
        for line in subtitle.lines[:count]:
            core.edit_onscreen_translation_line(line.id, "고친 " + line.text)


SERIES = RegionOrigin.SERIES
DIRECT = RegionOrigin.DIRECT


def test_series_apply_copies_to_empty_episodes_as_automatic_and_keeps_direct_ones(series):
    core, media, _, (first, second, third), other = series
    core.add_onscreen_subtitle_region(third, TOP, "ja")  # 3화는 직접 정한 화다
    read_all(core)
    kept = core.onscreen_subtitles(third)
    core.request_automatic_subtitles(other)  # 받아쓰기 자동 대상은 다른 종류라 따로 줄을 선다

    core.add_onscreen_subtitle_region(first, BAND, "en", series=True)

    assert regions(core, first) == regions(core, second) == [(BAND, "en", SERIES)]
    assert regions(core, third) == [(TOP, "ja", DIRECT)] and core.onscreen_subtitles(third) == kept
    assert regions(core, other) == []
    # 지금 화는 직접 요청, 시리즈에서 받은 화는 자동 대상이다.
    assert queue(core) == [(first, "queued"), (second, "queued")]
    core.add_onscreen_subtitle_region(other, CORNER, "en")  # 나중에 한 직접 요청도 자동 대상보다 앞선다
    assert queue(core) == [(first, "queued"), (other, "queued"), (second, "queued")]
    assert [(e.video_id, e.queue_kind) for e in core.subtitle_queue(kind=None)][:3] == [
        (first, ONSCREEN_SUBTITLE), (other, ONSCREEN_SUBTITLE), (other, TRANSCRIPTION)]
    read_all(core)
    # 해상도가 다른 화도 같은 비율 자리를 읽는다.
    paths = {call[0].name: call[1] for call in media.calls}
    assert paths["드라마 01화.mkv"] == paths["드라마 02화.mkv"] == BAND
    assert core.video(first).width != core.video(second).width
    assert [line.text for s in core.onscreen_subtitles(second) for line in s.lines] == ["Hello", "World"]
    assert core.onscreen_subtitles(third) == kept


def test_series_apply_makes_the_whole_region_set_of_this_episode_the_series_regions(series):
    core, _, _, (first, second, third), _ = series
    core.add_onscreen_subtitle_region(first, TOP, "ja")
    read_all(core)
    review(core, first)
    before = core.onscreen_subtitles(first)

    core.add_onscreen_subtitle_region(first, BAND, "en", series=True)

    expected = [(TOP, "ja", SERIES), (BAND, "en", SERIES)]
    assert regions(core, first) == regions(core, second) == regions(core, third) == expected
    # 지금 화의 기존 영역은 그대로 읽은 줄과 검수를 지킨다. 새 영역만 읽는다.
    assert [s.lines for s in core.onscreen_subtitles(first)] == [before[0].lines]
    assert len(core.onscreen_translation_reviewed_lines(first)) == 1
    assert queue(core) == [(first, "queued"), (second, "queued"), (third, "queued")]


def test_series_option_is_refused_outside_a_series_and_changes_nothing(series):
    core, _, _, _, other = series
    with pytest.raises(ValueError, match="시리즈"):
        core.add_onscreen_subtitle_region(other, BAND, "en", series=True)
    assert regions(core, other) == [] and queue(core) == []
