from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.onscreen_subtitles import RegionRect
from my_video_manager.review import ReviewConfirmationRequired
from my_video_manager.subtitles import TranscriberCancelled, TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine, TranslationError
from my_video_manager.translation_source import ONSCREEN
from test_onscreen_subtitles import BAND
from test_onscreen_translation import read_screen, screen


class Media:
    def read(self, path):
        return MediaInfo(100, "mkv")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"image")


class Transcriber:
    def __init__(self):
        self.result = TranscriberResult("en", tuple(TranscriptSegment(i, i + 2, f"source {i}") for i in (0, 10, 20, 30)), model="large-v3")
        self.calls = []
        self.error = None

    def transcribe(self, path, language, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class Translator:
    def __init__(self):
        self.calls = []
        self.error = None
        self.respond = None

    def translate(self, lines, language, **kwargs):
        self.calls.append(lines)
        if self.error:
            raise self.error
        if self.respond:
            self.respond()
        return tuple(TranslatedLine(line.id, f"번역 {line.text}") for line in lines)


@pytest.fixture
def setup(tmp_path):
    transcriber, translator = Transcriber(), Translator()
    time = [datetime(2026, 10, 14, tzinfo=timezone.utc)]
    def reopen():
        return AppCore(media=Media(), clock=lambda: time[0], database=tmp_path / "data/library.sqlite3",
                       transcriber=transcriber, translator=translator, translation_batch_size=2)
    core = reopen()
    path = tmp_path / "테스트 영상.mkv"
    path.write_bytes(b"movie")
    core.add_file(path)
    video_id = core.videos()[0].id
    core.request_subtitles(video_id)
    core.process_next_subtitle()
    return core, video_id, transcriber, translator, time, reopen


def finish(core):
    for _ in range(20):
        if not core.translation_ready():
            return
        core.process_next_translation()
    pytest.fail("번역이 끝나지 않음")


def test_stale_limit_response_keeps_new_request_unchanged_and_holds_account(setup):
    core, vid, _, translator, time, _ = setup
    translator.error = TranslationError("usage_limit", "limit")
    for _ in range(2):
        assert core.process_next_translation().state == "held"
        time[0] += timedelta(minutes=16)
    translator.error = None
    replacements = []

    def edit_then_limit():
        line = core.transcript(vid).lines[0]
        core.edit_transcript_line(vid, line.id, "new source")
        replacements.append(core.translation_queue()[0])
        raise TranslationError("usage_limit", "옛 요청 응답")

    translator.respond = edit_then_limit
    assert core.process_next_translation() is None
    assert core.translation_queue() == tuple(replacements)
    assert not core.translation_ready()
    translator.respond = None
    translator.error = TranslationError("usage_limit", "새 요청 응답")
    time[0] += timedelta(minutes=16)
    failed = core.process_next_translation()
    assert failed.state == "failed"
    assert "3회" in failed.error


def test_source_edit_keeps_id_and_only_retranslates_changed_line(setup):
    core, vid, _, translator, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    old_translation = core.translation(vid)
    line = before.lines[1]
    translator.calls.clear()
    core.edit_transcript_line(vid, line.id, "수정한 원어")
    assert core.transcript(vid).lines[1].id == line.id
    finish(core)
    assert [[l.id for l in call] for call in translator.calls] == [[line.id]]
    after = core.translation(vid)
    assert after.lines[0] == old_translation.lines[0]
    assert after.lines[2:] == old_translation.lines[2:]
    assert after.lines[1].text == "번역 수정한 원어"
    assert reopen().reviewed_line_count(vid) == 1
    assert core.review_line_position(vid, line.id) == 10


def test_manual_translation_is_protected_and_source_overwrite_requires_confirmation(setup):
    core, vid, _, translator, _, reopen = setup
    finish(core)
    line = core.transcript(vid).lines[0]
    core.edit_translation_line(vid, line.id, "직접 고침")
    core = reopen()
    core.request_translation(vid)
    finish(core)
    assert core.translation(vid).lines[0].text == "직접 고침"
    with pytest.raises(ReviewConfirmationRequired, match="직접 고친 번역"):
        core.edit_transcript_line(vid, line.id, "changed")
    assert core.transcript(vid).lines[0] == line
    core.edit_transcript_line(vid, line.id, "changed", overwrite_reviewed=True)
    translator.calls.clear()
    finish(core)
    assert len(translator.calls) == 1 and len(translator.calls[0]) == 1
    assert core.translation(vid).lines[0].text == "번역 changed"
    assert not core.review_lines(vid)[0].translation_reviewed
    assert core.reviewed_line_count(vid) == 1


def test_manual_translation_survives_held_resume_and_saved_batches(setup):
    core, vid, _, translator, time, reopen = setup
    core.process_next_translation()
    lines = core.transcript(vid).lines
    translator.error = TranslationError("usage_limit", "limit")
    assert core.process_next_translation().state == "held"
    core.edit_translation_line(vid, lines[0].id, "완료 묶음 검수")
    core.edit_translation_line(vid, lines[2].id, "미완료 묶음 검수")
    translator.error = None
    time[0] += timedelta(minutes=16)
    core = reopen()
    finish(core)
    assert [l.text for l in core.translation(vid).lines][::2] == ["완료 묶음 검수", "미완료 묶음 검수"]


def test_running_translation_cannot_overwrite_manual_edit(setup):
    core, vid, _, translator, _, _ = setup
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(5)
    translator.respond = wait
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        try:
            assert entered.wait(5)
            line = core.transcript(vid).lines[0]
            core.edit_translation_line(vid, line.id, "실행 중 검수")
        finally:
            release.set()
        future.result()
    translator.respond = None
    finish(core)
    assert core.translation(vid).lines[0].text == "실행 중 검수"


def test_running_translation_result_is_discarded_after_source_edit(setup):
    core, vid, _, translator, _, _ = setup
    line = core.transcript(vid).lines[0]
    translator.respond = lambda: core.edit_transcript_line(vid, line.id, "new source")
    assert core.process_next_translation() is None
    translator.respond = None
    finish(core)
    assert core.translation(vid).lines[0].text == "번역 new source"


@pytest.mark.parametrize("count", [0, 1, 3, 6])
def test_range_preserves_nonoverlapping_ids_and_reviews(setup, count):
    core, vid, transcriber, translator, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    core.edit_translation_line(vid, before.lines[0].id, "유지")
    core.edit_translation_line(vid, before.lines[1].id, "삭제")
    transcriber.result = TranscriberResult("en", tuple(TranscriptSegment(i, i + .5, f"new {i}") for i in range(count)), model="range-model")
    core.request_subtitle_range(vid, 5, 20)
    with pytest.raises(ValueError, match="재생성"):
        core.edit_transcript_line(vid, before.lines[0].id, "blocked")
    assert core.transcript(vid) == before
    core = reopen()
    assert core.process_next_subtitle().state == "completed"
    assert transcriber.calls[-1]["start"] == 5
    assert transcriber.calls[-1]["duration"] == 15
    after = core.transcript(vid)
    assert after.id == before.id
    assert after.model == before.model == "large-v3"
    assert after.lines[0] == before.lines[0]
    assert after.lines[-2:] == before.lines[-2:]  # 끝 시각에 시작하는 줄도 유지
    assert len(after.lines) == 3 + count
    assert {l.id for l in after.lines[1:-2]}.isdisjoint(l.id for l in before.lines)
    assert [l.start for l in after.lines[1:-2]] == [5 + i for i in range(count)]
    translator.calls.clear()
    finish(core)
    assert sum(len(call) for call in translator.calls) == count
    assert core.translation(vid).lines[0].text == "유지"
    assert core.reviewed_line_count(vid) == 1
    assert reopen().transcript(vid) == after


@pytest.mark.parametrize("error", [RuntimeError("실패"), TranscriberCancelled()])
def test_range_failure_or_cancel_keeps_original_and_translation(setup, error):
    core, vid, transcriber, _, _, _ = setup
    finish(core)
    before, translated = core.transcript(vid), core.translation(vid)
    transcriber.error = error
    core.request_subtitle_range(vid, 1, 20)
    result = core.process_next_subtitle()
    assert result.state == ("queued" if isinstance(error, TranscriberCancelled) else "failed")
    assert core.transcript(vid) == before
    assert core.translation(vid) == translated


def test_invalid_range_result_rolls_back_deletions(setup):
    core, vid, transcriber, _, _, _ = setup
    before = core.transcript(vid)
    transcriber.result = TranscriberResult("en", (TranscriptSegment(0, float("nan"), "invalid"),), model="large-v3")
    core.request_subtitle_range(vid, 1, 20)
    assert core.process_next_subtitle().state == "failed"
    assert core.transcript(vid) == before


@pytest.mark.parametrize("start,end", [(-1, 5), (2, 2), (3, 1), (0, 101), (float("nan"), 3), (0, float("inf"))])
def test_invalid_range_is_rejected(setup, start, end):
    core, vid, *_ = setup
    with pytest.raises(ValueError):
        core.request_subtitle_range(vid, start, end)
    assert not core.subtitle_queue()


@pytest.mark.parametrize("language", ["und"])
def test_noneligible_source_can_be_edited_and_range_regenerated_without_translation(setup, language):
    core, vid, transcriber, translator, _, _ = setup
    transcriber.result = TranscriberResult(language, transcriber.result.segments, model="large-v3")
    core.request_subtitles(vid)
    core.process_next_subtitle()
    line = core.transcript(vid).lines[0]
    core.edit_transcript_line(vid, line.id, "수정")
    assert not core.translation_queue()
    with pytest.raises(ValueError):
        core.edit_translation_line(vid, line.id, "번역")
    transcriber.result = TranscriberResult(language, (TranscriptSegment(0, 1, "새 줄"),), model="large-v3")
    core.request_subtitle_range(vid, 0, 5)
    assert core.process_next_subtitle().state == "completed"
    assert not core.translation_queue()
    assert not translator.calls


def test_whole_regeneration_warning_counts_distinct_reviewed_lines_and_cascades(setup):
    core, vid, _, _, _, _ = setup
    finish(core)
    lines = core.transcript(vid).lines
    core.edit_transcript_line(vid, lines[0].id, "수정")
    core.edit_translation_line(vid, lines[0].id, "직접 번역")
    core.edit_translation_line(vid, lines[1].id, "직접 번역 2")
    assert core.reviewed_line_count(vid) == 2
    assert "검수한 2줄" in core.subtitle_regeneration_warning(vid)
    core.request_subtitles(vid)
    assert core.reviewed_line_count(vid) == 2
    assert core.process_next_subtitle().state == "completed"
    assert core.reviewed_line_count(vid) == 0
    assert core.translation(vid) is None
    assert set(l.id for l in lines).isdisjoint(l.id for l in core.transcript(vid).lines)


def test_partial_export_uses_saved_batches_numbering_utf8_bom_and_explicit_destination(setup, tmp_path):
    core, vid, _, _, _, _ = setup
    core.process_next_translation()
    original = core.subtitle_export(vid)
    translated = core.subtitle_export(vid, translated=True)
    assert original.default_path == tmp_path / "테스트 영상.en.srt"
    assert translated.default_path == tmp_path / "테스트 영상.ko.srt"
    assert translated.missing_lines == 2
    assert "1\n00:00:00,000 --> 00:00:02,000\n번역 source 0" in translated.text
    assert "2\n00:00:10,000" in translated.text
    assert not list(tmp_path.glob("*.srt"))
    destination = tmp_path / "선택한 내보내기.srt"
    core.write_subtitle_export(translated, destination)
    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert destination.read_text(encoding="utf-8-sig") == translated.text
    assert not original.default_path.exists()


def test_blank_edits_and_stale_ids_do_not_change_review(setup):
    core, vid, *_ = setup
    line = core.transcript(vid).lines[0]
    for edit in (core.edit_transcript_line, core.edit_translation_line):
        with pytest.raises(ValueError):
            edit(vid, line.id, "  ")
        with pytest.raises(ValueError):
            edit(vid, "missing", "value")
    core.edit_transcript_line(vid, line.id, line.text)
    assert core.reviewed_line_count(vid) == 0


def test_review_scene_starts_at_line_and_same_video_reuses_viewing(setup):
    core, vid, *_ = setup
    first, second = core.transcript(vid).lines[1:3]
    target = core.play_review_line(vid, first.id)
    assert (target.video_id, target.start, target.action) == (vid, 10, "play")
    assert core.playback.position == 10
    assert core.playback.session.record_viewing
    session = core.playback.session
    target = core.play_review_line(vid, second.id)
    assert (target.start, target.action) == (20, "seek")
    assert core.playback.session is session
    core.playback.report(target.start, seeked=True)
    assert core.playback.position == 20
    assert len(core.viewings(vid)) == 1


def test_review_scene_leaves_reel_and_starts_normal_viewing(setup):
    core, vid, *_ = setup
    core.playback.start(vid, 0, record_viewing=False)
    core.execute_highlight_command(core.command_for_key("Insert"))
    highlight = core.highlights(vid)[0]
    core.update_highlight(highlight.id, start=0, end=8, note="복습")
    core.playback.end()
    core.start_reel(highlight_id=highlight.id)
    core.playback.report(3)
    before = core.reel_entries()[0].last_revisited_at
    assert before is not None
    target = core.play_review_line(vid, core.transcript(vid).lines[2].id)
    assert core.reel_playback is None
    assert (target.action, target.start) == ("play", 20)
    assert core.playback.session.record_viewing
    assert core.playback.position == 20
    assert len(core.viewings(vid)) == 1
    assert core.reel_entries()[0].last_revisited_at == before


def test_manual_review_of_all_remaining_targets_publishes_saved_batches(setup):
    core, vid, _, _, _, reopen = setup
    core.process_next_translation()
    for line in core.transcript(vid).lines[2:]:
        core.edit_translation_line(vid, line.id, "마지막 묶음 직접 검수")
    assert not core.translation_queue()
    translated = reopen().translation(vid)
    assert len(translated.lines) == 4
    assert translated.lines[0].text.startswith("번역 ")
    assert translated.lines[2].text == "마지막 묶음 직접 검수"


def test_core_range_passes_start_and_duration_to_process_adapter(setup, tmp_path):
    import sys
    from my_video_manager.transcription import FasterWhisperTranscriber
    core, vid, *_ = setup
    worker = tmp_path / "구간 어댑터.py"
    worker.write_text('''
import sys, json
assert sys.argv[3] == 'en'
assert list(map(float, sys.argv[4:])) == [10, 10]
print(json.dumps({'spoken_language': 'en', 'model': 'large-v3', 'segments': [{'start': 0.5, 'end': 2, 'text': 'range'}]}))
''', encoding="utf-8")
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database,
                   transcriber=FasterWhisperTranscriber(tmp_path / "models", command=(sys.executable, str(worker))))
    core.request_subtitle_range(vid, 10, 20)
    assert core.process_next_subtitle().state == "completed"
    assert core.transcript(vid).lines[1].start == 10.5


