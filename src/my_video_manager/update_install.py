"""Update download, verification and the post-exit installer handoff; no UI.

UpdateCheckResult is history, not authorization (see update_check): downloading
fetches the signed manifest of that release again and trusts only its file
names, sizes and hashes. Installer URLs are built from the manifest filename and
the same release tag, never from unsigned GitHub API fields.

The installer replaces my-video-manager.exe, so it cannot run while the app or
any process started from the install folder is alive. A small Windows
PowerShell helper (HELPER_SCRIPT) outlives the app: it waits for the app
process, runs the installer silently, records the exit code, and starts the app
again. The app reads that record on the next start (last_install).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable, Literal, Protocol, Sequence

from .app_version import RELEASES_URL
from .update_check import MANIFEST_LIMIT, InstalledUpdateInfo, _version
from .update_http import UpdateCheckError
from .update_manifest import FILENAME, ManifestError, verify_manifest

log = logging.getLogger(__name__)

UPDATES_DIRECTORY = 'updates'
INSTALLER_LOG = 'installer.log'
# Inno Setup: no UI or message boxes, never reboot, close (and do not restart)
# leftover processes that hold install files; the helper restarts the app.
INSTALLER_ARGUMENTS = ('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                       '/CLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS')
# installer/patch-validation.iss: PrepareToInstall rejected the installed runtime.
PATCH_REJECTED_EXIT_CODE = 7
APP_EXIT_TIMEOUT_MS = 5 * 60 * 1000
# A stuck installer is recorded as installer_timeout and left running.
INSTALLER_TIMEOUT_MS = 30 * 60 * 1000
READY_TIMEOUT = 20.0
UpdateAssetKind = Literal['patch', 'full']


class UpdateInstallError(Exception):
    """A stable code, never a path, URL, or exception message."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)


class UpdateDownloadHttp(Protocol):
    def get(self, url: str, *, max_bytes: int) -> bytes: ...

    def download(self, url: str, *, size: int, write: Callable[[bytes], object], cancellation=None) -> None: ...


@dataclass(frozen=True)
class PreparedUpdate:
    """An installer whose size and SHA-256 matched the signed manifest."""

    version: str
    kind: UpdateAssetKind
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdateDownloadResult:
    status: Literal['ready', 'failed', 'cancelled']
    update: PreparedUpdate | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class UpdateBusyState:
    """blocking: work a restart would interrupt now ('playback', 'transcription',
    'translation', 'refinement'). waiting_*: queued or held items that simply
    resume after the restart; information for the user, not a reason to wait.
    """

    blocking: tuple[str, ...]
    waiting_transcriptions: int
    waiting_translations: int


@dataclass(frozen=True)
class UpdateInstallOutcome:
    """The last installer handoff, read on a later start until cleared."""

    version: str
    kind: UpdateAssetKind
    started_at: datetime
    status: Literal['installed', 'failed', 'incomplete']
    failure_reason: str | None = None
    exit_code: int | None = None

    @property
    def retry_full(self) -> bool:
        """Only a patch that actually ran and failed is retried with the full installer.

        Other failures (the app did not exit, the installer never started or
        timed out, a changed file, no result) retry the same kind.
        """
        return self.kind == 'patch' and self.failure_reason in ('patch_rejected', 'installer_failed')


def updates_directory(data_directory: Path) -> Path:
    return Path(data_directory) / UPDATES_DIRECTORY


def _downloads(data_directory: Path) -> Path:
    return updates_directory(data_directory) / 'download'


