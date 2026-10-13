from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.review import ReviewConfirmationRequired
from my_video_manager.subtitles import TranscriberCancelled, TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine, TranslationError


class Media:
    def read(self, path):
        return MediaInfo(100, "mkv")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"image")


class Transcriber:
    def __init__(self):
        self.result = TranscriberResult("en", tuple(TranscriptSegment(i, i + 2, f"source {i}") for i in (0, 10, 20, 30)))
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
def test_range_replaces_start_inside_boundary_and_preserves_other_ids_and_reviews(setup, count):
    core, vid, transcriber, translator, _, reopen = setup
    finish(core)
    before = core.transcript(vid)
    core.edit_translation_line(vid, before.lines[0].id, "유지")
    core.edit_translation_line(vid, before.lines[1].id, "삭제")
    transcriber.result = TranscriberResult("en", tuple(TranscriptSegment(i, i + .5, f"new {i}") for i in range(count)))
    core.request_subtitle_range(vid, 1, 20)
    with pytest.raises(ValueError, match="재생성"):
        core.edit_transcript_line(vid, before.lines[0].id, "blocked")
    assert core.transcript(vid) == before
    core = reopen()
    assert core.process_next_subtitle().state == "completed"
    assert transcriber.calls[-1]["start"] == 1
    assert transcriber.calls[-1]["duration"] == 19
    after = core.transcript(vid)
    assert after.id == before.id
    assert after.lines[0] == before.lines[0]  # 앞 경계에 걸친 줄
    assert after.lines[-2:] == before.lines[-2:]  # 끝 시각에 시작하는 줄도 유지
    assert len(after.lines) == 3 + count
    assert {l.id for l in after.lines[1:-2]}.isdisjoint(l.id for l in before.lines)
    assert [l.start for l in after.lines[1:-2]] == [1 + i for i in range(count)]
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
    transcriber.result = TranscriberResult("en", (TranscriptSegment(0, 100, "outside"),))
    core.request_subtitle_range(vid, 1, 20)
    assert core.process_next_subtitle().state == "failed"
    assert core.transcript(vid) == before


@pytest.mark.parametrize("start,end", [(-1, 5), (2, 2), (3, 1), (0, 101), (float("nan"), 3), (0, float("inf"))])
def test_invalid_range_is_rejected(setup, start, end):
    core, vid, *_ = setup
    with pytest.raises(ValueError):
        core.request_subtitle_range(vid, start, end)
    assert not core.subtitle_queue()


@pytest.mark.parametrize("language", ["ko", "und"])
def test_noneligible_source_can_be_edited_and_range_regenerated_without_translation(setup, language):
    core, vid, transcriber, translator, _, _ = setup
    transcriber.result = TranscriberResult(language, transcriber.result.segments)
    core.request_subtitles(vid)
    core.process_next_subtitle()
    line = core.transcript(vid).lines[0]
    core.edit_transcript_line(vid, line.id, "수정")
    assert not core.translation_queue()
    with pytest.raises(ValueError):
        core.edit_translation_line(vid, line.id, "번역")
    transcriber.result = TranscriberResult(language, (TranscriptSegment(0, 1, "새 줄"),))
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
print(json.dumps({'spoken_language': 'en', 'segments': [{'start': 0.5, 'end': 2, 'text': 'range'}]}))
''', encoding="utf-8")
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database,
                   transcriber=FasterWhisperTranscriber(tmp_path / "models", command=(sys.executable, str(worker))))
    core.request_subtitle_range(vid, 10, 20)
    assert core.process_next_subtitle().state == "completed"
    assert core.transcript(vid).lines[1].start == 10.5
