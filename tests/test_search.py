from datetime import datetime, timezone
import unicodedata

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Transcriber:
    result = TranscriberResult("ko", (
        TranscriptSegment(12.25, 15, "체중이동을 연습하세요"),
        TranscriptSegment(42.5, 45, 'Hello WORLD: 100%_ "quoted"'),
        TranscriptSegment(60, 63, "체중 이동은 천천히"),
    ))

    def transcribe(self, path, spoken_language, *, cancellation):
        return self.result


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "야구 Lesson.mkv").write_bytes(b"one")
    (folder / "other.mp4").write_bytes(b"two")
    transcriber = Transcriber()
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=transcriber)
    core.add_watched_folder(folder)
    core.scan()
    video = next(v for v in core.videos() if v.title == "야구 Lesson")
    core.request_subtitles(video.id)
    assert core.process_next_subtitle().state == "completed"
    return core, video, transcriber


def note(core, video_id, text, start=25):
    core.switch_to(video_id, start=start)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    highlight = core.highlights(video_id)[-1]
    core.playback.end()
    return core.update_highlight(highlight.id, start=start, end=None, note=text)


def test_title_and_filename_include_extension_and_all_locations(library, tmp_path):
    core, video, _ = library
    copy = tmp_path / "videos" / "복사본.MKV"
    copy.write_bytes(b"one")
    core.scan()
    assert {(r.video_id, r.source) for r in core.search("LESSON")} == {
        (video.id, "title"), (video.id, "filename")}
    assert [(r.video_id, r.text, r.start) for r in core.search("복사본.mkv")] == [
        (video.id, "복사본.MKV", None)]
    assert core.search("videos") == ()  # 디렉터리 이름은 파일 이름이 아니다.


def test_video_and_highlight_tags_rename_detach_and_delete(library):
    core, video, _ = library
    h = note(core, video.id, "연습")
    tag = core.add_video_tag(video.id, "태그 검색")
    core.add_highlight_tag(h.id, "태그 검색")
    assert [(r.video_id, r.source, r.start) for r in core.search("태그검색")] == [(video.id, "tag", None)]
    core.remove_video_tag(video.id, tag.id)
    assert len(core.search("태그검색")) == 1
    core.rename_tag(tag.id, "새이름")
    assert core.search("태그검색") == ()
    assert core.search("새이름")[0].text == "새이름"
    core.remove_highlight_tag(h.id, tag.id)
    assert core.search("새이름") == ()
    core.add_highlight_tag(h.id, "새이름")
    core.delete_tag(tag.id)
    assert core.search("새이름") == ()


def test_note_edit_time_change_and_delete_are_immediate(library):
    core, video, _ = library
    h = note(core, video.id, "메모 부분검색")
    result, = core.search("부분 검색")
    assert (result.video_id, result.source, result.start, result.text) == (video.id, "note", 25, "메모 부분검색")
    core.update_highlight(h.id, start=33.5, end=40, note="바뀐 메모")
    assert core.search("부분검색") == ()
    assert core.search("바뀐메모")[0].start == 33.5
    core.delete_highlight(h.id)
    assert core.search("바뀐메모") == ()


@pytest.mark.parametrize("query", ["체중 이동", "체중이동", "체중", "이동", "중", unicodedata.normalize("NFD", "체중")])
def test_korean_substrings_and_short_queries(library, query):
    core, video, _ = library
    results = core.search(query)
    assert [(r.video_id, r.title, r.source, r.start) for r in results] == [
        (video.id, video.title, "transcript", 12.25), (video.id, video.title, "transcript", 60)]
    assert results[0].text == "체중이동을 연습하세요"


@pytest.mark.parametrize("query", ["hello world", "WORLD", "OR", "100%_", '"quoted"', "%_", '"', "_"])
def test_english_case_and_punctuation_are_literal(library, query):
    core, video, _ = library
    results = core.search(query)
    assert len(results) == 1
    assert (results[0].video_id, results[0].start) == (video.id, 42.5)


@pytest.mark.parametrize("query", ["", " \t\n", "존재하지않는문장", "NOT", '" OR *'])
def test_empty_or_unmatched_query_has_no_results(library, query):
    core, _, _ = library
    assert core.search(query) == ()


def test_subtitle_regeneration_removes_old_lines_and_reopen_preserves_results(library):
    core, video, adapter = library
    note(core, video.id, "저장된 메모")
    adapter.result = TranscriberResult("en", (TranscriptSegment(5.5, 8, "Replacement line"),))
    core.request_subtitles(video.id)
    assert core.process_next_subtitle().state == "completed"
    assert core.search("체중") == ()
    result, = core.search("replacement")
    assert (result.start, result.text, result.source) == (5.5, "Replacement line", "transcript")
    reopened = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database)
    assert reopened.search("replacement") == (result,)
    assert reopened.search("저장된메모") == core.search("저장된메모")


@pytest.mark.parametrize("query, expected", [("체중", 12.25), ("나의메모", 25), ("LESSON", 47), ("야구태그", 47)])
def test_scene_results_start_exactly_and_other_results_resume(library, query, expected):
    core, video, _ = library
    note(core, video.id, "나의 메모")
    core.add_video_tag(video.id, "야구태그")
    core.switch_to(video.id, start=0)
    core.playback.report(50)
    core.playback.end()
    result = core.search(query)[0]
    assert core.switch_to(result.video_id, start=result.start) == expected
    assert core.playback.position == expected
    core.playback.report(expected + 1)
    core.playback.end()
    assert core.viewings(video.id)[-1].played_seconds == 1


def test_scene_switch_closes_previous_viewing_and_open_highlight(library):
    core, video, _ = library
    other = next(v for v in core.videos() if v.id != video.id)
    core.switch_to(other.id, start=10)
    core.execute_highlight_command(Command(CommandType.RANGE_HIGHLIGHT))
    core.playback.report(20)
    result = core.search("체중")[0]
    core.switch_to(result.video_id, start=result.start)
    assert core.highlights(other.id)[0].end == 20
    assert core.viewings(other.id)[0].last_position == 20
    assert core.playback.session.video_id == video.id


@pytest.mark.parametrize("start", [-1, 101, float("nan"), float("inf")])
def test_invalid_scene_time_does_not_interrupt_current_playback(library, start):
    core, video, _ = library
    core.switch_to(video.id, start=10)
    with pytest.raises(ValueError):
        core.switch_to(video.id, start=start)
    assert core.playback.position == 10


def test_zero_scene_time_overrides_resume(library):
    core, video, _ = library
    core.switch_to(video.id)
    core.playback.report(50)
    core.playback.end()
    assert core.switch_to(video.id, start=0) == 0
