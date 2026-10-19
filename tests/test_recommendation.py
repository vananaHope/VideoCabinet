from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library import Location, Video
from my_video_manager.recommendation import (
    Recommendation, RecommendationRow, assign_rows, select_recommendations)
from my_video_manager.series import Series
from my_video_manager.viewing import ViewingSettings, ViewingStatus


class Clock:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def days(self, days):
        self.now += timedelta(days=days)


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


@pytest.fixture
def library(tmp_path):
    clock = Clock()
    core = AppCore(media=Media(), clock=clock, database=tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    core.add_watched_folder(folder)

    def add(name):
        path = folder / f"{name}.mkv"
        path.write_bytes(name.encode())
        core.add_file(path)
        return next(v for v in core.videos() if v.title == name)

    return core, clock, add


def watch(core, video, end=90):
    core.playback.start(video.id, 0)
    core.playback.report(end)
    core.playback.end()


def mark(core, video, position=10):
    core.playback.start(video.id, position, record_viewing=False)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    return next(h for h in core.highlights(video.id) if h.start == position)


def items(core):
    return [item for row in core.recommendations() for item in row.items]


def ids(core):
    return [item.video.id for item in items(core)]


def pairs(core):
    return [(item.video.id, row.kind) for row in core.recommendations() for item in row.items]


def candidate(kind, *video_ids):
    return RecommendationRow(kind, kind, tuple(Recommendation(SimpleNamespace(id=vid), f"{kind} 이유") for vid in video_ids))


def placed(rows):
    return [(row.kind, [item.video.id for item in row.items]) for row in rows]


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=31)
FINISHED = ViewingStatus(finished=True)
ABANDONED = ViewingStatus(abandoned=True, stopped_percent=40, last_viewed_at=NOW - timedelta(days=1))


def abandoned(*, days_ago=1):
    return ViewingStatus(abandoned=True, stopped_percent=40,
                         last_viewed_at=NOW - timedelta(days=days_ago))


def series_video(video_id, *, missing=False, excluded=False):
    return Video(video_id, f"{video_id}화", f"지문{video_id}", 100, "matroska", Path(f"{video_id}.png"),
                 OLD, () if missing else (Location(Path(f"{video_id}.mkv")),), excluded)


def select_series(videos, statuses=None, *, order=(1, 2, 3), dismissed=(), revisit_times=None):
    all_statuses = {video.id: ViewingStatus() for video in videos}
    all_statuses.update(statuses or {})
    return select_recommendations(videos, all_statuses, {}, (Series(1, "시리즈", tuple(order)),),
                                  set(dismissed), revisit_times or {}, now=NOW)


def select_rows(videos, statuses=None, *, series=(), dismissed=(), revisit_times=None, **periods):
    states = {video.id: ViewingStatus() for video in videos}
    states.update(statuses or {})
    return select_recommendations(videos, states, {}, series, set(dismissed), revisit_times or {},
                                  now=NOW, **periods)


@pytest.mark.parametrize("offset, kind", [(-1, "continue_watching"), (0, "continue_watching"), (1, "forgotten")])
def test_continue_watching_boundary_transfers_to_forgotten(offset, kind):
    stopped = NOW - timedelta(days=30, microseconds=offset)
    rows = select_rows([series_video(1)], {1: replace(ABANDONED, last_viewed_at=stopped)})
    assert placed(rows) == [(kind, [1])]
    if kind == "continue_watching":
        assert "40%" in rows[0].items[0].reason


@pytest.mark.parametrize("offset, expected", [(-1, []), (0, []), (1, [("forgotten", [1])])])
def test_forgotten_registration_boundary_ignores_glance(offset, expected):
    video = replace(series_video(1), registered_at=NOW - timedelta(days=30, microseconds=offset))
    assert placed(select_rows([video], {1: ViewingStatus(last_viewed_at=NOW)})) == expected


def test_forgotten_sorts_unwatched_and_abandoned_by_their_own_dates():
    videos = [replace(series_video(1), registered_at=NOW - timedelta(days=60)),
              replace(series_video(2), registered_at=NOW - timedelta(days=100)),
              replace(series_video(3), registered_at=NOW - timedelta(days=50)), series_video(4)]
    rows = select_rows(videos, {2: abandoned(days_ago=40), 4: FINISHED})
    assert placed(rows) == [("forgotten", [1, 3, 2])]
    assert "40일" in rows[0].items[-1].reason


def test_continue_watching_sorts_by_latest_stop_and_excludes_finished():
    rows = select_rows([series_video(i) for i in range(1, 5)],
                       {1: abandoned(days_ago=3), 2: abandoned(days_ago=1),
                        3: abandoned(days_ago=1), 4: FINISHED})
    assert placed(rows) == [("continue_watching", [2, 3, 1])]


