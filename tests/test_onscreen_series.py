"""화면 자막 영역 시리즈 전체 적용(#284): 시리즈에 속한 화의 영역 출처(직접 정함·시리즈에서 옴), 시리즈 영역 고치기·지우기,
나중에 시리즈에 들어온 화의 맞추기. 가짜 미디어·OCR을 끼운 실제 DB·대기열의 공개 동작만 본다."""
from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.onscreen_series import OnScreenSeriesChanged, OnScreenSeriesImpact
from my_video_manager.onscreen_subtitles import OnScreenRegionChanged, RegionEdit, RegionOrigin, RegionRect
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


# 나중에 시리즈에 들어온 화와 시리즈에서 빠진 화(AC-2, AC-4)


def apply_and_read(core, first):
    core.add_onscreen_subtitle_region(first, BAND, "en", series=True)
    core.add_onscreen_subtitle_region(first, TOP, "ja", series=True)
    read_all(core)
    return [(BAND, "en", SERIES), (TOP, "ja", SERIES)]


def join_by_scan(core, folder, tmp_path):
    (folder / "드라마 04화.mkv").write_bytes(b"episode 4")
    core.scan()
    return next(v.id for v in core.videos() if v.title == "드라마 04화")


def join_by_add_file(core, folder, tmp_path):
    path = folder / "드라마 04화.mkv"
    path.write_bytes(b"episode 4")
    core.add_file(path)
    return next(v.id for v in core.videos() if v.title == "드라마 04화")


def join_by_reconnect(core, folder, tmp_path):
    # 시리즈 밖에서 등록했던 영상의 파일이 사라졌다가, 시리즈 폴더의 같은 내용 파일로 다시 연결된다.
    outside = tmp_path / "밖" / "에피소드.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"episode 4")
    core.add_file(outside)
    video = next(v.id for v in core.videos() if v.title == "에피소드")
    outside.unlink()
    core.scan()
    assert core.series_for_video(video) is None
    (folder / "드라마 04화.mkv").write_bytes(b"episode 4")
    core.reconnect_video(video, folder / "드라마 04화.mkv")
    return video


def join_by_series_edit(core, folder, tmp_path):
    other = next(v.id for v in core.videos() if v.title == "따로")
    series = core.series_for_video(next(v.id for v in core.videos() if v.title == "드라마 01화"))
    core.update_series(series.id, name=series.name, video_ids=(*series.video_ids, other))
    return other


@pytest.mark.parametrize("join", [join_by_scan, join_by_add_file, join_by_reconnect, join_by_series_edit])
def test_episode_joining_the_series_later_gets_the_series_regions_once_as_automatic(series, tmp_path, join):
    core, media, folder, (first, second, third), _ = series
    expected = apply_and_read(core, first)
    assert queue(core) == []
    core.add_onscreen_subtitle_region(third, CORNER, "en")  # 직접 요청 하나가 대기 중이다

    joined = join(core, folder, tmp_path)

    assert joined in core.series_for_video(first).video_ids
    assert regions(core, joined) == expected
    assert queue(core) == [(third, "queued"), (joined, "queued")]
    before = (core.onscreen_subtitle_regions(joined), queue(core))
    # 같은 맞추기를 다시 불러도 아무것도 바뀌지 않는다.
    core.scan()
    series_now = core.series_for_video(first)
    core.update_series(series_now.id, name=series_now.name, video_ids=series_now.video_ids)
    assert (core.onscreen_subtitle_regions(joined), queue(core)) == before
    read_all(core)
    assert [line.text for s in core.onscreen_subtitles(joined) for line in s.lines] == ["Hello", "World"] * 2


def test_joining_episode_with_its_own_regions_and_members_left_without_regions_are_not_filled(series):
    core, _, folder, (first, second, third), other = series
    core.add_onscreen_subtitle_region(other, CORNER, "en")
    core.add_onscreen_subtitle_region(third, TOP, "ja")
    core.delete_onscreen_subtitle_region(core.onscreen_subtitle_regions(third)[0].id)  # 3화는 영역을 모두 지웠다
    apply_and_read(core, first)
    assert regions(core, third) == regions(core, second)  # 사용자가 고른 적용은 영역이 없는 화를 채운다
    band = core.onscreen_subtitle_regions(third)[0]
    core.update_onscreen_subtitle_region(band.id, band.rect, band.language, mode=RegionEdit.REBUILD)  # 3화만 고쳐 직접 정함이 된다
    for region in core.onscreen_subtitle_regions(third):
        core.delete_onscreen_subtitle_region(region.id)
    assert regions(core, third) == []
    series_now = core.series_for_video(first)
    core.update_series(series_now.id, name=series_now.name, video_ids=(*series_now.video_ids, other))
    core.scan()
    # 이미 시리즈에 있던 화는 영역이 없어도 다시 채우지 않고, 영역이 있는 새 화는 그대로 직접 정함이다.
    assert regions(core, third) == []
    assert regions(core, other) == [(CORNER, "en", DIRECT)]