def download_update(data_directory: Path, result, installation: Callable[[], InstalledUpdateInfo], *,
                    http: UpdateDownloadHttp, full: bool = False, progress=None,
                    cancellation=None) -> UpdateDownloadResult:
    """Synchronous download and verification for a worker thread.

    result is the latest UpdateCheckResult; only its version is used. full=True
    skips the patch (retry after a failed patch). progress(received, total) runs
    on the calling thread. Every failure or cancellation removes the partial file.
    """
    partial = None
    try:
        if (result is None or getattr(result, 'stale', True) or result.kind not in ('patch', 'full')
                or not isinstance(result.latest_version, str)):
            raise UpdateInstallError('no_update')
        version = result.latest_version
        try:
            target = _version(version)
        except ValueError:
            raise UpdateInstallError('no_update') from None
        try:
            installed = installation()
            installed_version = _version(installed.version)
        except Exception:
            raise UpdateInstallError('installation_unavailable') from None
        if target <= installed_version:
            raise UpdateInstallError('not_newer')
        base = f'{RELEASES_URL}/download/v{version}'
        data = http.get(f'{base}/{FILENAME}', max_bytes=MANIFEST_LIMIT)
        signature = http.get(f'{base}/{FILENAME}.sig', max_bytes=64)
        manifest = verify_manifest(data, signature)
        if manifest.version != version:
            raise UpdateInstallError('release_version_mismatch')
        if (not full and manifest.patch_available
                and installed.runtime_fingerprint == manifest.previous_runtime_fingerprint):
            kind, asset = 'patch', manifest.patch
        else:
            kind, asset = 'full', manifest.full
        folder = _downloads(data_directory)
        # Only one prepared installer at a time; older downloads are leftovers.
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(folder).free < asset.size:
            raise UpdateInstallError('disk_full')
        partial = folder / f'{asset.filename}.partial'
        digest = hashlib.sha256()
        received = 0
        with partial.open('xb') as output:
            def write(chunk):
                nonlocal received
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, asset.size)

            http.download(f'{base}/{asset.filename}', size=asset.size, write=write, cancellation=cancellation)
        if received != asset.size:
            raise UpdateInstallError('size_mismatch')
        if digest.hexdigest() != asset.sha256:
            raise UpdateInstallError('hash_mismatch')
        installer = folder / asset.filename
        partial.replace(installer)
        partial = None
        return UpdateDownloadResult('ready', PreparedUpdate(version, kind, installer, asset.size, asset.sha256))
    except (UpdateInstallError, UpdateCheckError, ManifestError) as exc:
        reason = exc.kind
    except TimeoutError:
        reason = 'timeout'
    except OSError:
        reason = 'storage'
    except Exception:
        # Do not persist or show exception strings, which may contain local paths.
        log.exception('업데이트 내려받기 실패')
        reason = 'download_failed'
    finally:
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                log.warning('업데이트 임시 파일을 지우지 못했습니다: %s', partial)
    if reason == 'cancelled':
        return UpdateDownloadResult('cancelled')
    return UpdateDownloadResult('failed', failure_reason=reason)


def update_busy_state(*, playing: bool, transcriptions, translations) -> UpdateBusyState:
    blocking = []
    if playing:
        blocking.append('playback')
    if any(entry.state == 'transcribing' for entry in transcriptions):
        blocking.append('transcription')
    active = {'refinement' if entry.kind == 'refinement' else 'translation'
              for entry in translations if entry.state == 'translating'}
    blocking.extend(kind for kind in ('translation', 'refinement') if kind in active)
    return UpdateBusyState(tuple(blocking),
                           sum(entry.state == 'queued' for entry in transcriptions),
                           sum(entry.state in ('queued', 'held') for entry in translations))


