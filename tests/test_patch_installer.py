"""Payload policy and real Inno silent-install scenarios in isolated directories."""
from fnmatch import fnmatchcase
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from my_video_manager.runtime_fingerprint import APP_OWNED_PATHS, FILENAME, make_runtime_fingerprint

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('patch_payload', ROOT / 'scripts/patch_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


def test_version_command_does_not_initialize_gui_or_data(tmp_path):
    from my_video_manager.app_version import current_version
    result = subprocess.run([sys.executable, '-m', 'my_video_manager', '--data-dir',
                             str(tmp_path / 'data'), '--version'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip() == current_version()
    assert not (tmp_path / 'data').exists()


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / 'bundle'
    files = {
        'my-video-manager.exe': b'new exe',
        'my_video_manager/build-version.txt': b'0.4.2',
        'my_video_manager/web/index.html': b'new html',
        'my_video_manager/web/assets/new.js': b'new js',
        'my_video_manager-0.4.2.dist-info/METADATA': b'new metadata',
        'licenses/license.txt': b'license',
        'THIRD-PARTY-NOTICES.txt': b'notices',
        'python310.dll': b'runtime unchanged',
        'ffmpeg/ffmpeg.exe': b'runtime unchanged',
    }
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    document = make_runtime_fingerprint(
        dependencies={'example': '1'},
        python=dict(implementation='CPython', version='3.10.6', platform='win32', machine='AMD64'),
        tools={'pyinstaller': '6.16.0', 'pyinstaller-hooks-contrib': '2026.8'},
        native_files={name: 'a' * 64 for name in ('ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe', 'mpv/libmpv-2.dll')},
        hooks={'hook.py': 'b' * 64}, bundle_files=list(files))
    (directory / FILENAME).write_text(json.dumps(document), encoding='utf-8')
    return directory


def test_payload_and_fingerprint_share_the_exact_ownership_boundary(bundle, tmp_path):
    selected = payload.write_patch_include(bundle, tmp_path / 'patch.iss', '0.4.2')
    all_files = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    assert set(selected) == {p for p in all_files if any(fnmatchcase(p.lower(), pat) for pat in APP_OWNED_PATHS)}
    inputs = json.loads((bundle / FILENAME).read_text())['inputs']
    original = make_runtime_fingerprint(**inputs)['fingerprint']
    inputs['bundle_files'] = list(all_files)
    assert make_runtime_fingerprint(**inputs)['fingerprint'] == original
    assert 'my-video-manager.exe' in selected
    assert 'python310.dll' not in selected
    generated = (tmp_path / 'patch.iss').read_text(encoding='utf-8-sig')
    assert 'Name: "{app}\\my_video_manager-*.dist-info"' in generated
    assert 'Name: "{app}\\licenses"' in generated
    assert 'ffmpeg' not in generated


@pytest.mark.parametrize('problem', ['version', 'missing', 'corrupt', 'unsafe'])
def test_incomplete_bundle_cannot_replace_previous_include(bundle, tmp_path, problem):
    output = tmp_path / 'patch.iss'
    output.write_text('previous')
    if problem == 'version':
        (bundle / 'my_video_manager/build-version.txt').write_text('different')
    elif problem == 'missing':
        (bundle / 'my-video-manager.exe').unlink()
    elif problem == 'unsafe':
        (bundle / 'my_video_manager/{app}.txt').write_text('unsafe')
    else:
        (bundle / FILENAME).write_text('{')
    with pytest.raises(ValueError):
        payload.write_patch_include(bundle, output, '0.4.2')
    assert output.read_text() == 'previous'
    assert not output.with_suffix('.iss.tmp').exists()


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


@pytest.fixture
def patch_exe(bundle, tmp_path):
    if sys.platform != 'win32':
        pytest.skip('Inno Setup requires Windows')
    compiler = shutil.which('ISCC.exe') or str(Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe')
    if not Path(compiler).is_file():
        pytest.skip('Inno Setup 6 compiler not installed')
    # A valid tiny ICO: BITMAPINFOHEADER + one BGRA pixel + padded AND mask.
    import struct
    bitmap = struct.pack('<IiiHHIIiiII', 40, 1, 2, 1, 32, 0, 4, 0, 0, 0, 0) + b'\xff\x80\x00\xff' + b'\0' * 4
    icon = struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 1, 1, 0, 0, 1, 32, len(bitmap), 22) + bitmap
    (bundle / 'my_video_manager/app.ico').write_bytes(icon)
    include = tmp_path / 'payload.iss'
    payload.write_patch_include(bundle, include, '0.4.2')
    result = subprocess.run([compiler, '/Q', '/DIsolatedTest', '/DAppVersion=0.4.2',
                             f'/DAppDirectory={bundle}', f'/DInstallerOutput={tmp_path}',
                             f'/DPatchInclude={include}', str(ROOT / 'installer/my-video-manager.iss')],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / 'MyVideoManager-Patch-0.4.2.exe'


@pytest.mark.parametrize('scenario', [
    'match', 'reordered', 'mismatch', 'no-install', 'no-exe', 'no-fingerprint',
    'invalid-json', 'forged-inputs', 'invalid-schema', 'duplicate-key', 'deep-json', 'trailing-json',
])
def test_silent_installer_accepts_only_matching_identity(bundle, patch_exe, tmp_path, scenario):
    installed = tmp_path / 'installed'
    shutil.copytree(bundle, installed)
    (installed / 'my-video-manager.exe').write_bytes(b'old exe')
    (installed / 'my_video_manager/web/assets/old.js').write_text('obsolete')
    (installed / 'my_video_manager-0.4.1.dist-info').mkdir()
    (installed / 'my_video_manager-0.4.1.dist-info/METADATA').write_text('old metadata')
    (installed / 'licenses/old.txt').write_text('old license')
    with closing(sqlite3.connect(installed / 'library.sqlite3')) as database, database:
        database.execute('create table user_data (value text)')
        database.execute("insert into user_data values ('keep me')")
    path = installed / FILENAME
    document = json.loads(path.read_text())
    if scenario == 'reordered':
        document['input_reasons'] = {'note': 'changed explanation'}
        path.write_text(json.dumps(dict(reversed(list(document.items()))), indent=4), encoding='utf-8')
    elif scenario == 'mismatch':
        document['inputs']['dependencies']['example'] = '2'
        path.write_text(json.dumps(make_runtime_fingerprint(**document['inputs'])))
    elif scenario == 'forged-inputs':
        document['inputs']['dependencies']['example'] = '2'
        path.write_text(json.dumps(document))
    elif scenario == 'invalid-schema':
        document['schema_version'] = 999
        path.write_text(json.dumps(document))
    elif scenario == 'duplicate-key':
        path.write_text(path.read_text()[:-1] + ', "schema_version": 2}')
    elif scenario == 'invalid-json':
        path.write_text('{')
    elif scenario == 'deep-json':
        path.write_text('{"x":' + '[' * 1000 + '0' + ']' * 1000 + '}')
    elif scenario == 'trailing-json':
        path.write_text(path.read_text() + 'junk')
    elif scenario == 'no-fingerprint':
        path.unlink()
    elif scenario == 'no-exe':
        (installed / 'my-video-manager.exe').unlink()
    elif scenario == 'no-install':
        shutil.rmtree(installed)
    before = snapshot(installed)
    existed_before = installed.exists()
    directories_before = {p.relative_to(installed).as_posix() for p in installed.rglob('*') if p.is_dir()}
    log = tmp_path / 'install.log'
    result = subprocess.run([str(patch_exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                             f'/DIR={installed}', f'/LOG={log}'], timeout=60)
    if scenario in ('match', 'reordered'):
        assert result.returncode == 0, log.read_text(encoding='utf-8-sig')
        for name in payload.app_files(bundle):
            assert (installed / name).read_bytes() == (bundle / name).read_bytes()
        assert not (installed / 'my_video_manager/web/assets/old.js').exists()
        assert not (installed / 'my_video_manager-0.4.1.dist-info').exists()
        assert not (installed / 'licenses/old.txt').exists()
        assert (installed / 'python310.dll').read_bytes() == b'runtime unchanged'
        assert snapshot(installed)['library.sqlite3'] == before['library.sqlite3']
    else:
        assert result.returncode != 0
        assert snapshot(installed) == before
        assert installed.exists() == existed_before
        assert {p.relative_to(installed).as_posix() for p in installed.rglob('*') if p.is_dir()} == directories_before
        assert '전체 설치 파일을 사용하세요' in log.read_text(encoding='utf-8-sig')