def assert_search_hits(core, video_id, query, expected):
    response = core.search(query)
    assert not response.truncated
    assert [(r.video_id, r.source, r.text, r.start) for r in response.results] == [
        (video_id, source, text, start) for source, text, start in expected]


def test_search_follows_original_line_review_immediately(setup):
    core, vid, _, _, _, reopen = setup
    line = core.transcript(vid).lines[1]
    assert_search_hits(core, vid, "source10", [("transcript", line.text, 10)])
    core.edit_transcript_line(vid, line.id, "수정한 타격 자세")
    assert core.transcript(vid).lines[1].id == line.id
    assert_search_hits(core, vid, "source10", [])
    expected = [("transcript", "수정한 타격 자세", 10)]
    assert_search_hits(core, vid, "수정한타격", expected)
    assert_search_hits(reopen(), vid, "수정한타격", expected)


def test_search_follows_direct_translation_review_immediately(setup):
    core, vid, _, _, _, reopen = setup
    finish(core)
    line = core.transcript(vid).lines[1]
    assert_search_hits(core, vid, "번역source10", [("translation", "번역 source 10", 10)])
    core.edit_translation_line(vid, line.id, "검수한 한국어 설명")
    assert_search_hits(core, vid, "번역source10", [])
    expected = [("translation", "검수한 한국어 설명", 10)]
    assert_search_hits(core, vid, "검수한한국어", expected)
    assert_search_hits(core, vid, "source10", [("transcript", line.text, 10)])
    assert_search_hits(reopen(), vid, "검수한한국어", expected)


