"""설치판 FFmpeg 입력. PATH 대신 고정 essentials 아카이브를 재검증한다."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

from install_libmpv import cache_lock

VERSION = "9.0.2"
NAME = f"ffmpeg-{VERSION}-essentials_build.7z"
URL = f"https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/{NAME}"
SHA256 = "4705843ccaaf54257c16ad90f3e952ece33c17df964ecf7bfdbb0f49c7171077"
EXECUTABLES = ("ffmpeg.exe", "ffprobe.exe")
DOCUMENTS = {"LICENSE": "LICENSE.txt", "README.txt": "README.txt"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def cache_directory():
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return local / "my-video-manager/cache/ffmpeg"


def prepare(destination, cache, seven_zip):
    cache.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with cache_lock(cache, name=NAME):
        archive = cache / NAME
        partial = cache / f"{NAME}.part"
        partial.unlink(missing_ok=True)
        if not archive.is_file() or digest(archive) != SHA256:
            archive.unlink(missing_ok=True)
            try:
                print(f"Downloading {URL}", flush=True)
                with urllib.request.urlopen(URL, timeout=120) as source, partial.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if digest(partial) != SHA256:
                    raise RuntimeError("FFmpeg 다운로드 SHA-256 불일치. 빌드를 중단합니다.")
                os.replace(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
        print(f"Verified FFmpeg {VERSION}: {SHA256}", flush=True)
        with tempfile.TemporaryDirectory(prefix="ffmpeg-", dir=destination.parent) as temporary:
            stage = Path(temporary)
            members = [f"ffmpeg-{VERSION}-essentials_build/bin/{name}" for name in EXECUTABLES]
            members += [f"ffmpeg-{VERSION}-essentials_build/{name}" for name in DOCUMENTS]
            subprocess.run([seven_zip, "e", str(archive), *members, f"-o{stage}", "-y"], check=True)
            if any(not (stage / name).is_file() for name in (*EXECUTABLES, *DOCUMENTS)):
                raise RuntimeError("FFmpeg 아카이브에 필수 실행 파일 또는 라이선스 문서가 없습니다.")
            manifest = {"version": VERSION, "url": URL, "sha256": SHA256,
                        "files": {name: digest(stage / name) for name in EXECUTABLES}}
            # 검증·추출이 성공한 뒤 이전 입력을 교체해 실패한 빌드의 혼합물을 쓰지 않는다.
            if destination.exists():
                shutil.rmtree(destination)
            destination.mkdir()
            for name in (*EXECUTABLES, *DOCUMENTS):
                os.replace(stage / name, destination / DOCUMENTS.get(name, name))
            (destination / "source.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def prepare_bundle(destination):
    seven_zip = shutil.which("7z") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe")
    if not Path(seven_zip).is_file():
        raise RuntimeError("7-Zip이 필요합니다. scripts/setup.ps1을 실행하세요.")
    prepare(destination, cache_directory(), seven_zip)
