"""Release tooling against synthetic installers and temporary test keys only."""
import importlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from my_video_manager.runtime_fingerprint import NATIVE_FILES, make_runtime_fingerprint
from my_video_manager.update_manifest import verify_manifest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    return (importlib.import_module('generate_update_key'), importlib.import_module('generate_update_manifest'))


@pytest.fixture
def artifacts(tmp_path):
    full, patch, runtime = (tmp_path / name for name in ('setup.exe', 'patch.exe', 'runtime.json'))
    full.write_bytes(b'synthetic full installer\0' * 100)
    patch.write_bytes(b'synthetic patch installer')
    document = make_runtime_fingerprint(
        dependencies={'cryptography': '50.0.2'},
        python={'implementation': 'CPython', 'version': '3.10.6', 'platform': 'win32', 'machine': 'AMD64'},
        tools={'pyinstaller': '6.16.0', 'pyinstaller-hooks-contrib': '2026.8'},
        native_files={name: 'a' * 64 for name in NATIVE_FILES}, hooks={'hook.py': 'b' * 64},
        bundle_files=['cryptography/hazmat/bindings/_rust.pyd'])
    runtime.write_text(json.dumps(document), encoding='utf-8')
    return full, patch, runtime


@pytest.mark.parametrize('previous_kind', ['first', 'same', 'changed'])
def test_generate_and_verify_release(scripts, artifacts, tmp_path, previous_kind):
    _, tool = scripts
    full, patch, runtime = artifacts
    previous = None
    if previous_kind != 'first':
        previous = tmp_path / 'previous.json'
        document = json.loads(runtime.read_text())
        if previous_kind == 'changed':
            document['inputs']['dependencies']['cryptography'] = '49.0.0'
            document = make_runtime_fingerprint(**document['inputs'])
        previous.write_text(json.dumps(document))
    manifest = tool.build_manifest(version='1.2.3', runtime=runtime, full=full,
                                   previous_runtime=previous, patch=patch if previous_kind == 'same' else None)
    key = Ed25519PrivateKey.generate()
    out, sig = tool.write_signed_manifest(manifest, key, tmp_path / 'out' / 'update-manifest.json',
                                           allow_unpinned_key_for_tests=True)
    result = verify_manifest(out.read_bytes(), sig.read_bytes(), public_key=key.public_key().public_bytes_raw())
    assert result == manifest
    assert result.full.size == full.stat().st_size
    assert result.full.sha256 == hashlib.sha256(full.read_bytes()).hexdigest()
    assert result.full.filename == full.name
    assert result.patch_available == (previous_kind == 'same')
    assert (result.patch is not None) == (previous_kind == 'same')
    if result.patch:
        assert result.patch.size == patch.stat().st_size
        assert result.patch.sha256 == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert len(sig.read_bytes()) == 64


@pytest.mark.parametrize('with_previous', [False, True])
def test_patch_input_must_match_runtime_policy(scripts, artifacts, with_previous):
    full, patch, runtime = artifacts
    with pytest.raises(ValueError, match='runtime requires'):
        scripts[1].build_manifest(version='1.2.3', runtime=runtime, full=full,
                                  previous_runtime=runtime if with_previous else None,
                                  patch=None if with_previous else patch)


@pytest.mark.parametrize('existing', ['manifest', 'signature'])
def test_existing_outputs_preserved_and_partial_new_output_removed(scripts, artifacts, tmp_path, existing):
    full, _, runtime = artifacts
    tool = scripts[1]
    manifest = tool.build_manifest(version='1.2.3', runtime=runtime, full=full)
    output = tmp_path / 'update-manifest.json'
    sig = tmp_path / 'update-manifest.json.sig'
    old = output if existing == 'manifest' else sig
    old.write_bytes(b'previous release')
    with pytest.raises(FileExistsError):
        tool.write_signed_manifest(manifest, Ed25519PrivateKey.generate(), output,
                                   allow_unpinned_key_for_tests=True)
    assert old.read_bytes() == b'previous release'
    assert not (sig if existing == 'manifest' else output).exists()