def test_episode_leaving_the_series_keeps_its_regions_lines_and_reviews_as_directly_set(series):
    core, _, _, (first, second, third), _ = series
    apply_and_read(core, first)
    review(core, second)
    kept = (core.onscreen_subtitles(second), core.onscreen_translation_reviewed_lines(second))
    series_now = core.series_for_video(first)

    core.update_series(series_now.id, name=series_now.name, video_ids=(first, third))

    assert [origin for *_, origin in regions(core, second)] == [DIRECT, DIRECT]
    assert [s.lines for s in core.onscreen_subtitles(second)] == [s.lines for s in kept[0]]
    assert core.onscreen_translation_reviewed_lines(second) == kept[1]
    # 이후 시리즈 영역 변경을 따르지 않는다.
    band = core.onscreen_subtitle_regions(first)[0]
    core.update_onscreen_subtitle_region(band.id, CORNER, "en", series=True, mode=RegionEdit.REBUILD)
    assert [s.lines for s in core.onscreen_subtitles(second)] == [s.lines for s in kept[0]]
    assert regions(core, second)[0][0] == BAND


def test_series_removed_by_regrouping_leaves_its_episodes_directly_set(series, tmp_path):
    core, _, folder, (first, second, third), _ = series
    apply_and_read(core, first)
    kept = core.onscreen_subtitles(second)
    # 파일 이름이 바뀌어 자동 묶기가 시리즈를 없앤다. 영상은 같은 내용이라 그대로 이어진다.
    for number, video in ((1, first), (2, second), (3, third)):
        (folder / f"드라마 0{number}화.mkv").rename(folder / f"장면 {chr(64 + number)}.mkv")
    core.scan()
    assert core.series_for_video(first) is None
    assert {origin for video in (first, second, third) for *_, origin in regions(core, video)} == {DIRECT}
    assert [(s.region.id, s.lines) for s in core.onscreen_subtitles(second)] == [(s.region.id, s.lines) for s in kept]


def test_membership_change_left_unreconciled_converges_on_the_next_regrouping(series):
    """시리즈 소속 변경과 출처 맞추기는 다른 트랜잭션이다. 그 사이 앱이 끝나도 다음 맞추기가 상태를 보고 다시 맞춘다."""
    import sqlite3
    from contextlib import closing
    core, media, _, (first, second, third), _ = series
    apply_and_read(core, first)
    series_id = core.series_for_video(first).id
    with closing(sqlite3.connect(core.database)) as db, db:
        # 시리즈 편집이 2화를 뺀 직후 앱이 끝난 상태: 소속만 바뀌고 출처는 아직 맞추지 않았다.
        db.execute("UPDATE series SET edited = 1 WHERE id = ?", (series_id,))
        db.execute("INSERT OR IGNORE INTO series_overrides VALUES (?)", (second,))
        db.execute("DELETE FROM series_videos WHERE video_id = ?", (second,))
    reopened = AppCore(media=media, clock=lambda: NOW, ocr_engine=FakeOcr(("en", "ja")), database=core.database)
    reopened.scan()
    assert [origin for *_, origin in regions(reopened, second)] == [DIRECT, DIRECT]
    before = regions(reopened, second), queue(reopened)
    reopened.scan()
    assert (regions(reopened, second), queue(reopened)) == before


# 시리즈 영역 고치기·지우기(AC-3, AC-4)와 확인 창의 범위(AC-5)


def series_with_direct_episode(core, first, third):
    """1·2화는 시리즈에서 온 화(영역 둘), 3화는 직접 정한 화다. 모두 읽고 화마다 영역별 한 줄씩 검수했다."""
    core.add_onscreen_subtitle_region(third, CORNER, "en")
    expected = apply_and_read(core, first)
    for video in core.series_for_video(first).video_ids:
        review(core, video)
    return expected


def state(core, video_id):
    """영역별 (영역 ID, 줄, 검수로 고친 줄)."""
    reviewed = core.onscreen_translation_reviewed_lines(video_id)
    return [(s.region.id, s.lines, {line.id for line in s.lines} & reviewed) for s in core.onscreen_subtitles(video_id)]


def everything(core, videos):
    return [(regions(core, v), state(core, v), core.translation(v, source=ONSCREEN)) for v in videos], queue(core)