# ASCII only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
HELPER_SCRIPT = r"""# Written by my-video-manager for one update. Waits for the app to exit, runs
# the verified installer silently, records its exit code, and starts the app.
param([Parameter(Mandatory = $true)][string]$PlanPath)
$ErrorActionPreference = 'Stop'
$plan = [IO.File]::ReadAllText($PlanPath) | ConvertFrom-Json

function Save-Result([hashtable]$Result) {
    $temporary = $plan.result + '.tmp'
    [IO.File]::WriteAllText($temporary, (ConvertTo-Json $Result -Compress))
    Move-Item -LiteralPath $temporary -Destination $plan.result -Force
}

function Start-Program([string]$Program, [string]$Arguments, [string]$Directory) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Program
    $info.Arguments = $Arguments
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    return [Diagnostics.Process]::Start($info)
}

# Without a handle to the running app we cannot know when it exits: stop
# before signalling ready, so the app keeps running and nothing is installed.
$app = [Diagnostics.Process]::GetProcessById([int]$plan.app_pid)
# An open handle also keeps the PID from being reused while we wait.
$null = $app.Handle
[IO.File]::WriteAllText($plan.ready, 'ready')
if (-not $app.WaitForExit([int]$plan.app_exit_timeout_ms)) {
    # The old app is still running; installing now would fail or kill it.
    Save-Result @{ error = 'app_did_not_exit' }
    exit 1
}
$result = $null
$relaunch = $true
$actual = $null
$unreadable = $false
try {
    # .NET directly: Get-FileHash lives in a module that may fail to load (see helper_environment).
    $stream = [IO.File]::OpenRead($plan.installer)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
    }
} catch {
    $unreadable = $true
}
if ($unreadable) {
    # Missing or locked (e.g. by an antivirus): never run what we could not verify.
    $result = @{ error = 'installer_unreadable' }
} elseif ($actual -ne [string]$plan.sha256) {
    # Changed or unreadable since the app verified it: never run it.
    $result = @{ error = 'hash_mismatch' }
} else {
    try {
        $installer = Start-Program $plan.installer $plan.installer_arguments $plan.working_directory
        if ($installer.WaitForExit([int]$plan.installer_timeout_ms)) {
            $result = @{ exit_code = $installer.ExitCode }
        } else {
            # Still installing: a relaunched app would race it for the same files.
            $result = @{ error = 'installer_timeout' }
            $relaunch = $false
        }
    } catch {
        $result = @{ error = 'installer_start_failed' }
    }
}
try {
    Save-Result $result
} catch {
    # Without a result the next start reads incomplete (or installed).
}
# Start the app even after a failure: it shows the result and the retry.
if ($relaunch) {
    $null = Start-Program $plan.program $plan.arguments $plan.program_directory
}
"""


class HelperProcess(Protocol):
    def poll(self) -> int | None: ...

    def kill(self) -> None: ...


class HelperLauncher(Protocol):
    def start(self, command: Sequence[str], *, cwd: Path) -> HelperProcess: ...


def helper_environment() -> dict[str, str]:
    """The app's environment without PSModulePath for the Windows PowerShell 5.1 helper.

    An app started from PowerShell 7 inherits its PSModulePath; Windows PowerShell
    then picks up PowerShell 7 modules and loses its own commands. Without the
    variable it uses its default module path. The relaunched app inherits this too.
    """
    return {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}


class SubprocessHelperLauncher:
    """Starts the helper without a console window, outside the app's job if allowed."""

    def start(self, command: Sequence[str], *, cwd: Path) -> HelperProcess:
        # The installer handoff runs only on Windows, so the flags are always present.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        options = dict(cwd=cwd, env=helper_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        try:
            # A parent job with kill-on-close (some terminals) would end the helper with the app.
            return subprocess.Popen(list(command), creationflags=(
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_BREAKAWAY_FROM_JOB), **options)
        except OSError:
            # Jobs that forbid breakaway reject the flag; the helper then stays in that job.
            return subprocess.Popen(list(command), creationflags=flags, **options)


def powershell_executable() -> str:
    # An absolute System32 path, not a PATH lookup that the current directory could shadow.
    return str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding='ascii')
    temporary.replace(path)


