from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine, TranslationCancelled, TranslationError


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"image")


class Transcriber:
    result = TranscriberResult("en", tuple(TranscriptSegment(i, i + 1, f"Line {i}") for i in range(5)))

    def transcribe(self, *args, **kwargs):
        return self.result


class Translator:
    def __init__(self):
        self.calls = []
        self.error = None
        self.prefix = "번역"
        self.response = None

    def translate(self, lines, language, *, cli, cancellation):
        self.calls.append((lines, language, cli))
        if self.error:
            raise self.error
        if self.response:
            return self.response(lines)
        return tuple(TranslatedLine(line.id, f"{self.prefix} {line.text}") for line in reversed(lines))


@pytest.fixture
def setup(tmp_path):
    time = [datetime(2026, 10, 14, tzinfo=timezone.utc)]
    transcriber, translator = Transcriber(), Translator()
    database = tmp_path / "data/library.sqlite3"

    def reopen(adapter=translator):
        return AppCore(media=Media(), clock=lambda: time[0], database=database,
                       transcriber=transcriber, translator=adapter, translation_batch_size=2)

    core = reopen()
    folder = tmp_path / "videos"
    folder.mkdir()
    for name in ("a", "b"):
        (folder / f"{name}.mkv").write_text(name)
    core.add_watched_folder(folder)
    core.scan()
    return core, transcriber, translator, time, reopen


def source(core, video_id, language=None):
    core.request_subtitles(video_id, language)
    assert core.process_next_subtitle().state == "completed"
    return core.transcript(video_id)


def finish(core):
    results = []
    while core.translation_ready():
        results.append(core.process_next_translation())
        assert len(results) < 20
    return results


def test_automatic_translation_has_exact_ids_timing_and_atomic_visibility(setup):
    core, _, adapter, _, reopen = setup
    video = core.videos()[0]
    transcript = source(core, video.id)
    assert core.translation_queue()[0].total_lines == 5
    assert core.playback_subtitle(video.id).read_text(encoding="utf-8").find("Line 0") >= 0
    first = core.process_next_translation()
    assert first.state == "queued" and first.completed_lines == 2
    assert core.translation(video.id) is None
    core = reopen()
    assert core.translation_queue()[0].completed_lines == 2
    results = finish(core)
    assert [r.completed_lines for r in results] == [4, 5]
    assert results[-1].state == "completed"
    translated = reopen().translation(video.id)
    assert [(s.id, s.start, s.end) for s in translated.lines] == [(s.id, s.start, s.end) for s in transcript.lines]
    assert [s.text for s in translated.lines] == [f"번역 {s.text}" for s in transcript.lines]
    assert [len(call[0]) for call in adapter.calls] == [2, 2, 1]
    assert core.translation_queue() == ()
    assert core.process_next_translation() is None
    assert list(video.locations[0].path.parent.glob("*.srt")) == []


@pytest.mark.parametrize("language,probability,segments", [
    ("ko", 1, (TranscriptSegment(0, 1, "안녕"),)),
    ("en", 0.2, (TranscriptSegment(0, 1, "noise"),)), ("en", 1, ()),
])
def test_ineligible_transcripts_never_call_translator(setup, language, probability, segments):
    core, transcriber, adapter, _, reopen = setup
    transcriber.result = TranscriberResult(language, segments, probability)
    video = core.videos()[0]
    transcript = source(core, video.id)
    assert not transcript.translation_eligible
    assert reopen().translation_queue() == ()
    assert core.process_next_translation() is None
    with pytest.raises(ValueError):
        core.request_translation(video.id)
    assert not adapter.calls


def test_cli_setting_defaults_persists_and_is_used_for_next_batch(setup):
    core, _, adapter, _, reopen = setup
    assert core.translation_cli == "codex"
    source(core, core.videos()[0].id)
    core.process_next_translation()
    core.set_translation_cli("claude")
    core = reopen()
    assert core.translation_cli == "claude"
    core.process_next_translation()
    assert [call[2] for call in adapter.calls] == ["codex", "claude"]
    with pytest.raises(ValueError):
        core.set_translation_cli("unknown")
    assert core.translation_cli == "claude"


