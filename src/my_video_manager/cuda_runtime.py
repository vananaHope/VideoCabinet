"""화면과 독립된 자막 기능 준비. 작업자 스레드에서 호출하고 Event로 취소한다."""

from dataclasses import dataclass
from contextlib import contextmanager
import errno
import hashlib
import http.client
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
from threading import Event, Lock
from typing import Callable
import urllib.request
import zipfile

from .runtime_assets import CUDA_WHEELS, WHISPER_FILES, WHISPER_REVISION, DownloadAsset


class PreparationError(RuntimeError):
    MESSAGES = {
        "gpu_unavailable": "사용 가능한 NVIDIA GPU가 없습니다. GPU와 드라이버를 확인하세요.",
        "network": "다운로드가 끊겼습니다. 인터넷 연결을 확인하고 다시 시도하세요.",
        "hash_mismatch": "다운로드 파일의 해시가 다릅니다. 다시 내려받으세요.",
        "disk_full": "저장 공간이 부족합니다. 데이터 폴더의 여유 공간을 확보하세요.",
        "cancelled": "자막 기능 준비를 취소했습니다. 다음에 다시 시도할 수 있습니다.",
        "invalid_archive": "CUDA 휠에서 올바른 DLL을 찾을 수 없습니다.",
        "storage": "준비 파일을 저장할 수 없습니다. 데이터 폴더의 권한을 확인하세요.",
    }

    def __init__(self, kind: str, detail: str = ""):
        self.kind, self.detail = kind, detail
        super().__init__(self.MESSAGES[kind])


@dataclass(frozen=True)
class PreparationProgress:
    phase: str  # download / verify / extract / reuse / ready
    asset: str
    completed: int
    total: int


Progress = Callable[[PreparationProgress], None]
_preparation_lock = Lock()
_CHUNK = 1024 * 1024


