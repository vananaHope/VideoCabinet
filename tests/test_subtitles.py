from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import (TranscriberCancelled, TranscriberResult, TranscriptSegment,
                                       Transcript, TranscriptLine, transcript_srt)


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class FakeMedia:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class FakeTranscriber:
    def __init__(self):
        self.calls = []
        self.result = TranscriberResult("en", (TranscriptSegment(1.25, 3.5, "Hello"),
                                           TranscriptSegment(5, 7, "World")), model="large-v3")
        self.error = None

    def transcribe(self, path, spoken_language, *, cancellation, progress=None):
        self.calls.append((path, spoken_language))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def setup(tmp_path):
    folder = tmp_path / "영상"
    folder.mkdir()
    for name in ("a", "b"):
        (folder / f"{name}.mkv").write_bytes(name.encode())
    adapter = FakeTranscriber()
    core = AppCore(media=FakeMedia(), clock=lambda: NOW, transcriber=adapter,
                   database=tmp_path / "data/library.sqlite3")
    core.add_watched_folder(folder)
    core.scan()
    return core, adapter, core.videos()


def reopen(core, adapter):
    return AppCore(media=FakeMedia(), clock=lambda: NOW, transcriber=adapter, database=core.database)


@pytest.mark.parametrize("no_speech", [False, True])
def test_full_transcription_records_result_model_and_replaces_it_on_regeneration(setup, no_speech):
    core, adapter, (video, _) = setup
    segments = () if no_speech else adapter.result.segments
    for model in ("large-v3", "future-model"):
        adapter.result = TranscriberResult("en", segments, model=model)
        core.request_subtitles(video.id)
        assert core.process_next_subtitle().state == "completed"
        transcript = core.transcript(video.id)
        assert transcript.model == model
        assert transcript.no_speech is no_speech
        core = reopen(core, adapter)
        assert core.transcript(video.id) == transcript


def test_queue_persists_fifo_and_duplicate_request_preserves_order(setup):
    core, adapter, (a, b) = setup
    first = core.request_subtitles(b.id)
    core.request_subtitles(a.id)
    assert core.request_subtitles(b.id) == first
    core = reopen(core, adapter)
    assert [entry.video_id for entry in core.subtitle_queue()] == [b.id, a.id]
    assert core.process_next_subtitle().video_id == b.id
    assert core.process_next_subtitle().video_id == a.id
    assert core.process_next_subtitle() is None
    assert core.subtitle_queue() == ()
    assert [path.name for path, _ in adapter.calls] == ["b.mkv", "a.mkv"]