def test_series_region_update_rereads_only_that_region_in_each_series_episode(series):
    core, media, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    direct = state(core, third)
    band, top = core.onscreen_subtitle_regions(second)
    kept_top = [entry for entry in state(core, second) if entry[0] == top.id]
    edited = core.onscreen_subtitle_regions(first)[0]
    # 다른 화 하나(2화), 1·2화의 그 영역에서 검수로 고친 줄 한 줄씩.
    assert core.onscreen_subtitle_region_series_impact(first, edited.id) == OnScreenSeriesImpact(1, 2, True)

    core.update_onscreen_subtitle_region(edited.id, CORNER, "ja", series=True, mode=RegionEdit.REBUILD)

    assert regions(core, first) == regions(core, second) == [(CORNER, "ja", SERIES), (TOP, "ja", SERIES)]
    assert core.onscreen_subtitle_regions(second)[0].id == band.id  # 그 자리에서 고친다
    # 다른 영역의 줄·번역·검수와 직접 정한 화는 그대로다.
    assert [entry for entry in state(core, second) if entry[0] == top.id] == kept_top
    assert state(core, third) == direct
    assert queue(core) == [(first, "queued"), (second, "queued")]
    media.calls.clear()
    read_all(core)
    assert [(call[0].name, call[1]) for call in media.calls] == [("드라마 01화.mkv", CORNER), ("드라마 02화.mkv", CORNER)]


def test_moving_a_series_region_in_one_episode_only_makes_it_directly_set_and_keeps_its_lines(series):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    band = core.onscreen_subtitle_regions(first)[0]
    kept, others = state(core, first), state(core, second)

    assert core.update_onscreen_subtitle_region(band.id, CORNER, "en", mode=RegionEdit.MOVE) is None

    assert regions(core, first) == [(CORNER, "en", DIRECT), (TOP, "ja", DIRECT)]
    assert state(core, first) == kept and queue(core) == []
    assert regions(core, second) == [(BAND, "en", SERIES), (TOP, "ja", SERIES)] and state(core, second) == others


def test_rereading_a_series_region_in_one_episode_only_makes_it_directly_set_and_reads_only_that_region(series):
    core, media, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    band = core.onscreen_subtitle_regions(first)[0]
    others = state(core, second)
    media.calls.clear()

    assert core.update_onscreen_subtitle_region(band.id, CORNER, "en", mode=RegionEdit.REREAD).state == "queued"

    assert regions(core, first) == [(CORNER, "en", DIRECT), (TOP, "ja", DIRECT)]
    assert core.process_next_onscreen_subtitle().state == "completed"
    assert [call[1] for call in media.calls] == [CORNER]
    assert regions(core, second) == [(BAND, "en", SERIES), (TOP, "ja", SERIES)] and state(core, second) == others


def test_moving_a_series_region_moves_every_series_copy_and_keeps_their_lines(series):
    """#428: 시리즈 영역 자리만 바꾸기는 시리즈에서 온 화마다 사각형만 바꾸고 줄·번역·검수가 그대로이며 대기열에 넣지 않는다."""
    core, media, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    edited = core.onscreen_subtitle_regions(first)[0]
    kept = {video: (state(core, video), core.translation(video, source=ONSCREEN)) for video in (first, second, third)}
    direct = regions(core, third)
    impact = core.onscreen_subtitle_region_series_impact(first, edited.id, mode=RegionEdit.MOVE)
    assert impact == OnScreenSeriesImpact(1, 0, True) and impact.change == "update"
    assert core.onscreen_subtitle_region_series_impact(first, edited.id).reviewed_line_count == 2  # 다시 만들기만 센다
    media.calls.clear()

    assert core.update_onscreen_subtitle_region(edited.id, CORNER, "en", series=True, mode=RegionEdit.MOVE,
                                                expected_series_impact=impact) is None

    assert regions(core, first) == regions(core, second) == [(CORNER, "en", SERIES), (TOP, "ja", SERIES)]
    assert regions(core, third) == direct
    assert {video: (state(core, video), core.translation(video, source=ONSCREEN))
            for video in (first, second, third)} == kept
    assert queue(core) == [] and core.process_next_onscreen_subtitle() is None and media.calls == []


