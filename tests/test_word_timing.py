import json
import sys
from types import SimpleNamespace

from my_video_manager import adapters, transcription
from my_video_manager.transcription import TimedWord, split_into_lines


def test_line_uses_first_word_start_and_last_word_end():
    lines = split_into_lines([TimedWord(1.0, 1.4, "こんにちは"), TimedWord(1.4, 2.0, "世界")], "ja")
    assert [(line.start, line.end, line.text) for line in lines] == [(1.0, 2.0, "こんにちは世界")]


def test_gap_at_eight_tenths_starts_new_line():
    lines = split_into_lines([TimedWord(0.0, 1.0, "첫"), TimedWord(1.0, 2.0, "줄"),
                              TimedWord(2.8, 3.4, "다음")], "ko")
    assert [line.text for line in lines] == ["첫줄", "다음"]


def test_shorter_gap_keeps_one_line():
    lines = split_into_lines([TimedWord(0.0, 1.0, "첫"), TimedWord(1.0, 2.0, "줄"),
                              TimedWord(2.79, 3.5, "다음")], "ko")
    assert [line.text for line in lines] == ["첫줄다음"]


def test_line_never_exceeds_seven_seconds():
    words = [TimedWord(float(index), float(index + 1), "가") for index in range(9)]
    lines = split_into_lines(words, "ko")
    assert [(line.start, line.end, line.text) for line in lines] == [(0.0, 7.0, "가" * 7), (7.0, 9.0, "가가")]


def test_cjk_limit_is_twenty_five_characters():
    words = [TimedWord(index * 0.1, index * 0.1 + 0.1, "あ") for index in range(26)]
    lines = split_into_lines(words, "ja")
    assert [len(line.text) for line in lines] == [25, 1]


def test_other_language_limit_is_forty_two_characters_ignoring_spaces():
    words = [TimedWord(index * 0.1, index * 0.1 + 0.1, " a") for index in range(43)]
    lines = split_into_lines(words, "en")
    assert [len(line.text.replace(" ", "")) for line in lines] == [42, 1]
    assert lines[0].text.startswith("a a")


def test_character_limit_split_prefers_last_punctuation():
    words = [TimedWord(0.0, 0.5, "あ" * 10), TimedWord(0.5, 0.6, "。"),
             TimedWord(0.6, 1.1, "い" * 14), TimedWord(1.1, 1.2, "う")]
    lines = split_into_lines(words, "ja")
    assert [line.text for line in lines] == ["あ" * 10 + "。", "い" * 14 + "う"]


def test_backtracked_words_are_checked_again():
    words = [TimedWord(0.0, 0.1, "。"), TimedWord(0.1, 0.2, "い" * 24), TimedWord(0.2, 0.3, "う" * 2)]
    lines = split_into_lines(words, "ja")
    assert [line.text for line in lines] == ["。", "い" * 24, "う" * 2]


def test_single_overlong_word_forms_its_own_line():
    words = [TimedWord(0.0, 1.0, "시작"), TimedWord(1.0, 9.0, "가" * 30), TimedWord(9.0, 10.0, "끝")]
    lines = split_into_lines(words, "ko")
    assert [line.text for line in lines] == ["시작", "가" * 30, "끝"]
    assert lines[1].end - lines[1].start == 8


def test_empty_and_non_positive_lines_are_dropped():
    words = [TimedWord(0.0, 1.0, " "), TimedWord(2.0, 3.0, "남음"),
             TimedWord(4.0, 4.0, "같음"), TimedWord(6.0, 5.0, "역전")]
    lines = split_into_lines(words, "ko")
    assert [line.text for line in lines] == ["남음"]


def test_spaces_follow_original_word_text():
    lines = split_into_lines([TimedWord(0.0, 1.0, " Hello"), TimedWord(1.0, 2.0, " world"),
                              TimedWord(5.0, 6.0, " Next"), TimedWord(6.0, 7.0, " line")], "en")
    assert [line.text for line in lines] == ["Hello world", "Next line"]


