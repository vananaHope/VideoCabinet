"""ffmpeg와 libmpv에 대한 외부 어댑터."""

from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .core import Command, CommandType, MediaInfo, playback_speed
from .media import parse_ffprobe_result


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
        return parse_ffprobe_result(result.stdout, suffix=path.suffix,
                                    returncode=result.returncode, error=result.stderr)

    def capture(self, path: Path, destination: Path, seconds: float) -> None:
        result = self._run([self.ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", str(seconds),
                            "-i", str(path), "-map", "0:V:0", "-frames:v", "1", "-vf", "scale=320:-2",
                            "-update", "1", str(destination)])
        if result.returncode or not destination.is_file():
            raise RuntimeError(result.stderr.strip() or "썸네일을 캡처할 수 없습니다.")


@lru_cache(maxsize=1)
def _prepare_mpv_runtime():
    if sys.platform == "win32":
        runtime = Path(__file__).resolve().parents[2] / ".runtime/mpv"
        if runtime.is_dir():
            # python-mpv의 ctypes.find_library 검색에는 PATH도 필요하다.
            # 캐시에 DLL 핸들을 보관해 등록을 유지하고, 프로세스당 한 번만 설정한다.
            os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
            return os.add_dll_directory(str(runtime))
    return None


class MpvPlayer:
    def __init__(self, window_id: int):
        _prepare_mpv_runtime()
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
            self._player.speed = playback_speed(self._player.speed, command.amount)

    def close(self) -> None:
        self._player.terminate()