def test_next_episode_requires_viewing_and_sorts_by_series_latest_viewing():
    videos = [replace(series_video(i), registered_at=NOW) for i in range(1, 14)]
    groups = (Series(1, "가", (1, 2, 3)), Series(2, "나", (4, 5)), Series(3, "다", (6, 7)),
              Series(4, "라", (8, 9)), Series(5, "마", (10, 11)), Series(6, "바", (12, 13)))
    states = {1: replace(FINISHED, last_viewed_at=NOW - timedelta(days=1)),
              2: replace(FINISHED, last_viewed_at=NOW - timedelta(days=5)),
              4: replace(FINISHED, last_viewed_at=NOW - timedelta(days=2)),
              6: ViewingStatus(last_viewed_at=NOW),  # 틀어보기만 한 시리즈는 들어오지 않는다.
              8: replace(FINISHED, last_viewed_at=NOW - timedelta(days=2)),
              11: replace(FINISHED, last_viewed_at=NOW)}  # 마지막 화까지 봤으면 없다.
    assert placed(select_rows(videos, states, series=groups)) == [("next_episode", [3, 5, 9])]


def test_next_episode_ignores_glance_only_episode_when_ranking_series():
    videos = [replace(series_video(i), registered_at=NOW) for i in range(1, 6)]
    states = {1: replace(FINISHED, last_viewed_at=NOW - timedelta(days=3)),
              2: ViewingStatus(last_viewed_at=NOW),
              4: replace(FINISHED, last_viewed_at=NOW - timedelta(days=1))}
    rows = select_rows(videos, states, series=(Series(1, "가", (1, 2, 3)), Series(2, "나", (4, 5))))
    assert placed(rows) == [("next_episode", [5, 2])]


def test_expired_series_abandoned_is_not_an_exception_for_forgotten():
    rows = select_series([series_video(i) for i in range(1, 4)], {2: abandoned(days_ago=31)})
    # 오래된 보다 만 2화는 일반 후보가 아니다. 다음 볼 화인 안 본 3화만 남는다.
    assert placed(rows) == [("forgotten", [3])]


def test_expired_series_abandoned_can_still_be_the_highlight_review_exception():
    rows = select_series([series_video(i) for i in range(1, 4)], {2: abandoned(days_ago=31)},
                         revisit_times={2: OLD})
    assert placed(rows) == [("forgotten", [3]), ("highlight_review", [2])]


@pytest.mark.parametrize("state", ["missing", "excluded", "dismissed"])
@pytest.mark.parametrize("kind", ["continue_watching", "next_episode", "highlight_review", "forgotten"])
def test_each_new_row_excludes_unavailable_or_dismissed_videos(state, kind):
    target = replace(series_video(2), registered_at=NOW if kind == "next_episode" else OLD)
    statuses = {1: replace(FINISHED, last_viewed_at=NOW)}
    if kind == "continue_watching":
        statuses[2] = ABANDONED
    elif kind == "highlight_review":
        statuses[2] = FINISHED
    groups = (Series(1, "시리즈", (1, 2, 3)),) if kind == "next_episode" else ()
    revisits = {2: OLD} if kind == "highlight_review" else {}
    third = replace(series_video(3), registered_at=NOW)
    assert placed(select_rows([series_video(1), target, third], statuses,
                              series=groups, revisit_times=revisits)) == [(kind, [2])]
    target = replace(target, locations=() if state == "missing" else target.locations,
                     excluded=state == "excluded")
    assert select_rows([series_video(1), target, third], statuses, series=groups, revisit_times=revisits,
                       dismissed={2} if state == "dismissed" else set()) == ()


@pytest.mark.parametrize("offset, expected", [(-1, []), (0, [("highlight_review", [1])]),
                                             (1, [("highlight_review", [1])])])
def test_highlight_review_keeps_inclusive_boundary(offset, expected):
    assert placed(select_rows([series_video(1)], {1: FINISHED},
                              revisit_times={1: NOW - timedelta(days=30, microseconds=offset)})) == expected


def test_highlight_review_sorts_oldest_first_with_stable_ties():
    videos = [series_video(i) for i in range(1, 4)]
    rows = select_rows(videos, {i: FINISHED for i in range(1, 4)},
                       revisit_times={1: OLD, 2: NOW - timedelta(days=40), 3: OLD})
    assert placed(rows) == [("highlight_review", [2, 1, 3])]