def test_search_replaces_translation_after_original_review_and_retranslation(setup):
    core, vid, *_ = setup
    finish(core)
    line = core.transcript(vid).lines[1]
    assert_search_hits(core, vid, "source10", [
        ("transcript", "source 10", 10), ("translation", "번역 source 10", 10)])
    core.edit_transcript_line(vid, line.id, "new batting instruction")
    # 재번역 완료 전에는 기존 번역을 보존하는 #8 계약을 따른다.
    assert_search_hits(core, vid, "source10", [("translation", "번역 source 10", 10)])
    finish(core)
    assert_search_hits(core, vid, "source10", [])
    assert_search_hits(core, vid, "newbatting", [
        ("transcript", "new batting instruction", 10),
        ("translation", "번역 new batting instruction", 10)])


@pytest.mark.parametrize("counts", [(4, 1, 0), (0, 4, 1)])
def test_search_survives_range_replacement_and_repeated_two_phase_reordering(setup, counts):
    core, vid, transcriber, _, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    # 조회를 먼저 해서 기존 FTS 결과가 생긴 뒤 삭제·UPDATE 트리거를 거치게 한다.
    assert len(core.search("source").results) == 8
    retained = tuple(result for result in core.search("source").results if result.start != 10)
    old_query = "source10"
    for generation, count in enumerate(counts):
        old_ids = {line.id for line in core.transcript(vid).lines}
        word = f"구간세대{generation}"
        transcriber.result = TranscriberResult("en", tuple(
            TranscriptSegment(i * 2 + .5, i * 2 + 1.5, f"{word} 문장{i}") for i in range(count)), model="large-v3")
        core.request_subtitle_range(vid, 10, 20)
        assert core.process_next_subtitle().state == "completed"
        current = core.transcript(vid)
        new_lines = current.lines[1:-2]
        assert len(new_lines) == count
        assert old_ids.isdisjoint(line.id for line in new_lines)
        assert current.lines[0] == before.lines[0]
        assert current.lines[-2:] == before.lines[-2:]
        assert_search_hits(core, vid, old_query, [])
        assert_search_hits(core, vid, word, [
            ("transcript", line.text, 10 + i * 2 + .5) for i, line in enumerate(new_lines)])
        finish(core)
        expected = [item for i, line in enumerate(new_lines) for item in (
            ("transcript", line.text, 10 + i * 2 + .5),
            ("translation", f"번역 {line.text}", 10 + i * 2 + .5))]
        assert_search_hits(core, vid, word, expected)
        # 임시 음수→최종 ordinal 갱신을 두 번 거친 바깥 줄도 중복·누락 없이 검색된다.
        assert core.search("source").results == retained
        assert_search_hits(core, vid, old_query, [])
        core = reopen()
        assert_search_hits(core, vid, word, expected)
        assert core.search("source").results == retained
        old_query = word


