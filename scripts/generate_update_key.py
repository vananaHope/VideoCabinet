"""Human-operated release key provisioning; private material never goes to stdout."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import sys
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import UnsupportedAlgorithm


PASSWORD_ENV = 'MVM_UPDATE_SIGNING_PASSWORD'
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def windows_acl(path: Path, *, run=subprocess.run) -> dict:
    """Read SID-based ACL entries without localized icacls output parsing."""
    literal = str(path).replace("'", "''")
    script = """
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath '%s'
@{user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  rules = @($acl.Access | ForEach-Object {
    @{sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
      allow = ($_.AccessControlType -eq 'Allow'); rights = [int]$_.FileSystemRights}
  })} | ConvertTo-Json -Depth 4 -Compress
""" % literal
    result = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                  base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
                 capture_output=True, text=True, timeout=30,
                 # PowerShell 7's inherited module path can load incompatible
                 # modules in Windows PowerShell 5.1 started by Python.
                 env={k: v for k, v in os.environ.items() if k.casefold() != 'psmodulepath'})
    if result.returncode:
        raise ValueError(f'Cannot inspect private key ACL: {path}')
    return json.loads(result.stdout)


def restrict_key_directory(path: Path, *, run=subprocess.run, inspect=windows_acl) -> None:
    if sys.platform != 'win32':
        return
    acl = inspect(path)
    user = acl['user']
    def apply(args):
        result = run(['icacls.exe', *args], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError(f'Cannot restrict private key directory ACL: {path}')

    apply([str(path), '/grant:r', f'*{user}:(OI)(CI)F', '/inheritance:r'])
    # Re-read after removing inheritance: stale/unresolvable inherited SIDs
    # need no /remove call (icacls may fail resolving even a now-absent SID).
    for sid in sorted({rule['sid'] for rule in inspect(path)['rules']} - {user}):
        apply([str(path), '/remove', f'*{sid}'])


def check_key_acl(path: Path, *, inspect=windows_acl) -> None:
    if sys.platform != 'win32':
        return
    for target in (path.parent, path):
        acl = inspect(target)
        # Empty/null DACL and unfamiliar ACEs are not accepted as proof of privacy.
        rules = acl['rules']
        if (not rules or any(r['sid'] not in {acl['user'], 'S-1-5-18'} for r in rules)
                or not any(r['sid'] == acl['user'] and r['allow']
                           and r['rights'] & 0x1F01FF == 0x1F01FF for r in rules)
                or any(not r['allow'] for r in rules)):
            raise ValueError(f'Unsafe private key ACL: {target}; key preserved at {path}')


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
    if path.exists():
        raise FileExistsError(path)
    restrict_key_directory(path.parent)
    # Exclusive creation preserves existing keys, including resolved link targets.
    # Windows only reflects the read-only bit here; access control uses ACLs.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(encoded)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    # A completed key must survive ACL verification failure for manual recovery.
    try:
        check_key_acl(path)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'WARNING: {exc}; key preserved at {path}', file=sys.stderr)
        raise ValueError(f'Private key ACL verification failed; key preserved at {path}') from None
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
    path = private_key_path(path)
    data = path.read_bytes()
    encrypted = b'-----BEGIN ENCRYPTED PRIVATE KEY-----' in data
    try:
        check_key_acl(path)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'WARNING: {exc}', file=sys.stderr)
        if not encrypted:
            raise ValueError(f'Unencrypted signing key requires private ACL: {path}') from None
    password = signing_password() if encrypted else None
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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Key generation failed: {exc}\n')
    print(f'Private key saved outside repository: {path}')
    print('Replace the placeholder in src/my_video_manager/update_manifest.py with:')
    print(f"UPDATE_PUBLIC_KEY = bytes.fromhex('{public.hex()}')")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