def test_new_rows_priority_and_overflow_to_next_episode_then_highlight_review():
    # 잊고 있던 영상 상위 20편이 배정되면 21번째 시리즈의 다음 볼 화는 아래 줄로 내려간다.
    videos, states, groups, revisits = [], {}, [], {}
    for index in range(21):
        watched_id, next_id = 2 * index + 1, 2 * index + 2
        videos.extend([series_video(watched_id), series_video(next_id)])
        states[watched_id] = replace(FINISHED, last_viewed_at=NOW)
        groups.append(Series(index + 1, str(index), (watched_id, next_id)))
        revisits[next_id] = OLD
    videos.extend([series_video(43), series_video(44)])
    states.update({43: ABANDONED, 44: FINISHED})
    revisits.update({43: OLD, 44: OLD})
    rows = select_rows(videos, states, series=groups, revisit_times=revisits)
    assert placed(rows) == [("forgotten", list(range(2, 41, 2))), ("continue_watching", [43]),
                            ("next_episode", [42]), ("highlight_review", [44])]


@pytest.mark.parametrize("days, expected", [(9.5, "continue_watching"), (10, "continue_watching"),
                                            (10.5, "forgotten")])
def test_abandoned_transition_uses_continue_period_independent_of_unwatched(days, expected):
    rows = select_rows([series_video(1)], {1: abandoned(days_ago=days)},
                       continue_watching_days=10, unwatched_days=100)
    assert placed(rows) == [(expected, [1])]


def test_short_unwatched_period_does_not_move_recent_abandoned_to_forgotten():
    assert placed(select_rows([series_video(1)], {1: abandoned(days_ago=10)},
                              continue_watching_days=20, unwatched_days=1)) == [("continue_watching", [1])]


@pytest.mark.parametrize("period", [0, 0.5, 365000])
def test_continue_period_supports_zero_fractional_and_maximum_days(period):
    stopped = NOW - timedelta(days=period)
    video = replace(series_video(1), registered_at=stopped)
    status = replace(ABANDONED, last_viewed_at=stopped)
    assert placed(select_rows([video], {1: status}, continue_watching_days=period)) == [("continue_watching", [1])]
    status = replace(status, last_viewed_at=stopped - timedelta(microseconds=1))
    assert placed(select_rows([video], {1: status}, continue_watching_days=period)) == [("forgotten", [1])]


def test_next_episode_core_uses_latest_viewing_including_later_glance(library):
    core, clock, add = library
    a, b, c, d = (add(name) for name in ("가1", "가2", "나1", "나2"))
    core.create_series("가", (a.id, b.id))
    core.create_series("나", (c.id, d.id))
    watch(core, a)
    clock.days(1)
    watch(core, c)
    assert pairs(core) == [(d.id, "next_episode"), (b.id, "next_episode")]
    clock.days(1)
    watch(core, a, 4)
    assert pairs(core) == [(b.id, "next_episode"), (d.id, "next_episode")]


def test_series_candidates_are_only_the_next_episode():
    videos = [series_video(video_id) for video_id in range(1, 6)]
    rows = select_series(videos, {1: FINISHED, 2: FINISHED, 4: FINISHED}, order=(1, 2, 3, 4, 5))
    # 시청한 1·2·4화가 아니라, 가장 뒤 시청 화의 다음 화인 5화만 후보가 된다.
    assert placed(rows) == [("forgotten", [5])]


def test_series_without_viewing_recommends_the_first_episode():
    videos = [series_video(video_id) for video_id in range(1, 4)]
    assert placed(select_series(videos)) == [("forgotten", [1])]


def test_series_with_every_episode_watched_has_no_general_candidate():
    videos = [series_video(video_id) for video_id in range(1, 4)]
    assert select_series(videos, {video.id: FINISHED for video in videos}) == ()


@pytest.mark.parametrize("state", ["missing", "excluded", "dismissed"])
def test_series_does_not_skip_an_ineligible_next_episode(state):
    videos = [series_video(1, missing=state == "missing", excluded=state == "excluded"),
              series_video(2), series_video(3)]
    dismissed = {1} if state == "dismissed" else set()
    assert select_series(videos, dismissed=dismissed) == ()
    assert placed(select_series([series_video(1), *videos[1:]])) == [("forgotten", [1])]


def test_series_abandoned_episode_stays_only_in_the_abandoned_row():
    videos = [series_video(video_id) for video_id in range(1, 4)]
    # 2화가 보다 만 화이므로 다음 볼 화는 3화다. 2화는 보다 만 예외로만 남는다.
    assert placed(select_series(videos, {2: ABANDONED})) == [("forgotten", [3]), ("continue_watching", [2])]


def test_series_abandoned_exception_does_not_restore_general_candidates():
    videos = [series_video(video_id) for video_id in range(1, 4)]
    # 다음 볼 화(3화)가 관심 없음이면 일반 후보는 없지만, 보다 만 2화는 예외로 남는다.
    assert placed(select_series(videos, {2: ABANDONED}, dismissed={3})) == [("continue_watching", [2])]