def test_search_removes_all_reviewed_lines_on_whole_regeneration(setup):
    core, vid, transcriber, _, _, reopen = setup
    finish(core)
    old_lines = core.transcript(vid).lines
    core.edit_transcript_line(vid, old_lines[1].id, "이전 검수 원어")
    finish(core)
    core.edit_translation_line(vid, old_lines[1].id, "이전 직접 번역")
    assert_search_hits(core, vid, "이전검수", [("transcript", "이전 검수 원어", 10)])
    assert_search_hits(core, vid, "이전직접", [("translation", "이전 직접 번역", 10)])
    assert len(core.search("source").results) == 6
    transcriber.result = TranscriberResult("en", (TranscriptSegment(7.125, 9, "전체 재생성 문장"),), model="large-v3")
    core.request_subtitles(vid)
    assert core.process_next_subtitle().state == "completed"
    assert {line.id for line in old_lines}.isdisjoint(line.id for line in core.transcript(vid).lines)
    for query in ("이전검수", "이전직접", "source"):
        assert_search_hits(core, vid, query, [])
    assert_search_hits(core, vid, "전체재생성", [("transcript", "전체 재생성 문장", 7.125)])
    finish(core)
    expected = [("transcript", "전체 재생성 문장", 7.125),
                ("translation", "번역 전체 재생성 문장", 7.125)]
    assert_search_hits(core, vid, "전체재생성", expected)
    core = reopen()
    assert_search_hits(core, vid, "전체재생성", expected)
    for query in ("이전검수", "이전직접", "source"):
        assert_search_hits(core, vid, query, [])


@pytest.mark.parametrize("old_start,old_end,bounds", [(9, 13, (5, 13)), (0, 6, (0, 10))])
def test_range_expands_across_both_boundaries_without_loss_or_duplicates(setup, old_start, old_end, bounds):
    core, vid, transcriber, _, _, reopen = setup
    transcriber.result = TranscriberResult("en", (
        TranscriptSegment(old_start, old_end, "boundary old"), TranscriptSegment(20, 22, "retained")), model="large-v3")
    core.request_subtitles(vid)
    core.process_next_subtitle()
    finish(core)
    before = core.transcript(vid)
    assert core.subtitle_range_bounds(vid, 5, 10) == bounds
    transcriber.result = TranscriberResult("en", (
        TranscriptSegment(old_start - bounds[0], old_end - bounds[0], "boundary new"),), model="large-v3")
    core.request_subtitle_range(vid, 5, 10)
    assert core.process_next_subtitle().state == "completed"
    assert (transcriber.calls[-1]["start"], transcriber.calls[-1]["duration"]) == (bounds[0], bounds[1] - bounds[0])
    after = reopen().transcript(vid)
    assert len(after.lines) == 2
    assert after.lines[0].id != before.lines[0].id
    assert (after.lines[0].start, after.lines[0].end) == (old_start, old_end)
    assert after.lines[1] == before.lines[1]
    assert_search_hits(core, vid, "boundaryold", [])
    assert_search_hits(core, vid, "boundarynew", [("transcript", "boundary new", old_start)])


