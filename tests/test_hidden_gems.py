from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.viewing import ViewingSettings


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


def ids(core):
    return [g.video.id for g in core.hidden_gems()]


@pytest.mark.parametrize("days, expected", [(29, False), (30, True), (31, True)])
@pytest.mark.parametrize("glance", [False, True])
def test_unwatched_boundary_and_glance(library, days, expected, glance):
    core, clock, add = library
    video = add("오래된 영상")
    if glance:
        watch(core, video, 4)
    clock.days(days)
    assert (ids(core) == [video.id]) == expected
    if expected:
        assert core.hidden_gems()[0].criterion == "unwatched"


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
    assert "78%" in core.hidden_gems()[0].reason
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
    gems = core.hidden_gems()
    assert [g.video.id for g in gems] == [abandoned.id, revisit.id, both.id, tag_old.id, tag_new.id, old.id]
    assert [g.criterion for g in gems] == ["abandoned", "revisit", "similar_tags", "similar_tags", "similar_tags", "unwatched"]
    assert "과학" in gems[2].reason and "우주" in gems[2].reason


def test_similar_tags_requires_favorite_video_tags_and_no_meaningful_viewing(library):
    core, _, add = library
    favorite, target = add("즐겨 보는 영상"), add("대상")
    core.add_video_tag(favorite.id, "공유")
    core.add_video_tag(target.id, "공유")
    watch(core, favorite)
    assert ids(core) == []
    watch(core, favorite)
    assert ids(core) == [target.id]
    watch(core, target, 4)
    assert core.hidden_gems()[0].criterion == "similar_tags"
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


def test_series_first_unfinished_and_no_fallback_when_ineligible_or_dismissed(library):
    core, clock, add = library
    a, b, c = add("첫 화"), add("둘째 화"), add("셋째 화")
    core.create_series("직접 정한 순서", (a.id, b.id, c.id))
    watch(core, b, 40)
    assert ids(core) == []  # a가 아직 어떤 기준에도 걸리지 않아 b를 추천하지 않음
    clock.days(30)
    assert ids(core) == [a.id]
    core.dismiss_video(a.id)
    assert ids(core) == []
    watch(core, a)
    assert ids(core) == [b.id]
    watch(core, b)
    assert ids(core) == [c.id]
    watch(core, c)
    assert ids(core) == []


def test_series_skips_missing_excluded_but_respects_restoration(library):
    core, clock, add = library
    a, b, c = add("없는 화"), add("제외 화"), add("남은 화")
    core.create_series("시리즈", (a.id, b.id, c.id))
    core.exclude_video(b.id)
    a.locations[0].path.unlink()
    core.scan()
    clock.days(30)
    assert ids(core) == [c.id]
    core.restore_video(b.id)
    assert ids(core) == [b.id]
    a.locations[0].path.write_bytes(a.title.encode())
    core.scan()
    assert ids(core) == [a.id]


def test_dismissal_persists_is_independent_of_library_and_restores(library):
    core, clock, add = library
    video = add("관심 없음")
    clock.days(30)
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


def test_limit_oldest_first_and_nonseries_exclusions(library):
    core, clock, add = library
    videos = []
    for i in range(15):
        videos.append(add(f"독립영상{chr(65 + i)}"))
        clock.days(1)
    core.exclude_video(videos[0].id)
    videos[1].locations[0].path.unlink()
    core.scan()
    core.dismiss_video(videos[2].id)
    clock.days(30)
    assert ids(core) == [v.id for v in videos[3:13]]


def test_settings_persist_and_use_injected_clock(library):
    core, clock, add = library
    a, b = add("안 본 영상"), add("다 본 영상")
    watch(core, b)
    mark(core, b)
    core.settings.set("recommend.unwatched_days", 2)
    core.settings.set("recommend.revisit_days", 4)
    core = AppCore(media=Media(), clock=clock, database=core.database)
    clock.days(2)
    assert ids(core) == [a.id]
    clock.days(2)
    assert ids(core) == [b.id, a.id]