def test_rereading_a_series_region_rereads_it_in_every_series_episode_keeping_matching_lines(series):
    """#428: 시리즈 영역 다시 읽기는 시리즈에서 온 화마다 그 영역만 다시 읽고(지금 화는 직접 요청, 다른 화는 자동 대상)
    글자가 같은 줄과 검수한 줄의 번역을 지킨다."""
    core, media, _, (first, second, third), other = series
    series_with_direct_episode(core, first, third)
    edited = core.onscreen_subtitle_regions(first)[0]
    kept = {video: (state(core, video), core.translation(video, source=ONSCREEN)) for video in (first, second, third)}
    impact = core.onscreen_subtitle_region_series_impact(first, edited.id, mode=RegionEdit.REREAD)
    assert impact == OnScreenSeriesImpact(1, 0, True)

    entry = core.update_onscreen_subtitle_region(edited.id, CORNER, "en", series=True, mode=RegionEdit.REREAD,
                                                 expected_series_impact=impact)

    assert (entry.video_id, entry.state) == (first, "queued")
    assert queue(core) == [(first, "queued"), (second, "queued")]
    core.add_onscreen_subtitle_region(other, CORNER, "en")  # 나중에 한 직접 요청은 자동 대상(2화)보다 앞선다
    assert queue(core) == [(first, "queued"), (other, "queued"), (second, "queued")]
    # 기다리는 동안에도 줄과 번역이 그대로 보인다.
    assert {video: (state(core, video), core.translation(video, source=ONSCREEN))
            for video in (first, second, third)} == kept
    media.calls.clear()
    read_all(core)
    assert [(call[0].name, call[1]) for call in media.calls] == [
        ("드라마 01화.mkv", CORNER), ("따로.mkv", CORNER), ("드라마 02화.mkv", CORNER)]
    # 같은 글자를 읽어 줄 ID·번역·검수가 그대로이고 새로 번역할 줄이 없다.
    assert {video: (state(core, video), core.translation(video, source=ONSCREEN))
            for video in (first, second, third)} == kept
    assert regions(core, second) == [(CORNER, "en", SERIES), (TOP, "ja", SERIES)]


@pytest.mark.parametrize("mode", [RegionEdit.MOVE, RegionEdit.REREAD])
def test_series_move_and_reread_are_refused_for_a_changed_language_or_an_unread_region(series, mode):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    band = core.onscreen_subtitle_regions(first)[0]
    before = everything(core, (first, second, third))
    with pytest.raises(ValueError, match="처음부터 다시 만들어야"):
        core.update_onscreen_subtitle_region(band.id, CORNER, "ja", series=True, mode=mode)
    assert everything(core, (first, second, third)) == before
    core.add_onscreen_subtitle_region(first, RegionRect(0, 0.4, 0.5, 0.2), "en", series=True)
    waiting = core.onscreen_subtitle_regions(first)[2]
    before = everything(core, (first, second, third))
    with pytest.raises(ValueError, match="처음부터 다시 만들어야"):
        core.update_onscreen_subtitle_region(waiting.id, CORNER, "en", series=True, mode=mode)
    assert everything(core, (first, second, third)) == before


@pytest.mark.parametrize("mode", [RegionEdit.MOVE, RegionEdit.REREAD])
def test_editing_a_direct_region_into_the_series_applies_the_mode_to_this_episode(series, mode):
    """#428: 직접 정한 화의 영역을 시리즈 전체에 적용하면 그 화에는 고른 방식이 적용되고, 묶음이 시리즈 영역이 된다.
    시리즈에서 온 다른 화는 지금처럼 이전 영역을 잃고 새 묶음을 받는다."""
    core, media, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    corner, = core.onscreen_subtitle_regions(third)
    kept = state(core, third), core.translation(third, source=ONSCREEN)
    impact = core.onscreen_subtitle_region_series_impact(third, corner.id, mode=mode)
    # 다른 화 둘(1·2화)이 이전 시리즈 영역 둘씩과 그 검수 한 줄씩을 잃는다. 이 화의 검수는 사라지지 않는다.
    assert impact == OnScreenSeriesImpact(2, 4, True) and impact.change == "replace"
    assert core.onscreen_subtitle_region_series_impact(third, corner.id).reviewed_line_count == 5

    core.update_onscreen_subtitle_region(corner.id, TOP, "en", series=True, mode=mode, expected_series_impact=impact)

    assert regions(core, first) == regions(core, second) == regions(core, third) == [(TOP, "en", SERIES)]
    assert (state(core, third), core.translation(third, source=ONSCREEN)) == kept
    expected = [(first, "queued"), (second, "queued")]
    assert queue(core) == (expected if mode == RegionEdit.MOVE else [(third, "queued"), *expected])
    read_all(core)
    assert (state(core, third), core.translation(third, source=ONSCREEN)) == kept


def test_a_series_move_that_saw_an_outdated_range_changes_nothing(series):
    core, _, folder, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    band = core.onscreen_subtitle_regions(first)[0]
    seen = core.onscreen_subtitle_region_series_impact(first, band.id, mode=RegionEdit.MOVE)
    (folder / "드라마 04화.mkv").write_bytes(b"episode 4")
    core.scan()  # 4화가 시리즈 영역을 받아 다른 화가 하나 늘었다
    before = everything(core, (first, second, third))
    with pytest.raises(OnScreenSeriesChanged) as changed:
        core.update_onscreen_subtitle_region(band.id, CORNER, "en", series=True, mode=RegionEdit.MOVE,
                                             expected_series_impact=seen)
    assert changed.value.impact == OnScreenSeriesImpact(2, 0, True)
    assert everything(core, (first, second, third)) == before