def test_usage_limit_preserves_progress_and_retries_only_after_due_time(setup):
    core, _, adapter, time, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    core.process_next_translation()
    adapter.error = TranslationError("usage_limit", "You've hit your usage limit")
    held = core.process_next_translation()
    assert held.state == "held" and held.completed_lines == 2
    assert held.retry_at == time[0] + timedelta(minutes=15)
    assert "보류" in held.error
    core = reopen()
    assert core.translation_queue() == (held,)
    assert not core.translation_ready()
    time[0] += timedelta(minutes=14, seconds=59)
    assert core.process_next_translation() is None
    adapter.error = None
    time[0] += timedelta(seconds=1)
    assert core.translation_ready()
    finish(core)
    assert core.translation(video.id)
    assert [line.id for line in adapter.calls[1][0]] == [line.id for line in adapter.calls[2][0]]


@pytest.mark.parametrize("kind", ["authentication", "missing_cli", "other", "timeout"])
def test_other_failures_require_explicit_retry_and_keep_completed_batches(setup, kind):
    core, _, adapter, time, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    core.process_next_translation()
    adapter.error = TranslationError(kind, "detail")
    failed = core.process_next_translation()
    assert failed.state == "failed" and failed.retry_at is None
    assert failed.error_detail == "detail"
    time[0] += timedelta(days=1)
    core = reopen()
    assert core.process_next_translation() is None
    adapter.error = None
    retry = core.request_translation(video.id)
    assert retry.completed_lines == 2
    finish(core)
    assert core.translation(video.id)


@pytest.mark.parametrize("response", [
    lambda lines: (),
    lambda lines: [TranslatedLine(lines[0].id, "a")] * len(lines),
    lambda lines: [TranslatedLine("extra", "a"), TranslatedLine(lines[1].id, "b")],
    lambda lines: [TranslatedLine(line.id, " ") for line in lines],
    lambda lines: None,
])
def test_invalid_ids_counts_text_retry_three_times_then_fail_atomically(setup, response):
    core, _, adapter, _, _ = setup
    video = core.videos()[0]
    source(core, video.id)
    adapter.response = response
    result = core.process_next_translation()
    assert result.state == "failed" and "형식" in result.error
    assert result.completed_lines == 0
    assert len(adapter.calls) == 3
    assert core.translation(video.id) is None


def test_format_retry_recovers_same_batch(setup):
    core, _, adapter, _, _ = setup
    source(core, core.videos()[0].id)
    adapter.response = lambda lines: (() if len(adapter.calls) == 1 else
                                      tuple(TranslatedLine(line.id, "안녕") for line in lines))
    assert core.process_next_translation().completed_lines == 2
    assert adapter.calls[0] == adapter.calls[1]


def test_regeneration_cascades_old_translation_and_staged_progress(setup):
    core, _, adapter, _, reopen = setup
    video = core.videos()[0]
    old = source(core, video.id)
    finish(core)
    core.request_translation(video.id)
    core.process_next_translation()
    core.request_subtitles(video.id, "ja")
    assert core.translation(video.id)
    assert not core.translation_ready()
    assert core.process_next_translation() is None
    core.process_next_subtitle()
    assert core.translation(video.id) is None
    core = reopen()
    assert core.translation_queue()[0].completed_lines == 0
    assert set(s.id for s in old.lines).isdisjoint(s.id for s in core.transcript(video.id).lines)
    finish(core)
    assert core.translation(video.id).transcript_id == core.transcript(video.id).id


def test_retranslation_of_only_selected_line_keeps_other_translations(setup):
    core, _, adapter, _, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    finish(core)
    before = core.translation(video.id)
    adapter.prefix = "수정"
    line_id = before.lines[2].id
    core.request_translation(video.id, [line_id])
    assert core.translation(video.id) == before
    assert core.process_next_translation().state == "completed"
    assert [line.id for line in adapter.calls[-1][0]] == [line_id]
    after = reopen().translation(video.id)
    assert after.lines[:2] == before.lines[:2] and after.lines[3:] == before.lines[3:]
    assert after.lines[2].text.startswith("수정")
    with pytest.raises(ValueError):
        core.request_translation(video.id, ["invalid"])


def test_failed_full_retranslation_keeps_old_result_until_all_new_lines_ready(setup):
    core, _, adapter, _, _ = setup
    video = core.videos()[0]
    source(core, video.id)
    finish(core)
    before = core.translation(video.id)
    adapter.prefix = "수정"
    core.request_translation(video.id)
    core.process_next_translation()
    adapter.error = TranslationError("other", "failure")
    core.process_next_translation()
    assert core.translation(video.id) == before
    adapter.error = None
    core.request_translation(video.id)
    finish(core)
    assert all(s.text.startswith("수정") for s in core.translation(video.id).lines)


