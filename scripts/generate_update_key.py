"""Human-operated release key provisioning; private material never goes to stdout."""
import argparse
import getpass
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import UnsupportedAlgorithm


PASSWORD_ENV = 'MVM_UPDATE_SIGNING_PASSWORD'
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def default_key_path() -> Path:
    base = Path(os.environ['APPDATA']) if os.environ.get('APPDATA') else Path.home() / '.config'
    return base / 'my-video-manager' / 'release-keys' / 'update-ed25519.pem'


def private_key_path(path: Path) -> Path:
    """Reject source trees (including linked worktrees) and UNC destinations.

    Check both lexical and resolved parents so a symlink into OR out of a
    repository cannot turn a repository path into a valid key location.
    """
    lexical = path.expanduser().absolute()
    if str(lexical).startswith(('\\\\', '//')):
        raise ValueError('Private keys must be on a local drive')
    resolved = lexical.resolve()
    for candidate in (lexical, resolved):
        if str(candidate).startswith(('\\\\', '//')):
            raise ValueError('Private keys must be on a local drive')
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW
            drive_type.argtypes = [wintypes.LPCWSTR]
            drive_type.restype = wintypes.UINT
            if drive_type(candidate.anchor) == 4:  # DRIVE_REMOTE (mapped network drive)
                raise ValueError('Private keys must be on a local drive')
        if candidate == REPOSITORY_ROOT or REPOSITORY_ROOT in candidate.parents:
            raise ValueError('Private keys must be outside repositories')
        if any((parent / '.git').exists() for parent in (candidate, *candidate.parents)):
            raise ValueError('Private keys must be outside repositories')
    return resolved


def generate_key(path: Path, password: bytes | None) -> bytes:
    """Write a new PKCS8 PEM exclusively and return only the raw public key."""
    path = private_key_path(path)
    encryption = serialization.NoEncryption() if password is None else serialization.BestAvailableEncryption(password)
    key = Ed25519PrivateKey.generate()
    encoded = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves existing keys, including resolved link targets.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(encoded)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return key.public_key().public_bytes_raw()


def signing_password(*, confirm: bool = False) -> bytes:
    password = os.environ.get(PASSWORD_ENV)
    if password:
        return password.encode('utf-8')
    if not sys.stdin.isatty():
        raise ValueError(f'Encrypted key requires {PASSWORD_ENV} in a non-interactive terminal')
    password = getpass.getpass('Signing key password: ')
    if not password:
        raise ValueError('Signing key password must not be empty')
    if confirm and password != getpass.getpass('Confirm signing key password: '):
        raise ValueError('Signing key passwords do not match')
    return password.encode('utf-8')


def load_signing_key(path: Path) -> Ed25519PrivateKey:
    data = private_key_path(path).read_bytes()
    password = signing_password() if b'-----BEGIN ENCRYPTED PRIVATE KEY-----' in data else None
    try:
        key = serialization.load_pem_private_key(data, password=password)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise ValueError('Cannot load signing key: invalid PEM or incorrect password') from None
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Signing key must be Ed25519')
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-key', type=Path, default=default_key_path())
    parser.add_argument('--no-password', action='store_true', help='Explicitly choose an unencrypted private key')
    args = parser.parse_args(argv)
    try:
        # Check destination before prompting or generating any key material.
        path = private_key_path(args.private_key)
        if path.exists():
            raise ValueError('Private key already exists; refusing to overwrite')
        public = generate_key(path, None if args.no_password else signing_password(confirm=True))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Key generation failed: {exc}\n')
    print(f'Private key saved outside repository: {path}')
    print('Replace the placeholder in src/my_video_manager/update_manifest.py with:')
    print(f"UPDATE_PUBLIC_KEY = bytes.fromhex('{public.hex()}')")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
