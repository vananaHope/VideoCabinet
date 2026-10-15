"""공식 mpv 설치 안내에 연결된 shinchiro 빌드를 고정 SHA-256으로 설치."""

import hashlib
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
NAME = "mpv-dev-x86_64-20261013-git-9d144e57b6.7z"
URL = f"https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261013/{NAME}"
SHA256 = "10860837bc04491862c1e66a95dc1af1d7886d69757ce447a09e1e49ae993b52"


def cache_directory():
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return local / "my-video-manager/cache/libmpv"


def verified(path):
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == SHA256


@contextmanager
def cache_lock(cache, timeout=None, *, name=NAME):
    # OS 잠금은 프로세스 강제 종료에도 해제된다. 잠금 파일은 지우지 않는다.
    with (cache / f"{name}.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        deadline = None if timeout is None else time.monotonic() + timeout
        next_notice = time.monotonic()
        while True:
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    raise TimeoutError(f"{name} 캐시 잠금 대기 시간이 초과되었습니다.") from exc
                if now >= next_notice:
                    print(f"다른 프로세스가 {name} 캐시를 준비 중입니다. 잠금 해제를 기다립니다.", flush=True)
                    next_notice = now + 30
                time.sleep(0.1)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def install(runtime, cache, seven_zip):
    cache.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    destination = runtime / "mpv"
    destination.mkdir(exist_ok=True)
    with cache_lock(cache):
        archive = cache / NAME
        partial = cache / f"{NAME}.part"
        # 잠금 소유자만 .part를 쓴다. 강제 종료로 남은 파일도 다음 실행에서 정리한다.
        partial.unlink(missing_ok=True)
        if not verified(archive):
            archive.unlink(missing_ok=True)
            print(f"Downloading {URL}", flush=True)
            try:
                with urllib.request.urlopen(URL, timeout=120) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output)
                if not verified(partial):
                    raise RuntimeError("libmpv 다운로드 SHA-256 불일치. 설치를 중단합니다.")
                os.replace(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
        else:
            print(f"Verified cache: {archive}", flush=True)
        # 추출 실패 시 기존 DLL을 보존하고, 성공한 DLL만 같은 볼륨에서 원자 교체한다.
        with tempfile.TemporaryDirectory(prefix="mpv-", dir=runtime) as stage:
            subprocess.run([seven_zip, "e", str(archive), "libmpv-2.dll", f"-o{stage}", "-y"], check=True)
            dll = Path(stage) / "libmpv-2.dll"
            if not dll.is_file():
                raise RuntimeError("아카이브에서 libmpv-2.dll을 찾을 수 없습니다.")
            os.replace(dll, destination / dll.name)
    print(f"Installed {destination / 'libmpv-2.dll'}")


def main():
    runtime = ROOT / ".runtime"
    seven_zip = shutil.which("7z") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe")
    if not Path(seven_zip).is_file():
        raise RuntimeError("7-Zip이 필요합니다. scripts/setup.ps1을 실행하세요.")
    install(runtime, cache_directory(), seven_zip)


if __name__ == "__main__":
    main()