@contextmanager
def _directory_lock(directory: Path, cancellation: Event):
    """앱과 받아쓰기 자식이 같은 임시 폴더를 동시에 정리하지 않도록 잠근다."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".subtitle-preparation.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        while True:
            _check_cancel(cancellation)
            lock.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                cancellation.wait(0.1)
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _check_cancel(cancellation: Event):
    if cancellation.is_set():
        raise PreparationError("cancelled")


def _report(progress: Progress | None, cancellation: Event, phase, asset, completed, total):
    _check_cancel(cancellation)
    if progress:
        progress(PreparationProgress(phase, asset, completed, total))
    _check_cancel(cancellation)


class RuntimeDownloadAdapter:
    """다운로드·검증·DLL 추출의 주입 지점. 네트워크 무응답 제한 시간은 10초다."""

    def download(self, asset: DownloadAsset, target: Path, cancellation: Event, progress: Progress | None):
        _report(progress, cancellation, "download", asset.name, 0, asset.size)
        try:
            response = urllib.request.urlopen(asset.url, timeout=10)
        except (OSError, http.client.HTTPException) as error:
            _check_cancel(cancellation)
            raise PreparationError("network", str(error)) from error
        with response, target.open("wb") as output:
            count = 0
            while True:
                _check_cancel(cancellation)
                try:
                    # read1은 느린 연결에서도 1 MiB를 다 채우려고 기다리지 않는다.
                    chunk = response.read1(_CHUNK)
                except (OSError, http.client.HTTPException) as error:
                    _check_cancel(cancellation)
                    raise PreparationError("network", str(error)) from error
                if not chunk:
                    break
                if count + len(chunk) > asset.size:
                    raise PreparationError("hash_mismatch", f"{asset.name}: unexpected size")
                output.write(chunk)
                count += len(chunk)
                _report(progress, cancellation, "download", asset.name, count, asset.size)
            if count != asset.size:
                raise PreparationError("network", f"{asset.name}: {count}/{asset.size} bytes")

    def verify(self, asset: DownloadAsset, target: Path, cancellation: Event, progress: Progress | None):
        digest, count = hashlib.sha256(), 0
        _report(progress, cancellation, "verify", asset.name, 0, asset.size)
        with target.open("rb") as source:
            while chunk := source.read(_CHUNK):
                digest.update(chunk)
                count += len(chunk)
                _report(progress, cancellation, "verify", asset.name, count, asset.size)
        if count != asset.size or digest.hexdigest() != asset.sha256:
            raise PreparationError("hash_mismatch", asset.name)

    def extract(self, asset: DownloadAsset, wheel: Path, target: Path,
                cancellation: Event, progress: Progress | None):
        try:
            with zipfile.ZipFile(wheel) as archive:
                dlls = [entry for entry in archive.infolist() if entry.filename.lower().endswith(".dll")]
                if not dlls:
                    raise PreparationError("invalid_archive", asset.name)
                self.require_space(target, sum(entry.file_size for entry in dlls))
                names = set()
                for entry in dlls:
                    path = PurePosixPath(entry.filename)
                    # 휠 경로를 extractall에 넘기지 않는다. DLL basename만 사용한다.
                    if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                        raise PreparationError("invalid_archive", entry.filename)
                    if path.name.lower() in names:
                        raise PreparationError("invalid_archive", entry.filename)
                    names.add(path.name.lower())
                    count = 0
                    _report(progress, cancellation, "extract", path.name, 0, entry.file_size)
                    with archive.open(entry) as source, (target / path.name).open("wb") as output:
                        while chunk := source.read(_CHUNK):
                            output.write(chunk)
                            count += len(chunk)
                            _report(progress, cancellation, "extract", path.name, count, entry.file_size)
        except zipfile.BadZipFile as error:
            raise PreparationError("invalid_archive", str(error)) from error

    def require_space(self, target: Path, size: int):
        if shutil.disk_usage(target).free < size:
            raise PreparationError("disk_full", f"{target}: {size} bytes required")


def cuda_gpu_available() -> bool:
    # cuBLAS/cuDNN 다운로드 전에 드라이버가 보고하는 CUDA 장치를 검사한다.
    import ctranslate2
    return ctranslate2.get_cuda_device_count() > 0


def _manifest(assets):
    return {asset.name: asset.sha256 for asset in assets}


def _is_ready(target: Path, assets) -> bool:
    try:
        manifest = json.loads((target / "ready.json").read_text(encoding="utf-8"))
        return (manifest["assets"] == _manifest(assets) and bool(manifest["files"])
                and all(Path(name).name == name and (target / name).is_file()
                        and (target / name).stat().st_size == size
                        for name, size in manifest["files"].items()))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def cuda_runtime_directories(data_directory: Path) -> tuple[Path, ...]:
    root = Path(data_directory) / "runtime/cuda"
    return tuple(root / asset.sha256 for asset in CUDA_WHEELS
                 if _is_ready(root / asset.sha256, (asset,)))


@dataclass(frozen=True)
class PreparedSubtitles:
    cuda_directories: tuple[Path, ...]
    model_directory: Path


class SubtitlePreparation:
    """한 번에 하나의 준비 작업을 실행한다. 완료 결과는 재설치 후에도 재사용한다.

    소스 실행은 기존 .venv CUDA와 HF 모델 캐시를 사용한다. 이 API는 설치판의
    명시적인 준비 진입점이며 데이터는 항상 전달받은 data_directory 아래에 둔다.
    """

    def __init__(self, data_directory: Path, *, adapter: RuntimeDownloadAdapter | None = None,
                 gpu_available: Callable[[], bool] = cuda_gpu_available,
                 cuda_assets=CUDA_WHEELS, model_assets=WHISPER_FILES,
                 model_revision: str = WHISPER_REVISION):
        self.data_directory = Path(data_directory).resolve()
        self.adapter = adapter if adapter is not None else RuntimeDownloadAdapter()
        self.gpu_available = gpu_available
        self.cuda_assets, self.model_assets = tuple(cuda_assets), tuple(model_assets)
        self.model_revision = model_revision

    def prepare(self, *, cancellation: Event | None = None, progress: Progress | None = None) -> PreparedSubtitles:
        cancellation = cancellation if cancellation is not None else Event()
        _check_cancel(cancellation)
        while not _preparation_lock.acquire(timeout=0.1):
            _check_cancel(cancellation)
        try:
            _check_cancel(cancellation)
            try:
                available = self.gpu_available()
            except Exception as error:
                raise PreparationError("gpu_unavailable", str(error)) from error
            if not available:
                raise PreparationError("gpu_unavailable")
            with _directory_lock(self.data_directory, cancellation):
                directories = tuple(self._prepare_group(
                    self.data_directory / "runtime/cuda" / asset.sha256, (asset,), True, cancellation, progress)
                    for asset in self.cuda_assets)
                model = self._prepare_group(self.data_directory / "models" / "large-v3" / self.model_revision,
                                            self.model_assets, False, cancellation, progress)
            _report(progress, cancellation, "ready", "subtitles", 1, 1)
            return PreparedSubtitles(directories, model)
        except OSError as error:
            kind = "disk_full" if error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112) else "storage"
            raise PreparationError(kind, str(error)) from error
        finally:
            _preparation_lock.release()

    def _prepare_group(self, target, assets, extract, cancellation, progress):
        stage = target.with_name(target.name + ".partial")
        # 완료 표시가 없는 파일을 재사용하지 않는다. 실패 시 그대로 두고 재시도 때 정리한다.
        if stage.exists():
            shutil.rmtree(stage)
        if _is_ready(target, assets):
            _report(progress, cancellation, "reuse", target.name, 1, 1)
            return target
        stage.mkdir(parents=True)
        for asset in assets:
            _check_cancel(cancellation)
            self.adapter.require_space(stage, asset.size)
            partial = stage / (asset.name + ".part")
            self.adapter.download(asset, partial, cancellation, progress)
            self.adapter.verify(asset, partial, cancellation, progress)
            _check_cancel(cancellation)
            if extract:
                self.adapter.extract(asset, partial, stage, cancellation, progress)
                partial.unlink()
            else:
                partial.replace(stage / asset.name)
        _check_cancel(cancellation)
        files = {path.name: path.stat().st_size for path in stage.iterdir() if path.is_file()}
        if not files:
            raise PreparationError("invalid_archive", str(target))
        (stage / "ready.json").write_text(json.dumps({"assets": _manifest(assets), "files": files}), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        stage.replace(target)
        return target
