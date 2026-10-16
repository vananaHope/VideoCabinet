"""Read previous GitHub metadata, plan patch assets, and sign before publication."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess

from bundle_fingerprint import verify_bundle_fingerprint
from generate_update_key import default_key_path, load_signing_key
from generate_update_manifest import build_manifest, validate_signing_key, write_signed_manifest
from my_video_manager.update_manifest import (
    FILENAME, UpdateAsset, UpdateManifest, encode_manifest, verify_manifest,
)


def version_tuple(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Release version must be X.Y.Z')
    return tuple(map(int, value.split('.')))


def gh_api(endpoint: str, *, optional: bool = False, binary: bool = False) -> bytes | None:
    """Only an explicit HTTP 404 may mean absence; other failures stop release."""
    command = ['gh', 'api', endpoint, '--hostname', 'github.com']
    command += ['-H', 'Accept: application/octet-stream'] if binary else ['--include']
    result = subprocess.run(command, capture_output=True, timeout=60)
    if binary:
        if result.returncode:
            raise ValueError('Previous release asset download failed')
        return result.stdout
    parts = re.split(br'\r?\n\r?\n', result.stdout, maxsplit=1)
    header = parts[0]
    if optional and re.match(br'HTTP/\S+\s+404\b', header):
        return None
    if result.returncode or len(parts) != 2 or not re.match(br'HTTP/\S+\s+200\b', header):
        raise ValueError('Previous release lookup failed (connection, permission or HTTP error)')
    return parts[1]


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def read_previous_manifest(data: bytes, signature: bytes | None) -> UpdateManifest:
    if signature is not None:
        # Verification MUST precede parsing, using only the application's pinned key.
        return verify_manifest(data, signature)
    # Legacy unsigned metadata still goes through the producer's shared schema validator.
    document = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)
    document['full'] = UpdateAsset(**document['full'])
    if document['patch'] is not None:
        document['patch'] = UpdateAsset(**document['patch'])
    manifest = UpdateManifest(**document)
    encode_manifest(manifest)
    return manifest


def previous_release(repository: str, version: str, *, api=gh_api) -> dict:
    target = version_tuple(version)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    empty = {'tag': None, 'runtime_fingerprint': None, 'authentication': 'none',
             'reason': '이전 Release 없음: 첫 릴리스로 취급'}
    data = api(f'repos/{repository}/releases/latest', optional=True)
    if data is None:
        return empty
    release = json.loads(data)
    tag = release['tag_name']
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Previous release tag must be vX.Y.Z')
    if version_tuple(tag[1:]) >= target:
        raise ValueError('Previous release version must be lower than the new version')
    if release['draft'] or release['prerelease']:
        raise ValueError('Previous release must be a published stable release')
    empty['tag'] = tag
    assets = {asset['name']: asset['id'] for asset in release['assets']}
    if FILENAME not in assets:
        return {**empty, 'reason': '이전 매니페스트 없음: 첫 릴리스로 취급'}

    def download(name: str) -> bytes:
        asset_id = assets[name]
        if type(asset_id) is not int or asset_id <= 0:
            raise ValueError('Invalid release asset ID')
        return api(f'repos/{repository}/releases/assets/{asset_id}', binary=True)

    # Transport failure is not an unsigned legacy release or an absent manifest.
    manifest_data = download(FILENAME)
    signature = download(FILENAME + '.sig') if FILENAME + '.sig' in assets else None
    try:
        manifest = read_previous_manifest(manifest_data, signature)
        if manifest.version != tag[1:]:
            raise ValueError('Manifest version does not match release tag')
    except (ValueError, TypeError, KeyError, RecursionError):
        return {**empty, 'authentication': 'invalid',
                'reason': '패치 불가(이전 매니페스트 검증 실패): 전체 설치만 발행'}
    return {'tag': tag, 'runtime_fingerprint': manifest.runtime_fingerprint,
            'authentication': 'verified' if signature is not None else 'unsigned',
            'reason': '이전 매니페스트 서명 검증 완료' if signature is not None else '이전 매니페스트에 서명 없음(스키마 검증 완료)'}


def plan_patch(directory: Path, previous: str | None, *, allow_missing: bool = False) -> dict:
    if previous is not None and not re.fullmatch('[0-9a-f]{64}', previous):
        raise ValueError('Invalid previous runtime fingerprint')
    if allow_missing and not directory.exists():
        return {'runtime_fingerprint': None, 'patch_available': None,
                'reason': '새 번들 없음: 미정 (-DryRun -Build로 지문 확인)'}
    current = verify_bundle_fingerprint(directory)
    compatible = previous == current
    reason = ('이전 지문과 새 지문 일치' if compatible else
              '이전 지문 없음: 전체 설치 필요' if previous is None else '런타임 지문 변경: 전체 설치 필요')
    return {'runtime_fingerprint': current, 'patch_available': compatible, 'reason': reason}


def checked_signing_key(path: Path):
    key = load_signing_key(path)
    validate_signing_key(key)
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    previous = commands.add_parser('previous')
    previous.add_argument('--repository', required=True)
    previous.add_argument('--version', required=True)
    plan = commands.add_parser('plan')
    plan.add_argument('--directory', type=Path, required=True)
    plan.add_argument('--previous-fingerprint')
    plan.add_argument('--allow-missing', action='store_true')
    preflight = commands.add_parser('preflight')
    preflight.add_argument('--private-key', type=Path, default=default_key_path())
    sign = commands.add_parser('sign')
    sign.add_argument('--private-key', type=Path, default=default_key_path())
    sign.add_argument('--version', required=True)
    sign.add_argument('--runtime-fingerprint', type=Path, required=True)
    sign.add_argument('--previous-fingerprint')
    sign.add_argument('--full', type=Path, required=True)
    sign.add_argument('--patch', type=Path)
    sign.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'previous':
            result = previous_release(args.repository, args.version)
        elif args.command == 'plan':
            result = plan_patch(args.directory, args.previous_fingerprint, allow_missing=args.allow_missing)
        elif args.command == 'preflight':
            checked_signing_key(args.private_key)
            result = {'signing_key': 'verified'}
        else:
            key = checked_signing_key(args.private_key)
            manifest = build_manifest(version=args.version, runtime=args.runtime_fingerprint, full=args.full,
                                      previous_fingerprint=args.previous_fingerprint, patch=args.patch)
            write_signed_manifest(manifest, key, args.output)
            result = asdict(manifest)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Release metadata failed: {exc}\n')
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