def test_turning_the_option_off_makes_only_this_episode_directly_set(series):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    band = core.onscreen_subtitle_regions(first)[0]
    others = state(core, second)

    core.update_onscreen_subtitle_region(band.id, CORNER, "en", expected_reviewed_line_count=1, mode=RegionEdit.REBUILD)

    assert regions(core, first) == [(CORNER, "en", DIRECT), (TOP, "ja", DIRECT)]
    assert regions(core, second) == [(BAND, "en", SERIES), (TOP, "ja", SERIES)] and state(core, second) == others
    assert queue(core) == [(first, "queued")]
    # 이후 시리즈 변경을 따르지 않는다.
    top = core.onscreen_subtitle_regions(second)[1]
    core.update_onscreen_subtitle_region(top.id, TOP, "en", series=True, mode=RegionEdit.REBUILD)
    core.add_onscreen_subtitle_region(second, BAND, "ja", series=True)
    assert regions(core, first) == [(CORNER, "en", DIRECT), (TOP, "ja", DIRECT)]
    # 새 영역을 선택지 없이 더해도 그 화만 직접 정함이 된다.
    core.add_onscreen_subtitle_region(second, CORNER, "en")
    assert [origin for *_, origin in regions(core, second)] == [DIRECT] * 4
    assert [origin for *_, origin in regions(core, third)] == [DIRECT]


def test_new_region_on_a_series_episode_is_added_to_the_series_without_touching_other_regions(series):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    kept, direct = state(core, second), state(core, third)
    assert core.onscreen_subtitle_region_series_impact(second) == OnScreenSeriesImpact(1, 0, False)

    core.add_onscreen_subtitle_region(second, CORNER, "en", series=True)

    expected = [(BAND, "en", SERIES), (TOP, "ja", SERIES), (CORNER, "en", SERIES)]
    assert regions(core, first) == regions(core, second) == expected
    assert state(core, second) == kept and state(core, third) == direct
    assert queue(core) == [(second, "queued"), (first, "queued")]


def test_series_apply_from_a_directly_set_episode_replaces_the_series_regions(series):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    kept = state(core, third)
    # 1·2화가 시리즈 영역 둘(영역마다 검수 한 줄)을 잃고 3화의 묶음을 받는다.
    impact = core.onscreen_subtitle_region_series_impact(third)
    assert impact == OnScreenSeriesImpact(2, 4, True)

    core.add_onscreen_subtitle_region(third, TOP, "en", series=True, expected_series_impact=impact)

    expected = [(CORNER, "en", SERIES), (TOP, "en", SERIES)]
    assert regions(core, first) == regions(core, second) == regions(core, third) == expected
    assert state(core, third) == kept  # 이 화의 기존 영역은 줄·검수를 지킨다(새 영역은 아직 읽지 않았다)
    assert core.onscreen_subtitles(first) == () and core.onscreen_translation_reviewed_lines(first) == frozenset()
    assert queue(core) == [(third, "queued"), (first, "queued"), (second, "queued")]


def test_editing_a_direct_region_with_the_option_on_makes_this_set_the_series_regions(series):
    core, _, _, (first, second, third), _ = series
    core.add_onscreen_subtitle_region(first, BAND, "en")
    core.add_onscreen_subtitle_region(first, TOP, "ja")
    read_all(core)
    review(core, first)
    band, top = core.onscreen_subtitle_regions(first)
    kept_top = [entry for entry in state(core, first) if entry[0] == top.id]
    # 시리즈 영역이 없으니 확인 창 없이 정하지만, 고친 영역의 검수 한 줄은 사라진다.
    impact = core.onscreen_subtitle_region_series_impact(first, band.id)
    assert impact == OnScreenSeriesImpact(2, 1, False)

    core.update_onscreen_subtitle_region(band.id, CORNER, "en", series=True, expected_series_impact=impact, mode=RegionEdit.REBUILD)

    assert regions(core, first) == regions(core, second) == regions(core, third) == [
        (CORNER, "en", SERIES), (TOP, "ja", SERIES)]
    assert [entry for entry in state(core, first) if entry[0] == top.id] == kept_top
    assert queue(core) == [(first, "queued"), (second, "queued"), (third, "queued")]


