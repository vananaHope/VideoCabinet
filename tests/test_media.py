import pytest

from my_video_manager.core import MediaInfo
from my_video_manager.media import parse_ffprobe_result


@pytest.mark.parametrize("suffix, output, expected", [
    (".jpg", '{"format":{"format_name":"image2","duration":"0.040000"},'
     '"streams":[{"codec_type":"video","codec_name":"mjpeg"}]}', None),
    (".jpg", '{"format":{"format_name":"jpeg_pipe"},'
     '"streams":[{"codec_type":"video","codec_name":"mjpeg"}]}', None),
    (".png", '{"format":{"format_name":"png_pipe","duration":"0.04"},'
     '"streams":[{"codec_type":"video","codec_name":"png"}]}', None),
    (".gif", '{"format":{"format_name":"gif","duration":"2.0"},'
     '"streams":[{"codec_type":"video","nb_frames":"20"}]}', MediaInfo(2, "gif")),
    (".gif", '{"format":{"format_name":"gif","duration":"0.1"},'
     '"streams":[{"codec_type":"video","nb_frames":"1"}]}', None),
    (".mp3", '{"format":{"format_name":"mp3","duration":"120.0"},'
     '"streams":[{"codec_type":"audio"}]}', None),
    (".mp3", '{"format":{"format_name":"mp3","duration":"120.0"},'
     '"streams":[{"codec_type":"audio"},'
     '{"codec_type":"video","disposition":{"attached_pic":1}}]}', None),
    (".mkv", '{"format":{"format_name":"matroska,webm","duration":"20.0"},'
     '"streams":[{"codec_type":"video","nb_frames":"1","disposition":{"attached_pic":1}},'
     '{"codec_type":"video","codec_name":"hevc"},'
     '{"codec_type":"audio","codec_name":"ac3"}]}', MediaInfo(20, "matroska,webm")),
    (".mkv", '{"format":{"format_name":"matroska,webm","duration":"20.0"},'
     '"streams":[{"codec_type":"video","disposition":{"attached_pic":1}},'
     '{"codec_type":"audio"}]}', None),
    (".mp4", '{"format":{"format_name":"mov,mp4","duration":"0.04"},'
     '"streams":[{"codec_type":"video","nb_frames":"1"}]}', None),
    (".mp4", '{"format":{"format_name":"mov,mp4","duration":"2"},'
     '"streams":[{"codec_type":"video","disposition":{"still_image":1}}]}', None),
    (".mkv", '{"format":{"format_name":"matroska,webm","duration":"N/A"},'
     '"streams":[{"codec_type":"video","duration":"3.5","nb_frames":"N/A"}]}', MediaInfo(3.5, "matroska,webm")),
    (".mkv", '{"format":{"format_name":"matroska,webm","duration":"0"},'
     '"streams":[{"codec_type":"video"}]}', None),
    (".mkv", '{"format":{"format_name":"matroska,webm","duration":"NaN"},'
     '"streams":[{"codec_type":"video"}]}', None),
])
def test_fixed_ffprobe_media_classification(suffix, output, expected):
    assert parse_ffprobe_result(output, suffix=suffix) == expected


def test_corrupt_video_is_reported():
    with pytest.raises(RuntimeError, match="Invalid data"):
        parse_ffprobe_result("{}", suffix=".MKV", returncode=1, error="Invalid data found when processing input")


def test_unrecognized_document_is_ignored():
    assert parse_ffprobe_result("{}", suffix=".txt", returncode=1, error="Invalid data") is None


def test_invalid_probe_json_is_reported():
    with pytest.raises(ValueError, match="ffprobe JSON"):
        parse_ffprobe_result("not json", suffix=".mkv")
