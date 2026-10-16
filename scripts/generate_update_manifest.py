"""Generate signed local release metadata; never publishes or builds installers."""
import argparse
import hashlib
from pathlib import Path
import sys
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from my_video_manager.runtime_fingerprint import load_runtime_fingerprint
from my_video_manager import update_manifest
from my_video_manager.update_manifest import (
    FILENAME, SCHEMA_VERSION, UpdateAsset, UpdateManifest, encode_manifest, verify_manifest,
)
from generate_update_key import default_key_path, load_signing_key


def describe_asset(path: Path) -> UpdateAsset:
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return UpdateAsset(path.name, size, digest.hexdigest())


def build_manifest(*, version: str, runtime: Path, full: Path,
                   previous_runtime: Path | None = None, patch: Path | None = None) -> UpdateManifest:
    current = load_runtime_fingerprint(runtime)['fingerprint']
    previous = None if previous_runtime is None else load_runtime_fingerprint(previous_runtime)['fingerprint']
    compatible = current == previous
    if compatible != (patch is not None):
        raise ValueError('Matching previous runtime requires a patch; first/changed runtime requires no patch')
    manifest = UpdateManifest(SCHEMA_VERSION, version, current, previous,
                              describe_asset(full), None if patch is None else describe_asset(patch), compatible)
    return manifest


def write_signed_manifest(manifest: UpdateManifest, key: Ed25519PrivateKey, output: Path,
                          *, allow_unpinned_key_for_tests: bool = False) -> tuple[Path, Path]:
    """Sign exact serialized bytes; refuse overwrite and remove partial new output."""
    data = encode_manifest(manifest)
    signature = key.sign(data)
    verify_manifest(data, signature, public_key=key.public_key().public_bytes_raw())
    if allow_unpinned_key_for_tests:
        print('WARNING: test-only unpinned signing key; not for release publication', file=sys.stderr)
    else:
        if not update_manifest.UPDATE_PUBLIC_KEY:
            raise ValueError('앱 공개 키가 설정되지 않았습니다')
        if key.public_key().public_bytes_raw() != update_manifest.UPDATE_PUBLIC_KEY:
            raise ValueError('서명 키가 앱 공개 키와 다릅니다')
        verify_manifest(data, signature)
    signature_path = output.with_name(output.name + '.sig')
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, payload in ((output, data), (signature_path, signature)):
            with path.open('xb') as stream:
                created.append(path)
                stream.write(payload)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return output, signature_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--runtime-fingerprint', type=Path, required=True)
    parser.add_argument('--previous-runtime-fingerprint', type=Path)
    parser.add_argument('--full', type=Path, required=True)
    parser.add_argument('--patch', type=Path)
    parser.add_argument('--private-key', type=Path, default=default_key_path())
    parser.add_argument('--output', type=Path, default=Path('dist/installer') / FILENAME)
    parser.add_argument('--allow-unpinned-key-for-tests', action='store_true',
                        help='TEST ONLY: bypass the embedded application public key check')
    args = parser.parse_args(argv)
    try:
        key = load_signing_key(args.private_key)
        manifest = build_manifest(version=args.version, runtime=args.runtime_fingerprint, full=args.full,
                                  previous_runtime=args.previous_runtime_fingerprint, patch=args.patch)
        paths = write_signed_manifest(manifest, key, args.output,
                                      allow_unpinned_key_for_tests=args.allow_unpinned_key_for_tests)
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Manifest generation failed: {exc}\n')
    for path in paths:
        print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
