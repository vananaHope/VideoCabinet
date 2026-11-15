"""Authenticated release metadata. No network, filesystem, or UI dependencies."""
from dataclasses import asdict, dataclass
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FILENAME = 'update-manifest.json'
SCHEMA_VERSION = 1
# Ed25519 public key of the release signing key (scripts/generate_update_key.py).
# The private key stays outside the repository; replacing this breaks updates for installed apps.
UPDATE_PUBLIC_KEY = bytes.fromhex('dab3990e35b9fbb3eb78245d95d137d19e255ca71102747bd50b001fb6f30934')


class ManifestError(ValueError):
    """Stable reason for update logs; never includes untrusted document contents."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class UpdateAsset:
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdateManifest:
    """patch_available describes publication relative to the previous release.

    Installation eligibility uses the installed runtime_fingerprint, not version
    adjacency: an older installation with the same runtime can use this patch.
    """

    schema_version: int
    version: str
    runtime_fingerprint: str
    previous_runtime_fingerprint: str | None
    full: UpdateAsset
    patch: UpdateAsset | None
    patch_available: bool


def _sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _asset(value: object) -> UpdateAsset:
    if not isinstance(value, dict) or set(value) != {'filename', 'size', 'sha256'}:
        raise ManifestError('invalid_format')
    name = value['filename']
    # Release assets are Windows basenames, never paths, URLs or ADS streams.
    if (not isinstance(name, str) or not name or name.endswith((' ', '.'))
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                             *(f'COM{i}' for i in range(1, 10)),
                                             *(f'LPT{i}' for i in range(1, 10))}
            or type(value['size']) is not int or value['size'] <= 0
            or not _sha256(value['sha256'])):
        raise ManifestError('invalid_format')
    return UpdateAsset(**value)


def _model(document: object) -> UpdateManifest:
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int:
        raise ManifestError('invalid_format')
    if document['schema_version'] != SCHEMA_VERSION:
        raise ManifestError('unsupported_schema')
    if set(document) != {'schema_version', 'version', 'runtime_fingerprint',
                         'previous_runtime_fingerprint', 'full', 'patch', 'patch_available'}:
        raise ManifestError('invalid_format')
    version = document['version']
    previous = document['previous_runtime_fingerprint']
    if (not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version)
            or not _sha256(document['runtime_fingerprint'])
            or (previous is not None and not _sha256(previous))
            or type(document['patch_available']) is not bool):
        raise ManifestError('invalid_format')
    full = _asset(document['full'])
    patch = None if document['patch'] is None else _asset(document['patch'])
    compatible = previous == document['runtime_fingerprint']
    if (document['patch_available'] != compatible or (patch is not None) != compatible
            or (patch is not None and patch.filename.casefold() == full.filename.casefold())):
        raise ManifestError('invalid_format')
    return UpdateManifest(**{**document, 'full': full, 'patch': patch})


def encode_manifest(manifest: UpdateManifest) -> bytes:
    """Validate producer input using the same schema and serialize once to UTF-8."""
    document = asdict(manifest)
    _model(document)
    return (json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError('Non-JSON constant')


def verify_manifest(data: bytes, signature: bytes, *, public_key: bytes | None = None) -> UpdateManifest:
    """Verify the exact bytes BEFORE decoding/parsing, then validate schema 1.

    The default trust anchor is compiled into the app. Explicit public_key is
    for offline tooling/tests, never a value read from the release being checked.
    Wrong-key and same-length corrupted signatures are indistinguishable and
    both report invalid_signature; malformed signature lengths report invalid_signature_format.
    """
    key = UPDATE_PUBLIC_KEY if public_key is None else public_key
    if not isinstance(key, bytes) or len(key) != 32:
        raise ManifestError('invalid_public_key')
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ManifestError('invalid_signature_format')
    if not isinstance(data, bytes):
        raise ManifestError('invalid_format')
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, data)
    except InvalidSignature:
        raise ManifestError('invalid_signature') from None
    try:
        document = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ManifestError('invalid_json') from None
    return _model(document)