def test_write_failure_cleans_both_new_outputs(scripts, artifacts, tmp_path, monkeypatch):
    full, _, runtime = artifacts
    tool = scripts[1]
    manifest = tool.build_manifest(version='1.2.3', runtime=runtime, full=full)
    output = tmp_path / 'manifest.json'
    original = Path.open

    def failing_open(path, *args, **kwargs):
        if path.name.endswith('.sig'):
            raise OSError('simulated disk failure')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', failing_open)
    with pytest.raises(OSError, match='simulated'):
        tool.write_signed_manifest(manifest, Ed25519PrivateKey.generate(), output,
                                   allow_unpinned_key_for_tests=True)
    assert not output.exists()
    assert not output.with_name(output.name + '.sig').exists()


@pytest.mark.parametrize('marker', ['directory', 'file'])
def test_key_rejected_in_any_repository_or_worktree(scripts, tmp_path, marker):
    root = tmp_path / 'other-repository'
    root.mkdir()
    if marker == 'directory':
        (root / '.git').mkdir()
    else:
        (root / '.git').write_text('gitdir: elsewhere')
    target = root / 'untracked' / 'release.pem'
    with pytest.raises(ValueError, match='outside repositories'):
        scripts[0].generate_key(target, None)
    assert not target.parent.exists()


def test_key_rejected_in_current_worktree_without_creating_file(scripts):
    target = ROOT / '.local' / 'must-not-create.pem'
    with pytest.raises(ValueError, match='outside repositories'):
        scripts[0].generate_key(target, None)
    assert not target.exists()


@pytest.mark.parametrize('direction', ['into', 'out_of'])
def test_key_rejects_directory_links_crossing_repository_boundary(scripts, tmp_path, direction):
    repository = tmp_path / 'repository'
    repository.mkdir()
    (repository / '.git').mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = (outside if direction == 'into' else repository) / 'link'
    target = repository if direction == 'into' else outside
    if sys.platform == 'win32':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match='outside repositories'):
            scripts[0].generate_key(link / 'key.pem', None)
        assert not (target / 'key.pem').exists()
    finally:
        if sys.platform == 'win32':
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows UNC path policy')
def test_rejected_unc_path_does_not_access_network(scripts, monkeypatch):
    def no_resolution(path):
        raise AssertionError('UNC must be rejected before filesystem resolution')
    monkeypatch.setattr(Path, 'resolve', no_resolution)
    with pytest.raises(ValueError, match='local drive'):
        scripts[0].generate_key(Path(r'\\server\share\key.pem'), None)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows mapped drive policy')
def test_rejected_mapped_network_drive(scripts, tmp_path, monkeypatch):
    import ctypes
    def remote_drive(anchor):
        return 4
    monkeypatch.setattr(ctypes.windll.kernel32, 'GetDriveTypeW', remote_drive)
    target = tmp_path / 'key.pem'
    with pytest.raises(ValueError, match='local drive'):
        scripts[0].generate_key(target, None)
    assert not target.exists()


def test_key_write_failure_removes_partial_key(scripts, tmp_path, monkeypatch):
    from contextlib import contextmanager
    original = os.fdopen

    @contextmanager
    def failing_writer(fd, mode):
        with original(fd, mode) as stream:
            class Writer:
                def write(self, data):
                    stream.write(data[:10])
                    raise OSError('simulated key write failure')
            yield Writer()

    monkeypatch.setattr(os, 'fdopen', failing_writer)
    # A newly created folder is restricted first, so the write path is reached.
    target = tmp_path / 'keys' / 'partial.pem'
    with pytest.raises(OSError, match='simulated key write failure'):
        scripts[0].generate_key(target, None)
    assert not target.exists()


@pytest.mark.parametrize('encrypted', [False, True])
def test_key_roundtrip_and_overwrite_protection(scripts, tmp_path, monkeypatch, encrypted):
    keytool = scripts[0]
    target = tmp_path / 'keys' / 'release.pem'
    password = b'disposable-test-password' if encrypted else None
    public = keytool.generate_key(target, password)
    original = target.read_bytes()
    if encrypted:
        assert b'BEGIN ENCRYPTED PRIVATE KEY' in original
        monkeypatch.setenv(keytool.PASSWORD_ENV, password.decode())
    else:
        assert b'BEGIN PRIVATE KEY' in original
    loaded = keytool.load_signing_key(target)
    assert loaded.public_key().public_bytes_raw() == public
    with pytest.raises(FileExistsError):
        keytool.generate_key(target, password)
    assert target.read_bytes() == original