def test_series_abandoned_exception_keeps_one_most_recent_episode():
    videos = [series_video(video_id) for video_id in range(1, 7)]
    rows = select_series(videos, {1: abandoned(days_ago=5), 3: abandoned(days_ago=2),
                                  5: abandoned(days_ago=1)}, order=(1, 2, 3, 4, 5, 6))
    # 1·3·5화가 모두 보다 만 화지만 가장 최근에 멈춘 5화 한 편만 남고, 다음 볼 화는 6화다.
    assert placed(rows) == [("forgotten", [6]), ("continue_watching", [5])]


def test_series_abandoned_exception_skips_dismissed_before_choosing():
    videos = [series_video(video_id) for video_id in range(1, 7)]
    rows = select_series(videos, {1: abandoned(days_ago=5), 3: abandoned(days_ago=2),
                                  5: abandoned(days_ago=1)}, order=(1, 2, 3, 4, 5, 6),
                         dismissed={5})
    # 가장 최근에 멈춘 5화가 관심 없음이면 그다음으로 최근에 멈춘 3화가 남는다.
    assert placed(rows) == [("forgotten", [6]), ("continue_watching", [3])]


def test_series_abandoned_exception_prefers_earlier_episode_on_tie():
    videos = [series_video(video_id) for video_id in range(1, 5)]
    same_time = abandoned(days_ago=1)
    rows = select_series(videos, {1: same_time, 3: same_time}, order=(1, 2, 3, 4))
    assert placed(rows) == [("forgotten", [4]), ("continue_watching", [1])]


def test_series_abandoned_exception_is_per_series():
    videos = [series_video(video_id) for video_id in range(1, 5)]
    state = {video.id: ViewingStatus() for video in videos}
    state.update({1: abandoned(days_ago=5), 2: abandoned(days_ago=1),
                  3: abandoned(days_ago=5), 4: abandoned(days_ago=1)})
    rows = select_recommendations(videos, state, {}, (Series(1, "가", (1, 2)), Series(2, "나", (3, 4))),
                                  set(), {}, now=NOW)
    # 시리즈마다 한 편씩 남으므로 다른 시리즈의 보다 만 화가 서로를 막지 않는다.
    assert placed(rows) == [("continue_watching", [2, 4])]


def test_series_revisit_exception_keeps_one_oldest_episode_with_next_episode():
    videos = [series_video(video_id) for video_id in range(1, 5)]
    rows = select_series(videos, {1: FINISHED}, order=(1, 2, 3, 4),
                         revisit_times={3: NOW - timedelta(days=31), 4: NOW - timedelta(days=31)})
    # 다음 볼 화는 2화이고, 복습 예외는 가장 오래 밀린 3화 한 편만 남긴다.
    assert placed(rows) == [("forgotten", [2]), ("highlight_review", [3])]


def test_rows_keep_priority_and_each_video_appears_only_in_its_highest_row():
    rows = assign_rows([candidate("위", 1, 2), candidate("가운데", 2, 3), candidate("아래", 3, 1, 4)])
    assert placed(rows) == [("위", [1, 2]), ("가운데", [3]), ("아래", [4])]
    assert rows[0].title == "위" and rows[2].items[0].reason == "아래 이유"


def test_overflow_from_upper_row_moves_down_and_lower_row_refills_to_limit():
    rows = assign_rows([candidate("위", *range(1, 26)), candidate("아래", 21, 3, 22, 30, 31)], limit=20)
    assert placed(rows) == [("위", list(range(1, 21))), ("아래", [21, 22, 30, 31])]
    # 위 줄에 들어간 영상을 먼저 빼고 자르므로 아래 줄도 상한까지 채운다.
    rows = assign_rows([candidate("위", 1, 2), candidate("아래", 1, 2, 3, 4)], limit=2)
    assert placed(rows) == [("위", [1, 2]), ("아래", [3, 4])]


def test_empty_rows_are_hidden_including_rows_emptied_by_upper_rows():
    assert assign_rows([]) == ()
    rows = assign_rows([candidate("빈 줄"), candidate("위", 1), candidate("겹침", 1), candidate("아래", 2)])
    assert placed(rows) == [("위", [1]), ("아래", [2])]


@pytest.mark.parametrize("days, expected", [(29, False), (30, False), (31, True)])
@pytest.mark.parametrize("glance", [False, True])
def test_unwatched_boundary_and_glance(library, days, expected, glance):
    core, clock, add = library
    video = add("오래된 영상")
    if glance:
        watch(core, video, 4)
    clock.days(days)
    assert (ids(core) == [video.id]) == expected
    if expected:
        assert [row.kind for row in core.recommendations()] == ["forgotten"]


