"""faster-whisper 어댑터. CUDA의 네이티브 실패도 앱 종료로 번지지 않도록 격리한다."""

from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys

from .subtitles import Transcription, TranscriptSegment


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
    def __init__(self, model_directory: Path):
        self.model_directory = Path(model_directory).resolve()

    def transcribe(self, path: Path, spoken_language: str | None) -> Transcription:
        result = subprocess.run(
            [sys.executable, "-m", "my_video_manager.transcription", str(path),
             str(self.model_directory), spoken_language or "auto"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            if sys.platform == "win32" else 0,
        )
        if result.returncode:
            raise RuntimeError(
                "GPU 받아쓰기 실패. NVIDIA 드라이버와 README의 CUDA 환경 준비를 확인하세요. "
                "CPU로 자동 전환하지 않습니다.\n" + (result.stderr.strip()[-4000:] or f"종료 코드 {result.returncode}")
            )
        payload = json.loads(result.stdout)
        return Transcription(payload["spoken_language"],
                             tuple(TranscriptSegment(**segment) for segment in payload["segments"]))


def transcribe_on_gpu(path: Path, model_directory: Path, spoken_language: str | None) -> Transcription:
    prepare_cuda_runtime()
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("사용 가능한 NVIDIA CUDA GPU가 없습니다.")
    model = WhisperModel("large-v3", device="cuda", compute_type="float16", cpu_threads=2,
                         num_workers=1, download_root=str(model_directory))
    segments, info = model.transcribe(str(path), language=spoken_language, beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False)
    return Transcription(info.language,
                         tuple(TranscriptSegment(s.start, s.end, s.text.strip()) for s in segments
                               if s.text.strip() and s.end > s.start))


if __name__ == "__main__":
    try:
        transcript = transcribe_on_gpu(Path(sys.argv[1]), Path(sys.argv[2]),
                                       None if sys.argv[3] == "auto" else sys.argv[3])
        print(json.dumps(asdict(transcript), ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
