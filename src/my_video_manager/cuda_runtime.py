"""화면과 독립된 자막 기능 준비. 작업자 스레드에서 호출하고 Event로 취소한다."""

from dataclasses import dataclass, replace
from contextlib import contextmanager
import errno
import hashlib
import http.client
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
from threading import Event, Lock, Thread
from typing import Callable
import urllib.request
import zipfile

from .runtime_assets import (CUDA_WHEELS, WHISPER_FILES, WHISPER_MODEL, WHISPER_REPOSITORY,
                             WHISPER_REVISION, DownloadAsset)
from .subtitle_preparation_state import safe_detail, log_failure


class PreparationError(RuntimeError):
    MESSAGES = {
        "gpu_unavailable": "사용 가능한 NVIDIA GPU가 없습니다. GPU와 드라이버를 확인하세요.",
        "network": "다운로드가 끊겼습니다. 인터넷 연결을 확인하고 다시 시도하세요.",
        "server": "서버가 일시적으로 응답하지 않습니다. 잠시 뒤 다시 시도하세요.",
        "hash_mismatch": "다운로드 파일의 해시가 다릅니다. 다시 내려받으세요.",
        "disk_full": "저장 공간이 부족합니다. 데이터 폴더의 여유 공간을 확보하세요.",
        "cancelled": "자막 기능 준비를 취소했습니다. 다음에 다시 시도할 수 있습니다.",
        "interrupted": "준비가 끝나기 전에 중단되었습니다. 다음에 다시 시도할 수 있습니다.",
        "invalid_archive": "CUDA 휠에서 올바른 DLL을 찾을 수 없습니다.",
        "storage": "준비 파일을 저장할 수 없습니다. 데이터 폴더의 권한을 확인하세요.",
        "preparation_required": "자막 기능 준비를 먼저 실행하세요.",
    }

    def __init__(self, kind: str, detail: str | Exception = ""):
        self.kind, self.detail = kind, safe_detail(detail)
        super().__init__(self.MESSAGES[kind])


@dataclass(frozen=True)
class PreparationProgress:
    phase: str  # download / verify / extract / reuse / ready
    asset: str
    completed: int
    total: int
    file_index: int = 0
    file_count: int = 0
    overall_completed: int = 0
    overall_total: int = 0


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


class PreparationCancellation(Event):
    """기존 Event 계약에 앱 종료 사유를 더한다."""
    reason = 'cancelled'

    def interrupt(self):
        self.reason = 'interrupted'
        self.set()


def _check_cancel(cancellation: Event):
    if cancellation.is_set():
        raise PreparationError(getattr(cancellation, 'reason', 'cancelled'))


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
            kind = 'server' if isinstance(error, urllib.error.HTTPError) and 500 <= error.code < 600 else 'network'
            raise PreparationError(kind, f"{asset.name}: {safe_detail(error)}") from error
        with response, target.open("wb") as output:
            count = 0
            while True:
                _check_cancel(cancellation)
                try:
                    # read1은 느린 연결에서도 1 MiB를 다 채우려고 기다리지 않는다.
                    chunk = response.read1(_CHUNK)
                except (OSError, http.client.HTTPException) as error:
                    _check_cancel(cancellation)
                    raise PreparationError("network", f"{asset.name}: {safe_detail(error)}") from error
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
            raise PreparationError("invalid_archive", error) from error

    def require_space(self, target: Path, size: int):
        if shutil.disk_usage(target).free < size:
            raise PreparationError("disk_full", f"{target}: {size} bytes required")


def cuda_gpu_available(*, command: tuple[str, ...] | None = None, timeout: float = 15,
                       cancellation: Event | None = None) -> bool:
    """네이티브 CUDA 탐지는 별도 프로세스에서만 실행한다."""
    if command is None:
        from .transcription import child_command
        command = (*child_command(), "--probe-cuda")
    cancellation = cancellation if cancellation is not None else Event()
    _check_cancel(cancellation)
    job, process = None, None
    try:
        flags = 0
        if sys.platform == "win32":
            from .windows_job import WindowsJob
            job = WindowsJob()
            flags = subprocess.CREATE_NO_WINDOW | 0x4
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", creationflags=flags)
        if job:
            job.attach_and_resume(process.pid)
        deadline = time.monotonic() + timeout
        while True:
            _check_cancel(cancellation)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                output, error = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        _check_cancel(cancellation)
        if process.returncode:
            raise PreparationError("gpu_unavailable", error.strip() or f"종료 코드 {process.returncode}")
        available = json.loads(output)["available"]
        if not isinstance(available, bool):
            raise ValueError("GPU 탐지 응답은 bool이어야 합니다.")
        return available
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as error:
        raise PreparationError("gpu_unavailable", error) from error
    finally:
        if job:
            job.close()
        if process:
            if process.poll() is None:
                process.kill()
            process.communicate()
            process.stdout.close()
            process.stderr.close()


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


