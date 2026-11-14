"""ffmpeg와 libmpv에 대한 외부 어댑터."""

from collections import deque
from dataclasses import dataclass
from collections.abc import Iterator
from functools import lru_cache
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import shutil
import subprocess
import sys
import time
from threading import Event, Lock, Thread

from .core import Command, CommandType, MediaInfo, playback_speed
from .media import parse_ffprobe_result
from .onscreen_subtitles import RegionImage, RegionRect


# 화면 자막 영역 읽기 전 영상 크기 조사(ffprobe)의 제한 시간. 일반 읽기(read)와 같은 120초로,
# 받아쓰기 등으로 바쁜 PC에서도 실패하지 않으면서 응답 없는 파일에서 끝없이 기다리지는 않는다.
REGION_PROBE_TIMEOUT_SECONDS = 120


class ProbeTimeout(RuntimeError):
    """영상 크기 조사가 제한 시간 안에 끝나지 않았다."""


@dataclass(frozen=True)
class VideoFrame:
    """재생 중인 영상의 한 장면. 화소는 bgr0(한 화소 4바이트), 한 행은 stride 바이트다."""
    width: int
    height: int
    stride: int
    data: bytes


def executable(name: str) -> str:
    if getattr(sys, "frozen", False) and name in ("ffmpeg", "ffprobe"):
        bundled = Path(sys.executable).resolve().parent / "ffmpeg" / f"{name}.exe"
        if bundled.is_file():
            return str(bundled)
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

    def read_resolution(self, path: Path, *, cancellation, timeout: float = 15) -> MediaInfo | None:
        """낮은 우선순위로 읽고 취소(종료·전경 작업·대기열 빼기)에 즉시 양보한다. 해상도 채우기와 화면 자막이 쓴다."""
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == 'win32' else 0
        process = subprocess.Popen([self.ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8', errors='replace', creationflags=flags)
        deadline = time.monotonic() + timeout
        try:
            while not cancellation.is_set():
                if time.monotonic() >= deadline:
                    raise ProbeTimeout(f'해상도 읽기 제한 시간({timeout:g}초)을 초과했습니다. 다시 검사해 주세요.')
                try:
                    output, error = process.communicate(timeout=0.05)
                    return parse_ffprobe_result(output, suffix=path.suffix, returncode=process.returncode, error=error)
                except subprocess.TimeoutExpired:
                    pass
            return None
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def capture(self, path: Path, destination: Path, seconds: float) -> None:
        result = self._run([self.ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", str(seconds),
                            "-i", str(path), "-map", "0:V:0", "-frames:v", "1", "-vf", "scale='min(640,iw)':-2",
                            "-update", "1", str(destination)])
        if result.returncode or not destination.is_file():
            raise RuntimeError(result.stderr.strip() or "썸네일을 캡처할 수 없습니다.")

    def capture_background(self, path, destination, seconds, *, cancellation):
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == 'win32' else 0
        process = subprocess.Popen([self.ffmpeg, '-v', 'error', '-nostdin', '-y', '-threads', '1',
                                    '-ss', str(seconds), '-i', str(path), '-map', '0:V:0', '-frames:v', '1',
                                    '-vf', "scale='min(640,iw)':-2", '-threads', '1', '-update', '1', str(destination)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8', errors='replace', creationflags=flags)
        deadline = time.monotonic() + 120
        try:
            while not cancellation.is_set():
                if time.monotonic() >= deadline:
                    raise RuntimeError('썸네일 캡처 제한 시간(120초)을 초과했습니다.')
                try:
                    _, error = process.communicate(timeout=0.05)
                    if process.returncode or not destination.is_file():
                        raise RuntimeError(error.strip() or '썸네일을 캡처할 수 없습니다.')
                    return
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def region_frames(
        self, path: Path, region: RegionRect, *, fps: float, cancellation: Event,
        start: float | None = None, end: float | None = None,
    ) -> Iterator[tuple[float, RegionImage]]:
        """표시 방향의 영역을 디스크에 쓰지 않고 회색조 프레임으로 읽는다. start·end를 주면 그 구간만 읽는다."""
        # 크기 조사도 취소를 받는다. 취소되면 아무 장도 내보내지 않고 끝나 실패가 아닌 대기로 돌아간다.
        try:
            info = self.read_resolution(path, cancellation=cancellation, timeout=REGION_PROBE_TIMEOUT_SECONDS)
        except ProbeTimeout as error:
            # 해상도 채우기의 '다시 검사' 안내는 화면 자막 작업을 되살리지 않는다. 실제 복구 방법을 안내한다.
            raise RuntimeError(f"화면 자막을 만들 영상 크기를 {REGION_PROBE_TIMEOUT_SECONDS:g}초 안에 읽지 못했습니다. "
                               "자막 대기열의 '실패 항목 모두 재시도'로 다시 시도하세요.") from error
        if cancellation.is_set():
            return
        if info is None or not info.width or not info.height:
            raise RuntimeError("영상의 표시 크기를 읽을 수 없습니다.")
        x = min(info.width - 1, max(0, int(region.x * info.width)))
        y = min(info.height - 1, max(0, int(region.y * info.height)))
        width = min(info.width - x, max(1, int(region.width * info.width)))
        height = min(info.height - y, max(1, int(region.height * info.height)))
        # 색차 서브샘플링 영상에서도 홀수 크기와 위치를 그대로 잘라야 한다.
        filters = f"crop={width}:{height}:{x}:{y}:exact=1,fps={fps}"
        if max(width, height) > 2560:
            ratio = 2560 / max(width, height)
            width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
            filters += f",scale={width}:{height}"
        filters += ",format=gray"
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == "win32" else 0
        try:
            # 입력 앞 -ss는 그 시각부터 정확히 디코딩한다(트랜스코딩). 나오는 장의 시각은 0부터라 offset을 더한다.
            seek = ["-ss", f"{start:.6f}"] if start else []
            limit = ["-t", f"{end - (start or 0):.6f}"] if end is not None else []
            process = subprocess.Popen(
                [self.ffmpeg, "-v", "error", "-nostdin", *seek, "-i", str(path), *limit,
                 "-map", "0:V:0", "-an", "-sn", "-vf", filters,
                 "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
            )
        except OSError as error:
            raise RuntimeError(f"영역 프레임을 읽을 수 없습니다: {error}") from error
        finished = Event()
        errors: deque[bytes] = deque(maxlen=16)

        def watch_cancellation():
            # 종료 신호도 기다려 생성기를 닫을 때 감시 스레드가 남지 않게 한다.
            while not finished.wait(0.02):
                if cancellation.is_set():
                    if process.poll() is None:
                        process.kill()
                    return

        def drain_errors():
            while chunk := process.stderr.read(4096):
                errors.append(chunk)

        watcher = Thread(target=watch_cancellation, name="region-frame-cancellation")
        error_reader = Thread(target=drain_errors, name="region-frame-stderr")
        try:
            watcher.start()
            error_reader.start()
            frame_size = width * height
            index = 0
            while not cancellation.is_set():
                pixels = process.stdout.read(frame_size)
                if cancellation.is_set():
                    return
                if len(pixels) != frame_size:
                    break
                yield (start or 0) + index / fps, RegionImage(width, height, pixels)
                index += 1
            code = process.wait()
            error_reader.join()
            if not cancellation.is_set():
                if code:
                    detail = b"".join(errors).decode("utf-8", errors="replace").strip()
                    raise RuntimeError(detail or "영역 프레임을 읽을 수 없습니다.")
                if pixels and len(pixels) != frame_size:
                    raise RuntimeError("영역 프레임의 픽셀 데이터가 잘렸습니다.")
        finally:
            finished.set()
            if process.poll() is None:
                process.kill()
            process.wait()
            if watcher.ident is not None:
                watcher.join()
            if error_reader.ident is not None:
                error_reader.join()
            process.stdout.close()
            process.stderr.close()


@lru_cache(maxsize=1)
def _prepare_mpv_runtime():
    if sys.platform == "win32":
        runtime = (Path(sys.executable).resolve().parent / "mpv" if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parents[2] / ".runtime/mpv")
        if runtime.is_dir():
            # python-mpv의 ctypes.find_library 검색에는 PATH도 필요하다.
            # 캐시에 DLL 핸들을 보관해 등록을 유지하고, 프로세스당 한 번만 설정한다.
            os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
            return os.add_dll_directory(str(runtime))
    return None


OSD_FONT = "Malgun Gothic"


class MpvPlayer:
    def __init__(self, window_id: int):
        _prepare_mpv_runtime()
        import mpv

        # 재생 상태 표시(OSD)의 한국어 글꼴. 맑은 고딕은 모든 Windows에 들어 있어 따로 묶지 않는다.
        self._player = mpv.MPV(wid=str(window_id), input_default_bindings=False,
                               input_vo_keyboard=False, osc=False, config=False, keep_open=True,
                               osd_font=OSD_FONT)
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
        self._eof = SimpleQueue()
        self._seeking = True
        self._awaiting_seek = False
        self._initial_start = None

        @self._player.event_callback("seek", "start-file")
        def seek_started(event):
            self._seeking = True
            self._awaiting_seek = False

        @self._player.event_callback("playback-restart")
        def restarted(event):
            # 탐색 도중의 임시 위치는 버리고 실제 재생 재개 위치를 새 기준점으로 보낸다.
            with self._callback_lock:
                if self._closing or self._awaiting_seek:
                    return
                position = self._player.time_pos
                if position is not None:
                    if self._initial_start is not None:
                        # loadfile의 첫 보고까지 실제 재생된 부분도 포함한다.
                        # 사용자 탐색은 아래 명령 진입점에서 이 시작 기준을 폐기한다.
                        self._positions.put((self._initial_start, True))
                        self._positions.put((position, False))
                        self._initial_start = None
                    else:
                        self._positions.put((position, True))
                self._seeking = False

        @self._player.property_observer("time-pos")
        def position_changed(name, position):
            with self._callback_lock:
                if position is not None and not self._seeking and not self._closing:
                    self._positions.put((position, False))

        @self._player.property_observer("eof-reached")
        def reached_end(name, reached):
            # time-pos는 마지막 프레임 시작까지만 보고할 수 있다. EOF로 마지막 구간을 닫는다.
            with self._callback_lock:
                if reached and not self._closing and not self._seeking:
                    duration = self._player.duration
                    if duration is not None:
                        self._positions.put((duration, False))
                    self._eof.put(True)

    def _app_subtitle_tracks(self):
        if self._subtitle_path is None:
            return []
        return [track for track in self._player.track_list
                if track.get("type") == "sub" and track.get("external-filename")
                and Path(track["external-filename"]).resolve() == self._subtitle_path]

    def play(self, path: Path, start: float = 0, *, subtitle: Path | None = None) -> None:
        self._initial_start = start
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
            remaining = [track for track in self._player.track_list if track.get("type") == "sub"]
            self._player.sid = remaining[0]["id"] if remaining else "no"

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
            self._initial_start = None
            self._player.command("seek", command.amount, "relative+exact")
        elif command.kind == CommandType.CHANGE_SPEED:
            self._player.speed = playback_speed(self._player.speed, command.amount)
        elif command.kind == CommandType.TOGGLE_SUBTITLES:
            self._player.cycle("sub-visibility")

    def show_status(self, text: str, duration: float) -> None:
        """재생 상태 표시. 영상 위에 글자를 duration초 보이고 저절로 지운다.

        client API 명령은 ${...} 속성 확장을 하지 않으므로 문구가 그대로 보인다.
        종료가 시작된 뒤에는 해제된 핸들에 닿지 않도록 표시를 생략한다.
        """
        with self._callback_lock:
            if not self._closing:
                self._player.command("show-text", text, round(duration * 1000))

    def pause(self) -> None:
        """토글과 달리 이미 멈춘 재생은 그대로 둔다."""
        self._player.pause = True

    @property
    def paused(self) -> bool:
        return bool(self._player.pause)

    def video_frame(self) -> VideoFrame | None:
        """지금 보이는 영상 프레임(자막·재생 상태 표시 제외). 영상이 아직 없거나 종료 중이면 None.

        mpv screenshot-raw의 bgr0 화소(한 화소 4바이트)를 그대로 돌려준다. 회전·화면비를 반영한 표시 모양이다.
        """
        with self._callback_lock:
            if self._closing:
                return None
            frame = self._player.command("screenshot-raw", "video")
        if not frame or frame.get("format") != "bgr0":
            return None
        return VideoFrame(frame["w"], frame["h"], frame["stride"], bytes(frame["data"]))

    def take_eof(self) -> bool:
        reached = False
        while True:
            try:
                reached = self._eof.get_nowait() or reached
            except Empty:
                return reached

    def playback_options(self) -> tuple[float, bool]:
        """모아보기의 항목 전환에도 사용자가 정한 배속과 자막 표시를 유지한다."""
        return self._player.speed, self._player.sub_visibility

    def apply_playback_options(self, options: tuple[float, bool]) -> None:
        self._player.speed, self._player.sub_visibility = options

    def seek_to(self, position: float, *, resume: bool = False) -> None:
        with self._callback_lock:
            self._seeking = self._awaiting_seek = True
            self.take_positions()
            self.take_eof()
            # 모아보기의 새 항목은 요청 시작점부터 센다. 첫 보고 자체는 seeked=True다.
            self._initial_start = position if resume else None
            self._player.command("seek", position, "absolute+exact")
            if resume:
                self._player.pause = False

    def prepare_close(self) -> None:
        """위치 보고의 경계를 확정한다. 뒤의 native 해제는 다른 스레드에서 가능하다."""
        with self._callback_lock:
            if self._closing:
                return
            self._closing = True
            try:
                self._player.pause = True
            except Exception:
                # 이미 죽은 native 코어는 pause도 거부할 수 있다. 보고 경계는
                # 닫은 채 두고 close의 terminate로 자원 해제를 계속한다.
                pass

    def close(self) -> None:
        # 콜백의 native handle 접근을 끝낸 뒤 핸들을 해제한다.
        # terminate는 이벤트 스레드를 기다리므로 lock 밖에서 실행한다.
        self.prepare_close()
        self._player.terminate()
