"""공개 AppCore 선택 영상 조회로 자막·번역·하이라이트 요약과 기록 보존을 검증한다."""

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
        return TranscriberResult("en", (TranscriptSegment(0, 5, "Hello"), TranscriptSegment(5, 10, "World")), model="large-v3")


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
    initial = core.library_details(video.id)
    with pytest.raises(ValueError):
        core.library_details(video.id + 999)
    assert not initial.has_transcript and initial.highlight_count == 0
    assert initial.subtitle_state is None and initial.translation_state is None
    core.playback.start(video.id, 0)
    core.execute_highlight_command(Command(CommandType.POINT_HIGHLIGHT))
    core.playback.end()
    core.request_subtitles(video.id, "en")
    queued = core.library_details(video.id)
    assert queued.subtitle_state == "queued" and queued.highlight_count == 1
    core.process_next_subtitle()
    original = core.library_details(video.id)
    assert original.has_transcript and original.spoken_language == "en"
    assert original.original_lines == 2 and original.translated_lines == 0
    assert original.subtitle_state is None and original.translation_state == "queued"
    core.process_next_translation()
    translated = core.library_details(video.id)
    assert translated.translated_lines == 2 and translated.translation_state is None
    path.unlink()
    core.scan()
    assert core.video(video.id).missing
    assert core.library_details(video.id) == translated
    core.exclude_video(video.id)
    assert core.library_details(video.id) == translated
    core.restore_video(video.id)
    assert core.library_details(video.id) == translated


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
    summary = core.library_details(video.id)
    assert summary.original_lines == 2 and summary.translated_lines == 1
    assert summary.translation_state == "held"
    assert summary.translated_lines == sum(line.translation is not None for line in core.review_lines(video.id))


@pytest.mark.parametrize("language", [None, "ko", "ja"])
def test_empty_transcript_summary_matches_public_language_semantics(tmp_path, language):
    class SilentTranscriber:
        def transcribe(self, *args, **kwargs):
            return TranscriberResult("en", (), model="large-v3")
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=SilentTranscriber(),
                   translator=Translator())
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    core.request_subtitles(video.id, language)
    assert core.process_next_subtitle().no_speech
    summary = core.library_details(video.id)
    assert summary.has_transcript
    assert summary.original_lines == 0
    assert summary.spoken_language == core.transcript(video.id).spoken_language == language
    # 자동 감지와 원어 직접 지정 모두 말소리 없음이며, 번역·다듬기는 원어 줄이 없어 등록하지 않는다.
    assert summary.no_speech and core.transcript(video.id).no_speech
    assert summary.translation_skip_reason == "no_speech"
    assert summary.translation_state is None and core.translation_queue() == ()
    # 다시 받아쓰기(원어 직접 지정 포함)는 그대로 요청할 수 있다.
    assert core.request_subtitles(video.id, "en").state == "queued"


def test_spoken_transcripts_are_not_no_speech_and_unknown_language_reason(tmp_path):
    class Uncertain(Transcriber):
        probability = 1.0

        def transcribe(self, *args, **kwargs):
            result = super().transcribe(*args, **kwargs)
            return TranscriberResult(result.spoken_language, result.segments, self.probability, model="large-v3")
    transcriber = Uncertain()
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=transcriber, translator=Translator())
    path = tmp_path / "영상.mkv"
    path.write_bytes(b"video")
    core.add_file(path)
    video, = core.videos()
    core.request_subtitles(video.id)
    assert not core.process_next_subtitle().no_speech
    spoken = core.library_details(video.id)
    assert not spoken.no_speech and spoken.translation_skip_reason is None
    assert spoken.original_lines == 2 and spoken.translation_state == "queued"
    core.remove_from_subtitle_queue(video.id)
    transcriber.probability = 0.2
    core.request_subtitles(video.id)
    core.process_next_subtitle()
    unknown = core.library_details(video.id)
    assert not unknown.no_speech and unknown.spoken_language is None
    assert unknown.translation_skip_reason == "unknown_language"


def test_snapshot_and_recommendations_do_not_read_details_and_selected_summaries_are_isolated(tmp_path, monkeypatch):
    core = AppCore(media=Media(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3", transcriber=Transcriber())
    for name in ("a", "b"):
        path = tmp_path / f"{name}.mkv"
        path.write_bytes(name.encode())
        core.add_file(path)
    a, b = core.videos()
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    assert core.library_details(a.id).original_lines == 2
    assert not core.library_details(b.id).has_transcript
    assert core.library_details(b.id).translated_lines == 0
    monkeypatch.setattr(core, "library_details", lambda *_: pytest.fail("목록에서 상세 조회"))
    assert core.library_snapshot().videos == core.videos()
    core.recommendations()