def test_range_expands_transitively_and_clips_output_to_video_bounds(setup):
    core, vid, transcriber, *_ = setup
    transcriber.result = TranscriberResult("en", tuple(
        TranscriptSegment(start, end, f"old {start}") for start, end in ((0, 4), (4, 10), (9, 50), (49, 105))), model="large-v3")
    core.request_subtitles(vid)
    core.process_next_subtitle()
    before = core.transcript(vid)
    assert core.subtitle_range_bounds(vid, 5, 6) == (4, 100)
    transcriber.result = TranscriberResult("en", (
        TranscriptSegment(-2, 2, "front"), TranscriptSegment(94, 110, "end"),
        TranscriptSegment(100, 102, "outside")), model="large-v3")
    core.request_subtitle_range(vid, 5, 6)
    assert core.process_next_subtitle().state == "completed"
    after = core.transcript(vid)
    assert after.lines[0] == before.lines[0]
    assert [(line.start, line.end) for line in after.lines[1:]] == [(4, 6), (98, 100)]
    assert_search_hits(core, vid, "old9", [])
    assert_search_hits(core, vid, "end", [("transcript", "end", 98)])


@pytest.mark.parametrize("translated", [False, True])
@pytest.mark.parametrize("edit", [False, True])
def test_srt_normalizes_blank_lines_for_export_and_playback(setup, translated, edit):
    core, vid, transcriber, translator, *_ = setup
    raw = "  first\r\n \r\n second \r third\n\n  "
    normalized = "first\nsecond\nthird"
    if edit:
        finish(core)
        line = core.transcript(vid).lines[0]
        method = core.edit_translation_line if translated else core.edit_transcript_line
        method(vid, line.id, raw)
        stored = core.translation(vid) if translated else core.transcript(vid)
        assert stored.lines[0].text == normalized
    else:
        transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 2, raw),), model="large-v3")
        core.request_subtitles(vid)
        core.process_next_subtitle()
        translator.translate = lambda lines, language, **kwargs: tuple(TranslatedLine(line.id, raw) for line in lines)
        finish(core)
    export = core.subtitle_export(vid, translated=translated)
    expected_count = len(core.transcript(vid).lines)
    assert len(export.text.strip().split("\n\n")) == expected_count
    assert export.text.split("\n\n")[0].endswith(normalized + ("\n" if expected_count == 1 else ""))
    assert "\r" not in export.text
    core.playback.start(vid, 0)
    if translated:
        assert core.toggle_subtitle_language()[0]
    playback = core.playback_subtitle(vid).read_text(encoding="utf-8")
    assert playback == export.text


def test_export_reports_pending_retranslation_until_published(setup):
    core, vid, *_ = setup
    finish(core)
    assert core.subtitle_export(vid, translated=True).pending_retranslation_lines == 0
    for line in core.transcript(vid).lines[:3]:
        core.edit_transcript_line(vid, line.id, f"changed {line.start}")
    core.process_next_translation()
    export = core.subtitle_export(vid, translated=True)
    assert export.pending_retranslation_lines == 3
    assert "0줄 미번역" in export.warning and "재번역 대기 3줄" in export.warning
    assert "번역 source" in export.text
    finish(core)
    assert core.subtitle_export(vid, translated=True).pending_retranslation_lines == 0


def test_empty_exports_are_rejected(setup):
    core, vid, transcriber, *_ = setup
    with pytest.raises(ValueError, match="^내보낼 자막 줄이 없습니다$"):
        core.subtitle_export(vid, translated=True)
    transcriber.result = TranscriberResult("en", (), model="large-v3")
    core.request_subtitle_range(vid, 0, 100)
    core.process_next_subtitle()
    for translated in (False, True):
        with pytest.raises(ValueError, match="^내보낼 자막 줄이 없습니다$"):
            core.subtitle_export(vid, translated=translated)


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_source_edit_preserves_limit_state_attempts_and_other_completed_targets(setup, failures):
    core, vid, _, translator, time, reopen = setup
    core.process_next_translation()
    translator.error = TranslationError("usage_limit", "limit detail")
    for _ in range(failures):
        core.process_next_translation()
        time[0] += timedelta(minutes=16)
    before = core.translation_queue()[0]
    line = core.transcript(vid).lines[0]
    core.edit_transcript_line(vid, line.id, "changed")
    core = reopen()
    after = core.translation_queue()[0]
    assert (after.state, after.retry_at, after.error, after.error_detail) == (
        before.state, before.retry_at, before.error, before.error_detail)
    assert (after.completed_lines, after.total_lines) == (1, 4)
    # 수정해도 한도 시도 횟수를 초기화하지 않는다.
    for _ in range(3 - failures):
        core.process_next_translation()
        time[0] += timedelta(minutes=16)
    assert core.translation_queue()[0].state == "failed"
    assert core.process_next_translation() is None
    translator.error = None
    translator.calls.clear()
    core.request_translation(vid)
    finish(core)
    assert [line.start for call in translator.calls for line in call] == [0, 20, 30]
    assert core.translation(vid).lines[1].text == "번역 source 10"


def test_source_edit_preserves_nonlimit_failure_until_explicit_retry(setup):
    core, vid, _, translator, time, reopen = setup
    translator.error = TranslationError("authentication", "login detail")
    before = core.process_next_translation()
    core.edit_transcript_line(vid, core.transcript(vid).lines[2].id, "changed")
    time[0] += timedelta(days=1)
    core = reopen()
    after = core.translation_queue()[0]
    assert (after.state, after.retry_at, after.error, after.error_detail) == (
        before.state, before.retry_at, before.error, before.error_detail)
    assert core.process_next_translation() is None


