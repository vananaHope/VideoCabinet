"""공식 mpv 설치 안내에 연결된 shinchiro 빌드를 고정 SHA-256으로 설치."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
NAME = "mpv-dev-x86_64-20261013-git-9d144e57b6.7z"
URL = f"https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261013/{NAME}"
SHA256 = "10860837bc04491862c1e66a95dc1af1d7886d69757ce447a09e1e49ae993b52"


def main():
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    archive = runtime / NAME
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        print(f"Downloading {URL}", flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("libmpv 다운로드 SHA-256 불일치. 설치를 중단합니다.")
    destination = runtime / "mpv"
    destination.mkdir(exist_ok=True)
    seven_zip = shutil.which("7z") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe")
    if not Path(seven_zip).is_file():
        raise RuntimeError("7-Zip이 필요합니다. scripts/setup.ps1을 실행하세요.")
    # 필요한 DLL만 평탄하게 추출하여 임의 아카이브 경로에 쓰지 않는다.
    subprocess.run([seven_zip, "e", str(archive), "libmpv-2.dll", f"-o{destination}", "-y"], check=True)
    if not (destination / "libmpv-2.dll").is_file():
        raise RuntimeError("아카이브에서 libmpv-2.dll을 찾을 수 없습니다.")
    print(f"Installed {destination / 'libmpv-2.dll'}")


if __name__ == "__main__":
    main()
