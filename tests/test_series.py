from datetime import datetime, timezone
import shutil

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.series import normalize_series_title, series_filename


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


@pytest.fixture
def core(tmp_path):
    return AppCore(media=Media(), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3")


def add(core, folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(str(folder / name).encode())
    core.add_watched_folder(folder)
    core.scan()
    return {v.title: v.id for v in core.videos()}


@pytest.mark.parametrize("filename, expected", [
    ("파이썬 01강.mkv", ("파이썬", (1, 1))),
    ("드라마 1화.mp4", ("드라마", (1, 1))),
    ("드라마 03회.mp4", ("드라마", (1, 3))),
    ("Drama.E01.1080p.H264.mkv", ("drama", (1, 1))),
    ("Drama_s01e02_[HEVC].mkv", ("drama", (1, 2))),
    ("Drama S02E01 [2160p x265].mkv", ("drama", (2, 1))),
    ("Lecture Part 3.mp4", ("lecture", (1, 3))),
    ("Lecture EP 003.mp4", ("lecture", (1, 3))),
    ("Lecture Episode 3.mp4", ("lecture", (1, 3))),
    ("Lecture_003.mp4", ("", (1, 3))),
    ("01 - 강의.mp4", ("", (1, 1))),
    ("01.mp4", ("", (1, 1))),
    ("강의 ０２강.mp4", ("강의", (1, 2))),
    ("Movie 2026.mkv", None), ("Movie 1080p.mkv", None),
    ("H264 소개.mp4", None), ("intro.mp4", None),
    ("3D 영상.mp4", None), ("Lesson2.mp4", None),
    ("Show 1 2.mkv", None), ("Show E01-E02.mkv", None),
    ("Show S00E01.mkv", None), ("Show E00.mkv", None),
    ("Show 01 [E1234567].mkv", ("show", (1, 1))),
    ("Show E01 [E1234567].mkv", ("show", (1, 1))),
    ("Show_01_230416_2026_ABCD1234.mkv", ("show", (1, 1))),
])
def test_filename_number_and_template(filename, expected):
    assert series_filename(filename) == expected


@pytest.mark.parametrize("title", ["Drama_A [1080p] (H.264)", "DRAMA-a_HEVC", "drama   a 4K AV1"])
def test_normalize_title_case_separators_and_technical_labels(title):
    assert normalize_series_title(title) == "drama a"


def test_same_folder_distinct_templates_numeric_order_and_singletons(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E10.mkv", "A E02.mkv", "A E01.mkv",
              "B 2화.mkv", "B 1화.mkv", "intro.mkv", "Single E01.mkv")
    a, b = core.series()
    assert a.video_ids == tuple(ids[name] for name in ("A E01", "A E02", "A E10"))
    assert b.video_ids == (ids["B 1화"], ids["B 2화"])
    assert core.series_for_video(ids["intro"]) is None
    assert core.series_for_video(ids["Single E01"]) is None
    before = core.series()
    core.scan()
    assert core.series() == before


def test_same_template_in_separate_folders_is_not_combined(core, tmp_path):
    add(core, tmp_path / "one", "A E01.mkv")
    add(core, tmp_path / "two", "A E02.mkv")
    assert core.series() == ()
    add(core, tmp_path / "one", "A E03.mkv")
    series, = core.series()
    assert len(series.video_ids) == 2


def test_season_order_and_technical_labels_share_a_template(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Drama S02E01 2160p.mkv", "Drama S01E10 H264.mkv",
              "DRAMA_E02_1080p_HEVC.mkv")
    series, = core.series()
    assert series.video_ids == tuple(ids[name] for name in ("DRAMA_E02_1080p_HEVC", "Drama S01E10 H264", "Drama S02E01 2160p"))


def test_duplicate_numbers_are_omitted_only_within_template(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E01.mkv", "A E01 1080p.mkv", "A E02.mkv", "A E03.mkv",
              "B E01.mkv", "B E02.mkv")
    a, b = core.series()
    assert a.video_ids == (ids["A E02"], ids["A E03"])
    assert b.video_ids == (ids["B E01"], ids["B E02"])
    assert core.series_for_video(ids["A E01"]) is None
    assert core.series_for_video(ids["A E01 1080p"]) is None


def test_new_duplicate_recalculates_untouched_series(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E01.mkv", "A E02.mkv")
    add(core, tmp_path / "shows", "A E01 1080p.mkv")
    assert core.series() == ()
    ids = add(core, tmp_path / "shows", "A E03.mkv")
    assert core.series()[0].video_ids == (ids["A E02"], ids["A E03"])


def test_new_episode_extends_untouched_series_in_numeric_order_with_same_id(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E01.mkv", "A E10.mkv")
    before, = core.series()
    ids = add(core, tmp_path / "shows", "A E02.mkv")
    after, = core.series()
    assert after.id == before.id
    assert after.video_ids == (ids["A E01"], ids["A E02"], ids["A E10"])


def test_late_duplicate_preserves_user_choices_but_recalculates_automatic_additions(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E01.mkv", "A E02.mkv")
    series, = core.series()
    core.update_series(series.id, name=series.name, video_ids=tuple(reversed(series.video_ids)))
    add(core, tmp_path / "shows", "A E03.mkv")
    assert len(core.series()[0].video_ids) == 3
    add(core, tmp_path / "shows", "A E03 1080p.mkv", "A E01 1080p.mkv")
    assert core.series()[0].video_ids == (ids["A E02"], ids["A E01"])


def test_copies_use_casefolded_first_location_not_registration_order(core, tmp_path):
    upper, lower = tmp_path / "Z-original", tmp_path / "a-copy"
    ids = add(core, upper, "Show E01.mkv", "Show E02.mkv")
    lower.mkdir()
    for name in ("Show E01.mkv", "Show E02.mkv"):
        shutil.copyfile(upper / name, lower / name)
    add(core, lower, "Show E03.mkv")
    series, = core.series()
    assert len(series.video_ids) == 3
    assert len(core.videos()) == 3
    assert all(len(v.locations) == 2 for v in core.videos() if v.id in ids.values())
    assert len({vid for s in core.series() for vid in s.video_ids}) == 3


def test_unnumbered_first_location_does_not_use_numbered_copy(core, tmp_path):
    first, other = tmp_path / "a-first", tmp_path / "b-copy"
    ids = add(core, first, "intro.mkv")
    other.mkdir()
    shutil.copyfile(first / "intro.mkv", other / "Show E01.mkv")
    add(core, other, "Show E02.mkv")
    assert core.series() == ()
    assert core.series_for_video(ids["intro"]) is None


def test_edit_preserves_add_remove_order_and_inserts_new_episode_after_predecessor(core, tmp_path):
    folder = tmp_path / "shows"
    ids = add(core, folder, "Show E01.mkv", "Show E02.mkv", "Show E04.mkv", "extra.mkv")
    series, = core.series()
    changed = (ids["Show E04"], ids["extra"], ids["Show E02"])
    core.update_series(series.id, name="내 시리즈", video_ids=changed)
    core.scan()
    assert core.series()[0].video_ids == changed
    assert core.series_for_video(ids["Show E01"]) is None
    ids = add(core, folder, "Show E03.mkv", "Show E05.mkv")
    expected = (ids["Show E04"], ids["Show E05"], ids["extra"], ids["Show E02"], ids["Show E03"])
    assert core.series()[0].video_ids == expected
    reopened = AppCore(media=Media(), clock=lambda: None, database=core.database)
    reopened.scan()
    assert reopened.series() == core.series()
    assert reopened.series()[0].name == "내 시리즈"
    assert reopened.series_for_video(ids["Show E01"]) is None


def test_new_episode_without_predecessor_is_appended_to_edited_order(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Show E02.mkv", "Show E04.mkv")
    series, = core.series()
    core.update_series(series.id, name=series.name, video_ids=(ids["Show E04"], ids["Show E02"]))
    ids = add(core, tmp_path / "shows", "Show E01.mkv")
    assert core.series()[0].video_ids == (ids["Show E04"], ids["Show E02"], ids["Show E01"])


def test_empty_edited_series_survives_and_only_new_episode_returns(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Show E01.mkv", "Show E02.mkv")
    series, = core.series()
    core.update_series(series.id, name=series.name, video_ids=())
    core.scan()
    assert core.series()[0].video_ids == ()
    ids = add(core, tmp_path / "shows", "Show E03.mkv")
    assert core.series()[0].video_ids == (ids["Show E03"],)


def test_manual_series_and_removed_video_do_not_get_automatically_reassigned(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Show E01.mkv", "Show E02.mkv", "extra.mkv")
    series, = core.series()
    core.update_series(series.id, name=series.name, video_ids=(ids["Show E02"],))
    manual = core.create_series("수동", (ids["extra"], ids["Show E01"]))
    core.scan()
    assert core.series_for_video(ids["Show E01"]) == manual
    core.update_series(manual.id, name=manual.name, video_ids=(ids["extra"],))
    core.scan()
    assert core.series_for_video(ids["Show E01"]) is None


def test_invalid_edits_are_atomic(core, tmp_path):
    ids = add(core, tmp_path / "shows", "A E01.mkv", "A E02.mkv", "B E01.mkv", "B E02.mkv")
    a, b = core.series()
    for name, members in [(" ", a.video_ids), ("bad", (9999,)), ("bad", (a.video_ids[0],) * 2), ("bad", b.video_ids)]:
        with pytest.raises(ValueError):
            core.update_series(a.id, name=name, video_ids=members)
        assert core.series() == (a, b)
    with pytest.raises(ValueError, match="시리즈를 찾을"):
        core.update_series(9999, name="없음", video_ids=())


@pytest.mark.parametrize("key, kind", [("PgUp", CommandType.PREVIOUS_VIDEO), ("PgDn", CommandType.NEXT_VIDEO)])
def test_navigation_key_bindings_can_be_replaced(core, key, kind):
    assert core.command_for_key(key) == Command(kind)
    core.set_key_bindings({"Space": Command(kind)})
    assert core.command_for_key(key) is None
    assert core.command_for_key("Space") == Command(kind)


def test_series_navigation_uses_edited_order_and_never_falls_through_at_ends(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Show E01.mkv", "Show E02.mkv", "Show E03.mkv", "extra.mkv")
    series, = core.series()
    order = (ids["Show E03"], ids["Show E01"], ids["Show E02"])
    core.update_series(series.id, name=series.name, video_ids=order)
    visible = (ids["extra"], *reversed(order))
    assert core.adjacent_video(order[0], visible, forward=False) is None
    assert core.adjacent_video(order[0], visible, forward=True) == order[1]
    assert core.adjacent_video(order[1], visible, forward=False) == order[0]
    assert core.adjacent_video(order[2], visible, forward=True) is None
    # 필터에서 보이지 않는 화도 시리즈 순서를 따른다.
    assert core.adjacent_video(order[0], (order[0],), forward=True) == order[1]


def test_nonseries_navigation_uses_exact_visible_order(core, tmp_path):
    ids = add(core, tmp_path / "shows", "one.mkv", "two.mkv", "three.mkv")
    visible = (ids["two"], ids["one"])
    assert core.adjacent_video(ids["two"], visible, forward=True) == ids["one"]
    assert core.adjacent_video(ids["one"], visible, forward=False) == ids["two"]
    assert core.adjacent_video(ids["two"], visible, forward=False) is None
    assert core.adjacent_video(ids["one"], visible, forward=True) is None
    assert core.adjacent_video(ids["three"], visible, forward=True) is None
    assert core.adjacent_video(ids["one"], (), forward=True) is None


def test_navigation_lifecycle_closes_viewing_and_highlight_then_resumes(core, tmp_path):
    ids = add(core, tmp_path / "shows", "Show E01.mkv", "Show E02.mkv")
    first, second = ids["Show E01"], ids["Show E02"]
    core.playback.start(second, 0)
    core.playback.report(40)
    core.playback.end()
    core.playback.start(first, 0)
    core.playback.report(10)
    core.execute_highlight_command(core.command_for_key("Delete"))
    core.playback.report(25)
    target = core.adjacent_video(first, (), forward=True)
    assert core.switch_to(target) == 37
    assert core.playback.position == 37
    assert core.viewings(first)[0].ended_at is not None
    assert core.highlights(first)[0].end == 25
    core.playback.report(100)
    core.playback.end()
    core.playback.start(second, 0)
    core.playback.report(90)
    core.playback.end()
    assert core.switch_to(second) == 0


@pytest.mark.parametrize("edit", ["rename", "remove", "add", "reorder"])
def test_review_early_episode_insertion_distinguishes_order_changes(core, tmp_path, edit):
    folder = tmp_path / "shows"
    ids = add(core, folder, "Show E02.mkv", "Show E03.mkv", "Show E04.mkv", "extra.mkv")
    series, = core.series()
    members = series.video_ids
    if edit == "remove":
        members = members[:-1]
    elif edit == "add":
        members = (*members, ids["extra"])
    elif edit == "reorder":
        members = tuple(reversed(members))
    core.update_series(series.id, name="내 쇼", video_ids=members)
    # 순서 변경 여부는 재시작 후 이름을 한 번 더 바꾸어도 보존된다.
    reopened = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database)
    reopened.update_series(series.id, name="내 쇼 변경", video_ids=members)
    ids = add(reopened, folder, "Show E01.mkv")
    expected = (*members, ids["Show E01"]) if edit == "reorder" else (ids["Show E01"], *members)
    assert reopened.series()[0].video_ids == expected


@pytest.mark.parametrize("names, template, numbers, name", [
    (("1강 오리엔테이션.mp4", "2강 변수.mp4"), "", ((1, 1), (1, 2)), "shows"),
    (("파이썬 강의 1강 - 변수.mp4", "파이썬 강의 2강 - 함수.mp4"), "파이썬 강의", ((1, 1), (1, 2)), "파이썬 강의"),
    (("01. 소개.mp4", "02. 설치.mp4"), "", ((1, 1), (1, 2)), "shows"),
    (("Lecture 01 - Intro.mp4", "Lecture 02 - Basics.mp4"), "", ((1, 1), (1, 2)), "shows"),
    (("런닝맨.E650.230416.720p-NEXT.mp4", "런닝맨.E651.230423.720p-NEXT.mp4"), "런닝맨", ((1, 650), (1, 651)), "런닝맨"),
    (("[SubsPlease] Frieren - 01 (1080p) [ABCD1234].mkv", "[SubsPlease] Frieren - 02 (1080p) [EF015678].mkv"), "frieren", ((1, 1), (1, 2)), "Frieren"),
    (("1주차 1강.mp4", "1주차 2강.mp4", "2주차 1강.mp4"), "", ((1, 1), (1, 2), (2, 1)), "shows"),
    (("드라마 제1화.mp4", "드라마 2화.mp4"), "드라마", ((1, 1), (1, 2)), "드라마"),
    (("Top 5 goals.mp4", "Top 10 goals.mp4"), "top", ((1, 5), (1, 10)), "Top"),
    (("Drama S01E01 1080p.mkv", "Drama S01E02 1080p.mkv"), "drama", ((1, 1), (1, 2)), "Drama"),
    (("Show 01 2026 230416 1080p [00123456] (Group 7).mkv", "Show 02 2026 230423 720p [1234ABCD] (Group 8).mkv"), "show", ((1, 1), (1, 2)), "Show"),
])
def test_review_filename_examples_group_in_number_order(core, tmp_path, names, template, numbers, name):
    for filename, number in zip(names, numbers):
        assert series_filename(filename) == (template, number)
    ids = add(core, tmp_path / "shows", *reversed(names))
    series, = core.series()
    assert series.video_ids == tuple(ids[filename.rsplit(".", 1)[0]] for filename in names)
    assert series.name == name


def test_review_multiple_episode_filename_is_excluded(core, tmp_path):
    assert series_filename("Show.S01E01E02.mkv") is None
    add(core, tmp_path / "shows", "Show.S01E01E02.mkv", "Show S01E03.mkv")
    assert core.series() == ()


def test_switch_to_same_video_finishes_before_computing_resume(core, tmp_path):
    ids = add(core, tmp_path / "shows", "first.mkv")
    video_id = ids["first"]
    core.switch_to(video_id)
    core.playback.report(40)
    assert core.switch_to(video_id) == 37
    first, second = core.viewings(video_id)
    assert first.ended_at is not None and first.last_position == 40
    assert second.ended_at is None and second.last_position == 37


def test_switch_to_delivers_end_before_start_and_preserves_target_subtitles(tmp_path):
    from my_video_manager.subtitles import TranscriberResult, TranscriptSegment

    class Transcriber:
        def transcribe(self, path, spoken_language, *, cancellation):
            return TranscriberResult("ko", (TranscriptSegment(0, 90, path.stem),))

    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   transcriber=Transcriber(), database=tmp_path / "data/library.sqlite3")
    ids = add(core, tmp_path / "shows", "Show E01.mkv", "Show E02.mkv")
    first, second = ids["Show E01"], ids["Show E02"]
    for video_id in (first, second):
        core.request_subtitles(video_id)
        assert core.process_next_subtitle().state == "completed"

    events = []

    class Listener:
        def playback_started(self, session, position):
            events.append(("start", session.video_id, position))

        def playback_position(self, session, position, seeked):
            pass

        def playback_ended(self, session, position):
            events.append(("end", session.video_id, position))

    core.playback.subscribe(Listener())
    core.switch_to(first)
    core.playback.report(12)
    assert core.switch_to(second) == 0
    assert events == [("start", first, 0), ("end", first, 12), ("start", second, 0)]
    assert core.viewings(first)[0].ended_at is not None
    assert "Show E02" in core.playback_subtitle(second).read_text(encoding="utf-8")
    assert "Show E01" in core.playback_subtitle(first).read_text(encoding="utf-8")
    assert core.command_for_key("/") == Command(CommandType.TOGGLE_SUBTITLES)
    assert core.command_for_key("PgDn") == Command(CommandType.NEXT_VIDEO)


@pytest.mark.parametrize("names, grouped", [
    (("01. 소개.mp4", "02. 설치.mp4", "03. 실행.mp4"), True),
    (("12 Angry Men.mkv", "21 Jump Street.mkv"), False),
    (("01 회의 녹화.mp4", "02 가족 여행.mp4"), True),
    (("1 소개.mp4", "3 설치.mp4"), True),
    (("1.mp4", "5.mp4"), False),
    (("2.mp4", "3.mp4"), False),
    (("0 소개.mp4", "1 설치.mp4"), True),
    (("0 소개.mp4", "2 설치.mp4"), True),
    (("0 소개.mp4", "3 설치.mp4"), False),
    (("1.mp4", "3.mp4", "5.mp4"), False),
    (("1강 소개.mp4", "5강 실행.mp4"), True),
    (("E12 소개.mp4", "E21 실행.mp4"), True),
    (("Lecture 12 - Intro.mp4", "Lecture 21 - Basics.mp4"), True),
    (("1주차 1강.mp4", "2주차 1강.mp4"), True),
    (("Movie 12.mkv", "Movie 21.mkv"), True),
])
def test_empty_template_bare_numbers_require_zero_or_one_start_and_at_most_one_gap(core, tmp_path, names, grouped):
    ids = add(core, tmp_path / "shows", *reversed(names))
    if grouped:
        series, = core.series()
        assert series.video_ids == tuple(ids[name.rsplit(".", 1)[0]] for name in names)
    else:
        assert core.series() == ()


@pytest.mark.parametrize("edited", [False, True])
def test_empty_template_gap_on_rescan_preserves_only_user_choices(core, tmp_path, edited):
    folder = tmp_path / "shows"
    ids = add(core, folder, "1.mp4", "2.mp4")
    series, = core.series()
    if edited:
        core.update_series(series.id, name="내 시리즈", video_ids=series.video_ids)
    ids = add(core, folder, "5.mp4")
    if edited:
        assert core.series()[0].video_ids == (ids["1"], ids["2"])
        assert core.series_for_video(ids["5"]) is None
    else:
        assert core.series() == ()