def test_subset_request_keeps_unfinished_full_translation_targets(setup):
    core, _, adapter, _, _ = setup
    video = core.videos()[0]
    transcript = source(core, video.id)
    core.process_next_translation()
    core.request_translation(video.id, [transcript.lines[0].id])
    assert core.translation_queue()[0].completed_lines == 1
    finish(core)
    assert core.translation(video.id)


def test_period_policy_keeps_transcript_before_translation_then_toggles_and_resets(setup):
    core, _, _, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    assert core.command_for_key(".") == Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)
    assert not core.toggle_subtitle_language()[0]
    core.playback.start(a.id, 0)
    original = core.playback_subtitle(a.id).read_text(encoding="utf-8")
    changed, message = core.toggle_subtitle_language()
    assert not changed and "아직" in message
    assert core.playback_subtitle(a.id).read_text(encoding="utf-8") == original
    finish(core)
    assert core.playback_subtitle(a.id).read_text(encoding="utf-8") == original
    assert core.toggle_subtitle_language() == (True, "번역 자막")
    assert "번역" in core.playback_subtitle(a.id).read_text(encoding="utf-8")
    assert core.toggle_subtitle_language() == (True, "원어 자막")
    core.toggle_subtitle_language()
    core.playback.start(b.id, 0)
    assert not core.toggle_subtitle_language()[0]
    core.playback.start(a.id, 0)
    assert core.playback_subtitle(a.id).read_text(encoding="utf-8") == original
    core.set_key_bindings({"T": Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)})
    assert core.command_for_key(".") is None
    assert core.command_for_key("T").kind == CommandType.TOGGLE_SUBTITLE_LANGUAGE


def test_regenerating_while_translation_selected_falls_back_to_new_transcript(setup):
    core, transcriber, _, _, _ = setup
    video = core.videos()[0]
    source(core, video.id)
    finish(core)
    core.playback.start(video.id, 0)
    core.toggle_subtitle_language()
    transcriber.result = TranscriberResult("ja", (TranscriptSegment(0, 1, "new source"),))
    source(core, video.id)
    assert "new source" in core.playback_subtitle(video.id).read_text(encoding="utf-8")
    assert not core.toggle_subtitle_language()[0]


def test_translation_worker_does_not_block_transcription_and_discards_stale_response(setup):
    core, _, adapter, _, reopen = setup
    a, b = core.videos()
    source(core, a.id)
    started, release = Event(), Event()

    class Blocking(Translator):
        def translate(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return super().translate(*args, **kwargs)

    core = reopen(Blocking())
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        try:
            assert started.wait(5)
            assert core.process_next_translation() is None
            source(core, b.id)
            source(core, a.id, "ja")
            assert core.playback_location(a.id)
        finally:
            release.set()
        assert future.result(timeout=5) is None
    assert core.translation(a.id) is None
    assert core.translation_queue()[0].completed_lines == 0
    core = reopen()
    finish(core)
    assert core.translation(a.id) and core.translation(b.id)


def test_requesting_transcript_during_translation_waits_even_before_generation_finishes(setup):
    core, _, adapter, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id)
    adapter.response = lambda lines: (core.request_subtitles(a.id), tuple(TranslatedLine(s.id, "번역") for s in lines))[1]
    assert core.process_next_translation() is None
    assert core.translation_queue()[0].completed_lines == 0
    adapter.response = None
    assert core.process_next_translation().video_id == b.id


def test_cancel_and_abnormal_exit_resume_at_last_committed_batch(setup):
    core, _, adapter, _, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    core.process_next_translation()
    adapter.error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        core.process_next_translation()
    core = reopen()
    assert core.translation_queue()[0].completed_lines == 2
    started = Event()

    class Cancellable(Translator):
        def translate(self, lines, language, *, cli, cancellation):
            started.set()
            assert cancellation.wait(5)
            raise TranslationCancelled

    core = reopen(Cancellable())
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        try:
            assert started.wait(5)
        finally:
            core.stop_translation_processing()
        assert future.result(timeout=5).completed_lines == 2
    assert core.process_next_translation() is None
    adapter.error = None
    core = reopen()
    finish(core)
    assert [len(call[0]) for call in adapter.calls] == [2, 2, 2, 1]


def test_one_held_video_does_not_block_other_videos(setup):
    core, _, adapter, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id)
    adapter.error = TranslationError("usage_limit", "rate limit")
    assert core.process_next_translation().state == "held"
    adapter.error = None
    assert all(result.video_id == b.id for result in finish(core))
    assert core.translation(b.id) and core.translation(a.id) is None
