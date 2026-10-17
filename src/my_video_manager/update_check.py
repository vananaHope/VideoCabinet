"""Update decisions and persisted display state; no UI or installer execution."""
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
import re
import unicodedata
from typing import Callable, Literal, Protocol

from . import update_manifest
from .app_version import RELEASE_REPOSITORY, RELEASES_URL, current_version
from .runtime_fingerprint import installed_runtime_fingerprint
from .settings import Settings
from .update_http import UpdateCheckError, UrllibUpdateHttp
from .update_manifest import FILENAME, ManifestError, verify_manifest


LATEST_RELEASE_URL = f'https://api.github.com/repos/{RELEASE_REPOSITORY}/releases/latest'
AUTO_CHECK_INTERVAL = timedelta(days=1)
TRANSIENT_FAILURE_CHECK_INTERVAL = timedelta(hours=3)
AUTO_CHECK_KEY = 'updates.check_on_startup'
LAST_CHECK_KEY = 'updates.last_check'
SKIPPED_VERSION_KEY = 'updates.skipped_version'
METADATA_LIMIT = 1024 * 1024
MANIFEST_LIMIT = 64 * 1024
# Release notes come from the unsigned GitHub API body: display-only plain text.
RELEASE_NOTES_LIMIT = 400
RELEASE_NOTES_LINES = 8
RELEASE_NOTES_SCAN = 20_000
RELEASE_NOTES_PASSES = 5
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

    latest_version identifies the verified release; a skipped version is compared to it.
    A future installer must fetch and verify metadata again, never trust this
    editable settings record. No unverified release fields survive a failure.
    release_notes is a short plain-text summary of the unsigned release body,
    kept only for display next to a patch/full result.
    """

    checked_at: datetime
    kind: UpdateKind
    current_version: str | None = None
    latest_version: str | None = None
    download_size: int | None = None
    failure_reason: str | None = None
    release_notes: str | None = None
    # Whether this history belongs to a different installed app version.
    # UpdateChecker computes it from its installation adapter; never persisted.
    # UI consumers must distinguish stale history from an update currently
    # available for the installed app.
    stale: bool = field(default=False, kw_only=True)

    @property
    def release_url(self) -> str | None:
        return f'{RELEASES_URL}/tag/v{self.latest_version}' if self.latest_version else None


def _version(value: str) -> tuple:
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('invalid version')
    # Numeric ordering without integer conversion limits on untrusted strings.
    return tuple((len(part), part) for part in value.split('.'))


def offers_update(result: UpdateCheckResult | None) -> bool:
    """Whether a result describes an update for the installed app (not stale history)."""
    return result is not None and not result.stale and result.kind in ('patch', 'full')


def announces_update(result: UpdateCheckResult | None, skipped_version: str | None) -> bool:
    """Whether to announce a result: a current update whose version is not the skipped one."""
    return offers_update(result) and result.latest_version != skipped_version


def release_notes_summary(body) -> str | None:
    """Short display text from an unsigned release body; Markdown/HTML are never rendered.

    Markup characters are dropped for readability, link targets and bare URLs
    are removed, control and format characters (including bidi overrides) are
    stripped. The summary of a summary is the same text, so a saved summary
    can be checked by summarizing it again.
    """
    if not isinstance(body, str):
        return None
    text = _summary_once(body)
    # Removing inline markup can join the pieces of a tag (a <**b**> c), so summarize
    # again until nothing changes. Real notes settle in one or two passes.
    for _ in range(RELEASE_NOTES_PASSES):
        if text is None or (again := _summary_once(text)) == text:
            break
        text = again
    return text


def _summary_once(body: str) -> str | None:
    # Comments and tags may span lines; GitHub hides them, so they never show here either.
    text = _until_stable(lambda value: re.sub(r'<!--.*?(?:-->|$)|</?[A-Za-z][^>]*>', '', value, flags=re.DOTALL),
                         body[:RELEASE_NOTES_SCAN])
    lines = []
    for raw in text.splitlines():
        line = ''.join(' ' if ch == '\t' else ch for ch in raw
                       if ch == '\t' or unicodedata.category(ch)[0] != 'C')
        nested = line[:1].isspace()
        line = _until_stable(_plain_line, line.strip())
        if item := re.match(r'[-*+](?:\s+|$)(.*)', line):
            line = item[1] and ('  · ' if nested else '· ') + item[1]
        elif nested and line.startswith('· '):
            line = '  ' + line  # an already summarized nested item
        if line:
            lines.append(line)
    text = '\n'.join(lines[:RELEASE_NOTES_LINES])
    if len(lines) <= RELEASE_NOTES_LINES and len(text) <= RELEASE_NOTES_LIMIT:
        return text or None
    return text[:RELEASE_NOTES_LIMIT - 1].rstrip() + '…'


# A link label with one level of brackets, and a target with one level of parentheses.
_LABEL = r'((?:[^\[\]]|\[[^\[\]]*\])*)'
_TARGET = r'(?:[^()\s]|\([^()\s]*\))*(?:\s+"[^"]*")?'


def _plain_line(line: str) -> str:
    if re.match(r'\[[^\]]+\]:\s', line):
        return ''  # reference link definition: [1]: https://...
    line = re.sub(r'^#{1,6}\s+', '', line)
    line = re.sub(rf'!?\[{_LABEL}\]\({_TARGET}\)', r'\1', line)
    line = re.sub(rf'!?\[{_LABEL}\]\[[^\[\]]*\]', r'\1', line)
    line = re.sub(r'https?://\S+', '', line)
    return re.sub(r'\*\*|__|`', '', line).strip()


def _until_stable(clean: Callable[[str], str], value: str) -> str:
    # Removing one piece of markup can join the pieces of another, e.g. <<b>b>.
    while (cleaned := clean(value)) != value:
        value = cleaned
    return value


def _transient(reason: str | None) -> bool:
    """Failures likely to clear soon: connectivity and GitHub server errors."""
    return reason in ('network', 'timeout') or bool(re.fullmatch(r'http_5[0-9][0-9]', reason or ''))


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
                        or result.release_notes is not None
                        or not isinstance(result.failure_reason, str)
                        or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', result.failure_reason)):
                    return None
            else:
                _version(result.current_version)
                _version(result.latest_version)
                if result.failure_reason is not None:
                    return None
                if result.kind == 'none':
                    if result.download_size is not None or result.release_notes is not None:
                        return None
                elif type(result.download_size) is not int or result.download_size <= 0:
                    return None
                elif result.release_notes is not None and (
                        not isinstance(result.release_notes, str)
                        or not 0 < len(result.release_notes) <= RELEASE_NOTES_LIMIT
                        or release_notes_summary(result.release_notes) != result.release_notes):
                    return None
            stale = result.current_version is None or result.current_version != self._installed_version()
            return replace(result, stale=stale)
        except (TypeError, ValueError, KeyError, OverflowError):
            return None

    def _installed_version(self) -> str | None:
        try:
            return self._installation().version
        except Exception:
            # Unreadable installation info always counts as stale: check again.
            return None

    def skipped_version(self) -> str | None:
        value = self._settings.get(SKIPPED_VERSION_KEY)
        try:
            _version(value)
        except ValueError:
            return None
        return value

    def skip_version(self, version: str) -> None:
        """Remember one release not to announce; a different latest version is announced again."""
        _version(version)
        self._settings.set(SKIPPED_VERSION_KEY, version)

    def clear_skipped_version(self) -> None:
        self._settings.reset(SKIPPED_VERSION_KEY)

    def update_to_announce(self) -> UpdateCheckResult | None:
        """The last result to announce: a current patch/full update whose version is not skipped."""
        last = self.last_result()
        return last if announces_update(last, self.skipped_version()) else None

    def should_check_on_startup(self) -> bool:
        if not self.automatic_enabled():
            return False
        last = self.last_result()
        if last is None or last.stale:
            return True
        elapsed = _utc(self._clock()) - last.checked_at
        interval = (TRANSIENT_FAILURE_CHECK_INTERVAL
                    if last.kind == 'failed' and _transient(last.failure_reason)
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
            size = notes = None
            if _version(manifest.version) > installed_version:
                if manifest.patch_available and installed.runtime_fingerprint == manifest.previous_runtime_fingerprint:
                    kind, size = 'patch', manifest.patch.size
                else:
                    kind, size = 'full', manifest.full.size
                # Reuse the release response already fetched; never a separate request.
                notes = release_notes_summary(release.get('body'))
            result = UpdateCheckResult(checked_at, kind, current, manifest.version, size, release_notes=notes)
        except (UpdateCheckError, ManifestError) as exc:
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason=exc.kind)
        except (TimeoutError, OSError) as exc:
            reason = 'timeout' if isinstance(exc, TimeoutError) else 'network'
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason=reason)
        except Exception:
            # Isolate adapter failures from ordinary app use; do not persist
            # exception strings, which may contain local paths or remote data.
            result = UpdateCheckResult(checked_at, 'failed', current, failure_reason='check_failed')
        record = asdict(result)
        del record['stale']
        self._settings.set(LAST_CHECK_KEY, {**record, 'checked_at': checked_at.isoformat()})
        # Same rule as last_result: without a readable installed version it is stale.
        return replace(result, stale=current is None)
