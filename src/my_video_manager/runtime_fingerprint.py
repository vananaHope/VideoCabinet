"""Versioned runtime identity, independent of application code and version.

This is a compatibility identifier, not a signature or an integrity guarantee.
Only build inputs are hashed; installed applications never inspect the build PC.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase


FILENAME = 'runtime-fingerprint.json'
SCHEMA_VERSION = 2
NATIVE_FILES = ('ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe', 'mpv/libmpv-2.dll')
# The complete input policy lives here. Descriptions are explanatory, not hashed.
APP_OWNED_PATHS = ('my-video-manager.exe', 'my_video_manager/**', 'my_video_manager-*.dist-info/**',
                   'licenses/**', 'third-party-notices.txt', FILENAME)
INPUT_REASONS = {
    'dependencies': 'Actual bundled Python distributions, pinned name==version; excludes the app itself.',
    'python': 'Python implementation, full version, platform and machine define interpreter compatibility.',
    'tools': 'PyInstaller and pyinstaller-hooks-contrib versions affect frozen runtime collection.',
    'native_files': 'SHA-256 of bundled ffmpeg, ffprobe and libmpv identifies the exact media binaries.',
    'hooks': 'SHA-256 of installer/hooks/*.py with CRLF normalized to LF detects custom collection policy changes.',
    'bundle_files': 'Sorted unique binary/data destinations, with Windows case and separators normalized; '
                    'detects runtime file selection changes without hashing sizes or contents. '
                    'Excludes PYZ pure Python (replaced with the exe) and app-owned paths replaced by app updates: '
                    + ', '.join(APP_OWNED_PATHS),
}


def make_runtime_fingerprint(*, dependencies: Mapping[str, str], python: Mapping[str, str],
                             tools: Mapping[str, str], native_files: Mapping[str, str],
                             hooks: Mapping[str, str], bundle_files: Sequence[str]) -> dict:
    """Compute a deterministic document from injected inputs, without IO.

    Dependencies are the resolved bundle snapshot, not the whole development
    environment or project metadata. App package aliases are always excluded.
    """
    locked = {}
    for name, version in dependencies.items():
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized == 'my-video-manager':
            continue
        if normalized in locked and locked[normalized] != version:
            raise ValueError(f'Conflicting runtime dependency: {normalized}')
        locked[normalized] = version
    inputs = dict(dependencies=locked, python=dict(python), tools=dict(tools),
                  native_files=dict(native_files), hooks=dict(hooks))
    for group, values in inputs.items():
        if not values or any(not isinstance(k, str) or not k or
                             not isinstance(v, str) or not v for k, v in values.items()):
            raise ValueError(f'Invalid runtime fingerprint input: {group}')
    required = {
        'python': {'implementation', 'version', 'platform', 'machine'},
        'tools': {'pyinstaller', 'pyinstaller-hooks-contrib'},
        'native_files': set(NATIVE_FILES),
    }
    for group, keys in required.items():
        if set(inputs[group]) != keys:
            raise ValueError(f'Invalid runtime fingerprint keys: {group}')
    for group in ('native_files', 'hooks'):
        if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in inputs[group].values()):
            raise ValueError(f'Invalid SHA-256: {group}')
    if isinstance(bundle_files, (str, bytes)) or not isinstance(bundle_files, Sequence) or any(
            not isinstance(name, str) or not name for name in bundle_files):
        raise ValueError('Invalid runtime fingerprint input: bundle_files')
    destinations = {name.replace('\\', '/').lower() for name in bundle_files}
    inputs['bundle_files'] = sorted(name for name in destinations
                                    if not any(fnmatchcase(name, pattern) for pattern in APP_OWNED_PATHS))
    payload = {'schema_version': SCHEMA_VERSION, 'inputs': inputs}
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return {**payload, 'fingerprint': hashlib.sha256(encoded).hexdigest(),
            'input_reasons': dict(INPUT_REASONS)}


def load_runtime_fingerprint(path: Path) -> dict:
    """Read and validate a document; missing/invalid files raise, for build checks."""
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported runtime fingerprint schema')
    inputs = document.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_REASONS) or any(
            not isinstance(value, list if group == 'bundle_files' else dict)
            for group, value in inputs.items()):
        raise ValueError('Invalid runtime fingerprint inputs')
    expected = make_runtime_fingerprint(**inputs)
    if document.get('fingerprint') != expected['fingerprint'] or inputs != expected['inputs']:
        raise ValueError('Runtime fingerprint mismatch')
    return document


def installed_runtime_fingerprint() -> str | None:
    """Return this installation's identity, or None for source/old/invalid installs."""
    if not getattr(sys, 'frozen', False):
        return None
    try:
        return load_runtime_fingerprint(Path(sys.executable).resolve().parent / FILENAME)['fingerprint']
    except (OSError, ValueError, RecursionError):
        return None