@pytest.mark.parametrize("days, expected", [(29, False), (30, True), (31, True)])
@pytest.mark.parametrize("revisited", [False, True])
def test_revisit_boundary(library, days, expected, revisited):
    core, clock, add = library
    video = add("복습 영상")
    watch(core, video)
    highlight = mark(core, video)
    if revisited:
        clock.days(40)
        core.start_reel(highlight_id=highlight.id)
        core.playback.report(13)
        core.playback.end()
        assert core.last_video_revisited_at(video.id) == clock.now
    clock.days(days)
    assert (ids(core) == [video.id]) == expected


def test_new_highlight_resets_revisit_wait_and_edits_do_not(library):
    core, clock, add = library
    video = add("복습 영상")
    watch(core, video)
    first = mark(core, video)
    clock.days(31)
    assert ids(core) == [video.id]
    mark(core, video, 20)
    assert ids(core) == []
    clock.days(30)
    core.update_highlight(first.id, start=11, end=None, note="메모 편집")
    assert ids(core) == [video.id]
    for highlight in core.highlights(video.id):
        core.delete_highlight(highlight.id)
    assert ids(core) == []


def test_abandoned_reason_resume_and_recent_order(library):
    core, clock, add = library
    first, second = add("첫 영상"), add("다음 영상")
    watch(core, first, 40)
    clock.days(1)
    watch(core, second, 20)
    clock.days(1)
    # 틀어보기는 상태를 없애지 않고 마지막 시청 순서와 멈춘 위치를 바꾼다.
    core.playback.start(first.id, 75)
    core.playback.report(78)
    core.playback.end()
    assert ids(core) == [first.id, second.id]
    assert "78%" in items(core)[0].reason
    assert core.switch_to(first.id) == 75
    core.playback.report(0, seeked=True)
    core.playback.report(90)
    assert ids(core) == [second.id]  # 진행 중 다 봄도 즉시 반영
    core.playback.end()


def test_priority_dedup_and_tag_order(library):
    core, clock, add = library
    old = add("오래 시청 없음")
    favorite = add("즐겨 보는 영상")
    watch(core, favorite)
    watch(core, favorite)
    watch(core, favorite)
    core.add_video_tag(favorite.id, "과학")
    core.add_video_tag(favorite.id, "우주")
    abandoned = add("보다 만")
    revisit = add("복습")
    mark(core, abandoned)
    mark(core, revisit)
    watch(core, abandoned, 40)
    tag_old = add("태그 하나 먼저 등록")
    core.add_video_tag(tag_old.id, "과학")
    clock.days(1)
    tag_new = add("태그 하나 나중 등록")
    both = add("태그 둘")
    for video in (abandoned, revisit, tag_new, both):
        core.add_video_tag(video.id, "과학")
    core.add_video_tag(both.id, "우주")
    clock.days(31)
    assert pairs(core) == [(both.id, "similar_tags"), (revisit.id, "similar_tags"),
                           (tag_old.id, "similar_tags"), (tag_new.id, "similar_tags"),
                           (old.id, "forgotten"), (abandoned.id, "forgotten")]
    rows = core.recommendations()
    assert [row.kind for row in rows] == ["similar_tags", "forgotten"]
    assert "과학" in rows[0].items[0].reason and "우주" in rows[0].items[0].reason


def test_similar_tags_requires_favorite_video_tags_and_no_meaningful_viewing(library):
    core, _, add = library
    favorite, target = add("즐겨 보는 영상"), add("대상")
    core.add_video_tag(favorite.id, "공유")
    core.add_video_tag(target.id, "공유")
    watch(core, favorite)
    watch(core, favorite)
    assert ids(core) == []
    watch(core, favorite)
    assert ids(core) == [target.id]
    watch(core, target, 4)
    assert pairs(core) == [(target.id, "similar_tags")]
    watch(core, target, 90)
    assert ids(core) == []
    third = add("하이라이트만 겹침")
    core.add_highlight_tag(mark(core, third).id, "공유")
    assert ids(core) == []


def test_revisit_oldest_first(library):
    core, clock, add = library
    a, b = add("가"), add("나")
    watch(core, a)
    watch(core, b)
    mark(core, b)
    clock.days(1)
    mark(core, a)
    clock.days(31)
    assert ids(core) == [b.id, a.id]


def test_series_uses_next_episode_and_dismissal_does_not_fall_back(library):
    core, clock, add = library
    a, b, c = add("첫 화"), add("둘째 화"), add("셋째 화")
    core.create_series("직접 정한 순서", (a.id, b.id, c.id))
    clock.days(31)
    assert ids(core) == [a.id]  # 시청이 없으면 첫 화가 다음 볼 화
    core.dismiss_video(a.id)
    assert ids(core) == []  # 다음 볼 화가 관심 없음이면 뒤 화로 넘어가지 않는다
    watch(core, b)
    assert ids(core) == [c.id]  # 가장 뒤 시청 화(b)의 다음 화만 일반 후보
    watch(core, a)
    assert ids(core) == [c.id]
    watch(core, c)
    assert ids(core) == []


