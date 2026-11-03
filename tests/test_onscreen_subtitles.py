"""화면 자막: 가짜 미디어(영역 이미지 순서열)와 가짜 OCR 엔진을 끼운 실제 DB·대기열의 공개 동작."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil

import pytest

from legacy_schema import replace_with_frozen
from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.library import LIBRARY_DB_VERSION
from my_video_manager.onscreen_subtitles import (NO_TEXT_NOTICE, OcrLanguageUnavailable, RegionImage, RegionRect,
                                                 SAMPLES_PER_SECOND, images_similar)
from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE, TRANSCRIPTION
from test_backup import apply


NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
BAND = RegionRect(0.1, 0.75, 0.8, 0.2)
WIDTH, HEIGHT = 16, 4


# 그림 → 그 그림에 보이는 글자. 가짜 OCR 엔진이 이 대응으로 읽는다.
SHOWN = {}


def image(text):
    """글자마다 화소가 크게 다른 영역 이미지(글자의 해시로 칠함). 빈 글자는 검은 그림이다."""
    pixels = hashlib.shake_256(text.encode()).digest(WIDTH * HEIGHT) if text else bytes(WIDTH * HEIGHT)
    SHOWN[pixels] = text
    return RegionImage(WIDTH, HEIGHT, pixels)


class FakeMedia:
    """영상 시각마다 그때 보이는 자막의 영역 이미지를 내보낸다."""

    def __init__(self, duration=100.0):
        self.duration = duration
        self.captions = ()  # (보이기 시작, 사라짐, 글자)
        self.misread = {}  # 장 번호 → 다르게 읽히는 글자(잡음)
        self.hook = None  # 장마다 부르는 함수(장 번호)
        self.error_at = None
        self.calls = []

    def read(self, path):
        return MediaInfo(self.duration, "matroska", 1280, 720)

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")

    def region_frames(self, path, region, *, fps, cancellation):
        self.calls.append((Path(path), region, fps))
        for index in range(round(self.duration * fps)):
            if cancellation.is_set():
                return
            if self.error_at == index:
                raise RuntimeError("Invalid data found when processing input")
            if self.hook:
                self.hook(index)
            seconds = index / fps
            text = self.misread.get(index) or next((t for start, end, t in self.captions if start <= seconds < end), "")
            yield seconds, image(text)


class FakeOcr:
    def __init__(self, languages=("en",)):
        self.languages = set(languages)
        self.calls = 0

    def language_available(self, language):
        return language in self.languages

    def missing_language_guidance(self, language):
        return f"{language} 언어 팩을 설치하세요."

    def read_text(self, image, language):
        self.calls += 1
        return "  " + SHOWN[image.pixels] + " \n"  # 정규화를 거쳐 저장되는지도 본다.


@pytest.fixture
def setup(tmp_path):
    folder = tmp_path / "영상"
    folder.mkdir()
    for name in ("a", "b"):
        (folder / f"{name}.mkv").write_bytes(name.encode())
    media, ocr = FakeMedia(), FakeOcr()
    core = AppCore(media=media, clock=lambda: NOW, ocr_engine=ocr, database=tmp_path / "data/library.sqlite3")
    core.add_watched_folder(folder)
    core.scan()
    return core, media, ocr, core.videos()


def reopen(core, media, ocr):
    return AppCore(media=media, clock=lambda: NOW, ocr_engine=ocr, database=core.database)


def lines(core, video_id):
    return [(line.start, line.end, line.text) for subtitle in core.onscreen_subtitles(video_id)
            for line in subtitle.lines]


def test_same_text_frames_merge_into_lines_within_quarter_second_and_survive_restart(setup):
    from test_onscreen_translation import Translator
    core, media, ocr, (a, _) = setup
    shown = ((1.1, 2.9, "Hello"), (4.3, 6.05, "World"))
    media.captions = shown
    entry = core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    assert (entry.state, entry.queue_kind) == ("queued", ONSCREEN_SUBTITLE)
    item, = core.subtitle_queue_items()
    assert (item.queue_kind, item.task_label, item.state) == (ONSCREEN_SUBTITLE, "화면 자막", "queued")

    result = core.process_next_onscreen_subtitle()
    assert (result.state, result.line_count) == ("completed", 2)
    saved = lines(core, a.id)
    assert [text for _, _, text in saved] == ["Hello", "World"]
    for (start, end, _), (visible, hidden, _) in zip(saved, shown):
        assert abs(start - visible) <= 1 / SAMPLES_PER_SECOND and abs(end - hidden) <= 1 / SAMPLES_PER_SECOND
    assert media.calls == [(a.locations[0].path, BAND, SAMPLES_PER_SECOND)]
    assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()
    item, = core.subtitle_queue_items()
    assert (item.state, item.task_label, item.error) == ("queued", "화면 번역", None)
    assert core.take_subtitle_queue_completion() is None  # 자동 요청한 화면 번역까지 끝나야 알린다.

    core = AppCore(media=media, clock=lambda: NOW, ocr_engine=ocr, database=core.database, translator=Translator())
    region, = core.onscreen_subtitle_regions(a.id)
    assert (region.rect, region.language) == (BAND, "en")
    assert lines(core, a.id) == saved
    assert core.process_next_translation().state == 'completed'
    item, = core.subtitle_queue_items()
    assert (item.state, item.task_label, item.error) == ('completed', '화면 번역', '화면 자막 2줄')


def test_unchanged_frames_reuse_the_previous_reading(setup):
    core, media, ocr, (a, _) = setup
    media.captions = ((1, 3, "Hello"), (4, 6, "World"))
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    # 400장 가운데 그림이 바뀐 다섯 번(빈 화면 → Hello → 빈 화면 → World → 빈 화면)만 읽는다.
    assert ocr.calls == 5
    assert [text for _, _, text in lines(core, a.id)] == ["Hello", "World"]


@pytest.mark.parametrize("changed,similar", [(0, True), (1, True), (2, True), (3, False), (40, False)])
def test_compression_noise_is_the_same_picture_but_new_strokes_are_not(changed, similar):
    """200×50 영역: 압축 잡음 같은 작은 밝기 변화는 같은 그림이고, 크게 바뀐 화소가 1/5000(2개)을 넘으면 다르다."""
    base = bytes((index * 7) % 200 for index in range(200 * 50))
    noisy = bytearray(value + (index % 21) for index, value in enumerate(base))  # 모든 화소 +0~20
    for index in range(changed):
        noisy[index * 97] = (noisy[index * 97] + 128) % 256
    assert images_similar(RegionImage(200, 50, base), RegionImage(200, 50, bytes(noisy))) is similar


@pytest.mark.parametrize("noise,expected", [
    (1, ["Hello"]), (2, ["Hello"]), (3, ["Hello", "Hell0", "Hello"])])
def test_one_or_two_misread_frames_between_the_same_text_are_bridged(setup, noise, expected):
    core, media, _, (a, _) = setup
    media.captions = ((1, 5, "Hello"),)
    media.misread = {12 + index: "Hell0" for index in range(noise)}
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    saved = lines(core, a.id)
    assert [text for _, _, text in saved] == expected
    assert (saved[0][0], saved[-1][1]) == (1, 5)


def test_neighbouring_readings_of_almost_the_same_text_are_one_line(setup):
    core, media, _, (a, _) = setup
    # 실제 Windows OCR에서 본 경우: 자막이 처음 보인 세 장만 글자 하나를 빠뜨리고 읽었다.
    media.captions = ((2, 4, "Round 1"), (4, 6, "Round 2"), (17, 21, "Goodbye for now"))
    media.misread = {68: "Goodby for now", 69: "Goodby for now", 70: "Goodby for now", 73: "Goodbye for n0w"}
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert lines(core, a.id) == [(2, 4, "Round 1"), (4, 6, "Round 2"), (17, 21, "Goodbye for now")]


def test_same_text_on_both_sides_of_a_long_misread_is_one_line(setup):
    core, media, _, (a, _) = setup
    # 0–2초 바른 글자, 2–2.75초(3장) 오인식, 다시 바른 글자 5초까지: 흔들림을 흡수한 뒤 같은 글자끼리 잇는다.
    media.captions = ((1, 5, "Goodbye for now"),)
    media.misread = {8: "Goodby for now", 9: "Goodby for now", 10: "Goodby for now"}
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert lines(core, a.id) == [(1, 5, "Goodbye for now")]


def test_long_lasting_similar_captions_stay_separate_lines(setup):
    core, media, _, (a, _) = setup
    # 거의 같은 글자라도 각각 충분히 오래 보였으면 OCR 흔들림이 아니라 다른 자막이다.
    media.captions = ((1, 4, "Player 1 wins"), (4, 7, "Player 2 wins"))
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert lines(core, a.id) == [(1, 4, "Player 1 wins"), (4, 7, "Player 2 wins")]


@pytest.mark.parametrize("frames,kept", [(2, False), (3, True)])
def test_very_short_lines_are_dropped(setup, frames, kept):
    core, media, _, (a, _) = setup
    # 앞뒤 글자가 달라 잡음 잇기가 적용되지 않는 사이에 잠깐 보인 줄이다.
    flash = (2, 2 + frames / SAMPLES_PER_SECOND, "Flash")
    media.captions = ((1, 2, "Before"), flash, (flash[1], 4, "After"))
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert lines(core, a.id) == [(1, 2, "Before"), *([flash] if kept else []), (flash[1], 4, "After")]


def test_no_text_is_a_completed_result_not_a_failure(setup):
    core, media, _, (a, _) = setup
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    result = core.process_next_onscreen_subtitle()
    assert (result.state, result.no_text, result.error) == ("completed", True, None)
    subtitle, = core.onscreen_subtitles(a.id)
    assert subtitle.no_text
    item, = core.subtitle_queue_items()
    assert (item.state, item.error) == ("completed", NO_TEXT_NOTICE)
    assert core.take_subtitle_queue_completion() == (0, 0, 0, 1)


def test_missing_language_pack_warns_and_changes_nothing(setup):
    core, media, ocr, (a, _) = setup
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    before = (core.onscreen_subtitle_regions(a.id), core.onscreen_subtitles(a.id))
    assert not core.onscreen_language_available("ja")
    with pytest.raises(OcrLanguageUnavailable, match="일본어.*ja 언어 팩을 설치하세요"):
        core.set_onscreen_subtitle_regions(a.id, [(RegionRect(0, 0, 0.5, 0.2), "ja")])
    with pytest.raises(ValueError, match="한국어"):
        core.set_onscreen_subtitle_regions(a.id, [(BAND, "ko")])
    assert (core.onscreen_subtitle_regions(a.id), core.onscreen_subtitles(a.id)) == before
    assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()


def test_language_pack_removed_after_request_fails_with_guidance_and_retries(setup):
    core, media, ocr, (a, _) = setup
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    ocr.languages.clear()
    result = core.process_next_onscreen_subtitle()
    assert result.state == "failed" and "en 언어 팩을 설치하세요" in result.error_detail
    ocr.languages.add("en")
    assert core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE).retried == 1
    assert core.process_next_onscreen_subtitle().state == "completed"


def test_direct_request_precedes_automatic_targets_and_kinds_queue_separately(setup):
    core, media, _, (a, b) = setup
    core.request_automatic_subtitles(b.id)
    core.request_automatic_subtitles(a.id)
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    assert [(e.video_id, e.queue_kind) for e in core.subtitle_queue(kind=None)] == [
        (a.id, ONSCREEN_SUBTITLE), (b.id, TRANSCRIPTION), (a.id, TRANSCRIPTION)]
    assert [(i.video_id, i.task_label) for i in core.subtitle_queue_items()] == [
        (a.id, "화면 자막"), (b.id, "받아쓰기"), (a.id, "받아쓰기")]


def test_stopping_returns_the_job_to_the_queue_and_resume_reads_again(setup):
    core, media, ocr, (a, _) = setup
    media.captions = ((1, 3, "Hello"),)
    media.hook = lambda index: index == 5 and core.stop_onscreen_subtitle_processing()
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    assert core.process_next_onscreen_subtitle().state == "queued"
    assert [e.state for e in core.subtitle_queue(kind=ONSCREEN_SUBTITLE)] == ["queued"]
    assert core.onscreen_subtitles(a.id) == ()
    assert core.process_next_onscreen_subtitle() is None  # 멈춘 동안에는 다시 시작하지 않는다.
    media.hook = None
    core.resume_subtitle_processing()
    assert core.process_next_onscreen_subtitle().line_count == 1


def test_removing_during_reading_cancels_without_saving(setup):
    core, media, _, (a, _) = setup
    media.captions = ((1, 3, "Hello"),)
    media.hook = lambda index: index == 5 and core.remove_from_subtitle_queue(a.id, kind=ONSCREEN_SUBTITLE)
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == ()
    assert core.onscreen_subtitles(a.id) == ()
    assert core.subtitle_queue_items() == ()


def test_failure_shows_reason_and_retry_reads_again(setup):
    core, media, _, (a, _) = setup
    media.captions = ((1, 3, "Hello"),)
    media.error_at = 3
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    result = core.process_next_onscreen_subtitle()
    assert result.state == "failed" and result.retry_guidance
    item, = core.subtitle_queue_items()
    assert (item.state, item.error) == ("failed", "Invalid data found when processing input")
    assert core.take_subtitle_queue_completion() == (0, 1, 0, 0)
    assert core.process_next_onscreen_subtitle() is None  # 실패는 저절로 다시 읽지 않는다.
    media.error_at = None
    assert core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE).retried == 1
    assert core.process_next_onscreen_subtitle().line_count == 1


def test_interrupted_reading_returns_to_queued_after_restart(setup):
    core, media, ocr, (a, _) = setup

    def crash(index):
        if index == 2:
            raise KeyboardInterrupt

    media.captions, media.hook = ((1, 3, "Hello"),), crash
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    with pytest.raises(KeyboardInterrupt):
        core.process_next_onscreen_subtitle()
    media.hook = None
    core = reopen(core, media, ocr)
    assert [e.state for e in core.subtitle_queue(kind=ONSCREEN_SUBTITLE)] == ["queued"]
    assert core.process_next_onscreen_subtitle().line_count == 1


def test_missing_file_fails_like_transcription_and_retry_is_skipped(setup):
    core, media, _, (a, _) = setup
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    a.locations[0].path.unlink()
    assert core.process_next_onscreen_subtitle().state == "failed"
    result = core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE)
    assert (result.retried, [s.queue_kind for s in result.skipped]) == (0, [ONSCREEN_SUBTITLE])
    with pytest.raises(ValueError):
        core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])


def test_new_region_replaces_the_old_region_and_its_lines(setup):
    core, media, _, (a, b) = setup
    media.captions = ((1, 3, "Hello"),)
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.set_onscreen_subtitle_regions(b.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    core.process_next_onscreen_subtitle()
    old, = core.onscreen_subtitles(a.id)
    other = core.onscreen_subtitles(b.id)
    top = RegionRect(0.6, 0.02, 0.38, 0.1)
    core.set_onscreen_subtitle_regions(a.id, [(top, "en")])
    region, = core.onscreen_subtitle_regions(a.id)
    assert region.rect == top and core.onscreen_subtitles(a.id) == ()
    media.captions = ((2, 4, "Corner"),)
    core.process_next_onscreen_subtitle()
    new, = core.onscreen_subtitles(a.id)
    assert [line.text for line in new.lines] == ["Corner"]
    assert new.id != old.id and {line.id for line in new.lines}.isdisjoint(line.id for line in old.lines)
    assert core.onscreen_subtitles(b.id) == other


@pytest.mark.parametrize("rect", [(0.5, 0.5, 0.6, 0.2), (-0.1, 0, 0.5, 0.5), (0, 0, 0.005, 0.5),
                                  (0, 0, float("nan"), 0.5)])
def test_region_outside_the_frame_or_too_small_is_rejected(rect):
    with pytest.raises(ValueError):
        RegionRect(*rect)


def test_region_and_lines_follow_video_content_when_moved_or_copied(setup, tmp_path):
    core, media, ocr, (a, _) = setup
    media.captions = ((1, 3, "Hello"),)
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    expected = (core.onscreen_subtitle_regions(a.id), core.onscreen_subtitles(a.id))
    elsewhere = tmp_path / "옮긴 곳"
    elsewhere.mkdir()
    copy = shutil.copy2(a.locations[0].path, elsewhere / "복사본.mkv")
    core.add_file(Path(copy))
    a.locations[0].path.unlink()
    core.scan()
    video = core.video(a.id)
    assert [location.path for location in video.locations] == [Path(copy).resolve()]
    assert (core.onscreen_subtitle_regions(a.id), core.onscreen_subtitles(a.id)) == expected
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    assert media.calls[-1][0] == Path(copy).resolve()


def test_backup_restore_round_trip_keeps_regions_and_lines(setup, tmp_path):
    core, media, ocr, (a, _) = setup
    media.captions = ((1, 3, "Hello"),)
    core.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    core.process_next_onscreen_subtitle()
    expected = (core.onscreen_subtitle_regions(a.id), core.onscreen_subtitles(a.id))
    archive = core.create_backup(tmp_path / "onscreen.zip").path
    media.captions = ((5, 7, "Changed"),)
    core.set_onscreen_subtitle_regions(a.id, [(RegionRect(0, 0, 0.5, 0.2), "en")])
    core.process_next_onscreen_subtitle()
    core.request_backup_restore(archive)
    assert apply(core.database).status == "applied"
    restored = reopen(core, media, ocr)
    assert (restored.onscreen_subtitle_regions(a.id), restored.onscreen_subtitles(a.id)) == expected


def test_v7_library_migrates_with_automatic_backup_and_accepts_regions(setup):
    core, media, ocr, (a, _) = setup
    core.request_subtitles(a.id)
    replace_with_frozen(core.database, 7)
    migrated = reopen(core, media, ocr)
    automatic, = migrated.automatic_backups()
    assert migrated.inspect_backup(automatic).db_version == 7
    assert [e.video_id for e in migrated.subtitle_queue()] == [a.id]
    media.captions = ((1, 3, "Hello"),)
    migrated.set_onscreen_subtitle_regions(a.id, [(BAND, "en")])
    assert migrated.process_next_onscreen_subtitle().line_count == 1
    assert migrated.create_backup(core.database.parent / "after.zip").metadata.db_version == LIBRARY_DB_VERSION
