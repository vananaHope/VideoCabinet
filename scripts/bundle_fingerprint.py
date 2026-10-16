"""Build adapter for the runtime identity; called after PyInstaller Analysis."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys
from collections.abc import Sequence

from my_video_manager.runtime_fingerprint import (
    FILENAME, NATIVE_FILES, load_runtime_fingerprint, make_runtime_fingerprint,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle_fingerprint(stage: Path, mpv_directory: Path, hooks_directory: Path,
                             *, bundle_files: Sequence[str]) -> Path:
    """Use the exact media sources and distribution snapshot selected by Analysis."""
    packages = json.loads((stage / 'licenses/python/manifest.json').read_text(encoding='utf-8'))
    native = {name: file_sha256(mpv_directory / Path(name).name if name.startswith('mpv/')
                                else stage / name) for name in NATIVE_FILES}
    document = make_runtime_fingerprint(
        dependencies={p['name']: p['version'] for p in packages if p['name'] != 'python'},
        python={'implementation': platform.python_implementation(), 'version': sys.version,
                'platform': sys.platform, 'machine': platform.machine()},
        tools={name: metadata.version(name) for name in ('pyinstaller', 'pyinstaller-hooks-contrib')},
        native_files=native,
        hooks={p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
               for p in sorted(hooks_directory.glob('*.py'))},
        bundle_files=bundle_files,
    )
    path = stage / FILENAME
    # All inputs must succeed before replacing a previous build's document.
    temporary = path.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def verify_bundle_fingerprint(directory: Path) -> str:
    """Verify a completed bundle, without substituting the current build environment."""
    document = load_runtime_fingerprint(directory / FILENAME)
    for name in NATIVE_FILES:
        if file_sha256(directory / name) != document['inputs']['native_files'][name]:
            raise ValueError(f'Runtime fingerprint binary mismatch: {name}')
    return document['fingerprint']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', type=Path, required=True)
    print(verify_bundle_fingerprint(parser.parse_args().check))
