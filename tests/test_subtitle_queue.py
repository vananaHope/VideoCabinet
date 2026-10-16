from wait_helpers import UI_READY_TIMEOUT

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from my_video_manager.core import AppCore
from my_video_manager.subtitles import TranscriberCancelled, TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslationError
from test_subtitles import FakeMedia, FakeTranscriber, NOW, setup, reopen
from test_translation import Translator


def test_folder_rule_registration_language_and_no_rescan_requeue(setup):
    core, adapter, (a, b) = setup
    folder = a.locations[0].path.parent
    rule = core.set_auto_subtitle_rule(folder=folder, spoken_language=" JA ")
    assert core.subtitle_queue() == ()
    (folder / "c.mkv").write_bytes(b"new")
    core.scan()
    entry, = core.subtitle_queue()
    assert entry.spoken_language == "ja"
    assert entry.video_id not in (a.id, b.id)
    core.process_next_subtitle()
    core.scan()
    assert core.subtitle_queue() == ()
    assert reopen(core, adapter).auto_subtitle_rules() == (rule,)


def test_scan_uses_starting_rules_and_next_scan_picks_up_changes(setup, tmp_path):
    core, adapter, (a, _) = setup
    folder = a.locations[0].path.parent
    core.set_auto_subtitle_rule(folder=folder, spoken_language="en")

    class ChangingMedia(FakeMedia):
        def read(self, path):
            core.set_auto_subtitle_rule(folder=folder, spoken_language="ja")
            return super().read(path)

    core = AppCore(media=ChangingMedia(), clock=lambda: NOW, database=core.database, transcriber=adapter)
    for name in ("c", "d"):
        (folder / f"{name}.mkv").write_bytes(name.encode())
    assert core.scan().added == 2
    assert [entry.spoken_language for entry in core.subtitle_queue()] == ["en", "en"]
    (folder / "e.mkv").write_bytes(b"e")
    assert core.scan().added == 1
    assert [entry.spoken_language for entry in core.subtitle_queue()] == ["en", "en", "ja"]


def test_existing_confirmation_tag_attachment_and_transcript_skip(setup):
    core, adapter, (a, b) = setup
    tag = core.add_video_tag(a.id, "영어")
    assert core.auto_subtitle_candidates(tag_id=tag.id) == (a.id,)
    core.set_auto_subtitle_rule(tag_id=tag.id, spoken_language="en", include_existing=False)
    assert core.subtitle_queue() == ()
    core.add_video_tag(b.id, "영어")
    assert [e.video_id for e in core.subtitle_queue()] == [b.id]
    core.set_auto_subtitle_rule(tag_id=tag.id, spoken_language="ja", include_existing=True)
    assert [(e.video_id, e.spoken_language) for e in core.subtitle_queue()] == [(b.id, "en"), (a.id, "ja")]
    core.process_next_subtitle()
    core.add_video_tag(b.id, "영어")
    assert [e.video_id for e in core.subtitle_queue()] == [a.id]
    core.delete_tag(tag.id)
    assert core.auto_subtitle_rules() == ()


def test_tag_event_uses_only_tag_rule_even_when_folder_rule_exists(setup):
    core, _, (a, b) = setup
    folder = a.locations[0].path.parent
    tag = core.create_tag("대상")
    first = core.set_auto_subtitle_rule(folder=folder, spoken_language="en")
    core.set_auto_subtitle_rule(tag_id=tag.id, spoken_language="ja")
    core.add_video_tag(a.id, tag.name)
    assert core.subtitle_queue()[0].spoken_language == "ja"
    core.remove_auto_subtitle_rule(first.id)
    core.add_video_tag(b.id, tag.name)
    assert core.subtitle_queue()[1].spoken_language == "ja"


def test_manual_before_automatic_fifo_and_promote_overrides_priority(setup):
    core, adapter, (a, b) = setup
    core.request_automatic_subtitles(a.id, "en")
    core.request_subtitles(b.id, "ja")
    assert [e.video_id for e in core.subtitle_queue()] == [b.id, a.id]
    core.promote_subtitle(a.id)
    core = reopen(core, adapter)
    assert core.process_next_subtitle().video_id == a.id
    assert core.process_next_subtitle().video_id == b.id


def test_automatic_fifo_and_manual_upgrade_never_loses_explicit_language(setup):
    core, _, (a, b) = setup
    core.request_automatic_subtitles(b.id, "en")
    core.request_automatic_subtitles(a.id, "en")
    assert [e.video_id for e in core.subtitle_queue()] == [b.id, a.id]
    core.request_subtitles(a.id, "ja")
    core.request_automatic_subtitles(a.id, "ko")
    assert [(e.video_id, e.spoken_language) for e in core.subtitle_queue()] == [(a.id, "ja"), (b.id, "en")]


