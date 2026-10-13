"""ffmpeg와 libmpv에 대한 외부 어댑터."""

from functools import lru_cache
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import shutil
import subprocess
import sys
from threading import Lock

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
        self._subtitle_path = None
        self._closing = False
        self._callback_lock = Lock()

        @self._player.event_callback("file-loaded")
        def select_app_subtitle(_event):
            with self._callback_lock:
                if not self._closing:
                    for track in self._app_subtitle_tracks():
                        self._player.sid = track["id"]

        self._positions = SimpleQueue()
        self._seeking = True

        @self._player.event_callback("seek", "start-file")
        def seek_started(event):
            self._seeking = True

        @self._player.event_callback("playback-restart")
        def restarted(event):
            # 탐색 도중의 임시 위치는 버리고 실제 재생 재개 위치를 새 기준점으로 보낸다.
            with self._callback_lock:
                if self._closing:
                    return
                position = self._player.time_pos
                if position is not None:
                    self._positions.put((position, True))
                self._seeking = False

        @self._player.property_observer("time-pos")
        def position_changed(name, position):
            if position is not None and not self._seeking:
                self._positions.put((position, False))

    def _app_subtitle_tracks(self):
        if self._subtitle_path is None:
            return []
        return [track for track in self._player.track_list
                if track.get("type") == "sub" and track.get("external-filename")
                and Path(track["external-filename"]).resolve() == self._subtitle_path]

    def play(self, path: Path, start: float = 0, *, subtitle: Path | None = None) -> None:
        self._player.start = start
        self._subtitle_path = subtitle.resolve() if subtitle else None
        # loadfile 옵션으로 전달해 비동기 file-loaded 이전의 sub-add 경합을 피한다.
        options = {"sub-files": str(subtitle)} if subtitle else {}
        self._player.loadfile(str(path), "replace", **options)
        self._player.pause = False

    def set_subtitle(self, path: Path | None) -> None:
        for track in self._app_subtitle_tracks():
            self._player.command("sub-remove", track["id"])
        self._subtitle_path = path.resolve() if path else None
        if path:
            self._player.command("sub-add", str(path), "select")
        else:
            self._player.sid = "auto"

    def take_positions(self) -> tuple[tuple[float, bool], ...]:
        """mpv 스레드의 (위치, 탐색 여부) 보고를 순서대로 UI 스레드에 넘긴다."""
        positions = []
        while True:
            try:
                positions.append(self._positions.get_nowait())
            except Empty:
                return tuple(positions)

    def execute(self, command: Command) -> None:
        if command.kind == CommandType.TOGGLE_PAUSE:
            self._player.cycle("pause")
        elif command.kind == CommandType.SEEK:
            self._player.command("seek", command.amount, "relative+exact")
        elif command.kind == CommandType.CHANGE_SPEED:
            self._player.speed = playback_speed(self._player.speed, command.amount)
        elif command.kind == CommandType.TOGGLE_SUBTITLES:
            self._player.cycle("sub-visibility")

    def position(self) -> float | None:
        return self._player.time_pos

    def seek_to(self, position: float) -> None:
        self._player.command("seek", position, "absolute+exact")

    def close(self) -> None:
        # 콜백의 native handle 접근을 끝낸 뒤 핸들을 해제한다.
        # terminate는 이벤트 스레드를 기다리므로 lock 밖에서 실행한다.
        with self._callback_lock:
            self._closing = True
        self._player.terminate()