def test_failed_range_retains_specific_retry_guidance_after_restart(setup):
    core, vid, transcriber, _, _, reopen = setup
    transcriber.error = RuntimeError("failed")
    core.request_subtitle_range(vid, 5, 15)
    failed = core.process_next_subtitle()
    assert "검수 창의 구간 다시 생성" in failed.retry_guidance
    assert "대기열 화면의 실패 항목 모두 재시도로 같은 구간" in failed.retry_guidance
    assert reopen().subtitle_queue()[0].retry_guidance == failed.retry_guidance
    core.request_subtitles(vid)
    assert core.process_next_subtitle().retry_guidance == "다시 요청하면 재시도합니다"


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_range_preserves_translation_backoff_failure_and_completed_batches(setup, failures):
    core, vid, transcriber, translator, time, reopen = setup
    core.process_next_translation()
    translator.error = TranslationError("usage_limit", "limit detail")
    for attempt in range(failures):
        if attempt:
            time[0] += timedelta(minutes=16)
        core.process_next_translation()
    before = core.translation_queue()[0]
    transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 1, "added"),), model="large-v3")
    core.request_subtitle_range(vid, 25, 27)
    core.process_next_subtitle()
    core = reopen()
    after = core.translation_queue()[0]
    assert (after.state, after.retry_at, after.error, after.error_detail) == (
        before.state, before.retry_at, before.error, before.error_detail)
    assert (after.completed_lines, after.total_lines) == (2, 5)
    item, = core.subtitle_queue_items()
    assert (item.state, item.progress) == (after.state, .4)
    assert core.process_next_translation() is None
    for _ in range(3 - failures):
        time[0] += timedelta(minutes=16)
        core.process_next_translation()
    assert core.subtitle_queue_items()[0].state == "failed"
    assert core.process_next_translation() is None


def test_range_queue_reports_progress_and_blocks_edits_until_translation(setup):
    core, vid, transcriber, *_ = setup
    finish(core)
    original = core.transcript(vid)
    transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 2, "new range"),), model="large-v3")
    original_call = transcriber.transcribe
    def transcribe(*args, **kwargs):
        assert kwargs["start"] == 10 and kwargs["duration"] == 10
        kwargs["progress"](5)
        item, = core.subtitle_queue_items()
        assert (item.state, item.progress) == ("transcribing", .5)
        for edit in (core.edit_transcript_line, core.edit_translation_line):
            with pytest.raises(ValueError, match="재생성"):
                edit(vid, original.lines[0].id, "blocked")
        with pytest.raises(ValueError, match="재생성"):
            core.request_subtitle_range(vid, 0, 1)
        assert core.process_next_translation() is None
        return original_call(*args, **kwargs)
    transcriber.transcribe = transcribe
    core.request_subtitle_range(vid, 10, 20)
    assert core.subtitle_queue_items()[0].state == "queued"
    assert core.process_next_subtitle().state == "completed"
    assert core.subtitle_queue_items()[0].state == "queued"  # 새 줄 번역 대기
    finish(core)
    assert (core.subtitle_queue_items()[0].state, core.subtitle_queue_items()[0].progress) == ("completed", 1)


@pytest.mark.parametrize("remove", [False, True])
def test_active_range_cancellation_preserves_review_and_original_lines(setup, remove):
    core, vid, transcriber, _, _, reopen = setup
    finish(core)
    core.edit_translation_line(vid, core.transcript(vid).lines[0].id, "protected")
    before, translated = core.transcript(vid), core.translation(vid)
    original_call = transcriber.transcribe
    def cancel(*args, **kwargs):
        if remove:
            core.remove_from_subtitle_queue(vid)
        else:
            core.stop_subtitle_processing()
        assert kwargs["cancellation"].is_set()
        return original_call(*args, **kwargs)  # 취소를 무시한 응답도 저장하지 않는다.
    transcriber.transcribe = cancel
    core.request_subtitle_range(vid, 10, 20)
    core.process_next_subtitle()
    assert core.transcript(vid) == before
    assert core.translation(vid) == translated
    assert core.reviewed_line_count(vid) == 1
    transcriber.transcribe = original_call
    transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 2, "retried"),), model="large-v3")
    core = reopen()
    if remove:
        assert not core.subtitle_queue_items()
        assert core.process_next_subtitle() is None
    else:
        assert core.subtitle_queue_items()[0].state == "queued"
        assert core.process_next_subtitle().state == "completed"
        assert transcriber.calls[-1]["start"] == 10
        assert core.transcript(vid).lines[0] == before.lines[0]


def test_interrupted_range_recovers_same_bounds_and_keeps_reviews(setup):
    core, vid, transcriber, _, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    core.edit_translation_line(vid, before.lines[0].id, "protected")
    transcriber.error = KeyboardInterrupt()
    core.request_subtitle_range(vid, 10, 20)
    with pytest.raises(KeyboardInterrupt):
        core.process_next_subtitle()
    assert core.subtitle_queue_items()[0].state == "transcribing"
    assert core.transcript(vid) == before
    transcriber.error = None
    transcriber.result = TranscriberResult("en", (TranscriptSegment(1, 2, "recovered"),), model="large-v3")
    core = reopen()
    assert core.subtitle_queue_items()[0].state == "queued"
    core.process_next_subtitle()
    assert (transcriber.calls[-1]["start"], transcriber.calls[-1]["duration"]) == (10, 10)
    assert core.transcript(vid).lines[0] == before.lines[0]
    assert core.review_lines(vid)[0].translation == "protected"


