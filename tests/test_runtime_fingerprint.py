"""Public runtime identity behavior; no PyInstaller or installer execution."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest

from my_video_manager.runtime_fingerprint import (
    FILENAME, NATIVE_FILES, installed_runtime_fingerprint, load_runtime_fingerprint,
    make_runtime_fingerprint,
)


@pytest.fixture
def inputs():
    return dict(
        dependencies={'PySide6': '6.10.2', 'av': '17.1.0', 'my-video-manager': '0.4.1'},
        python={'implementation': 'CPython', 'version': '3.10.6', 'platform': 'win32', 'machine': 'AMD64'},
        tools={'pyinstaller': '6.16.0', 'pyinstaller-hooks-contrib': '2026.8'},
        native_files={name: hashlib.sha256(name.encode()).hexdigest() for name in NATIVE_FILES},
        hooks={'hook-PySide6.QtQml.py': hashlib.sha256(b'hook').hexdigest()},
    )


def test_identity_is_order_independent_and_excludes_app_metadata(inputs):
    before = deepcopy(inputs)
    expected = make_runtime_fingerprint(**inputs)
    assert inputs == before
    reordered = {group: dict(reversed(list(values.items()))) for group, values in inputs.items()}
    reordered['dependencies'].pop('my-video-manager')
    reordered['dependencies']['My_Video.Manager'] = '99.0.0'
    assert make_runtime_fingerprint(**reordered) == expected
    assert expected['inputs']['dependencies'] == {'pyside6': '6.10.2', 'av': '17.1.0'}
    assert len(expected['fingerprint']) == 64


@pytest.mark.parametrize('group,key', [
    ('dependencies', 'av'), ('dependencies', 'PySide6'),
    ('python', 'implementation'), ('python', 'version'), ('python', 'platform'), ('python', 'machine'),
    ('tools', 'pyinstaller'), ('tools', 'pyinstaller-hooks-contrib'),
    *(('native_files', name) for name in NATIVE_FILES), ('hooks', 'hook-PySide6.QtQml.py'),
])
def test_every_runtime_input_changes_identity(inputs, group, key):
    original = make_runtime_fingerprint(**inputs)
    inputs[group][key] = hashlib.sha256(b'changed').hexdigest() if group in ('native_files', 'hooks') else 'different'
    assert make_runtime_fingerprint(**inputs)['fingerprint'] != original['fingerprint']


@pytest.mark.parametrize('frozen,present', [(False, False), (False, True), (True, False), (True, True)])
def test_installed_reader_uses_executable_directory_not_cwd(inputs, tmp_path, monkeypatch, frozen, present):
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    document = make_runtime_fingerprint(**inputs)
    if present:
        (tmp_path / FILENAME).write_text(json.dumps(document), encoding='utf-8')
    assert installed_runtime_fingerprint() == (document['fingerprint'] if frozen and present else None)


@pytest.mark.parametrize('damage', ['json', 'schema', 'digest', 'inputs', 'hash', 'shape'])
def test_invalid_installation_never_returns_an_identity(inputs, tmp_path, monkeypatch, damage):
    document = make_runtime_fingerprint(**inputs)
    if damage == 'schema':
        document['schema_version'] = 999
    elif damage == 'digest':
        document['fingerprint'] = '0' * 64
    elif damage == 'inputs':
        document['inputs']['dependencies']['av'] = 'changed'
    elif damage == 'hash':
        document['inputs']['native_files'][NATIVE_FILES[0]] = 'invalid'
    elif damage == 'shape':
        document['inputs']['dependencies'] = []
    path = tmp_path / FILENAME
    path.write_text('{' if damage == 'json' else json.dumps(document), encoding='utf-8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    assert installed_runtime_fingerprint() is None
    with pytest.raises(ValueError):
        load_runtime_fingerprint(path)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    module = importlib.import_module('bundle_fingerprint')
    monkeypatch.setattr(module.metadata, 'version', lambda name: '1.0')
    for name in NATIVE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    manifest = tmp_path / 'licenses/python/manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps([
        {'name': 'my-video-manager', 'version': '0.4.1', 'urls': ['file:///private/build']},
        {'name': 'av', 'version': '17.1.0'}, {'name': 'python', 'version': sys.version},
    ]))
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    (hooks / 'hook-example.py').write_text('collect_runtime = True')
    return module, tmp_path, hooks


def test_build_document_survives_app_only_changes_and_relocation(bundle, monkeypatch):
    module, stage, hooks = bundle
    path = module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    original = path.read_bytes()
    fingerprint = module.verify_bundle_fingerprint(stage)
    (stage / 'my-video-manager.exe').write_bytes(b'changed application code')
    (stage / 'web').mkdir()
    (stage / 'web/index.html').write_text('changed UI')
    manifest = stage / 'licenses/python/manifest.json'
    packages = json.loads(manifest.read_text())
    packages[0]['version'] = '99.0.0'
    packages[0]['urls'] = ['file:///other/build']
    manifest.write_text(json.dumps(packages))
    module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    assert path.read_bytes() == original
    assert str(stage) not in path.read_text()
    assert 'file:///' not in path.read_text()
    assert set(load_runtime_fingerprint(path)['input_reasons']) == set(load_runtime_fingerprint(path)['inputs'])
    relocated = stage.with_name(stage.name + '-relocated')
    stage.rename(relocated)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(relocated / 'my-video-manager.exe'))
    assert installed_runtime_fingerprint() == fingerprint
    assert module.verify_bundle_fingerprint(relocated) == fingerprint


@pytest.mark.parametrize('name', NATIVE_FILES)
def test_missing_binary_fails_build_and_preserves_previous_document(bundle, name):
    module, stage, hooks = bundle
    path = module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    before = path.read_bytes()
    (stage / name).unlink()
    with pytest.raises(FileNotFoundError):
        module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    assert path.read_bytes() == before
    assert not path.with_suffix('.json.tmp').exists()
    with pytest.raises(FileNotFoundError):
        module.verify_bundle_fingerprint(stage)


@pytest.mark.parametrize('name', NATIVE_FILES)
def test_bundle_check_rejects_changed_native_file(bundle, name):
    module, stage, hooks = bundle
    module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    (stage / name).write_bytes(b'changed runtime')
    with pytest.raises(ValueError, match='binary mismatch'):
        module.verify_bundle_fingerprint(stage)


def test_build_detects_custom_hook_content_change(bundle):
    module, stage, hooks = bundle
    path = module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    original = load_runtime_fingerprint(path)['fingerprint']
    (hooks / 'hook-example.py').write_text('collect_runtime = False')
    module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    assert load_runtime_fingerprint(path)['fingerprint'] != original


def test_write_failure_keeps_previous_fingerprint_and_cleans_temporary(bundle, monkeypatch):
    module, stage, hooks = bundle
    path = module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    original = path.read_bytes()
    def fail_replace(*args):
        raise PermissionError('locked')
    monkeypatch.setattr(Path, 'replace', fail_replace)
    with pytest.raises(PermissionError):
        module.write_bundle_fingerprint(stage, stage / 'mpv', hooks)
    assert path.read_bytes() == original
    assert not path.with_suffix('.json.tmp').exists()
