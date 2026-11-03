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

from my_video_manager.app_version import DISPLAY_NAME
from my_video_manager.runtime_fingerprint import APP_OWNED_PATHS, FILENAME, make_runtime_fingerprint

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('patch_payload', ROOT / 'scripts/patch_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)
metadata_spec = importlib.util.spec_from_file_location('installer_metadata', ROOT / 'scripts/installer_metadata.py')
metadata = importlib.util.module_from_spec(metadata_spec)
metadata_spec.loader.exec_module(metadata)


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


def write_test_icon(bundle):
    """Inno가 SetupIconFile·바로 가기 아이콘으로 읽을 최소 ICO."""
    import struct
    bitmap = struct.pack('<IiiHHIIiiII', 40, 1, 2, 1, 32, 0, 4, 0, 0, 0, 0) + b'\xff\x80\x00\xff' + b'\0' * 4
    icon = struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 1, 1, 0, 0, 1, 32, len(bitmap), 22) + bitmap
    (bundle / 'my_video_manager/app.ico').write_bytes(icon)


def inno_compiler():
    if sys.platform != 'win32':
        pytest.skip('Inno Setup requires Windows')
    compiler = shutil.which('ISCC.exe') or str(Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe')
    if not Path(compiler).is_file():
        pytest.skip('Inno Setup 6 compiler not installed')
    return compiler


def compile_isolated_installer(bundle, tmp_path, shortcut_root, patch_include=None, version='0.4.2'):
    """실제 제품 .iss를 격리 define으로 컴파일한다. 바로 가기 폴더는 임시 폴더로 돌린다."""
    compiler = inno_compiler()
    display_name = tmp_path / 'display-name.iss'
    metadata.write_display_name_include(display_name)
    arguments = [compiler, '/Q', '/DIsolatedTest', f'/DAppVersion={version}',
                 f'/DAppDirectory={bundle}', f'/DInstallerOutput={tmp_path}',
                 f'/DDisplayNameInclude={display_name}', f'/DShortcutRoot={shortcut_root}']
    if patch_include:
        arguments.append(f'/DPatchInclude={patch_include}')
    arguments.append(str(ROOT / 'installer/my-video-manager.iss'))
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def run_installer(executable, directory, log, *extra):
    return subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                           f'/DIR={directory}', f'/LOG={log}', *extra], timeout=60)


def shortcut_properties(path):
    """WScript.Shell로 .lnk의 대상·아이콘을 읽는다. 임시 폴더의 바로 가기만 읽는다."""
    shell = shutil.which('powershell') or shutil.which('pwsh')
    assert shell, 'PowerShell is required to inspect shortcuts'
    script = ('$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TEST_SHORTCUT); '
              '[Console]::OutputEncoding = [Text.Encoding]::UTF8; '
              'ConvertTo-Json @{ target = $link.TargetPath; icon = $link.IconLocation }')
    result = subprocess.run([shell, '-NoProfile', '-Command', script], capture_output=True,
                            text=True, encoding='utf-8-sig', timeout=60,
                            env={**os.environ, 'TEST_SHORTCUT': str(path)})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# 옛 표시 이름. My Video Manager는 v0.8.0까지 발행했고, 상영실(#301)은 발행 전 개발판에서만 썼다.
OLD_NAMES = ('My Video Manager', '상영실')


def make_old_shortcuts(shortcut_root, desktop=True, names=OLD_NAMES):
    for folder in ('Programs', 'Desktop') if desktop else ('Programs',):
        directory = shortcut_root / folder
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / f'{name}.lnk').write_bytes(b'old shortcut')


