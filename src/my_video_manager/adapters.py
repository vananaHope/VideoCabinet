"""ffmpeg와 libmpv에 대한 외부 어댑터."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .core import Command, CommandType, MediaInfo


def executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # winget 설치 직후 아직 부모 프로세스의 PATH가 갱신되지 않은 경우.
    if sys.platform == "win32":
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        for match in packages.glob(f"Gyan.FFmpeg_*/**/{name}.exe"):
            return str(match)
    raise RuntimeError(f"{name}를 찾을 수 없습니다. README의 환경 준비 절차를 실행하세요.")


class FFmpegMediaReader:
    def __init__(self):
        self.ffprobe = executable("ffprobe")
        self.ffmpeg = executable("ffmpeg")

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("미디어 처리 제한 시간(120초)을 초과했습니다.") from error

    def read(self, path: Path) -> MediaInfo | None:
        result = self._run([self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
        if result.returncode:
            # 일반 문서는 무시하고, 흔한 영상 확장자의 손상은 사용자에게 알린다.
            if path.suffix.lower() in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts", ".m2ts"}:
                raise RuntimeError(result.stderr.strip() or "영상 정보를 읽을 수 없습니다.")
            return None
        data = json.loads(result.stdout)
        streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"
                   and not s.get("disposition", {}).get("attached_pic")]
        if not streams:
            return None
        duration = float(data.get("format", {}).get("duration") or streams[0].get("duration") or 0)
        if duration <= 0:
            return None  # 이미지 등 재생 시간이 없는 입력은 영상으로 등록하지 않는다.
        return MediaInfo(duration, data["format"]["format_name"])

    def capture(self, path: Path, destination: Path, seconds: float) -> None:
        result = self._run([self.ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", str(seconds),
                            "-i", str(path), "-map", "0:V:0", "-frames:v", "1", "-vf", "scale=320:-2",
                            "-update", "1", str(destination)])
        if result.returncode or not destination.is_file():
            raise RuntimeError(result.stderr.strip() or "썸네일을 캡처할 수 없습니다.")


class MpvPlayer:
    def __init__(self, window_id: int):
        if sys.platform == "win32":
            runtime = Path(__file__).resolve().parents[2] / ".runtime/mpv"
            os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
        import mpv

        self._player = mpv.MPV(wid=str(window_id), input_default_bindings=False,
                               input_vo_keyboard=False, osc=False, config=False, keep_open=True)

    def play(self, path: Path) -> None:
        self._player.play(str(path))
        self._player.pause = False

    def execute(self, command: Command) -> None:
        if command.kind == CommandType.TOGGLE_PAUSE:
            self._player.cycle("pause")
        elif command.kind == CommandType.SEEK:
            self._player.command("seek", command.amount, "relative+exact")
        elif command.kind == CommandType.CHANGE_SPEED:
            self._player.speed = max(0.25, min(100, self._player.speed + command.amount))

    def close(self) -> None:
        self._player.terminate()