def test_bulk_retry_preserves_failed_range_and_outside_review(setup):
    core, vid, transcriber, _, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    core.edit_translation_line(vid, before.lines[0].id, "protected")
    transcriber.error = RuntimeError("range failure")
    core.request_subtitle_range(vid, 10, 20)
    core.process_next_subtitle()
    assert core.subtitle_queue_items()[0].state == "failed"
    core = reopen()
    result = core.retry_failed_subtitles()
    assert result.retried == 1 and not result.skipped
    assert core.subtitle_queue_items()[0].state == "queued"
    transcriber.error = None
    transcriber.result = TranscriberResult("en", (TranscriptSegment(1, 2, "retry"),), model="large-v3")
    core.process_next_subtitle()
    assert (transcriber.calls[-1]["start"], transcriber.calls[-1]["duration"]) == (10, 10)
    after = core.transcript(vid)
    assert after.id == before.id
    assert after.lines[0] == before.lines[0] and after.lines[-2:] == before.lines[-2:]
    assert core.review_lines(vid)[0].translation == "protected"
    finish(core)
    assert core.subtitle_queue_items()[0].state == "completed"


def test_range_request_registers_manual_fifo_priority_after_hidden_queue(setup, tmp_path):
    core, vid, _, _, _, reopen = setup
    finish(core)
    core.remove_from_subtitle_queue(vid)
    other_ids = []
    for index in range(3):
        path = tmp_path / f"queue{index}.mkv"
        path.write_bytes(f"movie{index}".encode())
        core.add_file(path)
        other_ids.append(next(v.id for v in core.videos() if v.locations[0].path == path))
    automatic, first, last = other_ids
    core.request_automatic_subtitles(automatic)
    core.request_subtitles(first)
    core.request_subtitle_range(vid, 10, 20)
    core.request_subtitles(last)
    core = reopen()
    assert [i.video_id for i in core.subtitle_queue_items()] == [first, vid, last, automatic]
    core.promote_subtitle(automatic)
    assert [i.video_id for i in core.subtitle_queue_items()] == [automatic, first, vid, last]


@pytest.mark.parametrize("promoted", [False, True])
def test_range_translation_preserves_request_order_and_promotion(setup, tmp_path, promoted):
    core, a, _, _, _, _ = setup
    finish(core)
    path = tmp_path / "b.mkv"
    path.write_bytes(b"second movie")
    core.add_file(path)
    b = next(v.id for v in core.videos() if v.id != a)
    if promoted:
        core.request_subtitles(b)
        core.process_next_subtitle()
        core.request_subtitle_range(a, 10, 20)
        core.promote_subtitle(a)
        core.process_next_subtitle()
    else:
        core.request_subtitle_range(a, 10, 20)
        core.request_subtitles(b)
        core.process_next_subtitle()
        core.process_next_subtitle()
    assert [entry.video_id for entry in core.translation_queue()] == [a, b]


@pytest.mark.parametrize("range_change", [False, True])
def test_replacing_active_translation_request_discards_old_result_and_queues_new_id(setup, range_change):
    core, vid, transcriber, translator, *_ = setup
    finish(core)
    line = core.transcript(vid).lines[1]
    core.edit_transcript_line(vid, line.id, "first change")
    def change():
        assert core.subtitle_queue_items()[0].state == "translating"
        if range_change:
            transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 2, "second change"),), model="large-v3")
            core.request_subtitle_range(vid, 10, 20)
            core.process_next_subtitle()
        else:
            core.edit_transcript_line(vid, line.id, "second change")
        assert core.subtitle_queue_items()[0].state == "queued"
    translator.respond = change
    assert core.process_next_translation() is None
    assert core.subtitle_queue_items()[0].state == "queued"
    assert "번역 first change" not in [r.translation for r in core.review_lines(vid)]
    translator.respond = None
    translator.calls.clear()
    finish(core)
    assert len(translator.calls) == 1 and len(translator.calls[0]) == 1
    assert core.translation(vid).lines[1].text == "번역 second change"
    assert core.subtitle_queue_items()[0].state == "completed"


def test_manual_review_protects_line_while_queue_shows_translating(setup):
    core, vid, _, translator, *_ = setup
    line = core.transcript(vid).lines[0]
    def review():
        assert core.subtitle_queue_items()[0].state == "translating"
        core.edit_translation_line(vid, line.id, "protected")
    translator.respond = review
    core.process_next_translation()
    translator.respond = None
    assert core.subtitle_queue_items()[0].state == "queued"
    finish(core)
    assert core.translation(vid).lines[0].text == "protected"
    assert core.review_lines(vid)[0].translation_reviewed
    assert core.subtitle_queue_items()[0].state == "completed"


def test_failed_range_retry_reports_unscanned_missing_file_without_changing_request(setup):
    core, vid, transcriber, *_ = setup
    before = core.transcript(vid)
    transcriber.error = RuntimeError("failed")
    core.request_subtitle_range(vid, 10, 20)
    core.process_next_subtitle()
    path = core.video(vid).locations[0].path
    contents = path.read_bytes()
    path.unlink()
    result = core.retry_failed_subtitles()
    assert result.retried == 0 and result.skipped_count == 1
    assert "파일 없음" in result.skipped[0].reason
    assert core.subtitle_queue()[0].state == "failed"
    assert core.transcript(vid) == before
    path.write_bytes(contents)
    core.add_file(path)
    assert core.retry_failed_subtitles().retried == 1
    transcriber.error = None
    transcriber.result = TranscriberResult("en", (TranscriptSegment(1, 2, "retried"),), model="large-v3")
    core.process_next_subtitle()
    assert (transcriber.calls[-1]["start"], transcriber.calls[-1]["duration"]) == (10, 10)