@pytest.fixture
def patch_exe(bundle, tmp_path):
    write_test_icon(bundle)
    include = tmp_path / 'payload.iss'
    payload.write_patch_include(bundle, include, '0.4.2')
    compile_isolated_installer(bundle, tmp_path, tmp_path / 'shortcuts', patch_include=include)
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
    shortcuts = tmp_path / 'shortcuts'
    make_old_shortcuts(shortcuts)
    log = tmp_path / 'install.log'
    result = run_installer(patch_exe, installed, log)
    if scenario in ('match', 'reordered'):
        assert result.returncode == 0, log.read_text(encoding='utf-8-sig')
        for name in payload.app_files(bundle):
            assert (installed / name).read_bytes() == (bundle / name).read_bytes()
        assert not (installed / 'my_video_manager/web/assets/old.js').exists()
        assert not (installed / 'my_video_manager-0.4.1.dist-info').exists()
        assert not (installed / 'licenses/old.txt').exists()
        assert (installed / 'python310.dll').read_bytes() == b'runtime unchanged'
        assert snapshot(installed)['library.sqlite3'] == before['library.sqlite3']
        # 패치 설치도 옛 이름 바로 가기를 지우고 표시 이름 바로 가기 하나만 남긴다.
        assert sorted(p.name for p in (shortcuts / 'Programs').iterdir()) == [f'{DISPLAY_NAME}.lnk']
        assert sorted(p.name for p in (shortcuts / 'Desktop').iterdir()) == [f'{DISPLAY_NAME}.lnk']
        link = shortcut_properties(shortcuts / 'Desktop' / f'{DISPLAY_NAME}.lnk')
        assert Path(link['target']).name == 'my-video-manager.exe'
        assert Path(link['icon'].split(',', 1)[0]).name == 'app.ico'
    else:
        assert result.returncode != 0
        assert snapshot(installed) == before
        assert installed.exists() == existed_before
        assert {p.relative_to(installed).as_posix() for p in installed.rglob('*') if p.is_dir()} == directories_before
        assert '전체 설치 파일을 사용하세요' in log.read_text(encoding='utf-8-sig')
        # 설치를 거부하면 바로 가기도 그대로다.
        for name in OLD_NAMES:
            assert (shortcuts / 'Programs' / f'{name}.lnk').exists()
            assert (shortcuts / 'Desktop' / f'{name}.lnk').exists()


@pytest.mark.parametrize('desktop_before, select_desktop_task', [
    (True, False), (False, False), (False, True), (True, True),
])
def test_overwrite_install_replaces_old_shortcuts_with_one_display_name(
        bundle, tmp_path, desktop_before, select_desktop_task):
    """덮어 설치도 옛 바로 가기를 지우고 표시 이름 하나만 남긴다(바탕 화면은 있던 사용자만)."""
    write_test_icon(bundle)
    shortcuts = tmp_path / 'shortcuts'
    compile_isolated_installer(bundle, tmp_path, shortcuts)
    installer = tmp_path / 'MyVideoManager-Setup-0.4.2.exe'
    installed = tmp_path / 'installed'
    shutil.copytree(bundle, installed)
    (installed / 'my-video-manager.exe').write_bytes(b'old exe')
    with closing(sqlite3.connect(installed / 'library.sqlite3')) as database, database:
        database.execute('create table user_data (value text)')
        database.execute("insert into user_data values ('keep me')")
    make_old_shortcuts(shortcuts, desktop=desktop_before)
    log = tmp_path / 'install.log'
    result = run_installer(installer, installed, log,
                           *(['/MERGETASKS=desktopicon'] if select_desktop_task else []))
    assert result.returncode == 0, log.read_text(encoding='utf-8-sig')
    assert (installed / 'my-video-manager.exe').read_bytes() == (bundle / 'my-video-manager.exe').read_bytes()
    with closing(sqlite3.connect(installed / 'library.sqlite3')) as database:
        assert database.execute('select value from user_data').fetchone() == ('keep me',)
    assert sorted(p.name for p in (shortcuts / 'Programs').iterdir()) == [f'{DISPLAY_NAME}.lnk']
    desktop = sorted(p.name for p in (shortcuts / 'Desktop').iterdir()) if (shortcuts / 'Desktop').is_dir() else []
    assert desktop == ([f'{DISPLAY_NAME}.lnk'] if desktop_before or select_desktop_task else [])
    assert not [path for name in OLD_NAMES for path in shortcuts.rglob(f'{name}.lnk')]
    if desktop:
        link = shortcut_properties(shortcuts / 'Desktop' / f'{DISPLAY_NAME}.lnk')
        assert Path(link['target']).name == 'my-video-manager.exe'
        assert Path(link['icon'].split(',', 1)[0]).name == 'app.ico'
