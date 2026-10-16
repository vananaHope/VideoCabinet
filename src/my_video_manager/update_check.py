"""Update decisions and persisted display state; no UI or installer execution."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Callable, Literal, Protocol

from . import update_manifest
from .app_version import RELEASES_URL, current_version
from .runtime_fingerprint import installed_runtime_fingerprint
from .settings import Settings
from .update_http import UpdateCheckError, UrllibUpdateHttp
from .update_manifest import FILENAME, ManifestError, verify_manifest


LATEST_RELEASE_URL = 'https://api.github.com/repos/vananaHope/my-video-manager/releases/latest'
AUTO_CHECK_INTERVAL = timedelta(days=1)
TRANSIENT_FAILURE_CHECK_INTERVAL = timedelta(hours=3)
AUTO_CHECK_KEY = 'updates.check_on_startup'
LAST_CHECK_KEY = 'updates.last_check'
METADATA_LIMIT = 1024 * 1024
MANIFEST_LIMIT = 64 * 1024
UpdateKind = Literal['none', 'patch', 'full', 'failed']


class UpdateHttp(Protocol):
    def get(self, url: str, *, max_bytes: int) -> bytes: ...


@dataclass(frozen=True)
class InstalledUpdateInfo:
    version: str
    runtime_fingerprint: str | None


def installed_update_info() -> InstalledUpdateInfo:
    """Read the same in-process version as Settings/--version; never spawn exe."""
    return InstalledUpdateInfo(current_version(), installed_runtime_fingerprint())


@dataclass(frozen=True)
class UpdateCheckResult:
    """Historical display state, NOT authorization to download or install.

    latest_version identifies the verified release for future skip-version UI.
    A future installer must fetch and verify metadata again, never trust this
    editable settings record. No unverified release fields survive a failure.
    """

    checked_at: datetime
    kind: UpdateKind
    current_version: str | None = None
    latest_version: str | None = None
    download_size: int | None = None
    failure_reason: str | None = None

    @property
    def stale(self) -> bool:
        """Whether this history belongs to a different installed app version.

        Computed on access, never persisted. UI consumers must distinguish stale
        history from an update currently available for the installed app.
        """
        return self.current_version != current_version()

    @property
    def release_url(self) -> str | None:
        return f'{RELEASES_URL}/tag/v{self.latest_version}' if self.latest_version else None


def _version(value: str) -> tuple:
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('invalid version')
    # Numeric ordering without integer conversion limits on untrusted strings.
    return tuple((len(part), part) for part in value.split('.'))


def _utc(value: datetime) -> datetime:
    # Match existing clocks: naive datetime values represent local wall time.
    return value.astimezone(timezone.utc)


class UpdateChecker:
    def __init__(self, settings: Settings, *, clock: Callable[[], datetime],
                 http: UpdateHttp | None = None,
                 installation: Callable[[], InstalledUpdateInfo] | None = None):
        self._settings = settings
        self._clock = clock
        self._http = http
        self._installation = installation if installation is not None else installed_update_info

    def automatic_enabled(self) -> bool:
        value = self._settings.get(AUTO_CHECK_KEY, True)
        return value if type(value) is bool else True

    def set_automatic_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError('enabled must be bool')
        self._settings.set(AUTO_CHECK_KEY, enabled)

    def last_result(self) -> UpdateCheckResult | None:
        saved = self._settings.get(LAST_CHECK_KEY)
        if not isinstance(saved, dict):
            return None
        try:
            result = UpdateCheckResult(**{**saved, 'checked_at': datetime.fromisoformat(saved['checked_at'])})
            if result.checked_at.tzinfo is None or result.kind not in ('none', 'patch', 'full', 'failed'):
                return None
            if result.current_version is not None:
                _version(result.current_version)
            if result.kind == 'failed':
                if (result.latest_version is not None or result.download_size is not None
                        or not isinstance(result.failure_reason, str)
                        or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', result.failure_reason)):
                    return None
            else:
                _version(result.current_version)
                _version(result.latest_version)
                if result.failure_reason is not None:
                    return None
                if result.kind == 'none':
                    if result.download_size is not None:
                        return None
                elif type(result.download_size) is not int or result.download_size <= 0:
                    return None
            return result
        except (TypeError, ValueError, KeyError, OverflowError):
            return None

    def should_check_on_startup(self) -> bool:
        if not self.automatic_enabled():
            return False
        last = self.last_result()
        if last is None or last.stale:
            return True
        elapsed = _utc(self._clock()) - last.checked_at
        interval = (TRANSIENT_FAILURE_CHECK_INTERVAL
                    if last.kind == 'failed' and last.failure_reason in ('network', 'timeout')
                    else AUTO_CHECK_INTERVAL)
        # A clock correction must not suppress checks indefinitely.
        return elapsed < timedelta(0) or elapsed >= interval

    def check(self) -> UpdateCheckResult:
        """Synchronous I/O; the UI owns worker scheduling and duplicate exclusion.

        Manual checks always run. Only should_check_on_startup applies retry
        intervals, including failed attempts, to avoid restart/retry storms.
        """
        checked_at = _utc(self._clock())
        current = None
        try:
            try:
                installed = self._installation()
            except Exception:
                raise UpdateCheckError('installation_unavailable') from None
            try:
                installed_version = _version(installed.version)
            except (ValueError, AttributeError):
                raise UpdateCheckError('invalid_installed_version') from None
            current = installed.version
            key = update_manifest.UPDATE_PUBLIC_KEY
            if not isinstance(key, bytes) or len(key) != 32:
                raise ManifestError('invalid_public_key')
            http = self._http if self._http is not None else UrllibUpdateHttp()
            release_data = http.get(LATEST_RELEASE_URL, max_bytes=METADATA_LIMIT)
            try:
                release = json.loads(release_data)
                tag = release['tag_name']
                if (release.get('draft') is not False or release.get('prerelease') is not False
                        or not isinstance(tag, str) or not tag.startswith('v')):
                    raise ValueError()
                _version(tag[1:])
            except (ValueError, KeyError, TypeError, RecursionError):
                raise UpdateCheckError('invalid_release') from None
            # Pin both requests to ONE release; latest/download could move
            # between the document request and the signature request.
            base = f'{RELEASES_URL}/download/{tag}'
            data = http.get(f'{base}/{FILENAME}', max_bytes=MANIFEST_LIMIT)
            signature = http.get(f'{base}/{FILENAME}.sig', max_bytes=64)
            manifest = verify_manifest(data, signature)
            if manifest.version != tag[1:]:
                raise UpdateCheckError('release_version_mismatch')
            kind: UpdateKind = 'none'
            size = None
            if _version(manifest.version) > installed_version:
                if manifest.patch_available and installed.runtime_fingerprint == manifest.previous_runtime_fingerprint:
                    kind, size = 'patch', manifest.patch.size
                else:
                    kind, size = 'full', manifest.full.size
            result = UpdateCheckResult(checked_at, kind, current, manifest.version, size)
        except (UpdateCheckError, ManifestError) as exc:
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason=exc.kind)
        except (TimeoutError, OSError) as exc:
            reason = 'timeout' if isinstance(exc, TimeoutError) else 'network'
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason=reason)
        except Exception:
            # Isolate adapter failures from ordinary app use; do not persist
            # exception strings, which may contain local paths or remote data.
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason='check_failed')
        self._settings.set(LAST_CHECK_KEY, {**asdict(result), 'checked_at': checked_at.isoformat()})
        return result