def start_install(data_directory: Path, update: PreparedUpdate, *, pid: int,
                  relaunch: tuple[str, Sequence[str]], started_at: datetime,
                  launcher: HelperLauncher, ready_timeout: float = READY_TIMEOUT,
                  app_exit_timeout_ms: int = APP_EXIT_TIMEOUT_MS,
                  installer_timeout_ms: int = INSTALLER_TIMEOUT_MS,
                  sleep: Callable[[float], None] = time.sleep) -> None:
    """Start the helper and block until it holds a handle to process pid.

    On return the caller must quit the app (process pid); the helper installs
    after that exit. On UpdateInstallError nothing will be installed and the
    app keeps running. relaunch is (program, arguments) to start afterwards.
    """
    directory = updates_directory(data_directory)
    folder = _downloads(data_directory).resolve()
    path = Path(update.path).resolve()
    try:
        valid = (path.parent == folder and path.is_file() and path.stat().st_size == update.size
                 and update.kind in ('patch', 'full'))
        _version(update.version)
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise UpdateInstallError('installer_missing')
    record = directory / 'install.json'
    result, ready, plan = directory / 'install-result.json', directory / 'helper-ready', directory / 'install-plan.json'
    script = directory / 'install-update.ps1'
    program, arguments = relaunch
    process = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for leftover in (result, ready):
            leftover.unlink(missing_ok=True)
        script.write_text(HELPER_SCRIPT, encoding='ascii')
        _write_json(plan, {
            'app_pid': pid, 'app_exit_timeout_ms': app_exit_timeout_ms,
            'installer': str(path), 'sha256': update.sha256, 'installer_timeout_ms': installer_timeout_ms,
            'installer_arguments': subprocess.list2cmdline(
                [*INSTALLER_ARGUMENTS, f'/LOG={directory.resolve() / INSTALLER_LOG}']),
            'working_directory': str(directory.resolve()),
            'program': str(program), 'arguments': subprocess.list2cmdline([str(a) for a in arguments]),
            'program_directory': str(Path(program).resolve().parent),
            'result': str(result.resolve()), 'ready': str(ready.resolve()),
        })
        # Written before the helper starts: a later start can always tell that an
        # install was attempted, even if the helper dies without a result.
        _write_json(record, {'version': update.version, 'kind': update.kind,
                             'started_at': started_at.astimezone(timezone.utc).isoformat()})
        try:
            process = launcher.start([powershell_executable(), '-NoLogo', '-NoProfile', '-NonInteractive',
                                      '-ExecutionPolicy', 'Bypass', '-File', str(script.resolve()),
                                      '-PlanPath', str(plan.resolve())], cwd=directory.resolve())
        except OSError:
            raise UpdateInstallError('helper_start_failed') from None
        deadline = time.monotonic() + ready_timeout
        while not ready.exists():
            if process.poll() is not None:
                raise UpdateInstallError('helper_failed')
            if time.monotonic() >= deadline:
                raise UpdateInstallError('helper_not_ready')
            sleep(0.05)
    except BaseException as exc:
        # A helper that signals later must not install when the app finally quits.
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
        for leftover in (record, plan, ready):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                log.warning('업데이트 설치 준비 파일을 지우지 못했습니다: %s', leftover)
        if isinstance(exc, OSError):
            raise UpdateInstallError('storage') from None
        raise


def last_install(data_directory: Path, installation: Callable[[], InstalledUpdateInfo]) -> UpdateInstallOutcome | None:
    """The recorded handoff, or None. Damaged records read as None."""
    directory = updates_directory(data_directory)
    try:
        saved = json.loads((directory / 'install.json').read_text(encoding='utf-8-sig'))
        version, kind = saved['version'], saved['kind']
        _version(version)
        started_at = datetime.fromisoformat(saved['started_at'])
        if kind not in ('patch', 'full') or started_at.tzinfo is None:
            return None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        log.warning('업데이트 설치 기록을 읽지 못했습니다')
        return None
    try:
        outcome = json.loads((directory / 'install-result.json').read_text(encoding='utf-8-sig'))
        if not isinstance(outcome, dict):
            outcome = {}
    except (OSError, ValueError):
        outcome = {}
    code, error = outcome.get('exit_code'), outcome.get('error')
    try:
        current = installation().version
    except Exception:
        current = None
    if code == 0 or (code is None and current == version):
        return UpdateInstallOutcome(version, kind, started_at, 'installed', exit_code=code)
    if type(code) is int:
        reason = ('patch_rejected' if kind == 'patch' and code == PATCH_REJECTED_EXIT_CODE
                  else 'installer_failed')
        return UpdateInstallOutcome(version, kind, started_at, 'failed', reason, code)
    if isinstance(error, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', error):
        return UpdateInstallOutcome(version, kind, started_at, 'failed', error)
    # The helper died or was stopped before it recorded the installer's exit.
    return UpdateInstallOutcome(version, kind, started_at, 'incomplete', 'no_result')


def installer_log(data_directory: Path) -> Path:
    return updates_directory(data_directory) / INSTALLER_LOG


def clear_install(data_directory: Path, *, keep_log: bool = False) -> None:
    """Forget the last handoff and remove downloaded installers and helper files.

    keep_log keeps installer.log so a failed install can still be diagnosed;
    the next successful install removes it.
    """
    directory = updates_directory(data_directory)
    (directory / 'install.json').unlink(missing_ok=True)
    # Leftovers (e.g. an installer an antivirus still holds) are retried next time.
    if not keep_log:
        shutil.rmtree(directory, ignore_errors=True)
        return
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name == INSTALLER_LOG:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            try:
                entry.unlink()
            except OSError:
                pass