@pytest.mark.parametrize('password', [None, '', 'incorrect-disposable-password'])
def test_encrypted_key_noninteractive_failure_is_safe(scripts, tmp_path, monkeypatch, password):
    keytool = scripts[0]
    target = tmp_path / 'release.pem'
    keytool.generate_key(target, b'disposable-correct-password')
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    monkeypatch.delenv(keytool.PASSWORD_ENV, raising=False)
    if password is not None:
        monkeypatch.setenv(keytool.PASSWORD_ENV, password)
    with pytest.raises(ValueError) as exc:
        keytool.load_signing_key(target)
    assert 'disposable' not in str(exc.value)
    assert ('non-interactive' if not password else 'incorrect password') in str(exc.value)


def test_interactive_password_confirmation_and_env_priority(scripts, monkeypatch):
    keytool = scripts[0]
    monkeypatch.delenv(keytool.PASSWORD_ENV, raising=False)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    prompts = iter(['temporary', 'temporary'])
    monkeypatch.setattr(keytool.getpass, 'getpass', lambda prompt: next(prompts))
    assert keytool.signing_password(confirm=True) == b'temporary'
    monkeypatch.setenv(keytool.PASSWORD_ENV, 'environment-value')
    assert keytool.signing_password() == b'environment-value'


@pytest.mark.parametrize('encrypted', [False, True])
def test_command_line_key_and_manifest_roundtrip(artifacts, tmp_path, encrypted):
    full, _, runtime = artifacts
    key_path = tmp_path / 'keys' / 'release.pem'
    output = tmp_path / 'release' / 'update-manifest.json'
    env = dict(os.environ)
    env['MVM_UPDATE_SIGNING_PASSWORD'] = 'disposable-cli-password'
    command = [sys.executable, str(ROOT / 'scripts/generate_update_key.py'), '--private-key', str(key_path)]
    if not encrypted:
        command.append('--no-password')
    generated = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert generated.returncode == 0, generated.stderr
    public = bytes.fromhex(generated.stdout.split("bytes.fromhex('")[1].split("')")[0])
    signed = subprocess.run([sys.executable, str(ROOT / 'scripts/generate_update_manifest.py'),
                             '--allow-unpinned-key-for-tests',
                             '--version', '1.2.3', '--runtime-fingerprint', str(runtime),
                             '--full', str(full), '--private-key', str(key_path), '--output', str(output)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert signed.returncode == 0, signed.stderr
    for text in (generated.stdout, generated.stderr, signed.stdout, signed.stderr):
        assert 'disposable-cli-password' not in text
        assert 'BEGIN PRIVATE KEY' not in text
        assert 'BEGIN ENCRYPTED PRIVATE KEY' not in text
    manifest = verify_manifest(output.read_bytes(), output.with_name(output.name + '.sig').read_bytes(), public_key=public)
    assert manifest.version == '1.2.3'


def test_invalid_runtime_file_never_produces_manifest(scripts, artifacts, tmp_path):
    full, _, runtime = artifacts
    document = json.loads(runtime.read_text())
    document['fingerprint'] = '0' * 64
    runtime.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='mismatch'):
        scripts[1].build_manifest(version='1.2.3', runtime=runtime, full=full)


@pytest.mark.parametrize('pin', ['placeholder', 'other', 'matching'])
def test_signing_requires_application_key_by_default(scripts, artifacts, tmp_path, monkeypatch, pin):
    from my_video_manager import update_manifest
    tool = scripts[1]
    full, _, runtime = artifacts
    key = Ed25519PrivateKey.generate()
    public = {'placeholder': b'', 'other': Ed25519PrivateKey.generate().public_key().public_bytes_raw(),
              'matching': key.public_key().public_bytes_raw()}[pin]
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', public)
    monkeypatch.setattr(tool, 'load_signing_key', lambda path: key)
    output = tmp_path / 'out' / 'manifest.json'
    args = ['--version', '1.2.3', '--runtime-fingerprint', str(runtime),
            '--full', str(full), '--output', str(output)]
    if pin == 'matching':
        assert tool.main(args) == 0
        assert verify_manifest(output.read_bytes(), output.with_suffix('.json.sig').read_bytes())
    else:
        with pytest.raises(SystemExit) as exc:
            tool.main(args)
        assert exc.value.code == 1
        assert not output.parent.exists()


def test_test_only_bypass_warns(scripts, artifacts, tmp_path, monkeypatch, capsys):
    from my_video_manager import update_manifest
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'')
    full, _, runtime = artifacts
    tool = scripts[1]
    manifest = tool.build_manifest(version='1.2.3', runtime=runtime, full=full)
    tool.write_signed_manifest(manifest, Ed25519PrivateKey.generate(), tmp_path / 'manifest.json',
                               allow_unpinned_key_for_tests=True)
    assert 'WARNING: test-only' in capsys.readouterr().err


