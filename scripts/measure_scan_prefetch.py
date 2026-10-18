"""첫 등록 검사 시간을 동시 개수별로 잰다(#173).

ffmpeg testsrc로 짧은 실제 영상 하나를 만들고 메타데이터만 바꾼 복사본을 하위 폴더에
나눠 둔다(파일마다 지문이 다르다). 동시 개수마다 새 DB로 AppCore.scan()을 한 번 잰다.
첫 측정 전에 한 번 검사해 파일 캐시를 데워 순서에 따른 차이를 줄인다.

    .venv/Scripts/python.exe scripts/measure_scan_prefetch.py --count 200 --workers 1 2 4 6 8
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from my_video_manager import scan_prefetch
from my_video_manager.adapters import FFmpegMediaReader, executable
from my_video_manager.core import AppCore


def make_videos(folder: Path, count: int, folders: int, seconds: int) -> None:
    ffmpeg = executable("ffmpeg")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    base = folder / "base.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=1280x720:rate=30",
                    "-pix_fmt", "yuv420p", str(base)], check=True, creationflags=flags)

    def copy(index):
        target = folder / "watched" / f"sub{index % folders:02d}" / f"video{index:04d}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(base), "-c", "copy",
                        "-metadata", f"comment=copy {index}", str(target)], check=True, creationflags=flags)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(copy, range(count)))
    base.unlink()


def first_scan(watched: Path, data: Path, workers: int) -> tuple[float, int]:
    scan_prefetch.SCAN_WORKERS = workers
    core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                   database=data / "library.sqlite3")
    core.set_minimum_duration(0)
    core.add_watched_folder(watched)
    started = time.perf_counter()
    result = core.scan()
    elapsed = time.perf_counter() - started
    if result.issues:
        raise RuntimeError(f"검사 오류: {result.issues[:3]}")
    return elapsed, result.added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--folders", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 6, 8])
    parser.add_argument("--root", type=Path, help="영상과 DB를 둘 빈 폴더(기본: 임시 폴더, 끝나면 삭제)")
    arguments = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="mvm-scan-", dir=arguments.root))
    try:
        make_videos(root, arguments.count, arguments.folders, arguments.seconds)
        watched = root / "watched"
        print(f"영상 {arguments.count}개({arguments.seconds}초 1280x720 mp4, 하위 폴더 {arguments.folders}개): {watched}")
        first_scan(watched, root / "warmup", 1)
        for workers in arguments.workers:
            elapsed, added = first_scan(watched, root / f"data-{workers}", workers)
            print(f"동시 개수 {workers}: {elapsed:.2f}초 (등록 {added}개, 파일당 {elapsed / added * 1000:.0f}ms)")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
