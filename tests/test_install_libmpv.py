"""설치의 캐시 재검증, 실패 복구, 프로세스 간 동시 사용 계약."""

import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install_libmpv.py"


@pytest.fixture
def installer(monkeypatch):
    spec = importlib.util.spec_from_file_location("install_libmpv", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SHA256", hashlib.sha256(b"archive").hexdigest())

    def extract(command, **kwargs):
        stage = Path(next(arg[2:] for arg in command if arg.startswith("-o")))
        (stage / "libmpv-2.dll").write_bytes(b"dll")

    monkeypatch.setattr(module.subprocess, "run", extract)
    return module


def test_reuse_rechecks_hash_and_repairs_corruption(installer, tmp_path, monkeypatch):
    calls = []

    def download(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(b"archive")

    monkeypatch.setattr(installer.urllib.request, "urlopen", download)
    cache = tmp_path / "cache"
    for number in range(2):
        installer.install(tmp_path / str(number), cache, "7z")
        assert (tmp_path / str(number) / "mpv/libmpv-2.dll").read_bytes() == b"dll"
    assert len(calls) == 1
    (cache / installer.NAME).write_bytes(b"corrupt")
    installer.install(tmp_path / "third", cache, "7z")
    assert len(calls) == 2
    assert (cache / installer.NAME).read_bytes() == b"archive"


@pytest.mark.parametrize("failure", ["hash", "network", "timeout", "cancel"])
def test_failed_download_cleans_partial_and_can_retry(installer, tmp_path, monkeypatch, failure):
    class BrokenResponse(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise {"network": OSError, "timeout": TimeoutError, "cancel": KeyboardInterrupt}[failure]()
            return super().read(3)

    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k:
                        io.BytesIO(b"wrong") if failure == "hash" else BrokenResponse(b"archive"))
    cache = tmp_path / "cache"
    with pytest.raises((RuntimeError, OSError, KeyboardInterrupt)):
        installer.install(tmp_path / "runtime", cache, "7z")
    assert not (cache / installer.NAME).exists()
    assert not list(cache.glob("*.part"))
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"archive"))
    installer.install(tmp_path / "runtime", cache, "7z")
    assert (tmp_path / "runtime/mpv/libmpv-2.dll").read_bytes() == b"dll"


@pytest.mark.parametrize("failure", ["exit", "missing"])
def test_failed_extraction_preserves_existing_dll(installer, tmp_path, monkeypatch, failure):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / installer.NAME).write_bytes(b"archive")
    (cache / f"{installer.NAME}.part").write_bytes(b"abandoned")
    runtime = tmp_path / "runtime"
    (runtime / "mpv").mkdir(parents=True)
    dll = runtime / "mpv/libmpv-2.dll"
    dll.write_bytes(b"previous")

    def extract(*args, **kwargs):
        if failure == "exit":
            raise subprocess.CalledProcessError(2, "7z")

    monkeypatch.setattr(installer.subprocess, "run", extract)
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        installer.install(runtime, cache, "7z")
    assert dll.read_bytes() == b"previous"
    assert list(runtime.iterdir()) == [runtime / "mpv"]
    assert not list(cache.glob("*.part"))


def test_two_processes_share_one_verified_download(tmp_path):
    code = '''
import hashlib, io, runpy, sys, time
from pathlib import Path
m = runpy.run_path(sys.argv[1])
install = m['install']
g = install.__globals__
g['SHA256'] = hashlib.sha256(b'archive').hexdigest()
cache = Path(sys.argv[2])
def download(*a, **k):
    with (cache / 'downloads').open('ab') as f: f.write(b'x')
    time.sleep(0.3)
    return io.BytesIO(b'archive')
def extract(command, **kwargs):
    stage = Path(next(a[2:] for a in command if a.startswith('-o')))
    (stage / 'libmpv-2.dll').write_bytes(b'dll')
g['urllib'].request.urlopen = download
g['subprocess'].run = extract
install(Path(sys.argv[3]), cache, '7z')
'''
    cache = tmp_path / "cache"
    processes = [subprocess.Popen([sys.executable, "-c", code, str(SCRIPT), str(cache),
                                   str(tmp_path / str(i))], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for i in range(2)]
    try:
        for process in processes:
            out, err = process.communicate(timeout=20)
            assert process.returncode == 0, (out, err)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert (cache / "downloads").read_bytes() == b"x"
    assert not list(cache.glob("*.part"))
    for i in range(2):
        assert (tmp_path / str(i) / "mpv/libmpv-2.dll").read_bytes() == b"dll"
