"""고정 ffprobe 출력으로 검증할 수 있는 순수 미디어 판정."""

import json
import math

from .core import MediaInfo


VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts", ".m2ts"}


def parse_ffprobe_result(output: str, *, suffix: str, returncode: int = 0, error: str = "") -> MediaInfo | None:
    """GIF·정지 이미지·음성·문서는 건너뛰고, 손상된 영상은 오류로 알린다."""
    if returncode:
        if suffix.lower() in VIDEO_SUFFIXES:
            raise RuntimeError(error.strip() or "영상 정보를 읽을 수 없습니다.")
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exception:
        raise ValueError("ffprobe JSON을 읽을 수 없습니다.") from exception
    media_format = data.get("format", {})
    format_name = media_format.get("format_name", "")
    formats = format_name.split(",")
    if any(name in {"gif", "image2", "image2pipe"} or name.endswith("_pipe") for name in formats):
        return None
    streams = [stream for stream in data.get("streams", [])
               if stream.get("codec_type") == "video"
               and not stream.get("disposition", {}).get("attached_pic")
               and not stream.get("disposition", {}).get("still_image")
               and str(stream.get("nb_frames")) != "1"]
    if not streams:
        return None
    for value in [media_format.get("duration"), *(stream.get("duration") for stream in streams)]:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            return MediaInfo(duration, format_name)
    return None