def acl_snapshot(*, foreign=False):
    rules = [{'sid': 'S-1-5-21-123', 'allow': True, 'rights': 0x1F01FF}]
    if foreign:
        rules.append({'sid': 'S-1-5-32-545', 'allow': True, 'rights': 0x120089})
    return {'user': 'S-1-5-21-123', 'rules': rules}


def test_acl_restriction_uses_argument_lists_and_removes_explicit_other_sids(scripts, tmp_path, monkeypatch):
    tool = scripts[0]
    monkeypatch.setattr(sys, 'platform', 'win32')
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    tool.restrict_key_directory(tmp_path, run=run, inspect=lambda path: acl_snapshot(foreign=True))
    assert calls == [
        ['icacls.exe', str(tmp_path), '/grant:r', '*S-1-5-21-123:(OI)(CI)F',
         '*S-1-5-18:(OI)(CI)F', '/inheritance:r'],
        ['icacls.exe', str(tmp_path), '/remove', '*S-1-5-32-545']]


@pytest.mark.parametrize('unsafe_target', ['folder', 'file'])
def test_generated_key_preserved_and_cli_fails_if_acl_stays_unsafe(
        scripts, tmp_path, monkeypatch, capsys, unsafe_target):
    tool = scripts[0]
    target = tmp_path / 'keys' / 'test.pem'
    monkeypatch.setattr(tool, 'restrict_key_directory', lambda path: None)
    original = tool.check_key_acl

    def check(path):
        monkeypatch.setattr(sys, 'platform', 'win32')
        original(path, inspect=lambda p: acl_snapshot(
            foreign=p == (target.parent if unsafe_target == 'folder' else target)))

    monkeypatch.setattr(tool, 'check_key_acl', check)
    with pytest.raises(SystemExit) as exc:
        tool.main(['--private-key', str(target), '--no-password'])
    assert exc.value.code == 1
    assert target.read_bytes().startswith(b'-----BEGIN PRIVATE KEY-----')
    error = capsys.readouterr().err
    assert 'WARNING' in error and str(target) in error


@pytest.mark.parametrize('encrypted', [False, True])
def test_signing_unsafe_acl_blocks_plain_key_but_warns_for_encrypted(
        scripts, tmp_path, monkeypatch, capsys, encrypted):
    tool = scripts[0]
    target = tmp_path / 'keys' / 'test.pem'
    password = b'temporary-password' if encrypted else None
    public = tool.generate_key(target, password)
    monkeypatch.setenv(tool.PASSWORD_ENV, 'temporary-password')
    original = tool.check_key_acl

    def check(path):
        monkeypatch.setattr(sys, 'platform', 'win32')
        original(path, inspect=lambda p: acl_snapshot(foreign=True))

    monkeypatch.setattr(tool, 'check_key_acl', check)
    if encrypted:
        assert tool.load_signing_key(target).public_key().public_bytes_raw() == public
    else:
        with pytest.raises(ValueError, match='requires private ACL'):
            tool.load_signing_key(target)
    assert 'WARNING' in capsys.readouterr().err


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows ACL in temporary folder only')
def test_real_windows_key_acl_is_private(scripts, tmp_path):
    target = tmp_path / 'private-keys' / 'test.pem'
    tool = scripts[0]
    tool.generate_key(target, None)
    tool.check_key_acl(target)
    for path in (target.parent, target):
        acl = tool.windows_acl(path)
        assert {rule['sid'] for rule in acl['rules']} == {acl['user'], 'S-1-5-18'}


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows ACL in temporary folder only')
@pytest.mark.parametrize('name', ['curly\u2019q dir', 'curly\u2018q dir',
                                 'q\u2019; New-Item -ItemType File -Name pwned.txt; \u2019'])
