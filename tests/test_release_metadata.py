"""Previous-release decisions and transport failures, with no real network or keys."""
import importlib
import json
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from my_video_manager import update_manifest
from my_video_manager.update_manifest import UpdateAsset, UpdateManifest, encode_manifest


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('release_metadata')


def metadata(version='1.2.3'):
    return encode_manifest(UpdateManifest(1, version, 'a' * 64, None,
                           UpdateAsset('full.exe', 10, 'b' * 64), None, False))


def transport(data, signature=None, *, tag='v1.2.3'):
    def api(endpoint, **kwargs):
        if endpoint.endswith('/latest'):
            assets = [] if data is None else [{'name': 'update-manifest.json', 'id': 1}]
            if signature is not None:
                assets.append({'name': 'update-manifest.json.sig', 'id': 2})
            return json.dumps(dict(tag_name=tag, assets=assets, draft=False, prerelease=False)).encode()
        return signature if endpoint.endswith('/2') else data
    return api


@pytest.mark.parametrize('kind', ['no-release', 'no-manifest', 'unsigned', 'signed', 'bad-signature',
                                 'placeholder', 'bad-json', 'tag-mismatch', 'duplicate-json'])
def test_previous_release_trust_and_first_release_fallback(tool, monkeypatch, kind):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', key.public_key().public_bytes_raw())
    data = metadata()
    signature = key.sign(data) if kind in ('signed', 'placeholder') else None
    if kind == 'placeholder':
        monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'')
    elif kind == 'bad-signature':
        signature = b'x' * 64
    elif kind == 'bad-json':
        data = b'[]'
    elif kind == 'tag-mismatch':
        data = metadata('1.2.2')
    elif kind == 'duplicate-json':
        data = data.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
    if kind in ('bad-json', 'tag-mismatch', 'duplicate-json'):
        signature = key.sign(data)
    api = transport(None if kind == 'no-manifest' else data, signature)
    if kind == 'no-release':
        api = lambda *args, **kwargs: None
    result = tool.previous_release('owner/repository', '1.3.0', api=api)
    assert result['runtime_fingerprint'] == ('a' * 64 if kind == 'signed' else None)
    if kind == 'signed':
        assert result['authentication'] == 'verified'
    elif kind not in ('no-release', 'no-manifest'):
        assert result['authentication'] == 'invalid'
        assert ('서명 없음' if kind == 'unsigned' else '검증 실패') in result['reason']


@pytest.mark.parametrize('tag', ['v1.3.0', 'v2.0.0', 'other', 'v01.2.3'])
def test_previous_version_must_be_lower_before_downloading_assets(tool, tag):
    with pytest.raises(ValueError):
        tool.previous_release('owner/repository', '1.3.0', api=transport(metadata(), tag=tag))


@pytest.mark.parametrize('failure', [ValueError('network'), subprocess.TimeoutExpired('gh', 60)])
def test_asset_download_failure_is_not_legacy_absence(tool, failure):
    original = transport(metadata(), b'x' * 64)
    def api(endpoint, **kwargs):
        if kwargs.get('binary'):
            raise failure
        return original(endpoint, **kwargs)
    with pytest.raises(type(failure)):
        tool.previous_release('owner/repository', '1.3.0', api=api)


@pytest.mark.parametrize('code,status,expected', [(0, 200, b'{}'), (1, 404, None), (1, 403, 'error'),
                                               (1, 500, 'error'), (1, None, 'error')])
def test_gh_transport_only_404_is_absence(tool, monkeypatch, code, status, expected):
    stdout = b'' if status is None else f'HTTP/2.0 {status} Status\r\nHeader: yes\r\n\r\n{{}}'.encode()
    monkeypatch.setattr(tool.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, code, stdout, b'error'))
    if expected == 'error':
        with pytest.raises(ValueError, match='lookup failed'):
            tool.gh_api('repos/owner/repository/releases/latest', optional=True)
    else:
        assert tool.gh_api('repos/owner/repository/releases/latest', optional=True) == expected


def test_signed_invalid_json_is_never_parsed_before_verification(tool, monkeypatch):
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', Ed25519PrivateKey.generate().public_key().public_bytes_raw())
    with pytest.raises(ValueError, match='invalid_signature'):
        tool.read_previous_manifest(b'invalid JSON', b'x' * 64)


def test_missing_bundle_is_unknown_only_in_dry_run(tool, tmp_path):
    path = tmp_path / 'not-built'
    assert tool.plan_patch(path, None, allow_missing=True)['patch_available'] is False
    assert tool.plan_patch(path, 'a' * 64, allow_missing=True)['patch_available'] is None
    with pytest.raises(OSError):
        tool.plan_patch(path, None)
    path.mkdir()
    with pytest.raises(OSError):
        tool.plan_patch(path, None, allow_missing=True)


def test_unsigned_manifest_is_never_parsed_or_trusted(tool):
    with pytest.raises(ValueError, match='signature is missing'):
        tool.read_previous_manifest(metadata(), None)
