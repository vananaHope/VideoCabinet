"""faster-whisper 어댑터. CUDA의 네이티브 실패도 앱 종료로 번지지 않도록 격리한다."""

from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event

from .subtitles import TranscriberCancelled, TranscriberError, TranscriberResult, TranscriptSegment


TRANSCRIPTION_MODEL = "large-v3"


@lru_cache(maxsize=None)
def prepare_cuda_runtime(data_directory: Path | None = None):
    if sys.platform != "win32":
        return ()
    # 등록 핸들은 프로세스가 끝날 때까지 보관한다. 소스는 .venv 경로를 유지한다.
    from importlib.metadata import distribution

    paths = []
    if getattr(sys, "frozen", False):
        from .core import default_data_directory
        from .cuda_runtime import cuda_runtime_directories
        paths.extend(cuda_runtime_directories(data_directory if data_directory is not None else default_data_directory()))
        if len(paths) != 2:
            raise RuntimeError("CUDA 런타임 준비가 필요합니다.")
    else:
        for package in ("nvidia-cublas-cu12", "nvidia-cudnn-cu12"):
            dist = distribution(package)
            paths.extend(sorted({Path(dist.locate_file(file)).parent for file in dist.files
                                 if str(file).endswith(".dll")}))
    os.environ["PATH"] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get("PATH", "")
    return tuple(os.add_dll_directory(str(path)) for path in paths)


def child_command() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        return (sys.executable, "transcription")
    return (sys.executable, "-m", "my_video_manager.transcription")


class FasterWhisperTranscriber:
    def __init__(self, model_directory: Path, *, command: tuple[str, ...] | None = None):
        self.model_directory = Path(model_directory).resolve()
        self.command = command or child_command()

    def transcribe(self, path: Path, spoken_language: str | None, *,
                   cancellation: Event | None = None, progress=None, start: float = 0,
                   duration: float | None = None) -> TranscriberResult:
        cancellation = cancellation if cancellation is not None else Event()
        if cancellation.is_set():
            raise TranscriberCancelled
        job, process = None, None
        progress_directory = tempfile.TemporaryDirectory(prefix="mvm-transcription-")
        progress_path = Path(progress_directory.name) / "progress"
        try:
            flags = 0
            if sys.platform == "win32":
                from .windows_job import WindowsJob
                job = WindowsJob()
                flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS | 0x4  # CREATE_SUSPENDED
            process = subprocess.Popen(
                [*self.command, str(path), str(self.model_directory), spoken_language or "auto",
                 *([str(start), str(duration)] if duration is not None else [])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "MVM_TRANSCRIPTION_PROGRESS": str(progress_path)}, creationflags=flags,
            )
            if job:
                job.attach_and_resume(process.pid)
            while True:
                if cancellation.is_set():
                    raise TranscriberCancelled
                try:
                    output, error = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if progress:
                        try:
                            progress(float(progress_path.read_text(encoding="ascii")))
                        except (OSError, ValueError):
                            pass  # 아직 보고가 없거나 쓰는 중이면 다음 주기에 읽는다.
                    continue
            if cancellation.is_set():
                raise TranscriberCancelled
            if process.returncode:
                detail = error.strip() or f"종료 코드 {process.returncode}"
                try:
                    failure = json.loads(detail.splitlines()[-1])
                    raise TranscriberError(failure["kind"], failure["detail"])
                except (ValueError, KeyError, TypeError):
                    raise TranscriberError("other", detail)
            try:
                payload = json.loads(output)
                model = payload["model"]
                if not isinstance(model, str) or not model.strip():
                    raise ValueError("모델 이름은 비어 있지 않은 문자열이어야 합니다.")
                return TranscriberResult(payload["spoken_language"],
                                         tuple(TranscriptSegment(**s) for s in payload["segments"]),
                                         float(payload.get("language_probability", 1.0)), model=model)
            except (ValueError, KeyError, TypeError) as error:
                raise TranscriberError("other", f"받아쓰기 응답 형식 오류: {error}") from error
        finally:
            if job:
                job.close()  # 정상 종료 때도 남은 손자 프로세스를 정리한다.
            if process:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                process.stdout.close()
                process.stderr.close()
            progress_directory.cleanup()