def test_review_line_after_video_end_is_clamped_for_play_and_seek(setup):
    core, vid, transcriber, _, _, _ = setup
    transcriber.result = TranscriberResult("en", (TranscriptSegment(105, 107, "late line"),), model="large-v3")
    core.request_subtitles(vid)
    assert core.process_next_subtitle().state == "completed"
    line = core.transcript(vid).lines[0]
    play = core.play_review_line(vid, line.id)
    assert play.action == "play" and play.start == 100
    assert core.playback.position == 100
    session = core.playback.session
    seek = core.play_review_line(vid, line.id)
    assert seek.action == "seek" and seek.start == 100
    assert core.playback.session is session
    assert len(core.viewings(vid)) == 1


def srt_lines(text):
    """SRT 블록을 (시작, 끝, 글자)로 되읽는다. 번호가 1부터 이어지는지도 본다."""
    def seconds(stamp):
        clock, milliseconds = stamp.split(",")
        hours, minutes, whole = map(int, clock.split(":"))
        return round(hours * 3600 + minutes * 60 + whole + int(milliseconds) / 1000, 3)

    result = []
    for number, block in enumerate(text.strip("\n").split("\n\n"), 1):
        index, timing, *body = block.split("\n")
        assert index == str(number)
        start, end = timing.split(" --> ")
        result.append((seconds(start), seconds(end), "\n".join(body)))
    return result


def saved_onscreen_lines(core, video_id):
    return sorted((round(line.start, 3), round(line.end, 3), line.text)
                  for subtitle in core.onscreen_subtitles(video_id) for line in subtitle.lines)


def test_onscreen_exports_merge_regions_in_time_order_and_match_saved_lines(screen, tmp_path):
    core, media, *_ = screen
    video = core.videos()[0]
    top = RegionRect(0.1, 0.0, 0.8, 0.15)
    media.captions_by_region = {BAND: ((10, 12, "Bottom one"), (30, 32, "Bottom two")),
                                top: ((20, 21.5, "Top one"),)}
    read_screen(core, media, video.id, captions=(), regions=((BAND, "en"), (top, "en")))
    saved = saved_onscreen_lines(core, video.id)
    assert [text for *_, text in saved] == ["Bottom one", "Top one", "Bottom two"]
    shown = core.subtitle_export(video.id, source=ONSCREEN)
    assert shown.default_path == tmp_path / "a.en.onscreen.srt"
    assert srt_lines(shown.text) == saved
    assert core.process_next_translation().completed_lines == 2  # 세 줄 중 두 줄만 저장
    partial = core.subtitle_export(video.id, translated=True, source=ONSCREEN)
    assert partial.missing_lines == 1
    assert "1줄 미번역" in partial.warning and "저장된 화면 번역 자막으로" in partial.warning
    assert srt_lines(partial.text) == [(s, e, "번역 " + t) for s, e, t in saved[:2]]
    finish(core)
    translated = core.subtitle_export(video.id, translated=True, source=ONSCREEN)
    assert translated.default_path == tmp_path / "a.ko.onscreen.srt"
    assert translated.missing_lines == translated.pending_retranslation_lines == 0
    assert srt_lines(translated.text) == [(s, e, "번역 " + t) for s, e, t in saved]
    assert not list(tmp_path.glob("*.srt"))
    destination = tmp_path / "고른 화면 번역.srt"
    core.write_subtitle_export(translated, destination)
    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert destination.read_text(encoding="utf-8-sig") == translated.text
    # 고친 화면 번역 줄은 내보내기에도 그대로 나온다.
    first = next(line for subtitle in core.onscreen_subtitles(video.id) for line in subtitle.lines
                 if line.text == "Top one")
    core.edit_onscreen_translation_line(first.id, "직접 고친\n위 글자")
    edited = srt_lines(core.subtitle_export(video.id, translated=True, source=ONSCREEN).text)
    assert edited[1] == (saved[1][0], saved[1][1], "직접 고친\n위 글자")


def test_onscreen_export_of_mixed_region_languages_names_multiple_languages(screen, tmp_path):
    core, media, *_ = screen
    video = core.videos()[0]
    top = RegionRect(0.1, 0.0, 0.8, 0.15)
    read_screen(core, media, video.id, regions=((BAND, "en"), (top, "ja")))
    assert core.subtitle_export(video.id, source=ONSCREEN).default_path == tmp_path / "a.mul.onscreen.srt"


def test_missing_onscreen_exports_are_rejected_and_not_offered(screen):
    core, media, *_ = screen
    a, b = core.videos()

    def rejected(video_id, translated, message):
        with pytest.raises(ValueError, match=f"^{message}$"):
            core.subtitle_export(video_id, translated=translated, source=ONSCREEN)
        # 검수 화면이 단추를 보일지 묻는 가벼운 조회도 같은 판단을 한다.
        assert not core.onscreen_export_available(video_id, translated=translated)

    for translated in (False, True):
        rejected(a.id, translated, "내보낼 화면 자막이 없습니다")
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])  # 아직 읽지 않은 영역
    rejected(a.id, False, "내보낼 화면 자막이 없습니다")
    read_screen(core, media, a.id)
    assert core.onscreen_export_available(a.id)
    rejected(a.id, True, "내보낼 자막 줄이 없습니다")  # 아직 번역하지 않음
    core.process_next_translation()  # 진행 중 요청에 저장된 묶음만 있어도 내보낼 수 있다.
    assert core.onscreen_export_available(a.id, translated=True)
    core.subtitle_export(a.id, translated=True, source=ONSCREEN)
    read_screen(core, media, b.id, captions=())  # 읽은 글자 없음
    for translated in (False, True):
        rejected(b.id, translated, "내보낼 자막 줄이 없습니다")
    read_screen(core, media, a.id, captions=((40, 42, "New caption"),))  # 다시 만든 화면 자막은 번역 전이다.
    assert core.onscreen_export_available(a.id)
    rejected(a.id, True, "내보낼 자막 줄이 없습니다")
