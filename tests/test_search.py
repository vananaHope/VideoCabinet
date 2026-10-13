from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import unicodedata

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine


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
    assert {(r.video_id, r.source) for r in core.search("LESSON").results} == {
        (video.id, "title"), (video.id, "filename")}
    assert [(r.video_id, r.text, r.start) for r in core.search("복사본.mkv").results] == [
        (video.id, "복사본.MKV", None)]
    assert core.search("videos").results == ()  # 디렉터리 이름은 파일 이름이 아니다.


def test_video_and_highlight_tags_rename_detach_and_delete(library):
    core, video, _ = library
    h = note(core, video.id, "연습")
    tag = core.add_video_tag(video.id, "태그 검색")
    core.add_highlight_tag(h.id, "태그 검색")
    assert [(r.video_id, r.source, r.start) for r in core.search("태그검색").results] == [(video.id, "tag", None)]
    core.remove_video_tag(video.id, tag.id)
    assert len(core.search("태그검색").results) == 1
    core.rename_tag(tag.id, "새이름")
    assert core.search("태그검색").results == ()
    assert core.search("새이름").results[0].text == "새이름"
    core.remove_highlight_tag(h.id, tag.id)
    assert core.search("새이름").results == ()
    core.add_highlight_tag(h.id, "새이름")
    core.delete_tag(tag.id)
    assert core.search("새이름").results == ()


def test_note_edit_time_change_and_delete_are_immediate(library):
    core, video, _ = library
    h = note(core, video.id, "메모 부분검색")
    result, = core.search("부분 검색").results
    assert (result.video_id, result.source, result.start, result.text) == (video.id, "note", 25, "메모 부분검색")
    core.update_highlight(h.id, start=33.5, end=40, note="바뀐 메모")
    assert core.search("부분검색").results == ()
    assert core.search("바뀐메모").results[0].start == 33.5
    core.delete_highlight(h.id)
    assert core.search("바뀐메모").results == ()


@pytest.mark.parametrize("query", ["체중 이동", "체중이동", "체중", "이동", "중", unicodedata.normalize("NFD", "체중")])
def test_korean_substrings_and_short_queries(library, query):
    core, video, _ = library
    results = core.search(query).results
    assert [(r.video_id, r.title, r.source, r.start) for r in results] == [
        (video.id, video.title, "transcript", 12.25), (video.id, video.title, "transcript", 60)]
    assert results[0].text == "체중이동을 연습하세요"


@pytest.mark.parametrize("query", ["hello world", "WORLD", "OR", "100%_", '"quoted"', "%_", '"', "_"])
def test_english_case_and_punctuation_are_literal(library, query):
    core, video, _ = library
    results = core.search(query).results
    assert len(results) == 1
    assert (results[0].video_id, results[0].start) == (video.id, 42.5)


@pytest.mark.parametrize("query", ["", " \t\n", "존재하지않는문장", "NOT", '" OR *'])
def test_empty_or_unmatched_query_has_no_results(library, query):
    core, _, _ = library
    assert core.search(query).results == ()


def test_subtitle_regeneration_removes_old_lines_and_reopen_preserves_results(library):
    core, video, adapter = library
    note(core, video.id, "저장된 메모")
    adapter.result = TranscriberResult("en", (TranscriptSegment(5.5, 8, "Replacement line"),))
    core.request_subtitles(video.id)
    assert core.process_next_subtitle().state == "completed"
    assert core.search("체중").results == ()
    result, = core.search("replacement").results
    assert (result.start, result.text, result.source) == (5.5, "Replacement line", "transcript")
    reopened = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database)
    assert reopened.search("replacement").results == (result,)
    assert reopened.search("저장된메모").results == core.search("저장된메모").results


@pytest.mark.parametrize("query, expected", [("체중", 12.25), ("나의메모", 25), ("LESSON", 47), ("야구태그", 47)])
def test_scene_results_start_exactly_and_other_results_resume(library, query, expected):
    core, video, _ = library
    note(core, video.id, "나의 메모")
    core.add_video_tag(video.id, "야구태그")
    core.switch_to(video.id, start=0)
    core.playback.report(50)
    core.playback.end()
    result = core.search(query).results[0]
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
    result = core.search("체중").results[0]
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


@pytest.mark.parametrize("with_translation", [False, True])
@pytest.mark.parametrize("old_search", [False, True])
def test_pre_search_database_backfills_original_and_translation(tmp_path, with_translation, old_search):
    database = tmp_path / "legacy.sqlite3"
    fixtures = Path(__file__).parent / "fixtures"
    with sqlite3.connect(database) as db:
        db.executescript((fixtures / "search_d692c23.sql").read_text(encoding="utf-8"))
        if with_translation:
            db.executescript((fixtures / "search_f81ea11.sql").read_text(encoding="utf-8"))
        if old_search:
            db.executescript((fixtures / "search_85d4118.sql").read_text(encoding="utf-8"))
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=database)
    original, = core.search("weightshift").results
    assert (original.source, original.start, original.missing) == ("transcript", 12.5, True)
    assert not core.search("weightshift").truncated
    if with_translation:
        translated, = core.search("체중 이동").results
        assert (translated.source, translated.start, translated.title) == ("translation", 12.5, "기존 영상")
    else:
        # 원어 색인이 이미 있는 DB에 구 빌드가 번역을 저장한 뒤 다시 열어도 검색된다.
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO translation_lines VALUES (?, ?)", ("legacy-line", "뒤늦은 번역"))
        core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=database)
        assert core.search("뒤늦은번역").results[0].source == "translation"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE transcript_lines SET text='Legacy edited' WHERE id='legacy-line'")
    assert core.search("legacyedited").results[0].source == "transcript"


