from datetime import datetime, timezone
import random

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.random_pick import choose_video_id


class FakeMedia:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


def make_core(database):
    return AppCore(media=FakeMedia(), clock=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc),
                   database=database)


@pytest.fixture
def core(tmp_path):
    core = make_core(tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    for name in ("a", "b", "c", "d"):
        (folder / f"{name}.mkv").write_bytes(name.encode())
    core.add_watched_folder(folder)
    assert core.scan().added == 4
    return core


class FixedChoice:
    """선택 어댑터에 전달된 공개 입력도 확인해 후보 누락을 잡는다."""
    def __init__(self, expected, selected):
        self.expected = set(expected)
        self.selected = selected

    def __call__(self, candidates):
        assert len(candidates) == len(self.expected)
        assert set(candidates) == self.expected
        return self.selected


def test_all_videos_are_candidates_and_selection_does_not_play(core):
    ids = tuple(video.id for video in core.videos())
    assert core.random_video_count() == 4
    assert core.pick_random_video(choice=FixedChoice(ids, ids[-1])) == ids[-1]
    assert core.playback.session is None
    assert all(core.viewings(video_id) == () for video_id in ids)


def test_result_ids_ignore_unknowns_duplicates_and_input_order(core):
    a, b, c, d = (video.id for video in core.videos())
    scope = [d, b, d, 999999]
    assert core.random_video_count(video_ids=iter(scope)) == 2
    assert core.pick_random_video(video_ids=iter(scope), choice=FixedChoice([b, d], d)) == d


def test_tag_or_counts_each_video_once_and_ignores_highlight_tags(core):
    a, b, c, d = (video.id for video in core.videos())
    red = core.add_video_tag(a, "red")
    core.add_video_tag(b, "red")
    blue = core.add_video_tag(b, "blue")
    core.add_video_tag(c, "blue")
    core.playback.start(d, 10)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    core.add_highlight_tag(core.highlights(d)[0].id, "red")
    tags = [red.id, blue.id, red.id, 999999]
    assert core.random_video_count(tag_ids=iter(tags)) == 3
    assert core.pick_random_video(tag_ids=iter(tags), choice=FixedChoice([a, b, c], c)) == c
    assert core.random_video_count(tag_ids=[red.id]) == 2


@pytest.mark.parametrize("scope_kind", ["all", "results", "tags"])
def test_missing_and_excluded_are_out_but_finished_is_in(core, scope_kind):
    missing, excluded, finished, unwatched = core.videos()
    tag = core.create_tag("all")
    for video in core.videos():
        core.add_video_tag(video.id, tag.name)
    missing.locations[0].path.unlink()
    core.scan()
    core.exclude_video(excluded.id)
    core.playback.start(finished.id, 0)
    core.playback.report(95)
    core.playback.end()
    assert core.video(missing.id).missing
    assert core.viewing_status(finished.id).finished
    scope = {"all": {}, "results": {"video_ids": [missing.id, excluded.id, finished.id, unwatched.id]},
             "tags": {"tag_ids": [tag.id]}}[scope_kind]
    assert core.random_video_count(**scope) == 2
    assert core.pick_random_video(**scope, choice=FixedChoice([finished.id, unwatched.id], finished.id)) == finished.id


def test_previous_selection_is_shared_across_scopes_and_count_does_not_change_it(core):
    a, b, c, d = (video.id for video in core.videos())
    tag = core.add_video_tag(a, "pair")
    core.add_video_tag(b, "pair")
    assert core.pick_random_video(video_ids=[a, b], choice=FixedChoice([a, b], a)) == a
    assert core.random_video_count(tag_ids=[tag.id]) == 2
    assert core.pick_random_video(tag_ids=[tag.id], choice=FixedChoice([b], b)) == b
    assert core.random_video_count() == 4
    assert core.pick_random_video(choice=FixedChoice([a, c, d], c)) == c
    assert core.pick_random_video(video_ids=[a, b], choice=FixedChoice([a, b], a)) == a


def test_single_candidate_can_repeat(core):
    video_id = core.videos()[0].id
    for _ in range(2):
        assert core.pick_random_video(video_ids=[video_id, video_id],
                                      choice=FixedChoice([video_id], video_id)) == video_id
        assert core.random_video_count(video_ids=[video_id]) == 1


@pytest.mark.parametrize("scope", [{"video_ids": []}, {"tag_ids": []},
                                  {"video_ids": [999999]}, {"tag_ids": [999999]}])
def test_empty_scope_returns_none_without_resetting_previous(core, scope):
    a, b = (video.id for video in core.videos()[:2])
    assert core.pick_random_video(video_ids=[a]) == a
    assert core.random_video_count(**scope) == 0
    assert core.pick_random_video(**scope, choice=lambda _: pytest.fail("빈 후보의 난수 호출")) is None
    assert core.pick_random_video(video_ids=[a, b], choice=FixedChoice([b], b)) == b


def test_empty_library(tmp_path):
    core = make_core(tmp_path / "library.sqlite3")
    assert core.random_video_count() == 0
    assert core.pick_random_video() is None


def test_unused_and_highlight_only_tags_have_no_candidates(core):
    unused = core.create_tag("unused")
    video = core.videos()[0]
    core.playback.start(video.id, 10)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    highlight_only = core.add_highlight_tag(core.highlights(video.id)[0].id, "highlight only")
    assert core.random_video_count(tag_ids=[unused.id, highlight_only.id]) == 0
    assert core.pick_random_video(tag_ids=[unused.id, highlight_only.id]) is None


@pytest.mark.parametrize("method", ["pick_random_video", "random_video_count"])
def test_simultaneous_scopes_are_rejected(core, method):
    with pytest.raises(ValueError):
        getattr(core, method)(video_ids=[], tag_ids=[])


def test_previous_selection_is_local_to_core_and_not_persisted(core):
    ids = [video.id for video in core.videos()]
    assert core.pick_random_video(choice=FixedChoice(ids, ids[0])) == ids[0]
    reopened = make_core(core.database)
    assert reopened.pick_random_video(choice=FixedChoice(ids, ids[0])) == ids[0]
    assert core.pick_random_video(choice=FixedChoice(ids[1:], ids[1])) == ids[1]


def test_regular_playback_does_not_change_random_history_or_get_interrupted(core):
    a, b, c, d = (video.id for video in core.videos())
    core.pick_random_video(video_ids=[a])
    core.switch_to(b)
    session = core.playback.session
    assert core.pick_random_video(choice=FixedChoice([b, c, d], b)) == b
    assert core.playback.session is session
    core.playback.end()


def test_changed_library_and_tag_membership_are_reflected(core):
    a, b = core.videos()[:2]
    tag = core.add_video_tag(a.id, "changing")
    assert core.random_video_count(tag_ids=[tag.id]) == 1
    core.remove_video_tag(a.id, tag.id)
    core.add_video_tag(b.id, tag.name)
    assert core.pick_random_video(tag_ids=[tag.id]) == b.id
    core.exclude_video(b.id)
    assert core.random_video_count(tag_ids=[tag.id]) == 0
    assert core.pick_random_video(tag_ids=[tag.id]) is None
    core.restore_video(b.id)
    assert core.pick_random_video(tag_ids=[tag.id]) == b.id
    core.delete_tag(tag.id)
    assert core.random_video_count(tag_ids=[tag.id]) == 0


@pytest.mark.parametrize("invalid_result", [False, True])
def test_adapter_failure_preserves_previous_selection(core, invalid_result):
    a, b = (video.id for video in core.videos()[:2])
    core.pick_random_video(video_ids=[a])

    def failing_choice(candidates):
        if invalid_result:
            return 999999
        raise RuntimeError("난수 어댑터 실패")

    with pytest.raises(ValueError if invalid_result else RuntimeError):
        core.pick_random_video(video_ids=[a, b], choice=failing_choice)
    assert core.pick_random_video(video_ids=[a, b], choice=FixedChoice([b], b)) == b


def test_seeded_random_adapter_and_injected_previous_choice():
    expected = random.Random(198).choice((10, 30))
    assert choose_video_id((10, 20, 30), previous_video_id=20,
                           choice=random.Random(198).choice) == expected


def test_selected_abandoned_video_keeps_existing_resume_position(core):
    video_id = core.videos()[0].id
    core.playback.start(video_id, 0)
    core.playback.report(40)
    core.playback.end()
    assert core.viewing_status(video_id).abandoned
    assert core.pick_random_video(video_ids=[video_id]) == video_id
    assert core.playback.session is None
    assert core.resume_start(video_id) == 37