def test_series_region_delete_removes_it_from_series_episodes_only(series):
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    direct = state(core, third)
    top = core.onscreen_subtitle_regions(first)[1]
    kept_band = state(core, second)[0]
    impact = core.onscreen_subtitle_region_series_impact(first, top.id, delete=True)
    assert impact == OnScreenSeriesImpact(1, 2, True)

    core.delete_onscreen_subtitle_region(top.id, expected_series_impact=impact)

    assert regions(core, first) == regions(core, second) == [(BAND, "en", SERIES)]
    assert state(core, second) == [kept_band] and state(core, third) == direct
    # 지운 영역의 화면 번역 자막도 사라진다.
    assert {line.id for line in core.translation(second, source=ONSCREEN).lines} == {
        line.id for s in core.onscreen_subtitles(second) for line in s.lines}
    assert queue(core) == []
    # 시리즈 영역에서도 빠져, 나중에 들어온 화는 남은 영역만 받는다.
    series_now = core.series_for_video(first)
    core.update_series(series_now.id, name=series_now.name, video_ids=(first, second))
    for region in core.onscreen_subtitle_regions(third):
        core.delete_onscreen_subtitle_region(region.id)
    core.update_series(series_now.id, name=series_now.name, video_ids=(first, second, third))
    assert regions(core, third) == [(BAND, "en", SERIES)]


def impact_of(core, change, first, third, region):
    if change == "replace":
        return core.onscreen_subtitle_region_series_impact(third)
    return core.onscreen_subtitle_region_series_impact(first, region.id, delete=change == "delete")


def change_with(core, change, third, region, seen):
    if change == "update":
        core.update_onscreen_subtitle_region(region.id, CORNER, "en", series=True, expected_series_impact=seen, mode=RegionEdit.REBUILD)
    elif change == "delete":
        core.delete_onscreen_subtitle_region(region.id, expected_series_impact=seen)
    else:
        core.add_onscreen_subtitle_region(third, TOP, "en", series=True, expected_series_impact=seen)


@pytest.mark.parametrize("change", ["update", "delete", "replace"])
def test_a_series_change_that_saw_an_outdated_range_is_refused_without_changing_anything(series, change):
    core, _, folder, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    region = core.onscreen_subtitle_regions(first)[0]
    seen = impact_of(core, change, first, third, region)
    # 확인 창이 열린 사이 다른 화의 그 영역에서 검수가 늘었다.
    other = core.onscreen_subtitles(second)[0]
    core.edit_onscreen_translation_line(other.lines[1].id, "또 고친 줄")
    before = everything(core, (first, second, third))
    with pytest.raises(OnScreenSeriesChanged) as changed:
        change_with(core, change, third, region, seen)
    assert isinstance(changed.value, OnScreenRegionChanged)
    assert changed.value.impact == OnScreenSeriesImpact(seen.other_videos, seen.reviewed_line_count + 1, True)
    assert everything(core, (first, second, third)) == before
    # 영향받는 화 수만 달라져도 다시 확인받는다. 시리즈에서 온 화가 하나 늘었다.
    (folder / "드라마 04화.mkv").write_bytes(b"episode 4")
    core.scan()
    seen = changed.value.impact
    before = everything(core, (first, second, third))
    with pytest.raises(OnScreenSeriesChanged) as changed:
        change_with(core, change, third, region, seen)
    assert changed.value.impact == OnScreenSeriesImpact(seen.other_videos + 1, seen.reviewed_line_count, True)
    assert everything(core, (first, second, third)) == before
    change_with(core, change, third, region, changed.value.impact)  # 지금 범위로 다시 확인하면 바뀐다
    assert everything(core, (first, second, third)) != before


def test_a_failure_while_changing_many_episodes_changes_nothing(series, monkeypatch):
    import my_video_manager.onscreen_series as onscreen_series
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    before = everything(core, (first, second, third))
    region = core.onscreen_subtitle_regions(first)[0]
    original, calls = onscreen_series.reread_region, []

    def failing(db, *args):
        calls.append(args)
        if len(calls) == 2:  # 지금 화를 고친 뒤 시리즈의 다른 화에서 실패한다
            raise RuntimeError("디스크 오류")
        return original(db, *args)
    monkeypatch.setattr(onscreen_series, "reread_region", failing)
    with pytest.raises(RuntimeError):
        core.update_onscreen_subtitle_region(region.id, CORNER, "en", series=True, mode=RegionEdit.REBUILD)
    assert len(calls) == 2
    assert everything(core, (first, second, third)) == before


def test_automatic_targets_never_demote_an_episode_already_requested_directly(series):
    core, _, _, (first, second, third), _ = series
    apply_and_read(core, first)
    band = core.onscreen_subtitles(second)[0]
    core.request_onscreen_subtitle_range(band.region.id, band.lines[0].start, band.lines[0].end)  # 2화 직접 요청

    core.add_onscreen_subtitle_region(first, CORNER, "en", series=True)

    # 2화는 시리즈에서 영역을 더 받아도 먼저 한 직접 요청의 차례를 지키고, 3화만 자동 대상으로 뒤에 선다.
    assert queue(core) == [(second, "queued"), (first, "queued"), (third, "queued")]
    read_all(core)
    assert [len(s.lines) for s in core.onscreen_subtitles(second)] == [2, 2, 2]