def test_split_lines_keep_every_word_in_order():
    words = [TimedWord(index * 0.4, index * 0.4 + 0.3, f" word{index}") for index in range(50)]
    lines = split_into_lines(words, "en")
    assert len(lines) > 1
    assert "".join("".join(line.text.split()) for line in lines) == "".join("".join(word.text.split()) for word in words)


def fake_transcription(monkeypatch, language, segments):
    calls = {}

    class Model:
        def __init__(self, path, **options):
            calls["model"] = (path, options)

        def transcribe(self, audio, **options):
            calls["transcribe"] = options
            return iter(segments), SimpleNamespace(language=language, language_probability=0.75)

    monkeypatch.setattr(transcription, "prepare_cuda_runtime", lambda *arguments: ())
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", SimpleNamespace(decode_audio=lambda path: []))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils",
                        SimpleNamespace(download_model=lambda name, *, cache_dir: "model"))
    return calls


def test_child_entrypoint_passes_word_timestamps_and_balanced_vad(monkeypatch, capsys, tmp_path):
    segment = SimpleNamespace(start=0.0, end=2.0, text="こんにちは世界", words=[
        SimpleNamespace(start=0.0, end=1.0, word="こんにちは"),
        SimpleNamespace(start=1.0, end=2.0, word="世界"),
    ])
    calls = fake_transcription(monkeypatch, "ja", [segment])
    assert transcription.main([str(tmp_path / "영상.mkv"), str(tmp_path / "models"), "auto"]) == 0
    options = calls["transcribe"]
    assert options["word_timestamps"] is True
    assert options["vad_filter"] is True
    assert options["vad_parameters"] == {"threshold": 0.40, "min_speech_duration_ms": 100,
                                         "max_speech_duration_s": 6.0, "min_silence_duration_ms": 300,
                                         "speech_pad_ms": 400}
    assert "neg_threshold" not in options["vad_parameters"]
    assert options["beam_size"] == 5
    assert options["condition_on_previous_text"] is False
    assert options["language"] is None
    payload = json.loads(capsys.readouterr().out)
    assert payload["spoken_language"] == "ja"
    assert payload["segments"] == [{"start": 0.0, "end": 2.0, "text": "こんにちは世界"}]


def test_auto_language_uses_detected_language_for_line_limit(monkeypatch, capsys, tmp_path):
    words = [SimpleNamespace(start=index * 0.1, end=index * 0.1 + 0.1, word="あ") for index in range(26)]
    fake_transcription(monkeypatch, "ja", [SimpleNamespace(start=0.0, end=2.6, text="", words=words)])
    assert transcription.main([str(tmp_path / "영상.mkv"), str(tmp_path / "models"), "auto"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [len(segment["text"]) for segment in payload["segments"]] == [25, 1]


def test_child_entrypoint_applies_range_to_each_split_line(monkeypatch, capsys, tmp_path):
    class Reader:
        ffmpeg = "ffmpeg"

    monkeypatch.setattr(adapters, "FFmpegMediaReader", Reader)
    monkeypatch.setattr(transcription.subprocess, "run", lambda *arguments, **options: SimpleNamespace(stdout=b""))
    words = [SimpleNamespace(start=0.0, end=2.0, word="하나"), SimpleNamespace(start=2.0, end=4.0, word="둘"),
             SimpleNamespace(start=4.5, end=6.0, word="셋"), SimpleNamespace(start=7.0, end=8.0, word="넷")]
    fake_transcription(monkeypatch, "ko", [SimpleNamespace(start=0.0, end=8.0, text="", words=words)])
    assert transcription.main([str(tmp_path / "영상.mkv"), str(tmp_path / "models"), "ko", "10", "5"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["segments"] == [{"start": 0.0, "end": 5.0, "text": "하나둘셋"}]


def test_child_entrypoint_keeps_segment_without_word_timestamps(monkeypatch, capsys, tmp_path):
    fake_transcription(monkeypatch, "ko", [SimpleNamespace(start=1.0, end=2.0, text=" 대체 ", words=None)])
    assert transcription.main([str(tmp_path / "영상.mkv"), str(tmp_path / "models"), "ko"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["segments"] == [{"start": 1.0, "end": 2.0, "text": "대체"}]
    assert "단어 시각" in captured.err