def test_windows_acl_treats_path_as_data(scripts, tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'q').mkdir()
    target = tmp_path / name
    target.mkdir()
    assert scripts[0].windows_acl(target)['rules']
    assert not (tmp_path / 'pwned.txt').exists()


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows ACL in temporary folder only')
@pytest.mark.parametrize('encrypted', [False, True])
def test_existing_key_directory_and_children_keep_acl(scripts, tmp_path, capsys, encrypted):
    tool = scripts[0]
    folder = tmp_path / 'existing'
    child = folder / 'sub' / 'doc.txt'
    child.parent.mkdir(parents=True)
    child.write_text('unrelated document')
    # Ensure the pre-existing directory is unsafe regardless of the temp root ACL.
    result = subprocess.run(['icacls.exe', str(folder), '/grant', '*S-1-1-0:(OI)(CI)R'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    targets = (folder, child.parent, child)
    before = {path: tool.windows_acl(path) for path in targets}
    target = folder / 'key.pem'
    if encrypted:
        assert len(tool.generate_key(target, b'disposable-password')) == 32
        assert target.exists()
    else:
        with pytest.raises(ValueError, match='ACL verification failed'):
            tool.generate_key(target, None)
        # The unsafe directory is detected before the key is written.
        assert not target.exists()
    assert {path: tool.windows_acl(path) for path in targets} == before
    assert child.read_text() == 'unrelated document'
    error = capsys.readouterr().err
    assert 'WARNING' in error and 'icacls $keyFolder' in error and 'icacls $keyFile' in error


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows ACL in temporary folder only')
def test_existing_private_directory_is_reused_without_restriction(scripts, tmp_path, monkeypatch):
    tool = scripts[0]
    target = tmp_path / 'keys' / 'first.pem'
    tool.generate_key(target, None)
    before = tool.windows_acl(target.parent)

    def no_restriction(path):
        pytest.fail('Existing directory must not be restricted again')

    monkeypatch.setattr(tool, 'restrict_key_directory', no_restriction)
    second = target.with_name('second.pem')
    tool.generate_key(second, None)
    tool.check_key_acl(second)
    assert tool.windows_acl(target.parent) == before


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows ACL in temporary folder only')
def test_passwordless_key_refused_before_writing_into_inheriting_directory(scripts, tmp_path, capsys):
    tool = scripts[0]
    folder = tmp_path / 'existing'
    folder.mkdir()
    # Ensure the pre-existing directory is unsafe regardless of the temp root ACL.
    result = subprocess.run(['icacls.exe', str(folder), '/grant', '*S-1-1-0:(OI)(CI)R'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    target = folder / 'key.pem'
    with pytest.raises(ValueError, match='ACL verification failed'):
        tool.generate_key(target, None)
    assert not target.exists()
    error = capsys.readouterr().err
    assert 'WARNING' in error and 'icacls $keyFolder' in error


@pytest.mark.parametrize('encrypted', [False, True])
def test_unsafe_acl_warning_names_preserved_key_once(scripts, tmp_path, monkeypatch, capsys, encrypted):
    tool = scripts[0]
    target = tmp_path / 'keys' / 'test.pem'
    monkeypatch.setattr(tool, 'restrict_key_directory', lambda path: None)

    def unsafe(path):
        raise ValueError(f'Unsafe private key ACL: {path.parent}; key preserved at {path}')

    monkeypatch.setattr(tool, 'check_key_acl', unsafe)
    if encrypted:
        tool.generate_key(target, b'disposable-password')
    else:
        with pytest.raises(ValueError, match='ACL verification failed'):
            tool.generate_key(target, None)
    error = capsys.readouterr().err
    assert error.count(f'key preserved at {target}') == 1