def test_detected_language_and_stable_lines_survive_reopen_without_sidecar(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    assert core.process_next_subtitle().state == "completed"
    transcript = core.transcript(a.id)
    assert transcript.spoken_language == "en"
    assert not transcript.language_specified
    assert transcript.created_at == NOW
    assert [(line.start, line.end, line.text) for line in transcript.lines] == [(1.25, 3.5, "Hello"), (5, 7, "World")]
    assert len({line.id for line in transcript.lines}) == 2
    assert reopen(core, adapter).transcript(a.id) == transcript
    subtitle = core.playback_subtitle(a.id)
    assert subtitle.is_relative_to(core.database.parent)
    assert "00:00:01,250 --> 00:00:03,500\nHello" in subtitle.read_text(encoding="utf-8")
    assert sorted(path.suffix for path in a.locations[0].path.parent.iterdir()) == [".mkv", ".mkv"]


def test_specifying_language_regenerates_atomically_with_new_line_ids(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    old = core.transcript(a.id)
    request = core.request_subtitles(a.id, " KO ")
    assert request.spoken_language == "ko"
    assert core.transcript(a.id) == old  # 요청만으로 기존 자막을 지우지 않는다.
    core = reopen(core, adapter)
    core.process_next_subtitle()
    new = core.transcript(a.id)
    assert adapter.calls[-1][1] == "ko"
    assert new.spoken_language == "ko" and new.language_specified
    assert {line.id for line in old.lines}.isdisjoint(line.id for line in new.lines)
    core.request_subtitles(a.id)  # 자동 감지로 되돌릴 수 있다.
    core.process_next_subtitle()
    assert not core.transcript(a.id).language_specified
    assert core.transcript(a.id).spoken_language == "en"


def test_failure_keeps_previous_transcript_and_next_request_runs_then_retry(setup):
    core, adapter, (a, b) = setup
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    old = core.transcript(a.id)
    adapter.error = RuntimeError("GPU unavailable")
    core.request_subtitles(a.id, "ko")
    failed = core.process_next_subtitle()
    assert failed.state == "failed" and "GPU unavailable" in failed.error_detail
    assert reopen(core, adapter).subtitle_queue() == (failed,)
    assert core.transcript(a.id) == old
    adapter.error = None
    core.request_subtitles(b.id)
    assert core.process_next_subtitle().video_id == b.id
    assert core.process_next_subtitle() is None
    core.request_subtitles(a.id, "ko")
    assert core.process_next_subtitle().state == "completed"
    assert core.subtitle_queue() == ()


def test_empty_speech_is_success_and_replaces_old_lines(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    adapter.result = TranscriberResult("en", (), model="large-v3")
    core.request_subtitles(a.id)
    assert core.process_next_subtitle().state == "completed"
    assert core.transcript(a.id).lines == ()
    assert core.playback_subtitle(a.id) is None


@pytest.mark.parametrize("language", ["", "english", "../en", "e1"])
def test_invalid_language_does_not_enqueue(setup, language):
    core, _, (a, _) = setup
    with pytest.raises(ValueError):
        core.request_subtitles(a.id, language)
    assert core.subtitle_queue() == ()


def test_unknown_video_rejected(setup):
    core, _, _ = setup
    with pytest.raises(ValueError, match="영상"):
        core.request_subtitles(999)
    assert core.subtitle_queue() == ()
    assert core.transcript(999) is None


@pytest.mark.parametrize("segment", [TranscriptSegment(-1, 2, "a"), TranscriptSegment(2, 1, "a"),
                                    TranscriptSegment(1, float("nan"), "a"), TranscriptSegment(1, 2, " ")])
def test_invalid_adapter_result_does_not_replace_saved_transcript(setup, segment):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    old = core.transcript(a.id)
    adapter.result = TranscriberResult("en", (segment,), model="large-v3")
    core.request_subtitles(a.id)
    assert core.process_next_subtitle().state == "failed"
    assert core.transcript(a.id) == old


def test_busy_transcriber_does_not_block_core_and_new_language_supersedes_result(setup):
    core, adapter, (a, b) = setup
    started, release = Event(), Event()

    class BlockingTranscriber(FakeTranscriber):
        def transcribe(self, path, spoken_language, *, cancellation, progress=None):
            started.set()
            assert release.wait(5)
            return super().transcribe(path, spoken_language, cancellation=cancellation)

    core = reopen(core, BlockingTranscriber())
    core.request_subtitles(a.id)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_subtitle)
        try:
            assert started.wait(5)
            assert core.process_next_subtitle() is None
            assert core.playback_location(a.id) == a.locations[0]
            assert core.command_for_key("/") == Command(CommandType.TOGGLE_SUBTITLES)
            core.request_subtitles(b.id)
            core.request_subtitles(a.id, "ja")
        finally:
            release.set()
        future.result(timeout=5)
    assert core.transcript(a.id) is None
    assert [entry.video_id for entry in core.subtitle_queue()] == [b.id, a.id]
    core.process_next_subtitle()
    core.process_next_subtitle()
    assert core.transcript(a.id).spoken_language == "ja"


def test_interrupted_processing_remains_queued_on_restart(setup):
    core, adapter, (a, _) = setup

    class Interrupted(FakeTranscriber):
        def transcribe(self, path, spoken_language, *, cancellation, progress=None):
            raise KeyboardInterrupt

    core = reopen(core, Interrupted())
    core.request_subtitles(a.id, "ja")
    with pytest.raises(KeyboardInterrupt):
        core.process_next_subtitle()
    core = reopen(core, adapter)
    assert core.subtitle_queue()[0].state == "queued"
    assert core.process_next_subtitle().state == "completed"


def test_subtitle_key_can_be_remapped(setup):
    core, _, _ = setup
    core.set_key_bindings({"S": Command(CommandType.TOGGLE_SUBTITLES)})
    assert core.command_for_key("/") is None
    assert core.command_for_key("S").kind == CommandType.TOGGLE_SUBTITLES


def test_stopping_processing_cancels_adapter_and_preserves_queue_and_old_transcript(setup):
    core, adapter, (a, b) = setup
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    old = core.transcript(a.id)
    started = Event()

    class Cancellable(FakeTranscriber):
        def transcribe(self, path, spoken_language, *, cancellation, progress=None):
            started.set()
            assert cancellation.wait(5)
            raise TranscriberCancelled

    core = reopen(core, Cancellable())
    core.request_subtitles(a.id, "ja")
    core.request_subtitles(b.id)
    pending = core.subtitle_queue()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_subtitle)
        try:
            assert started.wait(5)
        finally:
            core.stop_subtitle_processing()
        assert future.result(timeout=5).state == "queued"
    assert core.subtitle_queue() == pending
    assert core.transcript(a.id) == old
    assert core.process_next_subtitle() is None
    core = reopen(core, adapter)
    assert core.process_next_subtitle().state == "completed"
    assert core.transcript(a.id).spoken_language == "ja"


def test_stop_before_worker_starts_preserves_pending_request(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    pending = core.subtitle_queue()
    core.stop_subtitle_processing()
    assert core.process_next_subtitle() is None
    assert not adapter.calls
    assert core.subtitle_queue() == pending


@pytest.mark.parametrize("probability, segments", [(1, ()), (0.49, (TranscriptSegment(0, 1, "Hello"),))])
def test_unknown_language_is_not_eligible_for_translation(setup, probability, segments):
    core, adapter, (a, _) = setup
    adapter.result = TranscriberResult("nn", segments, probability, model="large-v3")
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    transcript = reopen(core, adapter).transcript(a.id)
    assert transcript.spoken_language is None
    assert not transcript.translation_eligible


@pytest.mark.parametrize("language, probability, expected", [(None, 0.5, "en"), ("ko", 0.1, "ko"), ("ja", 0.1, "ja")])
def test_confident_or_specified_language_is_retained(setup, language, probability, expected):
    core, adapter, (a, _) = setup
    adapter.result = TranscriberResult("en", (TranscriptSegment(0, 1, "Hello"),), probability, model="large-v3")
    core.request_subtitles(a.id, language)
    core.process_next_subtitle()
    transcript = core.transcript(a.id)
    assert transcript.spoken_language == expected
    assert transcript.translation_eligible == (expected != "ko")


@pytest.mark.parametrize("seconds, timestamp", [(0.9995, "00:00:01,000"), (59.9995, "00:01:00,000"),
                                             (3599.9995, "01:00:00,000"), (3661.125, "01:01:01,125")])
def test_srt_rounding_carries_to_minutes_and_hours(seconds, timestamp):
    transcript = Transcript(1, "transcript", "en", False, NOW,
                            (TranscriptLine("line", seconds, seconds + 1, "Hello"),), model="large-v3")
    assert transcript_srt(transcript).startswith(f"1\n{timestamp} --> ")


def test_subtitles_share_playback_with_viewing_and_highlight_keys(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    core.playback.start(a.id, 0)
    core.playback.report(10)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.report(20)
    core.execute_highlight_command(core.command_for_key("Delete"))
    assert core.process_next_subtitle().state == "completed"
    core.playback.report(30)
    core.execute_highlight_command(core.command_for_key("Delete"))
    assert [(h.start, h.end) for h in core.highlights(a.id)] == [(10, None), (20, 30)]
    assert core.execute_highlight_command(core.command_for_key("Home")) == 20
    core.playback.report(15, seeked=True)
    assert core.execute_highlight_command(core.command_for_key("End")) == 20
    assert not core.is_highlight_command(core.command_for_key("/"))
    core.playback.end()
    assert core.viewings(a.id)[0].played_seconds == 30
    assert core.resume_start(a.id) == 12
    assert core.transcript(a.id).lines