@pytest.mark.parametrize("recursive_triggers", [0, 1])
def test_connections_without_app_functions_can_write_update_and_cascade_delete(library, recursive_triggers):
    core, video, _ = library
    transcript = core.transcript(video.id)
    # 다른 빌드/외부 도구의 연결 계약을 검증한다. 앱 함수는 등록하지 않는다.
    with sqlite3.connect(core.database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive_triggers}")
        db.execute("INSERT INTO transcript_lines VALUES (?, ?, ?, ?, ?, ?)",
                   ("external-line", transcript.id, 99, 70, 75, "External phrase"))
        db.execute("INSERT INTO translation_lines VALUES (?, ?)", ("external-line", "외부 번역문"))
    assert core.search("externalphrase").results[0].start == 70
    assert core.search("외부번역문").results[0].start == 70
    with sqlite3.connect(core.database) as db:
        db.execute("UPDATE transcript_lines SET text=?, start=? WHERE id=?", ("Changed phrase", 71.5, "external-line"))
        db.execute("UPDATE translation_lines SET text=? WHERE line_id=?", ("수정된 번역문", "external-line"))
    assert core.search("externalphrase").results == ()
    assert core.search("외부번역문").results == ()
    assert core.search("changedphrase").results[0].start == 71.5
    assert core.search("수정된번역문").results[0].start == 71.5
    # 텍스트를 건드리지 않고 원어 시각만 바꿔도 양쪽 결과가 즉시 따라간다.
    with sqlite3.connect(core.database) as db:
        db.execute("UPDATE transcript_lines SET start=72 WHERE id='external-line'")
    assert core.search("changedphrase").results[0].start == 72
    assert core.search("수정된번역문").results[0].start == 72
    with sqlite3.connect(core.database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive_triggers}")
        db.execute("DELETE FROM transcript_lines WHERE id='external-line'")
    assert core.search("changedphrase").results == ()
    assert core.search("수정된번역문").results == ()


def test_translation_generation_retranslation_and_transcript_replacement(library):
    core, video, transcriber = library

    class Translator:
        text = "번역된 체중 이동"

        def translate(self, lines, language, **kwargs):
            return tuple(TranslatedLine(line.id, self.text) for line in lines)

    translator = Translator()
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database,
                   transcriber=transcriber, translator=translator)
    transcriber.result = TranscriberResult("en", (TranscriptSegment(20, 22, "Weight shift"),))
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    assert core.process_next_translation().state == "completed"
    result, = core.search("번역된체중").results
    assert (result.source, result.start, result.video_id) == ("translation", 20, video.id)
    assert core.switch_to(result.video_id, start=result.start) == 20
    core.playback.end()
    translator.text = "새로 번역한 줄"
    core.request_translation(video.id)
    assert core.process_next_translation().state == "completed"
    assert not core.search("번역된체중").results
    assert core.search("새로번역한줄").results[0].start == 20
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    assert not core.search("새로번역한줄").results


@pytest.mark.parametrize("count", [499, 500, 501, 5000])
@pytest.mark.parametrize("query", ["이", "체중", "체중 이동"])
def test_result_limit_and_truncation_for_short_and_fts_queries(library, count, query):
    core, video, transcriber = library
    transcriber.result = TranscriberResult("ko", tuple(
        TranscriptSegment(i / 100, i / 100 + 1, f"체중이동 {i}") for i in range(count)))
    core.request_subtitles(video.id)
    assert core.process_next_subtitle().state == "completed"
    response = core.search(query)
    assert len(response.results) == min(count, 500)
    assert response.truncated == (count > 500)
    assert response == core.search(query)


def test_limit_is_shared_across_scopes(library):
    core, video, transcriber = library
    core.add_video_tag(video.id, "체중")
    note(core, video.id, "체중")
    transcriber.result = TranscriberResult("ko", tuple(
        TranscriptSegment(i / 10, i / 10 + 1, "체중") for i in range(499)))
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    response = core.search("체중")
    assert len(response.results) == 500 and response.truncated
    assert {r.source for r in response.results} == {"tag", "note", "transcript"}


def test_metadata_results_are_also_bounded(library):
    core, video, _ = library
    for i in range(501):
        core.add_video_tag(video.id, f"공통태그{i}")
    response = core.search("공통태그")
    assert len(response.results) == 500 and response.truncated
    assert all(result.source == "tag" for result in response.results)


def test_missing_and_excluded_state_and_title_changes_follow_library(library):
    core, video, _ = library
    core.rename_video(video.id, "새로운 이름")
    assert core.search("새로운이름").results[0].source == "title"
    assert all(result.source != "title" for result in core.search("Lesson").results)
    video.locations[0].path.unlink()
    core.scan()
    result, = core.search("새로운이름").results
    assert result.missing
    assert core.search("체중").results[0].missing
    core.exclude_video(video.id)
    assert not core.search("새로운이름").results
    assert not core.search("체중").results
    core.restore_video(video.id)
    assert core.search("새로운이름").results[0].missing