# 제외 영상(#365): 시리즈 영역 변경에서 빠진다


def test_excluded_episode_without_regions_is_neither_filled_nor_counted(series):
    core, _, _, (first, second, third), _ = series
    core.exclude_video(second)
    assert core.onscreen_subtitle_region_series_impact(first) == OnScreenSeriesImpact(1, 0, False)

    core.add_onscreen_subtitle_region(first, BAND, "en", series=True)

    assert regions(core, second) == []
    assert queue(core) == [(first, "queued"), (third, "queued")]


def excluded_change(core, change, first, third, region):
    if change == "update":
        core.update_onscreen_subtitle_region(region.id, CORNER, "en", series=True, mode=RegionEdit.REBUILD)
    elif change == "delete":
        core.delete_onscreen_subtitle_region(region.id)
    elif change == "add":
        core.add_onscreen_subtitle_region(first, CORNER, "en", series=True)
    else:
        core.add_onscreen_subtitle_region(third, TOP, "en", series=True)


@pytest.mark.parametrize("change, impact", [
    ("update", OnScreenSeriesImpact(0, 1, True, "update")), ("delete", OnScreenSeriesImpact(0, 1, True, "delete")),
    ("add", OnScreenSeriesImpact(0, 0, False, "add")), ("replace", OnScreenSeriesImpact(1, 2, True, "replace"))])
def test_excluded_episode_from_the_series_keeps_its_regions_as_directly_set(series, change, impact):
    """시리즈에서 온 제외 영상은 세지 않고, 대기열에 넣지 않고, 영역·줄·검수를 지킨 채 직접 정함이 된다."""
    core, _, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    kept = (regions(core, second), state(core, second))
    core.exclude_video(second)
    region = core.onscreen_subtitle_regions(first)[0]
    seen = impact_of(core, change, first, third, region) if change != "add" else \
        core.onscreen_subtitle_region_series_impact(first)
    # 2화의 검수 줄은 사라질 수에 들어가지 않는다. 남은 화는 1화(지금 화이거나 다른 화)와 직접 정한 3화뿐이다.
    assert (seen, seen.change) == (impact, impact.change)

    excluded_change(core, change, first, third, region)

    assert [(rect, language) for rect, language, _ in regions(core, second)] == [
        (rect, language) for rect, language, _ in kept[0]]
    assert {origin for *_, origin in regions(core, second)} == {DIRECT}
    assert state(core, second) == kept[1]
    assert second not in [video for video, _ in queue(core)]
    # 되돌려도 직접 정한 화로 남아, 이후 시리즈 영역 변경을 따르지 않는다.
    core.restore_video(second)
    core.scan()
    assert state(core, second) == kept[1]
    band = core.onscreen_subtitle_regions(third)[0] if change == "replace" else core.onscreen_subtitle_regions(first)[0]
    core.update_onscreen_subtitle_region(band.id, RegionRect(0.2, 0.2, 0.3, 0.3), "en", series=True, mode=RegionEdit.REBUILD)
    assert state(core, second) == kept[1]


# 소속이 바뀐 뒤 출처를 맞추기 전에 끊긴 상태(#365)


def leave_without_reconcile(core, video_id):
    """시리즈 편집이 그 화를 뺀 직후 앱이 끝난 상태: 소속만 바뀌고 출처는 아직 맞추지 않았다."""
    import sqlite3
    from contextlib import closing
    series_id = core.series_for_video(video_id).id
    with closing(sqlite3.connect(core.database)) as db, db:
        db.execute("UPDATE series SET edited = 1 WHERE id = ?", (series_id,))
        db.execute("INSERT OR IGNORE INTO series_overrides VALUES (?)", (video_id,))
        db.execute("DELETE FROM series_videos WHERE video_id = ?", (video_id,))


@pytest.mark.parametrize("change", ["delete", "update"])
def test_episode_left_unreconciled_changes_only_itself(series, change):
    core, _, _, (first, second, third), _ = series
    apply_and_read(core, first)
    review(core, second)
    leave_without_reconcile(core, second)
    others = everything(core, (first, third))
    # 시리즈에서 빠진 화의 영역은 직접 정함으로 보여, 확인 창은 그 화만의 검수 수를 묻는다.
    assert {origin for *_, origin in regions(core, second)} == {DIRECT}
    band = core.onscreen_subtitle_regions(second)[0]
    reviewed = core.onscreen_subtitle_region_reviewed_line_count(band.id)
    assert reviewed == 1

    if change == "delete":
        core.delete_onscreen_subtitle_region(band.id, expected_reviewed_line_count=reviewed)
        assert regions(core, second) == [(TOP, "ja", DIRECT)]
    else:
        core.update_onscreen_subtitle_region(band.id, CORNER, "en", expected_reviewed_line_count=reviewed, mode=RegionEdit.REBUILD)
        assert regions(core, second) == [(CORNER, "en", DIRECT), (TOP, "ja", DIRECT)]
    assert everything(core, (first, third))[0] == others[0]
    assert regions(core, first) == [(BAND, "en", SERIES), (TOP, "ja", SERIES)]