def test_series_does_not_fall_back_when_next_episode_is_missing_or_excluded(library):
    core, clock, add = library
    a, b, c = add("없는 화"), add("제외 화"), add("남은 화")
    core.create_series("시리즈", (a.id, b.id, c.id))
    core.exclude_video(b.id)
    a.locations[0].path.unlink()
    core.scan()
    clock.days(31)
    assert ids(core) == []  # 다음 볼 화(a)가 파일 없음이면 c로 건너뛰지 않는다
    core.restore_video(b.id)
    assert ids(core) == []
    a.locations[0].path.write_bytes(a.title.encode())
    core.scan()
    assert ids(core) == [a.id]


def test_dismissal_persists_is_independent_of_library_and_restores(library):
    core, clock, add = library
    video = add("관심 없음")
    clock.days(31)
    core.dismiss_video(video.id)
    core.dismiss_video(video.id)
    assert ids(core) == []
    assert [v.id for v in core.videos()] == [video.id]
    core = AppCore(media=Media(), clock=clock, database=core.database)
    assert ids(core) == []
    assert [v.id for v in core.dismissed_videos()] == [video.id]
    core.exclude_video(video.id)
    assert [v.id for v in core.dismissed_videos()] == [video.id]
    core.restore_dismissed_video(video.id)
    assert ids(core) == []
    core.restore_video(video.id)
    assert ids(core) == [video.id]
    assert core.dismissed_videos() == ()
    with pytest.raises(ValueError):
        core.dismiss_video(9999)


def test_row_limit_oldest_first_and_nonseries_exclusions(library):
    core, clock, add = library
    videos = []
    for i in range(26):
        videos.append(add(f"독립영상{chr(65 + i)}"))
        clock.days(1)
    core.exclude_video(videos[0].id)
    videos[1].locations[0].path.unlink()
    core.scan()
    core.dismiss_video(videos[2].id)
    clock.days(30)
    assert ids(core) == [v.id for v in videos[3:23]]


def test_similar_tags_overflow_appears_in_unwatched_row(library):
    core, clock, add = library
    favorite = add("즐겨 보는 영상")
    watch(core, favorite)
    watch(core, favorite)
    watch(core, favorite)
    core.add_video_tag(favorite.id, "주제")
    tagged = []
    for i in range(22):
        tagged.append(add(f"태그 영상{i:02}"))
        core.add_video_tag(tagged[-1].id, "주제")
        clock.days(1)
    plain = add("태그 없는 영상")
    clock.days(31)
    rows = core.recommendations()
    assert [(row.kind, len(row.items)) for row in rows] == [("similar_tags", 20), ("forgotten", 3)]
    assert [i.video.id for i in rows[0].items] == [v.id for v in tagged[:20]]
    # 태그 줄에서 밀려난 두 편은 오래 시청 없음 조건에도 맞아 그 줄에 나온다.
    assert [i.video.id for i in rows[1].items] == [tagged[20].id, tagged[21].id, plain.id]
    core.dismiss_video(tagged[0].id)
    rows = core.recommendations()
    assert tagged[0].id not in ids(core)
    assert [i.video.id for i in rows[0].items] == [v.id for v in tagged[1:21]]
    assert [i.video.id for i in rows[1].items] == [tagged[21].id, plain.id]


def test_settings_persist_and_use_injected_clock(library):
    core, clock, add = library
    a, b, c = add("안 본 영상"), add("다 본 영상"), add("보다 만 영상")
    watch(core, b)
    watch(core, c, 40)
    mark(core, b)
    core.settings.set("recommend.unwatched_days", 2)
    core.settings.set("recommend.revisit_days", 4)
    core.settings.set("recommend.continue_watching_days", 2.5)
    core = AppCore(media=Media(), clock=clock, database=core.database)
    clock.days(2.5)
    assert pairs(core) == [(a.id, "forgotten"), (c.id, "continue_watching")]
    clock.days(1.5)
    assert pairs(core) == [(a.id, "forgotten"), (c.id, "forgotten"), (b.id, "highlight_review")]


@pytest.mark.parametrize("value", [-1, True, "30", None, float("inf"), float("nan")])
@pytest.mark.parametrize("criterion", ["unwatched", "revisit", "continue_watching"])
def test_invalid_period_rejected(library, value, criterion):
    core, _, _ = library
    core.settings.set(f"recommend.{criterion}_days", value)
    with pytest.raises(ValueError):
        core.recommendations()


