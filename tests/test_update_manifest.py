"""Authenticated release contracts, using freshly generated disposable keys."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from my_video_manager.update_manifest import ManifestError, verify_manifest
from my_video_manager import update_manifest


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def document():
    return {'schema_version': 1, 'version': '1.2.3', 'runtime_fingerprint': 'a' * 64,
            'previous_runtime_fingerprint': None, 'patch_available': False, 'patch': None,
            'full': {'filename': 'MyVideoManager-Setup-1.2.3.exe', 'size': 1234, 'sha256': 'b' * 64}}


def verify(data, key, signature=None):
    return verify_manifest(data, key.sign(data) if signature is None else signature,
                           public_key=key.public_key().public_bytes_raw())


def test_valid_signed_bytes_return_immutable_model(document, key):
    # Whitespace is intentionally non-canonical: verify original bytes, not reserialized JSON.
    data = json.dumps(document, indent=3).encode() + b' \r\n'
    result = verify(data, key)
    assert result.version == '1.2.3'
    assert result.full.filename == document['full']['filename']
    assert result.full.size == 1234
    assert result.patch is None and not result.patch_available
    with pytest.raises(FrozenInstanceError):
        result.full.size = 2


@pytest.mark.parametrize('damage', ['content', 'whitespace', 'other_key', 'signature'])
def test_signature_rejects_tampering(document, key, damage):
    data = json.dumps(document).encode()
    signature = key.sign(data)
    if damage == 'content':
        data = data.replace(b'1.2.3', b'9.9.9')
    elif damage == 'whitespace':
        data += b'\n'
    elif damage == 'other_key':
        signature = Ed25519PrivateKey.generate().sign(data)
    else:
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    with pytest.raises(ManifestError) as exc:
        verify(data, key, signature)
    assert exc.value.kind == 'invalid_signature'


@pytest.mark.parametrize('signature', [b'', b'broken', b'x' * 63, b'x' * 65, b'x' * 128])
def test_malformed_signature_length(key, signature):
    with pytest.raises(ManifestError) as exc:
        verify(b'not JSON', key, signature)
    assert exc.value.kind == 'invalid_signature_format'


def test_signature_precedes_json_parsing(key):
    with pytest.raises(ManifestError) as exc:
        verify(b'not JSON', key, key.sign(b'different'))
    assert exc.value.kind == 'invalid_signature'


@pytest.mark.parametrize('data', [b'not JSON', b'\xff', b'{"schema_version":1,"schema_version":1}',
                                b'{"value":NaN}', b'{"value":Infinity}', b'[' * 2000])
def test_signed_malformed_json(key, data):
    with pytest.raises(ManifestError) as exc:
        verify(data, key)
    assert exc.value.kind == 'invalid_json'


def test_placeholder_is_fail_closed(document, key, monkeypatch):
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'')
    data = json.dumps(document).encode()
    with pytest.raises(ManifestError) as exc:
        verify_manifest(data, key.sign(data))
    assert exc.value.kind == 'invalid_public_key'


def test_default_verifier_uses_embedded_trust_anchor(document, key, monkeypatch):
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', key.public_key().public_bytes_raw())
    data = json.dumps(document).encode()
    assert verify_manifest(data, key.sign(data)).version == document['version']
    with pytest.raises(ManifestError) as exc:
        verify_manifest(data, Ed25519PrivateKey.generate().sign(data))
    assert exc.value.kind == 'invalid_signature'


@pytest.mark.parametrize('schema,kind', [(2, 'unsupported_schema'), (0, 'unsupported_schema'),
                                       (True, 'invalid_format'), ('1', 'invalid_format')])
def test_schema_rejections(document, key, schema, kind):
    document['schema_version'] = schema
    with pytest.raises(ManifestError) as exc:
        verify(json.dumps(document).encode(), key)
    assert exc.value.kind == kind


@pytest.mark.parametrize('field,value', [('size', -1), ('size', 0), ('size', True), ('size', 1.5),
                                      ('sha256', 'abc'), ('sha256', 'A' * 64),
                                      ('filename', '../setup.exe'), ('filename', 'C:\\setup.exe'),
                                      ('filename', 'setup.exe:stream'), ('filename', 'CON.exe'),
                                      ('filename', 'bad\n.exe'), ('filename', 'file.exe.')])
def test_signed_invalid_asset(document, key, field, value):
    document['full'][field] = value
    with pytest.raises(ManifestError) as exc:
        verify(json.dumps(document).encode(), key)
    assert exc.value.kind == 'invalid_format'


@pytest.mark.parametrize('damage', ['root', 'missing', 'unknown', 'version', 'fingerprint',
                                  'flag_type', 'false_compatible', 'no_patch', 'extra_patch', 'same_name'])
def test_signed_schema_inconsistencies(document, key, damage):
    if damage == 'root':
        document = []
    elif damage == 'missing':
        del document['full']
    elif damage == 'unknown':
        document['unknown'] = 1
    elif damage == 'version':
        document['version'] = 'v1.2.3'
    elif damage == 'fingerprint':
        document['runtime_fingerprint'] = 'invalid'
    elif damage == 'flag_type':
        document['patch_available'] = 0
    elif damage == 'false_compatible':
        document['previous_runtime_fingerprint'] = document['runtime_fingerprint']
    elif damage == 'no_patch':
        document.update(previous_runtime_fingerprint='a' * 64, patch_available=True)
    elif damage == 'extra_patch':
        document['patch'] = deepcopy(document['full'])
    else:
        document.update(previous_runtime_fingerprint='a' * 64, patch_available=True,
                        patch=deepcopy(document['full']))
    with pytest.raises(ManifestError) as exc:
        verify(json.dumps(document).encode(), key)
    assert exc.value.kind == 'invalid_format'