def _plain_directory(path: Path) -> bool:
    info = path.lstat()
    return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class SubtitlePreparation:
    """한 번에 하나의 준비 작업을 실행한다. 완료 결과는 재설치 후에도 재사용한다.

    소스 실행은 기존 .venv CUDA와 HF 모델 캐시를 사용한다. 이 API는 설치판의
    명시적인 준비 진입점이며 데이터는 항상 전달받은 data_directory 아래에 둔다.
    progress 콜백은 예외를 던지지 않아야 한다. 콜백의 오류 처리는 호출자가 맡는다.
    """

    def __init__(self, data_directory: Path, *, adapter: RuntimeDownloadAdapter | None = None,
                 gpu_available: Callable[[], bool] | None = None,
                 cuda_assets=CUDA_WHEELS, model_assets=WHISPER_FILES,
                 model_revision: str = WHISPER_REVISION):
        self.data_directory = Path(data_directory).resolve()
        self.adapter = adapter if adapter is not None else RuntimeDownloadAdapter()
        self.gpu_available = gpu_available
        self.cuda_assets, self.model_assets = tuple(cuda_assets), tuple(model_assets)
        self.model_revision = model_revision

    def prepare(self, *, cancellation: Event | None = None, progress: Progress | None = None) -> PreparedSubtitles:
        from .subtitle_preparation_state import PreparationHistory
        history = PreparationHistory(self.data_directory)
        assets = self.cuda_assets + self.model_assets
        completed = dict.fromkeys((asset.name for asset in assets), 0)
        index = 0

        def report(value):
            nonlocal index
            for position, asset in enumerate(assets, 1):
                if value.asset == asset.name:
                    index = position
                    if value.phase == 'download' and value.completed == 0:
                        completed[asset.name] = 0
                    amount = min(asset.size, value.completed) if value.phase in ('download', 'verify') else asset.size
                    completed[asset.name] = max(completed[asset.name], amount)
                    break
            if progress:
                progress(replace(value, file_index=index, file_count=len(assets),
                                 overall_completed=sum(completed.values()),
                                 overall_total=sum(asset.size for asset in assets)))

        try:
            # 강제 종료도 다음 시작에서 자동 다운로드로 이어지지 않게 한다.
            history.save('interrupted')
            result = self._prepare(cancellation=cancellation, progress=report)
            self.cleanup_previous_models()
            try:
                history.save('ready')
            except OSError as error:
                log_failure(self.data_directory, 'storage', '준비 완료 기록을 저장하지 못했습니다.', error)
            return result
        except PreparationError as error:
            history.failed(error.kind, str(error), error.detail)
            raise
        except OSError as error:
            failure = PreparationError('storage', error)
            history.failed(failure.kind, str(failure), failure.detail)
            raise failure from error
        except Exception as error:
            history.failed('other', '자막 기능 준비에 실패했습니다.', error)
            raise

    def status(self):
        """이전 실패와 완료 manifest를 읽기만 한다. 다운로드는 시작하지 않는다."""
        from .subtitle_preparation_state import PreparationHistory
        try:
            self.prepared()
        except PreparationError:
            previous = PreparationHistory(self.data_directory).read()
            if previous and previous['kind'] != 'ready':
                return previous
            if previous is None and (any((self.data_directory / 'runtime/cuda').glob('*.partial'))
                                     or any((self.data_directory / 'models').rglob('*.partial'))):
                return dict(kind='interrupted', message=PreparationError.MESSAGES['interrupted'], detail='')
            return dict(kind='idle', message='', detail='')
        return dict(kind='ready', message='', detail='')

    def _prepare(self, *, cancellation: Event | None = None, progress: Progress | None = None) -> PreparedSubtitles:
        cancellation = cancellation if cancellation is not None else Event()
        _check_cancel(cancellation)
        while not _preparation_lock.acquire(timeout=0.1):
            _check_cancel(cancellation)
        try:
            _check_cancel(cancellation)
            try:
                _report(progress, cancellation, "probe", "NVIDIA GPU", 0, 0)
                available = (self.gpu_available() if self.gpu_available is not None else
                             cuda_gpu_available(cancellation=cancellation))
            except PreparationError:
                raise
            except Exception as error:
                raise PreparationError("gpu_unavailable", error) from error
            if not available:
                raise PreparationError("gpu_unavailable")
            with _directory_lock(self.data_directory, cancellation):
                directories = tuple(self._prepare_group(
                    self.data_directory / "runtime/cuda" / asset.sha256, (asset,), True, cancellation, progress)
                    for asset in self.cuda_assets)
                model = self._prepare_model(cancellation, progress)
            _report(progress, cancellation, "ready", "subtitles", 1, 1)
            return PreparedSubtitles(directories, model)
        except OSError as error:
            kind = "disk_full" if error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112) else "storage"
            raise PreparationError(kind, error) from error
        finally:
            _preparation_lock.release()

    def prepared(self) -> PreparedSubtitles:
        """이미 검증·게시된 결과만 읽는다. 탐지·다운로드·해시 검증·쓰기는 하지 않는다."""
        directories = tuple(self.data_directory / "runtime/cuda" / asset.sha256 for asset in self.cuda_assets)
        if all(_is_ready(path, (asset,)) for path, asset in zip(directories, self.cuda_assets)):
            for model in self._model_directories():
                if _is_ready(model, self.model_assets):
                    return PreparedSubtitles(directories, model)
        raise PreparationError("preparation_required")

    def _model_directories(self):
        models = self.data_directory / "models"
        return (models / WHISPER_MODEL / self.model_revision,
                models / ('models--' + WHISPER_REPOSITORY.replace('/', '--')) / "snapshots" / self.model_revision)

    def start_cleanup_if_ready(self) -> Thread | None:
        """설치판 앱 시작에서 한 번 호출한다. 삭제는 시작을 막지 않는 뒤 작업이다."""
        try:
            self.prepared()
            worker = Thread(target=self.cleanup_previous_models, name='previous-model-cleanup', daemon=True)
            worker.start()
            return worker
        except PreparationError:
            return None
        except (OSError, RuntimeError) as error:
            log_failure(self.data_directory, 'storage', '이전 모델 정리를 시작하지 못했습니다.', error)
            return None

    def cleanup_previous_models(self):
        """turbo 게시 뒤 앱 전용 large-v3만 정리한다. 실패는 다음 준비/시작에서 재시도한다."""
        try:
            self.prepared()
            models = self.data_directory / 'models'
            # models 자체가 정션인 경우에도 외부 저장소를 따라 들어가지 않는다.
            if not _plain_directory(models) or models.resolve().parent != self.data_directory:
                return
            for target in models.iterdir():
                name = target.name
                legacy = (name == 'large-v3' or
                          (name.startswith('large-v3') and name.endswith('.partial')
                           and not name.startswith(WHISPER_MODEL)))
                if not legacy:
                    continue
                try:
                    if (target.parent == models and _plain_directory(target)
                            and target.resolve().parent == models):
                        # Python 3.8+ rmtree는 하위 symlink/Windows junction을 따라가지 않는다.
                        shutil.rmtree(target)
                except OSError as error:
                    log_failure(self.data_directory, 'storage', '이전 모델 폴더를 정리하지 못했습니다.', error)
        except PreparationError:
            return
        except OSError as error:
            log_failure(self.data_directory, 'storage', '이전 모델 폴더를 정리하지 못했습니다.', error)

    def _prepare_model(self, cancellation, progress):
        target, cached = self._model_directories()
        stage = target.with_name(target.name + ".partial")
        if stage.exists():
            shutil.rmtree(stage)
        if _is_ready(target, self.model_assets):
            return self._prepare_group(target, self.model_assets, False, cancellation, progress)
        if _is_ready(cached, self.model_assets):
            for asset in self.model_assets:
                _report(progress, cancellation, "reuse", asset.name, 1, 1)
            return cached
        if all((cached / asset.name).is_file() and (cached / asset.name).stat().st_size == asset.size
               for asset in self.model_assets):
            try:
                for asset in self.model_assets:
                    self.adapter.verify(asset, cached / asset.name, cancellation, progress)
            except PreparationError as error:
                if error.kind != "hash_mismatch":
                    raise
                # 다른 작업이 쓰는 HF 캐시는 지우지 않고 앱 전용 폴더에 새로 받는다.
            else:
                _check_cancel(cancellation)
                manifest = {"assets": _manifest(self.model_assets),
                            "files": {asset.name: asset.size for asset in self.model_assets}}
                partial = cached / "ready.json.part"
                partial.write_text(json.dumps(manifest), encoding="utf-8")
                partial.replace(cached / "ready.json")
                for asset in self.model_assets:
                    _report(progress, cancellation, "reuse", asset.name, 1, 1)
                return cached
        return self._prepare_group(target, self.model_assets, False, cancellation, progress)

    def _prepare_group(self, target, assets, extract, cancellation, progress):
        stage = target.with_name(target.name + ".partial")
        # 완료 표시가 없는 파일을 재사용하지 않는다. 실패 시 그대로 두고 재시도 때 정리한다.
        if stage.exists():
            shutil.rmtree(stage)
        if _is_ready(target, assets):
            for asset in assets:
                _report(progress, cancellation, "reuse", asset.name, 1, 1)
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