def test_bulk_status_and_tags_match_single_reads_and_include_empty_and_excluded(library):
    core, clock, add = library
    a, b, c = add("시청 중"), add("태그 있음"), add("제외 영상")
    core.add_video_tag(b.id, "나")
    core.add_video_tag(b.id, "가")
    core.exclude_video(c.id)
    core.playback.start(a.id, 0)
    core.playback.report(40)
    statuses, tags = core.viewing_status_map(), core.video_tags_map()
    assert set(statuses) == set(tags) == {a.id, b.id, c.id}
    for v in (a, b, c):
        assert statuses[v.id] == core.viewing_status(v.id)
        assert tags[v.id] == core.video_tags(v.id)
    assert statuses[a.id].abandoned and statuses[a.id].last_viewed_at == clock.now
    assert tags[a.id] == ()
    core.playback.end()
    core = AppCore(media=Media(), clock=clock, database=core.database,
                   viewing_settings=ViewingSettings(abandoned_ratio=0.5))
    assert not core.viewing_status_map()[a.id].abandoned


def test_finished_series_recommends_only_oldest_overdue_revisit(library):
    core, clock, add = library
    a, b, c = add("첫 강의"), add("둘째 강의"), add("셋째 강의")
    core.create_series("전부 다 본 강의", (a.id, b.id, c.id))
    for video in (a, b, c):
        watch(core, video)
    mark(core, b)
    clock.days(1)
    mark(core, a)
    mark(core, c)
    clock.days(30)
    assert pairs(core) == [(b.id, "highlight_review")]
    core.start_reel(highlight_id=core.highlights(b.id)[0].id)
    core.playback.report(13)
    core.playback.end()
    # 같은 기준 시각이면 영상 ID 순으로 한 편만 남는다.
    assert ids(core) == [a.id]


def test_series_normal_rows_only_apply_to_next_episode_with_revisit_exception(library):
    core, clock, add = library
    finished, next_video, later = add("다 본 강의"), add("다음 볼 화"), add("뒤 화")
    core.create_series("강의", (finished.id, next_video.id, later.id))
    watch(core, finished)
    watch(core, finished)
    watch(core, finished)  # 즐겨 보는 영상
    mark(core, finished)
    for video in (finished, next_video, later):
        core.add_video_tag(video.id, "주제")
    clock.days(30)
    # 다음 볼 화(둘째 화)만 일반 후보가 되고, 뒤 화는 태그가 겹쳐도 나오지 않는다.
    assert pairs(core) == [(next_video.id, "similar_tags"), (finished.id, "highlight_review")]


def test_oldest_revisit_already_shown_as_abandoned_is_not_duplicated(library):
    core, clock, add = library
    first, later = add("보다 만 화"), add("뒤 강의")
    core.create_series("강의", (first.id, later.id))
    watch(core, first, 40)
    mark(core, first)
    clock.days(1)
    watch(core, later)
    mark(core, later)
    clock.days(30)
    watch(core, first, 40)  # 이어 보기 기한 안으로 되돌리고 복습 시각은 유지한다.
    # 가장 오래 밀린 복습이 보다 만 줄로 나오면 복습 자리를 다른 화로 채우지 않는다.
    assert pairs(core) == [(first.id, "continue_watching")]


def test_series_later_abandoned_is_shown_in_the_abandoned_row_only(library):
    core, clock, add = library
    first, later = add("첫 미완료"), add("뒤 보다 만")
    core.create_series("강의", (first.id, later.id))
    watch(core, later, 40)
    mark(core, later)
    core.settings.set("recommend.unwatched_days", 100)
    clock.days(30)
    # 마지막 화까지 시청해 일반 후보는 없지만, 보다 만 화 예외로 그 화만 나온다.
    assert pairs(core) == [(later.id, "continue_watching")]
    core.dismiss_video(first.id)  # 다른 화의 관심 없음은 보다 만 예외를 막지 않는다.
    assert ids(core) == [later.id]


@pytest.mark.parametrize("state", ["missing", "excluded", "dismissed"])
def test_series_revisit_skips_ineligible_overdue_video(library, state):
    core, clock, add = library
    a, b = add("오래 밀린 강의"), add("다음 밀린 강의")
    core.create_series("강의", (a.id, b.id))
    watch(core, a)
    watch(core, b)
    mark(core, a)
    clock.days(1)
    mark(core, b)
    if state == "missing":
        a.locations[0].path.unlink()
        core.scan()
    elif state == "excluded":
        core.exclude_video(a.id)
    else:
        core.dismiss_video(a.id)
    clock.days(30)
    assert ids(core) == [b.id]