def test_active_state_progress_remove_discards_result_and_does_not_preempt(setup):
    core, _, (a, b) = setup
    entered, release = Event(), Event()

    class Reporting(FakeTranscriber):
        def transcribe(self, path, language, *, cancellation, progress):
            progress(25)
            entered.set()
            assert release.wait(5)
            return self.result

    core = reopen(core, Reporting())
    core.request_subtitles(a.id)
    core.request_subtitles(b.id)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_subtitle)
        try:
            assert entered.wait(5)
            item = next(i for i in core.subtitle_queue_items() if i.video_id == a.id)
            assert (item.state, item.progress) == ("transcribing", .25)
            core.promote_subtitle(b.id)
            assert core.process_next_subtitle() is None
            core.remove_from_subtitle_queue(a.id)
        finally:
            release.set()
        future.result(5)
    assert core.transcript(a.id) is None
    assert [e.video_id for e in core.subtitle_queue()] == [b.id]


def test_cancel_then_resume_without_restart(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    core.stop_subtitle_processing()
    core.stop_translation_processing()
    assert core.process_next_subtitle() is None
    core.resume_subtitle_processing()
    assert core.process_next_subtitle().state == "completed"


def test_interrupted_transcribing_is_visible_then_recovered(setup):
    core, adapter, (a, _) = setup

    class Interrupted(FakeTranscriber):
        def transcribe(self, *args, **kwargs):
            raise KeyboardInterrupt

    core = reopen(core, Interrupted())
    core.request_subtitles(a.id)
    with pytest.raises(KeyboardInterrupt):
        core.process_next_subtitle()
    assert core.subtitle_queue()[0].state == "transcribing"
    core = reopen(core, adapter)
    assert core.subtitle_queue()[0].state == "queued"
    assert core.process_next_subtitle().state == "completed"


def translation_core(core, adapter, translator):
    return AppCore(media=FakeMedia(), clock=lambda: NOW, database=core.database,
                   transcriber=adapter, translator=translator, translation_batch_size=1)


def test_unified_translation_progress_held_failure_retry_and_notification(setup):
    core, adapter, (a, b) = setup
    translator = Translator()
    core = translation_core(core, adapter, translator)
    core.request_subtitles(a.id)
    core.request_subtitles(b.id, "ko")
    core.process_next_subtitle()
    core.process_next_subtitle()
    assert core.take_subtitle_queue_completion() is None
    core.promote_subtitle(b.id)
    while any(e.video_id == b.id for e in core.translation_queue()):
        core.process_next_translation()
    translator.error = TranslationError("authentication", "로그인")
    core.process_next_translation()
    assert {i.video_id: i.state for i in core.subtitle_queue_items()} == {a.id: "failed", b.id: "completed"}
    assert core.take_subtitle_queue_completion() == (1, 1, 0)
    assert core.take_subtitle_queue_completion() is None
    assert core.retry_failed_subtitles().retried == 1
    translator.error = None
    assert core.process_next_translation().state == "queued"
    item = next(i for i in core.subtitle_queue_items() if i.video_id == a.id)
    assert (item.state, item.progress) == ("queued", .5)
    assert core.take_subtitle_queue_completion() is None
    core.process_next_translation()
    assert core.take_subtitle_queue_completion() == (1, 0, 0)


def test_retry_all_transcription_failures_and_remove_translation_survives_restart(setup):
    core, adapter, (a, b) = setup
    adapter.error = RuntimeError("GPU")
    core.request_subtitles(a.id)
    core.request_subtitles(b.id)
    core.process_next_subtitle()
    core.process_next_subtitle()
    assert core.retry_failed_subtitles().retried == 2
    adapter.error = None
    core.process_next_subtitle()
    core.process_next_subtitle()
    core.remove_from_subtitle_queue(a.id)
    core = translation_core(core, adapter, Translator())
    assert [e.video_id for e in core.translation_queue()] == [b.id]
    core.request_translation(a.id)
    assert {e.video_id for e in core.translation_queue()} == {a.id, b.id}


def test_translation_active_state_and_promoted_order(setup):
    core, adapter, (a, b) = setup
    entered, release = Event(), Event()

    class Blocking(Translator):
        def translate(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().translate(*args, **kwargs)

    core = translation_core(core, adapter, Blocking())
    core.request_subtitles(a.id)
    core.request_subtitles(b.id)
    core.process_next_subtitle()
    core.process_next_subtitle()
    core.promote_subtitle(b.id)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        try:
            assert entered.wait(5)
            assert next(i for i in core.subtitle_queue_items() if i.video_id == b.id).state == "translating"
            core.remove_from_subtitle_queue(b.id)
        finally:
            release.set()
        future.result(5)
    assert core.translation(b.id) is None


def test_held_translation_prevents_premature_notification(setup):
    core, adapter, (a, _) = setup
    translator = Translator()
    translator.error = TranslationError("usage_limit", "한도")
    core = translation_core(core, adapter, translator)
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    core.process_next_translation()
    assert core.subtitle_queue_items()[0].state == "held"
    assert core.take_subtitle_queue_completion() is None


@pytest.mark.parametrize("kwargs", [{}, {"tag_id": 999}, {"folder": "missing"}, {"folder": ".", "tag_id": 1}])
def test_invalid_rule_rejected(setup, kwargs):
    core, _, _ = setup
    with pytest.raises(ValueError):
        core.set_auto_subtitle_rule(**kwargs)


def test_direct_file_registration_and_missing_excluded_are_not_automatic_targets(setup, tmp_path):
    core, _, (a, b) = setup
    folder = a.locations[0].path.parent
    core.set_auto_subtitle_rule(folder=folder, spoken_language="ko")
    path = folder / "직접 추가.mkv"
    path.write_bytes(b"direct")
    core.add_file(path)
    assert len(core.subtitle_queue()) == 1
    core.exclude_video(a.id)
    b.locations[0].path.unlink()
    core.scan()
    assert core.auto_subtitle_candidates(folder=folder) == ()
    core.remove_watched_folder(folder)
    assert core.auto_subtitle_rules() == ()


def test_remove_active_cancels_only_that_video_and_next_can_run(setup):
    core, adapter, (a, b) = setup
    entered = Event()

    class Cancellable(FakeTranscriber):
        def transcribe(self, path, language, *, cancellation, progress=None):
            if path.name == "a.mkv":
                entered.set()
                assert cancellation.wait(5)
                raise TranscriberCancelled
            return self.result

    core = reopen(core, Cancellable())
    core.request_subtitles(a.id)
    core.request_subtitles(b.id, "ko")
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_subtitle)
        assert entered.wait(5)
        core.remove_from_subtitle_queue(a.id)
        future.result(5)
    assert core.process_next_subtitle().video_id == b.id
    assert core.take_subtitle_queue_completion() is None
    core = translation_core(core, adapter, Translator())
    while core.translation_ready():
        core.process_next_translation()
    assert core.take_subtitle_queue_completion() == (1, 0, 0)
    assert not core.translation_queue()


def test_completed_removal_and_first_tray_notice_survive_restart(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id, "ko")
    core.process_next_subtitle()
    assert core.subtitle_queue_items()[0].state == "queued"
    core = translation_core(core, adapter, Translator())
    while core.translation_ready():
        core.process_next_translation()
    assert core.subtitle_queue_items()[0].state == "completed"
    core.remove_from_subtitle_queue(a.id)
    assert core.acknowledge_tray_notice()
    core = reopen(core, adapter)
    assert core.subtitle_queue_items() == ()
    assert core.transcript(a.id) is not None
    assert not core.acknowledge_tray_notice()
    core.request_subtitles(a.id, "ko")
    assert core.subtitle_queue_items()[0].state == "queued"


def test_progress_from_subprocess_reaches_core_public_queue(setup, tmp_path):
    import sys
    from my_video_manager.transcription import FasterWhisperTranscriber

    core, _, (a, _) = setup
    child = tmp_path / "progress.py"
    observed_signal = tmp_path / "progress-observed"
    child.write_text('''
import json, os, sys, time
from pathlib import Path
Path(os.environ["MVM_TRANSCRIPTION_PROGRESS"]).write_text("40", encoding="ascii")
while not Path(sys.argv[1]).exists():
    time.sleep(.02)
print(json.dumps({"spoken_language": "ko", "segments": []}))
''', encoding="utf-8")
    core = reopen(core, FasterWhisperTranscriber(
        tmp_path / "models", command=(sys.executable, str(child), str(observed_signal))))
    core.request_subtitles(a.id)
    from time import monotonic, sleep
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_subtitle)
        # 고정 1초 노출은 xdist 부하에서 놓칠 수 있다. 공개 큐에서 실제
        # 진행률을 관찰한 뒤 자식을 풀고, 실패해도 finally로 정리한다.
        deadline = monotonic() + UI_READY_TIMEOUT
        observed = False
        try:
            while monotonic() < deadline and not future.done():
                if any(i.state == "transcribing" and i.progress == .4 for i in core.subtitle_queue_items()):
                    observed = True
                    break
                sleep(.02)
        finally:
            observed_signal.touch()
        assert future.result(30).state == "completed"
    assert observed


@pytest.mark.parametrize("language", [None, "ja"])
def test_no_speech_completion_stays_with_notice_and_is_counted_separately(setup, language):
    core, adapter, (a, b) = setup
    core = translation_core(core, adapter, Translator())
    adapter.result = TranscriberResult("nn", (), 0.61)
    core.request_subtitles(a.id, language)
    core.request_subtitles(b.id)
    assert core.process_next_subtitle().no_speech
    adapter.result = TranscriberResult("en", (TranscriptSegment(0, 1, "Hello"),))
    assert not core.process_next_subtitle().no_speech
    while core.translation_ready():
        core.process_next_translation()
    items = {i.video_id: i for i in core.subtitle_queue_items()}
    assert (items[a.id].state, items[a.id].task_label, items[a.id].error) == ("completed", "받아쓰기", "말소리를 찾지 못했습니다.")
    assert items[b.id].state == "completed" and not items[b.id].error
    completion = core.take_subtitle_queue_completion()
    assert completion == (1, 0, 1) and completion.no_speech == 1
