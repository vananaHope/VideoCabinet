from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
import sqlite3

import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine, TranslationCancelled, TranslationError
from my_video_manager.translation_cli import classify_cli_failure


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

    def translate(self, lines, language, *, cli, cancellation, model="", effort=""):
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


def test_completed_translation_direct_request_joins_after_waiting_video(setup):
    core, _, _, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    core.promote_subtitle(a.id)
    finish(core)
    source(core, b.id)
    core.request_translation(a.id)
    assert [entry.video_id for entry in core.translation_queue()] == [b.id, a.id]


@pytest.mark.parametrize("source_edit", [False, True])
def test_legacy_completed_order_does_not_leak_into_new_direct_request(setup, source_edit):
    core, _, _, _, reopen = setup
    a, b = core.videos()
    transcript = source(core, a.id)
    core.promote_subtitle(a.id)
    finish(core)
    # 공개 API가 정리하는 옛 완료 순번 행만 복원해 업그레이드 전 DB를 재현한다.
    with sqlite3.connect(core.database) as db:
        db.execute("INSERT INTO subtitle_queue_order(video_id, automatic, promoted) VALUES (?, 0, 1)", (a.id,))
    db.close()
    core = reopen()
    source(core, b.id)
    if source_edit:
        core.edit_transcript_line(a.id, transcript.lines[0].id, "edited source")
    else:
        core.request_translation(a.id)
    assert [entry.video_id for entry in core.translation_queue()] == [b.id, a.id]


@pytest.mark.parametrize("source_edit", [False, True])
def test_removed_translation_new_direct_request_joins_after_waiting_video(setup, source_edit):
    core, _, _, _, _ = setup
    a, b = core.videos()
    transcript = source(core, a.id)
    source(core, b.id)
    core.promote_subtitle(a.id)
    core.remove_from_subtitle_queue(a.id)
    if source_edit:
        core.edit_transcript_line(a.id, transcript.lines[0].id, "edited source")
    else:
        core.request_translation(a.id)
    assert [entry.video_id for entry in core.translation_queue()] == [b.id, a.id]


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


def test_cli_setting_defaults_persists_and_is_used_for_next_job(setup):
    core, _, adapter, _, reopen = setup
    assert core.translation_cli == "codex"
    source(core, core.videos()[0].id)
    core.process_next_translation()
    core.set_translation_cli("claude")
    core = reopen()
    assert core.translation_cli == "claude"
    assert core.settings.get("translation.cli") == "claude"
    core.process_next_translation()
    assert [call[2] for call in adapter.calls] == ["codex", "codex"]
    with pytest.raises(ValueError):
        core.set_translation_cli("unknown")
    assert core.translation_cli == "claude"
    core.settings.reset("translation.cli")
    assert core.translation_cli == "codex"


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


@pytest.mark.parametrize("sensitive", [
    "API_KEY=private-key-value",
    '"access_token": "private-token-value"',
    "Authorization: Bearer private-bearer-value",
    "sk-private-key-value",
    r"C:\Users\PrivateName\cli\config.json",
    r"C:\Users\Private Name\cli\config.json",
    '"C:\\Users\\Private Name\\cli\\config.json"',
    "/home/private-name/.config/cli.json",
    "/home/private name/.config/cli.json",
    r"\\private-server\private-share\config.json",
])
def test_queue_failure_detail_is_readable_and_redacted_after_restart(setup, sensitive):
    from my_video_manager.web_queue_data import row_data

    core, _, adapter, _, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    adapter.error = TranslationError("other", f"segfault in helper xyz; {sensitive}\nexit code 3")
    assert core.process_next_translation().state == "failed"
    for current in (core, reopen()):
        entry, = current.subtitle_queue_items()
        message = row_data(entry)["message"]
        assert "segfault in helper xyz" in message
        assert "exit code 3" in message
        assert "번역에 실패" in message
        assert sensitive not in message
        assert "private" not in message.lower()
        assert "[가림]" in message


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
    assert core.playback_subtitle_language == "translated"
    assert "번역" in core.playback_subtitle(a.id).read_text(encoding="utf-8")
    assert core.toggle_subtitle_language() == (True, "원어 자막")
    assert core.playback_subtitle_language == "original"
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
        def translate(self, lines, language, *, cli, cancellation, model="", effort=""):
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