@pytest.mark.parametrize("value", [-1, True, "30", None, float("inf"), float("nan")])
def test_invalid_period_rejected(library, value):
    core, _, _ = library
    core.settings.set("recommend.revisit_days", value)
    with pytest.raises(ValueError):
        core.hidden_gems()


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
    assert [(g.video.id, g.criterion) for g in core.hidden_gems()] == [(b.id, "revisit")]
    core.start_reel(highlight_id=core.highlights(b.id)[0].id)
    core.playback.report(13)
    core.playback.end()
    # 같은 기준 시각이면 영상 ID 순으로 한 편만 남는다.
    assert ids(core) == [a.id]


@pytest.mark.parametrize("normal", ["abandoned", "similar_tags", "unwatched"])
def test_series_allows_first_unfinished_plus_one_finished_revisit(library, normal):
    core, clock, add = library
    finished, first, later = add("다 본 강의"), add("첫 미완료"), add("뒤 미완료")
    core.create_series("강의", (finished.id, first.id, later.id))
    watch(core, finished)
    watch(core, finished)  # 태그 기준의 즐겨 보는 영상
    mark(core, finished)
    watch(core, later, 40)  # 뒤 미완료 화의 일반 기준은 적용하지 않는다.
    if normal == "abandoned":
        watch(core, first, 20)
    elif normal == "similar_tags":
        core.add_video_tag(finished.id, "주제")
        core.add_video_tag(first.id, "주제")
    clock.days(30)
    expected = [(finished.id, "revisit"), (first.id, normal)]
    if normal == "abandoned":
        expected.reverse()
    assert [(g.video.id, g.criterion) for g in core.hidden_gems()] == expected


def test_series_same_first_unfinished_and_oldest_revisit_is_not_duplicated(library):
    core, clock, add = library
    first, later = add("첫 미완료"), add("뒤 강의")
    core.create_series("강의", (first.id, later.id))
    watch(core, first, 40)
    mark(core, first)
    clock.days(1)
    watch(core, later)
    mark(core, later)
    clock.days(30)
    # 가장 오래 밀린 복습이 보다 만 기준으로 나와도 뒤 화로 복습 자리를 채우지 않는다.
    assert [(g.video.id, g.criterion) for g in core.hidden_gems()] == [(first.id, "abandoned")]


def test_series_later_abandoned_can_only_appear_for_revisit(library):
    core, clock, add = library
    first, later = add("첫 미완료"), add("뒤 미완료")
    core.create_series("강의", (first.id, later.id))
    watch(core, later, 40)
    mark(core, later)
    core.settings.set("recommend.unwatched_days", 100)
    clock.days(30)
    assert [(g.video.id, g.criterion) for g in core.hidden_gems()] == [(later.id, "revisit")]
    core.dismiss_video(first.id)  # 일반 후보 관심 없음도 복습 예외를 막지 않는다.
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


def test_series_revisit_exceptions_still_share_ten_item_limit(library):
    core, clock, add = library
    for letter in "ABCDEF":
        finished, first = add(letter + "다 본 강의"), add(letter + "미완료")
        core.create_series(letter, (finished.id, first.id))
        watch(core, finished)
        mark(core, finished)
        watch(core, first, 40)
    clock.days(30)
    gems = core.hidden_gems()
    assert len(gems) == len({g.video.id for g in gems}) == 10
    assert [g.criterion for g in gems] == ["abandoned"] * 6 + ["revisit"] * 4


@pytest.mark.parametrize("state, expected", [("excluded", False), ("missing", True), ("dismissed", True)])
def test_favorite_tag_evidence_excludes_only_excluded_videos(library, state, expected):
    core, _, add = library
    favorite, target = add("즐겨 보는 영상"), add("대상")
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
    clock.days(30)
    snapshot = core.library_snapshot()
    assert snapshot.videos == core.videos()
    assert snapshot.statuses == core.viewing_status_map()
    assert snapshot.tags == core.video_tags_map()
    assert snapshot.series == core.series()
    assert core.hidden_gems(snapshot=snapshot) == core.hidden_gems()
    # 이후 시청은 기존 스냅숏에 섞이지 않고 새 갱신에서 반영된다.
    watch(core, b)
    assert b.id in [g.video.id for g in core.hidden_gems(snapshot=snapshot)]
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
    assert [(g.video.id, g.criterion) for g in core.hidden_gems()] == [(1, "revisit")]
    clock.days(1)
    core = AppCore(media=Media(), clock=clock, database=database)
    assert ids(core) == [1]
