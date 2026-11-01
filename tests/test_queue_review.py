from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import sys

import pytest

from my_video_manager.translation import TranslationCancelled, TranslationError
from my_video_manager.transcription import FasterWhisperTranscriber
from test_subtitles import setup, reopen
from test_subtitle_queue import translation_core
from test_translation import Translator, setup as translation_setup


def test_unrelated_tag_does_not_apply_declined_folder_rule(setup):
    core, _, (a, _) = setup
    core.set_auto_subtitle_rule(folder=a.locations[0].path.parent, include_existing=False)
    core.add_video_tag(a.id, "아무태그")
    assert core.subtitle_queue() == ()


def test_rename_and_move_do_not_apply_declined_folder_rule(setup):
    core, _, (a, _) = setup
    folder = a.locations[0].path.parent
    core.set_auto_subtitle_rule(folder=folder, include_existing=False)
    moved = folder / "하위"
    moved.mkdir()
    a.locations[0].path.rename(moved / "renamed.mkv")
    core.scan()
    assert core.subtitle_queue() == ()


def test_removed_video_return_does_not_reapply_folder_rule(setup):
    core, _, (a, _) = setup
    path = a.locations[0].path
    core.set_auto_subtitle_rule(folder=path.parent, include_existing=True)
    core.remove_from_subtitle_queue(a.id)
    contents = path.read_bytes()
    path.unlink()
    core.scan()
    path.write_bytes(contents)
    core.scan()
    assert a.id not in {e.video_id for e in core.subtitle_queue()}


def test_existing_video_moving_into_rule_folder_is_not_new(setup, tmp_path):
    core, _, (a, _) = setup
    target = tmp_path / "new-folder"
    target.mkdir()
    core.add_watched_folder(target)
    core.set_auto_subtitle_rule(folder=target)
    a.locations[0].path.rename(target / "moved.mkv")
    core.scan()
    assert core.subtitle_queue() == ()


def test_only_newly_attached_tag_applies_and_duplicate_attachment_is_not_an_event(setup):
    core, _, (a, _) = setup
    tag = core.add_video_tag(a.id, "대상")
    core.set_auto_subtitle_rule(tag_id=tag.id, include_existing=False)
    core.add_video_tag(a.id, "다른 태그")
    core.add_video_tag(a.id, tag.name)
    assert core.subtitle_queue() == ()
    core.remove_video_tag(a.id, tag.id)
    core.add_video_tag(a.id, tag.name)
    assert core.subtitle_queue()[0].video_id == a.id


def test_retry_all_skips_missing_and_reports_reason_but_retries_rest(setup):
    core, adapter, (a, b) = setup
    adapter.error = RuntimeError("GPU")
    for video in (a, b):
        core.request_subtitles(video.id)
        core.process_next_subtitle()
    a.locations[0].path.unlink()
    core.scan()
    result = core.retry_failed_subtitles()
    assert result.retried == 1 and result.skipped_count == 1
    assert result.skipped[0].video_id == a.id and "파일 없음" in result.skipped[0].reason
    assert {e.video_id: e.state for e in core.subtitle_queue()} == {a.id: "failed", b.id: "queued"}


def test_completed_items_are_current_run_only_and_do_not_read_transcript_lines(setup, monkeypatch):
    core, adapter, (a, b) = setup
    core = translation_core(core, adapter, Translator())
    core.request_subtitles(a.id, "ko")
    core.process_next_subtitle()
    while core.translation_ready():
        core.process_next_translation()

    def no_lines(*args):
        raise AssertionError("대기열 화면에서 원어 줄을 읽음")
    # 반환값만으로 전체 자막 읽기 비용을 알 수 없어 공개 조회 경계에만 감시 함수를 둔다.
    monkeypatch.setattr(core, "transcript", no_lines)
    assert [(i.video_id, i.state) for i in core.subtitle_queue_items()] == [(a.id, "completed")]
    assert core.take_subtitle_queue_completion() == (1, 0, 0, 0)
    assert core.take_subtitle_queue_completion() is None
    assert core.subtitle_queue_items()[0].state == "completed"
    core = reopen(core, adapter)
    assert core.subtitle_queue_items() == ()
    adapter.error = RuntimeError("실패")
    core.request_subtitles(b.id)
    core.process_next_subtitle()
    assert reopen(core, adapter).subtitle_queue_items()[0].state == "failed"


def test_translation_failure_retry_resets_promoted_order(setup):
    core, adapter, (a, b) = setup
    translator = Translator()
    core = translation_core(core, adapter, translator)
    for v in (a, b):
        core.request_subtitles(v.id)
    core.promote_subtitle(a.id)
    core.process_next_subtitle()
    core.process_next_subtitle()
    translator.error = TranslationError("authentication", "로그인")
    core.process_next_translation()
    core.request_translation(a.id)
    assert [e.video_id for e in core.translation_queue()] == [b.id, a.id]


def test_held_translation_cancel_retains_state_and_retry_time(translation_setup):
    core, _, translator, time, _ = translation_setup
    video = core.videos()[0]
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    translator.error = TranslationError("usage_limit", "한도")
    held = core.process_next_translation()
    time[0] += timedelta(minutes=16)
    entered = Event()

    def cancel(lines, language, *, cli, cancellation, model="", effort="", context=(), glossary=()):
        entered.set()
        assert cancellation.wait(5)
        raise TranslationCancelled
    translator.translate = cancel
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        assert entered.wait(5)
        core.stop_translation_processing()
        future.result(5)
    pending = core.translation_queue()[0]
    assert pending.state == "held" and pending.retry_at == held.retry_at
    core.resume_subtitle_processing()
    assert core.translation_ready()


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_progress_file_failure_does_not_fail_transcription(setup, tmp_path, failure):
    core, _, (a, _) = setup
    child = tmp_path / "child.py"
    child.write_text("""
import json
import os
from pathlib import Path
from my_video_manager.transcription import report_progress
path = Path(os.environ["MVM_TRANSCRIPTION_PROGRESS"])
(path.with_suffix(".tmp") if FAILURE == "write" else path).mkdir()
report_progress(40)
print(json.dumps({"spoken_language": "ko", "model": "large-v3", "segments": []}))
""".replace("FAILURE", repr(failure)), encoding="utf-8")
    core = reopen(core, FasterWhisperTranscriber(tmp_path / "models", command=(sys.executable, str(child))))
    core.request_subtitles(a.id)
    assert core.process_next_subtitle().state == "completed"


def test_legacy_order_follows_new_direct_requests_and_preserves_relative_order():
    # 순서 없는 옛 항목은 현재 AppCore로 만들 수 없어 이전 버전 호환 정렬을 순수 함수로 검증한다.
    from my_video_manager.subtitle_queue import subtitle_order_key
    positions = {(1, "transcription"): (0, 0, 5), (2, "transcription"): (0, 1, 3),
                 (3, "transcription"): (-1, 1, 2)}
    videos = [8, 9, 2, 1, 3]
    assert sorted(videos, key=lambda video_id: subtitle_order_key(video_id, positions)) == [3, 1, 8, 9, 2]