def test_series_revisit_exceptions_fill_their_own_row(library):
    core, clock, add = library
    for letter in "ABCDEF":
        finished, first = add(letter + "다 본 강의"), add(letter + "미완료")
        core.create_series(letter, (finished.id, first.id))
        watch(core, finished)
        mark(core, finished)
        watch(core, first, 40)
    clock.days(30)
    assert len(ids(core)) == len(set(ids(core))) == 12
    assert [(row.kind, len(row.items)) for row in core.recommendations()] == [("continue_watching", 6), ("highlight_review", 6)]


@pytest.mark.parametrize("state, expected", [("excluded", False), ("missing", True), ("dismissed", True)])
def test_favorite_tag_evidence_excludes_only_excluded_videos(library, state, expected):
    core, _, add = library
    favorite, target = add("즐겨 보는 영상"), add("대상")
    watch(core, favorite)
    watch(core, favorite)
    watch(core, favorite)
    core.add_video_tag(favorite.id, "주제")
    core.add_video_tag(target.id, "주제")
    if state == "excluded":
        core.exclude_video(favorite.id)
    elif state == "missing":
        favorite.locations[0].path.unlink()
        core.scan()
    else:
        core.dismiss_video(favorite.id)
    assert ids(core) == ([target.id] if expected else [])
    if state == "excluded":
        core.restore_video(favorite.id)
        assert ids(core) == [target.id]


def test_library_snapshot_reuses_public_state_and_preserves_tag_filter_scope(library):
    core, clock, add = library
    a, b, excluded = add("태그 영상"), add("다른 영상"), add("제외 영상")
    core.create_series("시리즈", (excluded.id, a.id))
    core.exclude_video(excluded.id)
    core.add_video_tag(a.id, "주제")
    clock.days(31)
    snapshot = core.library_snapshot()
    assert snapshot.videos == core.videos()
    assert snapshot.statuses == core.viewing_status_map()
    assert snapshot.tags == core.video_tags_map()
    assert snapshot.series == core.series()
    assert core.recommendations(snapshot=snapshot) == core.recommendations()
    # 이후 시청은 기존 스냅숏에 섞이지 않고 새 갱신에서 반영된다.
    watch(core, b)
    assert b.id in [i.video.id for row in core.recommendations(snapshot=snapshot) for i in row.items]
    assert b.id not in ids(core)


def test_legacy_highlight_upgrade_baseline_is_preserved_on_reopen(tmp_path):
    # #14 이전 main의 저장 형식 fixture. 생성 시각 테이블이 없는 DB를 독립적으로 만든다.
    # 검증은 테이블 값이나 private 메서드 대신 AppCore의 추천 결과로만 한다.
    database = tmp_path / "legacy.sqlite3"
    path = tmp_path / "legacy.mkv"
    path.write_bytes(b"legacy")
    old = "2020-01-01T00:00:00+00:00"
    with sqlite3.connect(database) as db:
        db.executescript("""
            PRAGMA user_version = 2;
            CREATE TABLE watched_folders(path TEXT PRIMARY KEY);
            CREATE TABLE videos(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL, duration REAL NOT NULL, format TEXT NOT NULL,
                thumbnail TEXT NOT NULL, registered_at TEXT NOT NULL, excluded INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE locations(path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                size INTEGER, mtime_ns INTEGER);
            CREATE TABLE library_file_checks(path TEXT PRIMARY KEY, size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL, duration REAL, fingerprint TEXT);
            CREATE TABLE highlights(id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                start REAL NOT NULL CHECK(start >= 0), end REAL CHECK(end > start), note TEXT);
            CREATE TABLE viewings(id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                duration REAL NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                ended_at TEXT, intervals TEXT NOT NULL, last_position REAL);
            INSERT INTO highlights VALUES (7, 1, 10, NULL, '기존 하이라이트');
        """)
        db.execute("INSERT INTO videos VALUES (1, 'legacy', '기존 영상', 100, 'matroska', 'old.png', ?, 0)", (old,))
        db.execute("INSERT INTO locations VALUES (?, 1, NULL, NULL)", (str(path),))
        db.execute("INSERT INTO viewings VALUES (1, 1, 100, ?, ?, ?, '[[0, 90]]', 90)", (old, old, old))
    clock = Clock()
    core = AppCore(media=Media(), clock=clock, database=database)
    assert core.highlights(1)[0].note.text == "기존 하이라이트"
    assert ids(core) == []
    clock.days(29)
    core = AppCore(media=Media(), clock=clock, database=database)
    assert ids(core) == []
    clock.days(1)
    assert pairs(core) == [(1, "highlight_review")]
    clock.days(1)
    core = AppCore(media=Media(), clock=clock, database=database)
    assert ids(core) == [1]
