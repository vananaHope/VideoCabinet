"""공개 AppCore 스냅숏으로 자막·번역·하이라이트 요약과 기록 보존을 검증한다."""

from datetime import datetime, timezone
import pytest

from my_video_manager.core import AppCore, Command, CommandType, MediaInfo
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.translation import TranslatedLine, TranslationError


class Media:
    def read(self, path):
        return MediaInfo(100, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


class Transcriber:
    def transcribe(self, *args, **kwargs):
        return TranscriberResult("en", (TranscriptSegment(0, 5, "Hello"), TranscriptSegment(5, 10, "World")))


class Translator:
    def translate(self, lines, *args, **kwargs):
        return tuple(TranslatedLine(line.id, "번역") for line in lines)


def test_summary_tracks_queue_original_translation_highlights_missing_and_excluded(tmp_path):
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=Transcriber(), translator=Translator())
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    initial = core.library_details_map()[video.id]
    assert not initial.has_transcript and initial.highlight_count == 0
    assert initial.subtitle_state is None and initial.translation_state is None
    core.playback.start(video.id, 0)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    core.request_subtitles(video.id, "en")
    queued = core.library_snapshot().details[video.id]
    assert queued.subtitle_state == "queued" and queued.highlight_count == 1
    core.process_next_subtitle()
    original = core.library_details_map()[video.id]
    assert original.has_transcript and original.spoken_language == "en"
    assert original.original_lines == 2 and original.translated_lines == 0
    assert original.subtitle_state is None and original.translation_state == "queued"
    core.process_next_translation()
    translated = core.library_snapshot().details[video.id]
    assert translated.translated_lines == 2 and translated.translation_state is None
    path.unlink()
    core.scan()
    assert core.video(video.id).missing
    assert core.library_details_map()[video.id] == translated
    core.exclude_video(video.id)
    assert video.id not in core.library_details_map()
    core.restore_video(video.id)
    assert core.library_snapshot().details[video.id] == translated


def test_summary_includes_saved_partial_translation_while_held(tmp_path):
    class PartialTranslator(Translator):
        calls = 0

        def translate(self, lines, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise TranslationError("usage_limit", "limit")
            return super().translate(lines, *args, **kwargs)

    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=Transcriber(),
                   translator=PartialTranslator(), translation_batch_size=1)
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    core.request_subtitles(video.id, "en")
    core.process_next_subtitle()
    assert core.process_next_translation().state == "queued"
    assert core.process_next_translation().state == "held"
    summary = core.library_snapshot().details[video.id]
    assert summary.original_lines == 2 and summary.translated_lines == 1
    assert summary.translation_state == "held"
    assert summary.translated_lines == sum(line.translation is not None for line in core.review_lines(video.id))


@pytest.mark.parametrize("language", [None, "ko"])
def test_empty_transcript_summary_matches_public_language_semantics(tmp_path, language):
    class SilentTranscriber:
        def transcribe(self, *args, **kwargs):
            return TranscriberResult("en", ())
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=SilentTranscriber())
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    core.request_subtitles(video.id, language)
    core.process_next_subtitle()
    summary = core.library_details_map()[video.id]
    assert summary.has_transcript
    assert summary.original_lines == 0
    assert summary.spoken_language == core.transcript(video.id).spoken_language