# 확인 가드와 변경 종류(#365)


def test_an_outdated_series_change_does_not_discard_a_reading_in_progress(series):
    core, media, _, (first, second, third), _ = series
    series_with_direct_episode(core, first, third)
    core.add_onscreen_subtitle_region(first, CORNER, "ja", series=True)  # 1화(직접 요청)와 2화가 새 영역을 읽는다
    region = core.onscreen_subtitle_regions(first)[0]
    seen = core.onscreen_subtitle_region_series_impact(first, region.id)
    core.edit_onscreen_translation_line(core.onscreen_subtitles(second)[0].lines[1].id, "또 고친 줄")
    refused = []  # 1화가 읽는 중일 때 낡은 범위로 1화에서 시리즈 영역을 고친다

    def change_while_reading(index):
        if index == 5 and not refused:
            with pytest.raises(OnScreenSeriesChanged) as changed:
                core.update_onscreen_subtitle_region(region.id, CORNER, "en", series=True,
                                                     expected_series_impact=seen, mode=RegionEdit.REBUILD)
            refused.append(changed.value)
    media.hook = change_while_reading

    result = core.process_next_onscreen_subtitle()

    assert refused and (result.video_id, result.state) == (first, "completed")
    assert [len(s.lines) for s in core.onscreen_subtitles(first)] == [2, 2, 2]


def test_an_outdated_single_episode_change_does_not_discard_a_reading_in_progress(setup_single):
    core, media, video = setup_single
    refused = []

    def delete_while_reading(index):
        if index == 5 and not refused:
            band = core.onscreen_subtitle_regions(video)[0]
            with pytest.raises(OnScreenRegionChanged) as changed:
                core.delete_onscreen_subtitle_region(band.id, expected_reviewed_line_count=0)
            refused.append(changed.value)
    media.hook = delete_while_reading

    result = core.process_next_onscreen_subtitle()

    assert refused and result.state == "completed"
    assert [len(s.lines) for s in core.onscreen_subtitles(video)] == [2, 2]


@pytest.fixture
def setup_single(series):
    """시리즈 밖 영상 하나: 아래 띠는 읽고 한 줄 검수했고, 위 모서리는 새로 더해 읽기를 기다린다."""
    core, media, _, _, other = series
    core.add_onscreen_subtitle_region(other, BAND, "en")
    read_all(core)
    review(core, other)
    core.add_onscreen_subtitle_region(other, CORNER, "en")
    return core, media, other


def test_impact_names_the_change_it_will_make(series):
    core, _, _, (first, second, third), _ = series
    core.add_onscreen_subtitle_region(third, CORNER, "en")
    assert core.onscreen_subtitle_region_series_impact(first).change == "replace"
    apply_and_read(core, first)
    region = core.onscreen_subtitle_regions(first)[0]
    assert core.onscreen_subtitle_region_series_impact(first).change == "add"
    assert core.onscreen_subtitle_region_series_impact(first, region.id).change == "update"
    assert core.onscreen_subtitle_region_series_impact(first, region.id, delete=True).change == "delete"
    assert core.onscreen_subtitle_region_series_impact(third).change == "replace"


def test_a_series_change_whose_kind_changed_is_refused(series):
    """확인 창이 본 뒤 시리즈에서 온 화가 직접 정함이 되면, 더하기가 바꾸기로 바뀌어 다시 확인받는다."""
    core, _, _, (first, second, third), _ = series
    apply_and_read(core, first)
    seen = core.onscreen_subtitle_region_series_impact(second)
    assert seen.change == "add"
    band = core.onscreen_subtitle_regions(second)[0]
    core.update_onscreen_subtitle_region(band.id, band.rect, band.language, mode=RegionEdit.REBUILD)  # 2화만 고쳐 직접 정함이 된다
    before = everything(core, (first, second, third))
    with pytest.raises(OnScreenSeriesChanged) as changed:
        core.add_onscreen_subtitle_region(second, CORNER, "en", series=True, expected_series_impact=seen)
    assert changed.value.impact.change == "replace"
    assert everything(core, (first, second, third)) == before