def test_usage_limit_pauses_all_videos_until_cli_deadline_even_after_restart_and_retry(setup):
    core, _, adapter, time, reopen = setup
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id)
    adapter.error = TranslationError("usage_limit", "rate limit")
    assert core.process_next_translation().state == "held"
    adapter.error = None
    core = reopen()
    core.request_translation(a.id)
    assert core.process_next_translation() is None
    assert not core.translation_ready()
    assert len(adapter.calls) == 1
    # 원어를 다시 만들어 한도 오류를 받은 작업이 없어져도 CLI 전체 보류는 남는다.
    source(core, a.id)
    time[0] += timedelta(minutes=14, seconds=59)
    assert reopen().process_next_translation() is None
    time[0] += timedelta(seconds=1)
    finish(core)
    assert core.translation(a.id) and core.translation(b.id)


def test_each_cli_keeps_its_own_usage_deadline_and_can_resume_held_video(setup):
    core, _, adapter, time, reopen = setup
    source(core, core.videos()[0].id)
    adapter.error = TranslationError("usage_limit", "limit")
    assert core.process_next_translation().state == "held"
    time[0] += timedelta(minutes=5)
    core.set_translation_cli("claude")
    assert not core.translation_ready()  # 기존 작업은 시작할 때의 Codex를 유지한다.
    core.request_translation(core.videos()[0].id)  # 직접 재시도는 새 설정으로 시작한다.
    assert core.translation_ready()
    assert core.process_next_translation().state == "held"
    assert [call[2] for call in adapter.calls] == ["codex", "claude"]
    core = reopen()
    time[0] += timedelta(minutes=10)
    assert not core.translation_ready()  # claude는 아직 5분 남았다.
    core.set_translation_cli("codex")
    assert not core.translation_ready()
    core.request_translation(core.videos()[0].id)
    assert core.translation_ready()
    adapter.error = None
    finish(core)
    assert core.translation(core.videos()[0].id)


@pytest.mark.parametrize("kind", ["authentication", "missing_cli", "format", "other", "timeout"])
def test_one_failed_video_does_not_block_other_videos(setup, kind):
    core, _, adapter, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id)
    adapter.error = TranslationError(kind, "failure")
    assert core.process_next_translation().state == "failed"
    adapter.error = None
    assert all(result.video_id == b.id for result in finish(core))
    assert core.translation(b.id) and core.translation(a.id) is None


def test_n1_output_limit_does_not_repeatedly_hold_all_videos(setup):
    core, _, adapter, time, _ = setup
    a, b = core.videos()
    transcript = source(core, a.id)
    source(core, b.id)
    a_ids = {line.id for line in transcript.lines}

    def translate(lines):
        if lines[0].id in a_ids:
            message = "Partial reply. The last attempt reached the limit while still thinking…"
            raise TranslationError(classify_cli_failure(message), message)
        return tuple(TranslatedLine(line.id, "번역") for line in lines)

    adapter.response = translate
    for _ in range(4):
        finish(core)
        time[0] += timedelta(minutes=15)
    assert core.translation(b.id) is not None
    assert core.translation_queue()[0].state == "failed"
    assert sum(call[0][0].id in a_ids for call in adapter.calls) == 1


def test_queued_video_precedes_repeatedly_held_video_after_cli_cooldown(setup):
    core, _, adapter, time, reopen = setup
    a, b = core.videos()
    transcript = source(core, a.id)
    source(core, b.id)
    a_ids = {line.id for line in transcript.lines}

    def translate(lines):
        if lines[0].id in a_ids:
            raise TranslationError("usage_limit", "possibly misclassified diagnostic")
        return tuple(TranslatedLine(line.id, "번역") for line in lines)

    adapter.response = translate
    assert core.process_next_translation().state == "held"
    assert not core.translation_ready()
    time[0] += timedelta(minutes=15)
    core = reopen()
    for _ in range(3):
        assert core.process_next_translation().video_id == b.id
    assert core.translation(b.id) is not None
    assert core.process_next_translation().state == "held"


