"""faster-whisper 어댑터. CUDA의 네이티브 실패도 앱 종료로 번지지 않도록 격리한다."""

from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

from .subtitles import TranscriberCancelled, TranscriberError, TranscriberResult, TranscriptSegment


@lru_cache(maxsize=1)
def prepare_cuda_runtime():
    if sys.platform != "win32":
        return ()
    # NVIDIA 공식 Windows wheels의 DLL을 이 프로세스에서만 등록한다.
    from importlib.metadata import distribution

    paths = []
    for package in ("nvidia-cublas-cu12", "nvidia-cudnn-cu12"):
        dist = distribution(package)
        paths.extend({Path(dist.locate_file(file)).parent for file in dist.files
                      if str(file).endswith(".dll")})
    os.environ["PATH"] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get("PATH", "")
    return tuple(os.add_dll_directory(str(path)) for path in paths)


class FasterWhisperTranscriber:
    def __init__(self, model_directory: Path, *, command: tuple[str, ...] | None = None):
        self.model_directory = Path(model_directory).resolve()
        self.command = command or (sys.executable, "-m", "my_video_manager.transcription")

    def transcribe(self, path: Path, spoken_language: str | None, *,
                   cancellation: Event | None = None) -> TranscriberResult:
        cancellation = cancellation if cancellation is not None else Event()
        if cancellation.is_set():
            raise TranscriberCancelled
        job, process = None, None
        try:
            flags = 0
            if sys.platform == "win32":
                from .windows_job import WindowsJob
                job = WindowsJob()
                flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS | 0x4  # CREATE_SUSPENDED
            process = subprocess.Popen(
                [*self.command, str(path), str(self.model_directory), spoken_language or "auto"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=flags,
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
                return TranscriberResult(payload["spoken_language"],
                                         tuple(TranscriptSegment(**s) for s in payload["segments"]),
                                         float(payload.get("language_probability", 1.0)))
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


def transcribe_on_gpu(path: Path, model_directory: Path, spoken_language: str | None) -> TranscriberResult:
    try:
        prepare_cuda_runtime()
        import ctranslate2
        from faster_whisper import WhisperModel
        from faster_whisper.audio import decode_audio
        from faster_whisper.utils import download_model
        if ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("사용 가능한 NVIDIA CUDA GPU가 없습니다.")
    except Exception as error:
        raise TranscriberError("gpu_unavailable", str(error)) from error
    try:
        audio = decode_audio(str(path))
    except Exception as error:
        raise TranscriberError("decode", str(error)) from error
    try:
        model_path = download_model("large-v3", cache_dir=str(model_directory))
    except Exception as error:
        raise TranscriberError("model_download", str(error)) from error
    try:
        model = WhisperModel(model_path, device="cuda", compute_type="float16", cpu_threads=2, num_workers=1)
    except Exception as error:
        raise TranscriberError("gpu_unavailable", str(error)) from error
    segments, info = model.transcribe(audio, language=spoken_language, beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False)
    return TranscriberResult(info.language,
                         tuple(TranscriptSegment(s.start, s.end, s.text.strip()) for s in segments
                               if s.text.strip() and s.end > s.start), info.language_probability)


if __name__ == "__main__":
    try:
        transcript = transcribe_on_gpu(Path(sys.argv[1]), Path(sys.argv[2]),
                                       None if sys.argv[3] == "auto" else sys.argv[3])
        print(json.dumps(asdict(transcript), ensure_ascii=False))
    except Exception as error:
        failure = error if isinstance(error, TranscriberError) else TranscriberError("other", str(error))
        print(json.dumps({"kind": failure.kind, "detail": failure.detail}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