def transcribe_on_gpu(path: Path, model_directory: Path, spoken_language: str | None, *,
                      progress=None, start: float = 0, duration: float | None = None) -> TranscriberResult:
    prepared = None
    if getattr(sys, "frozen", False):
        from .cuda_runtime import PreparationError, SubtitlePreparation
        try:
            prepared = SubtitlePreparation(model_directory.parent).prepared()
        except PreparationError as error:
            raise TranscriberError(error.kind, str(error)) from error
    try:
        prepare_cuda_runtime(model_directory.parent)
        import ctranslate2
        from faster_whisper import WhisperModel
        from faster_whisper.audio import decode_audio
        from faster_whisper.utils import download_model
        if ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("사용 가능한 NVIDIA CUDA GPU가 없습니다.")
    except Exception as error:
        raise TranscriberError("gpu_unavailable", str(error)) from error
    try:
        if duration is None:
            audio = decode_audio(str(path))
        else:
            import numpy as np
            from .adapters import FFmpegMediaReader
            # 자식 프로세스 트리 안에서 지정 구간만 디코드한다. 결과 시각은 구간 상대값이다.
            decoded = subprocess.run(
                [FFmpegMediaReader().ffmpeg, "-v", "error", "-nostdin", "-ss", str(start),
                 "-i", str(path), "-t", str(duration), "-vn", "-ac", "1", "-ar", "16000",
                 "-f", "f32le", "pipe:1"], capture_output=True, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            audio = np.frombuffer(decoded.stdout, dtype=np.float32)
    except Exception as error:
        raise TranscriberError("decode", str(error)) from error
    try:
        model_path = (str(prepared.model_directory) if prepared else
                      download_model(TRANSCRIPTION_MODEL, cache_dir=str(model_directory)))
    except Exception as error:
        raise TranscriberError("model_download", str(error)) from error
    try:
        model = WhisperModel(model_path, device="cuda", compute_type="float16", cpu_threads=2, num_workers=1)
    except Exception as error:
        raise TranscriberError("gpu_unavailable", str(error)) from error
    segments, info = model.transcribe(audio, language=spoken_language, beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False)
    lines = []
    for segment in segments:
        if segment.text.strip() and segment.end > segment.start and (duration is None or segment.start < duration):
            lines.append(TranscriptSegment(segment.start, min(segment.end, duration) if duration is not None else segment.end, segment.text.strip()))
        if progress:
            progress(segment.end)
    return TranscriberResult(info.language, tuple(lines), info.language_probability, model=TRANSCRIPTION_MODEL)


def report_progress(seconds):
    """부가 진행 보고의 파일 잠금·디스크 오류는 받아쓰기 결과에 영향을 주지 않는다."""
    target = os.environ.get("MVM_TRANSCRIPTION_PROGRESS")
    if not target:
        return
    try:
        temporary = Path(target).with_suffix(".tmp")
        temporary.write_text(str(seconds), encoding="ascii")
        os.replace(temporary, target)
    except OSError:
        pass


def probe_cuda_device() -> bool:
    """--probe-cuda 자식 전용. 앱 프로세스에서는 호출하지 않는다."""
    import ctranslate2
    return ctranslate2.get_cuda_device_count() > 0


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if arguments == ["--probe-cuda"]:
            print(json.dumps({"available": probe_cuda_device()}))
            return 0
        transcript = transcribe_on_gpu(Path(arguments[0]), Path(arguments[1]),
                                       None if arguments[2] == "auto" else arguments[2], progress=report_progress,
                                       start=float(arguments[3]) if len(arguments) > 3 else 0,
                                       duration=float(arguments[4]) if len(arguments) > 4 else None)
        print(json.dumps(asdict(transcript), ensure_ascii=False))
        return 0
    except Exception as error:
        failure = error if isinstance(error, TranscriberError) else TranscriberError("other", str(error))
        print(json.dumps({"kind": failure.kind, "detail": failure.detail}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