def test_repeated_usage_limit_stops_after_three_attempts_across_restarts(setup):
    core, _, adapter, time, reopen = setup
    video = core.videos()[0]
    source(core, video.id)
    core.process_next_translation()
    adapter.error = TranslationError("usage_limit", "You've hit your usage limit")
    for expected in ("held", "held", "failed"):
        core = reopen()
        result = core.process_next_translation()
        assert result.state == expected
        assert result.completed_lines == 2
        assert not core.translation_ready()
        time[0] += timedelta(minutes=15)
    assert "반복" in result.error and "재시도" in result.error
    assert result.retry_at is None
    assert result.error_detail == adapter.error.detail
    assert reopen().process_next_translation() is None
    assert len(adapter.calls) == 4  # 성공한 첫 묶음 + 한도 오류 3회
    core.request_translation(video.id)
    assert core.process_next_translation().state == "held"  # 명시적 재시도는 횟수를 초기화한다.
    time[0] += timedelta(minutes=15)
    adapter.error = None
    finish(core)
    assert core.translation(video.id) is not None


def test_successful_batch_resets_consecutive_usage_limit_count(setup):
    core, _, adapter, time, _ = setup
    source(core, core.videos()[0].id)
    for _ in range(2):
        adapter.error = TranslationError("usage_limit", "usage_limit")
        assert core.process_next_translation().state == "held"
        time[0] += timedelta(minutes=15)
    adapter.error = None
    assert core.process_next_translation().completed_lines == 2
    adapter.error = TranslationError("usage_limit", "usage_limit")
    assert core.process_next_translation().state == "held"


def test_setting_change_does_not_reset_running_job_usage_limit_count(setup):
    core, _, adapter, time, reopen = setup
    source(core, core.videos()[0].id)
    adapter.error = TranslationError("usage_limit", "usage_limit")
    for cli in ("codex", "claude"):
        core.set_translation_cli(cli)
        assert core.process_next_translation().state == "held"
        time[0] += timedelta(minutes=15)
    core = reopen()
    assert core.process_next_translation().state == "failed"
    assert [call[2] for call in adapter.calls] == ["codex"] * 3


def test_usage_limit_from_replaced_request_still_holds_cli_without_stale_attempts(setup):
    core, _, adapter, time, _ = setup
    video = core.videos()[0]
    source(core, video.id)

    def replace_then_fail(lines):
        source(core, video.id)
        raise TranslationError("usage_limit", "usage_limit")

    adapter.response = replace_then_fail
    assert core.process_next_translation() is None
    assert not core.translation_ready()
    time[0] += timedelta(minutes=15)
    adapter.response = None
    finish(core)
    assert core.translation(video.id) is not None


def test_series_switch_to_resets_language_and_keeps_translations_with_their_video(setup):
    core, _, adapter, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    finish(core)
    adapter.prefix = "다른 영상"
    source(core, b.id)
    finish(core)
    core.create_series("번역 시리즈", (a.id, b.id))
    core.switch_to(a.id)
    core.toggle_subtitle_language()
    assert "번역" in core.playback_subtitle(a.id).read_text(encoding="utf-8")
    target = core.adjacent_video(a.id, (b.id, a.id), forward=True)
    assert target == b.id
    core.switch_to(target)
    assert "다른 영상" not in core.playback_subtitle(b.id).read_text(encoding="utf-8")
    assert core.toggle_subtitle_language() == (True, "번역 자막")
    assert core.playback_subtitle_language == "translated"
    assert "다른 영상" in core.playback_subtitle(b.id).read_text(encoding="utf-8")
    core.switch_to(core.adjacent_video(b.id, (), forward=False))
    assert "번역" not in core.playback_subtitle(a.id).read_text(encoding="utf-8")
    assert core.command_for_key("PgUp").kind == CommandType.PREVIOUS_VIDEO
    assert core.command_for_key("PgDn").kind == CommandType.NEXT_VIDEO


def test_translation_completion_after_switch_to_does_not_change_new_video_subtitle(setup):
    core, _, _, _, _ = setup
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id, "ko")
    core.switch_to(a.id)
    core.process_next_translation()
    core.switch_to(b.id)
    original = core.playback_subtitle(b.id).read_text(encoding="utf-8")
    finish(core)
    assert core.translation(a.id) is not None
    assert core.translation(b.id) is None
    assert core.toggle_subtitle_language()[0] is False
    assert core.playback_subtitle(b.id).read_text(encoding="utf-8") == original
