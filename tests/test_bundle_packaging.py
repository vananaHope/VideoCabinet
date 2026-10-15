"""설치 입력의 출처 검증·실패 복구와 배포 필수 자산 계약."""
from wait_helpers import CHILD_READY_TIMEOUT

import ast
import hashlib
import importlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def packaging(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('bundle_ffmpeg'), importlib.import_module('check_bundle')


@pytest.fixture
def ffmpeg(packaging, monkeypatch):
    module, _ = packaging
    monkeypatch.setattr(module, 'SHA256', hashlib.sha256(b'archive').hexdigest())
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'archive'))

    def extract(command, **kwargs):
        stage = Path(next(arg[2:] for arg in command if arg.startswith('-o')))
        for name in (*module.EXECUTABLES, *module.DOCUMENTS):
            (stage / name).write_bytes(name.encode())

    monkeypatch.setattr(module.subprocess, 'run', extract)
    return module


def test_ffmpeg_cache_is_verified_on_each_build_and_never_uses_path(ffmpeg, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ffmpeg.urllib.request, 'urlopen', lambda *a, **k: calls.append(a) or io.BytesIO(b'archive'))
    cache = tmp_path / 'cache'
    destination = tmp_path / 'assets/ffmpeg'
    for _ in range(2):
        ffmpeg.prepare(destination, cache, '7z')
    assert len(calls) == 1
    assert {p.name for p in destination.iterdir()} == {'ffmpeg.exe', 'ffprobe.exe', 'source.json', 'LICENSE.txt', 'README.txt'}
    manifest = json.loads((destination / 'source.json').read_text())
    assert manifest['url'] == ffmpeg.URL
    assert manifest['files']['ffmpeg.exe'] == hashlib.sha256(b'ffmpeg.exe').hexdigest()
    (cache / ffmpeg.NAME).write_bytes(b'corrupt')
    (cache / (ffmpeg.NAME + '.part')).write_bytes(b'abandoned')
    ffmpeg.prepare(destination, cache, '7z')
    assert len(calls) == 2
    assert not list(cache.glob('*.part'))


@pytest.mark.parametrize('failure', ['hash', 'network', 'timeout', 'cancel', 'extract', 'missing', 'missing-license'])
def test_ffmpeg_failure_preserves_previous_input_and_cleans_partial(ffmpeg, tmp_path, monkeypatch, failure):
    destination, cache = tmp_path / 'assets/ffmpeg', tmp_path / 'cache'
    ffmpeg.prepare(destination, cache, '7z')
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    (cache / ffmpeg.NAME).unlink()

    def download(*args, **kwargs):
        if failure in ('network', 'timeout', 'cancel'):
            raise {'network': OSError, 'timeout': TimeoutError, 'cancel': KeyboardInterrupt}[failure]()
        return io.BytesIO(b'wrong' if failure == 'hash' else b'archive')

    def extract(*args, **kwargs):
        if failure == 'extract':
            raise subprocess.CalledProcessError(2, '7z')
        if failure == 'missing-license':
            stage = Path(next(arg[2:] for arg in args[0] if arg.startswith('-o')))
            for name in ffmpeg.EXECUTABLES:
                (stage / name).write_bytes(b'executable')

    monkeypatch.setattr(ffmpeg.urllib.request, 'urlopen', download)
    if failure in ('extract', 'missing', 'missing-license'):
        monkeypatch.setattr(ffmpeg.subprocess, 'run', extract)
    with pytest.raises((OSError, RuntimeError, KeyboardInterrupt, subprocess.CalledProcessError)):
        ffmpeg.prepare(destination, cache, '7z')
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == before
    assert not list(cache.glob('*.part'))
    assert list(destination.parent.iterdir()) == [destination]


def test_parallel_builds_share_one_ffmpeg_download(tmp_path):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    code = '''
import hashlib, io, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import bundle_ffmpeg as bundle
bundle.SHA256=hashlib.sha256(b'archive').hexdigest()
cache=Path(sys.argv[2])
def download(*args, **kwargs):
    with (cache/'downloads').open('ab') as output: output.write(b'x')
    time.sleep(.3)
    return io.BytesIO(b'archive')
def extract(command, **kwargs):
    stage=Path(next(a[2:] for a in command if a.startswith('-o')))
    for name in (*bundle.EXECUTABLES, *bundle.DOCUMENTS): (stage/name).write_bytes(b'executable')
bundle.urllib.request.urlopen=download
bundle.subprocess.run=extract
bundle.prepare(Path(sys.argv[3]), cache, '7z')
'''
    cache = tmp_path / 'cache'
    processes = [subprocess.Popen([sys.executable, '-c', code, str(scripts), str(cache), str(tmp_path / str(i))],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    try:
        for process in processes:
            out, err = process.communicate(timeout=CHILD_READY_TIMEOUT)
            assert process.returncode == 0, (out, err)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=CHILD_READY_TIMEOUT)
    assert (cache / 'downloads').read_bytes() == b'x'
    for i in range(2):
        assert (tmp_path / str(i) / 'ffprobe.exe').read_bytes() == b'executable'


@pytest.fixture
def bundle(packaging, tmp_path, monkeypatch):
    ffmpeg, checker = packaging
    files = [
        'my-video-manager.exe', 'my_video_manager/web/index.html', 'my_video_manager/web_tokens.json',
        'my_video_manager/app.ico', 'my_video_manager/build-version.txt', 'mpv/libmpv-2.dll',
        'PySide6/QtWebEngineProcess.exe', 'PySide6/plugins/platforms/qwindows.dll', 'PySide6/opengl32sw.dll',
        *('PySide6/resources/' + name for name in ['icudtl.dat', 'qtwebengine_resources.pak',
          'qtwebengine_resources_100p.pak', 'qtwebengine_resources_200p.pak', 'v8_context_snapshot.bin']),
        'PySide6/translations/qtwebengine_locales/ko.pak', 'PySide6/translations/qtwebengine_locales/en-US.pak',
        'ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe', 'ffmpeg/LICENSE.txt', 'ffmpeg/README.txt',
        'THIRD-PARTY-NOTICES.txt', 'licenses/LGPL-3.0.txt', *checker.REQUIRED_LICENSES,
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'asset')
    for kind, file in [('python', 'faster-whisper/metadata/LICENSE'), ('web', 'node_modules/react/LICENSE')]:
        (tmp_path / 'licenses' / kind / 'manifest.json').write_text(json.dumps([
            {'name': 'example', 'files': [{'path': file, 'sha256': hashlib.sha256(b'asset').hexdigest()}]}
        ]))
    (tmp_path / 'ffmpeg/source.json').write_text(json.dumps({
        'version': ffmpeg.VERSION, 'url': ffmpeg.URL, 'sha256': ffmpeg.SHA256,
        'files': {name: ffmpeg.digest(tmp_path / 'ffmpeg' / name) for name in ffmpeg.EXECUTABLES}}))
    monkeypatch.setattr(checker.subprocess, 'run', lambda args, **kw: subprocess.CompletedProcess(args, 0,
        f'{Path(args[0]).stem} version {ffmpeg.VERSION}-essentials_build-www.gyan.dev Copyright\n', ''))
    monkeypatch.setattr(checker, 'pyav_versions', lambda directory: ((62, 28, 101), '8.1.1'))
    (tmp_path / 'THIRD-PARTY-NOTICES.txt').write_text('PyAV 17.1.0 bundled FFmpeg 8.1.1')
    return checker, tmp_path


def test_bundle_logs_pinned_ffmpeg_version(bundle, capsys):
    checker, directory = bundle
    checker.check_bundle(directory)
    assert 'ffmpeg version 9.0.2-essentials_build' in capsys.readouterr().out


@pytest.mark.parametrize('name', ['THIRD-PARTY-NOTICES.txt', 'ffmpeg/LICENSE.txt',
    'ffmpeg/README.txt', 'licenses/LGPL-3.0.txt',
    'licenses/GPL-3.0.txt', 'licenses/python/ctranslate2/LICENSE',
    'licenses/python/faster-whisper/metadata/LICENSE', 'licenses/python/tokenizers/LICENSE',
    'licenses/python/av/metadata/licenses/LICENSE.txt',
    'licenses/web/THIRD-PARTY-WEB.txt', 'licenses/web/node_modules/react/LICENSE', 'PySide6/QtWebEngineProcess.exe', 'PySide6/resources/v8_context_snapshot.bin',
    'PySide6/translations/qtwebengine_locales/ko.pak', 'PySide6/translations/qtwebengine_locales/en-US.pak'])
def test_bundle_missing_required_runtime_fails(bundle, name):
    checker, directory = bundle
    (directory / name).unlink()
    with pytest.raises(RuntimeError, match='missing='):
        checker.check_bundle(directory)


@pytest.mark.parametrize('name', ['PySide6/qml/QtQuick/qmldir', 'PySide6/resources/v8_context_snapshot.debug.bin',
    'PySide6/resources/qtwebengine_resources.debug.pak', 'PySide6/translations/qtwebengine_locales/fr.pak',
    'cublas64_12.dll', *('PySide6/' + name + '.dll' for name in (
        'Qt6Quick3DUtils', 'Qt63DCore', 'Qt6Charts', 'Qt6Graphs', 'Qt6Multimedia',
        'Qt6VirtualKeyboard', 'Qt6Pdf', 'Qt6Location'))])
def test_bundle_rejects_excluded_assets(bundle, name):
    checker, directory = bundle
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    with pytest.raises(RuntimeError, match='설치판 자산 검사 실패'):
        checker.check_bundle(directory)


@pytest.mark.parametrize('change', ['binary', 'source', 'version'])
def test_bundle_rejects_changed_ffmpeg(bundle, monkeypatch, change):
    checker, directory = bundle
    if change == 'binary':
        (directory / 'ffmpeg/ffmpeg.exe').write_bytes(b'different')
    elif change == 'source':
        path = directory / 'ffmpeg/source.json'
        data = json.loads(path.read_text())
        data['url'] = 'https://example.org/other.7z'
        path.write_text(json.dumps(data))
    else:
        monkeypatch.setattr(checker.subprocess, 'run', lambda args, **kw: subprocess.CompletedProcess(args, 0, 'ffmpeg version other', ''))
    with pytest.raises(RuntimeError, match='FFmpeg'):
        checker.check_bundle(directory)


def test_installer_child_keeps_both_json_pipes_in_utf8():
    entry = Path(__file__).resolve().parents[1] / 'installer/entry.py'
    code = '''
import json, runpy, sys, types
def main():
    print(json.dumps({'text': '한국어 자막'}, ensure_ascii=False))
    print(json.dumps({'detail': '준비 필요'}, ensure_ascii=False), file=sys.stderr)
    return 0
sys.modules['my_video_manager.__main__'] = types.SimpleNamespace(main=main)
entry=sys.argv[1]
sys.argv=[entry, 'transcription']
runpy.run_path(entry, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', code, str(entry)], capture_output=True, timeout=CHILD_READY_TIMEOUT,
                            env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
    assert result.returncode == 0
    assert json.loads(result.stdout.decode('utf-8')) == {'text': '한국어 자막'}
    assert json.loads(result.stderr.decode('utf-8')) == {'detail': '준비 필요'}


def test_bundle_rejects_size_regression(bundle, monkeypatch):
    checker, directory = bundle
    size = sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
    monkeypatch.setattr(checker, 'MAX_BUNDLE_BYTES', size)
    checker.check_bundle(directory)
    (directory / 'unexpected.dat').write_bytes(b'x')
    with pytest.raises(RuntimeError, match='크기 상한 초과'):
        checker.check_bundle(directory)


def test_windowed_entry_supports_print_without_standard_streams():
    entry = Path(__file__).resolve().parents[1] / 'installer/entry.py'
    code = """
import runpy, sys, types
def main():
    assert sys.stdout is not None and sys.stderr is not None
    print('windowed output', flush=True)
    print('windowed error', file=sys.stderr, flush=True)
    return 0
sys.modules['my_video_manager.__main__'] = types.SimpleNamespace(main=main)
entry = sys.argv[1]
sys.argv = [entry]
sys.stdout = sys.stderr = None
runpy.run_path(entry, run_name='__main__')
"""
    result = subprocess.run([sys.executable, '-c', code, str(entry)], capture_output=True, timeout=CHILD_READY_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == b''


def assert_hidden_console(source, label):
    tree = ast.parse(source)
    modules = {'subprocess': 'subprocess', 'os': 'os', 'asyncio': 'asyncio'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ('subprocess', 'os', 'asyncio'):
                    modules[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom):
            assert node.module != 'subprocess', (label, node.lineno, 'Use qualified subprocess calls')
            assert not (node.module == 'os' and any((a.name in ('system', 'popen', '*') or a.name.startswith(('spawn', 'exec'))) for a in node.names)), (label, node.lineno)
            assert not (node.module == 'asyncio' and any(a.name.startswith('create_subprocess_') or a.name == '*'
                        for a in node.names)), (label, node.lineno)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ('subprocess_exec', 'subprocess_shell'), (label, node.lineno)
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)):
            continue
        module, method = modules.get(node.func.value.id), node.func.attr
        assert not (module == 'os' and (method in ('system', 'popen') or method.startswith(('spawn', 'exec')))), (label, node.lineno, 'os.system')
        assert not (module == 'asyncio' and method.startswith('create_subprocess_')), (label, node.lineno)
        if module != 'subprocess' or method not in (
                'Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'):
            continue
        calls.append((label, node.lineno))
        # Shell convenience functions cannot accept creationflags at all.
        assert method not in ('getoutput', 'getstatusoutput'), (label, node.lineno, method)
        flags = next((k.value for k in node.keywords if k.arg == 'creationflags'), None)
        assert flags is not None, (label, node.lineno, 'creationflags missing')
        expressions = [flags]
        if isinstance(flags, ast.Name):
            scope = parents[node]
            while not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                scope = parents[scope]
            expressions += [n.value for n in ast.walk(scope) if isinstance(n, ast.Assign)
                            and n.lineno < node.lineno and any(isinstance(t, ast.Name)
                            and t.id == flags.id for t in n.targets)]
        assert any(isinstance(n, ast.Attribute) and n.attr == 'CREATE_NO_WINDOW'
                   and isinstance(n.value, ast.Name) and modules.get(n.value.id) == 'subprocess'
                   for expr in expressions for n in ast.walk(expr)), (label, node.lineno)
    return calls


def test_source_subprocess_calls_hide_windows_console():
    root = Path(__file__).resolve().parents[1] / 'src'
    calls = []
    for path in root.rglob('*.py'):
        calls.extend(assert_hidden_console(path.read_text(encoding='utf-8-sig'), path))
    assert calls, 'No subprocess calls were inspected'


@pytest.mark.parametrize('source', [
    *(f"import subprocess\nsubprocess.{method}(['tool'])" for method in
      ('Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput')),
    "from subprocess import Popen\nPopen(['tool'])",
    "from subprocess import run as launch\nlaunch(['tool'])",
    "import subprocess as sp\nsp.check_output(['tool'])",
    *(f"import os\nos.{method}('tool')" for method in ('popen', 'spawnl', 'spawnve', 'execl', 'execve')),
    "from os import popen as launch\nlaunch('tool')",
    "import asyncio\nasyncio.get_event_loop().subprocess_exec('tool')",
    "loop.subprocess_shell('tool')",
    "import os\nos.system('tool')",
    "import os as system\nsystem.system('tool')",
    "from os import system as launch\nlaunch('tool')",
    "import asyncio\nasyncio.create_subprocess_exec('tool')",
    "import asyncio as aio\naio.create_subprocess_shell('tool')",
    "from asyncio import create_subprocess_exec as launch\nlaunch('tool')",
    "import subprocess\nflags = 0\nsubprocess.run(['tool'], creationflags=flags)",
])
def test_console_guard_rejects_unsafe_forms(source):
    with pytest.raises(AssertionError):
        assert_hidden_console(source, 'injected.py')


@pytest.mark.parametrize('method', ['Popen', 'run', 'call', 'check_call', 'check_output'])
def test_console_guard_accepts_hidden_calls_and_module_aliases(method):
    assert assert_hidden_console(
        f"import subprocess as sp\nflags = sp.CREATE_NO_WINDOW if True else 0\n"
        f"sp.{method}(['tool'], creationflags=flags)", 'valid.py')


@pytest.fixture
def licenses(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('bundle_licenses')


def assert_no_build_machine_paths(directory):
    for path in directory.rglob('*'):
        if not path.is_file():
            continue
        content = path.read_text(encoding='utf-8')
        assert not re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:home|Users)/|~[\\/]', content), path
        assert str(Path.home()) not in content, path
        assert Path.home().as_posix() not in content, path


def test_python_licenses_follow_analysis_files_not_installed_requirements(licenses, tmp_path, monkeypatch):
    from importlib.metadata import PathDistribution

    site = tmp_path / 'site-packages'
    site.mkdir()
    distributions = []
    for name in ('pure', 'native', 'data', 'unused', 'nvidia-cublas-cu12', 'pytest', 'no-text'):
        info = site / f'{name}-1.0.dist-info'
        info.mkdir()
        (info / 'METADATA').write_text(
            f'Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\n'
            'License-Expression: MIT\nProject-URL: Source, https://example.org/source\n')
        paths = [f'{name}/module.py', f'{name}/native.pyd', f'{name}/data.bin']
        if name != 'no-text':
            paths += [f'{info.name}/licenses/LICENSE', f'{info.name}/licenses/NOTICE',
                      f'{name}/vendor/COPYING']
        for relative in paths:
            path = site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'original copyright\r\npermission\r\n')
        (info / 'RECORD').write_text(''.join(f'{path},,\n' for path in paths))
        distributions.append(PathDistribution(info))
    monkeypatch.setattr(licenses.metadata, 'distributions', lambda: distributions)
    entries = [(name, str(site / name / file), kind) for name, file, kind in [
        ('pure', 'module.py', 'PYMODULE'), ('native', 'native.pyd', 'EXTENSION'),
        ('data', 'data.bin', 'DATA'), ('no-text', 'module.py', 'PYMODULE')]]
    target = tmp_path / 'licenses'
    with pytest.raises(RuntimeError, match='Missing license originals'):
        licenses.python_licenses(entries, target)
    monkeypatch.setattr(licenses, 'PYTHON_METADATA_ONLY', {('no-text', '1.0')})
    packages = licenses.python_licenses(entries, target)
    assert {p['name'] for p in packages} == {'pure', 'native', 'data', 'no-text', 'python'}
    assert sum(len(p['files']) for p in packages) == 10
    assert (target / 'pure/metadata/licenses/LICENSE').read_bytes() == b'original copyright\r\npermission\r\n'
    notice = (target / 'no-text/NOTICE.txt').read_text()
    assert 'MIT' in notice and 'https://example.org/source' in notice and 'no LICENSE' in notice
    assert next(p for p in packages if p['name'] == 'no-text')['metadata_only']
    assert_no_build_machine_paths(target)
    runtime = next(p for p in packages if p['name'] == 'python')
    assert runtime['files'][0]['source'] == 'sys.base_prefix/LICENSE.txt'
    # Rebuilds remove stale notices for packages no longer included by Analysis.
    licenses.python_licenses(entries[:1], target)
    assert not (target / 'native').exists()


@pytest.fixture
def npm_tree(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    packages = {'': {'dependencies': {'direct': '1.0'}}}
    for name, flags in [('direct', {}), ('transitive', {}), ('shared', {}),
                        ('direct/node_modules/nested', {}), ('dev-only', {'dev': True}),
                        ('optional-dev', {'devOptional': True})]:
        location = 'node_modules/' + name
        packages[location] = {'version': '1.0', 'license': 'MIT', **flags}
        directory = frontend / location
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'package.json').write_text(json.dumps({'name': name, 'version': '1.0', 'license': 'MIT'}))
        (directory / 'LICENSE').write_bytes(b'Copyright original\r\nMIT terms\r\n')
    (frontend / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': packages}))
    return frontend


def test_web_licenses_include_production_transitives_and_nested_packages(licenses, npm_tree, tmp_path):
    target = tmp_path / 'licenses'
    packages = licenses.web_licenses(npm_tree, target)
    assert {p['name'] for p in packages} == {'direct', 'transitive', 'shared', 'direct/node_modules/nested', 'optional-dev'}
    assert sum(len(p['files']) for p in packages) == 5
    assert (target / 'node_modules/direct/LICENSE').read_bytes() == b'Copyright original\r\nMIT terms\r\n'
    assert not (target / 'node_modules/dev-only').exists()
    assert_no_build_machine_paths(target)


@pytest.mark.parametrize('failure', ['license', 'empty', 'package', 'version'])
def test_web_licenses_fail_on_incomplete_or_stale_install(licenses, npm_tree, tmp_path, failure):
    package = npm_tree / 'node_modules/direct'
    if failure == 'license':
        (package / 'LICENSE').unlink()
    elif failure == 'empty':
        (package / 'LICENSE').write_bytes(b'')
    elif failure == 'package':
        (package / 'package.json').unlink()
    else:
        (package / 'package.json').write_text(json.dumps({'name': 'direct', 'version': '2.0'}))
    with pytest.raises((RuntimeError, FileNotFoundError)):
        licenses.web_licenses(npm_tree, tmp_path / 'licenses')


@pytest.mark.parametrize('change', ['missing', 'modified', 'escape', 'empty'])
def test_bundle_validates_all_manifest_license_files(bundle, change):
    checker, directory = bundle
    path = directory / 'licenses/web/node_modules/react/LICENSE'
    manifest = directory / 'licenses/web/manifest.json'
    if change == 'missing':
        # Use a non-representative file to exercise manifest validation.
        data = json.loads(manifest.read_text())
        data[0]['files'][0]['path'] = 'other/LICENSE'
        manifest.write_text(json.dumps(data))
    elif change == 'modified':
        path.write_bytes(b'changed')
    elif change == 'escape':
        data = json.loads(manifest.read_text())
        data[0]['files'][0]['path'] = '../../../ffmpeg/LICENSE.txt'
        manifest.write_text(json.dumps(data))
    else:
        manifest.write_text('[]')
    with pytest.raises(RuntimeError, match='[Ll]icense'):
        checker.check_bundle(directory)


@pytest.mark.parametrize('change', ['codec', 'ffmpeg', 'notice'])
def test_pyav_notice_matches_actual_dll_versions(bundle, monkeypatch, change):
    checker, directory = bundle
    if change == 'notice':
        (directory / 'THIRD-PARTY-NOTICES.txt').write_text('FFmpeg 8.0')
    else:
        monkeypatch.setattr(checker, 'pyav_versions', lambda directory:
                            ((62, 0, 0), '8.1.1') if change == 'codec' else ((62, 28, 101), '8.2'))
    with pytest.raises(RuntimeError, match='PyAV FFmpeg'):
        checker.check_bundle(directory)


@pytest.mark.parametrize('name,version', [('ctranslate2', '4.8.3'), ('tokenizers', '0.23.3')])
@pytest.mark.parametrize('change', ['valid', 'hash', 'version'])
def test_python_supplement_is_exact_and_verified(licenses, tmp_path, monkeypatch, name, version, change):
    from importlib.metadata import PathDistribution
    info = tmp_path / f'{name}.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text(f'Name: {name}\nVersion: {version if change != "version" else "99.0"}\n')
    module = tmp_path / 'module.py'
    module.touch()
    (info / 'RECORD').write_text('module.py,,\n')
    monkeypatch.setattr(licenses.metadata, 'distributions', lambda: [PathDistribution(info)])
    if change == 'hash':
        source = tmp_path / f'{name}-{version}/LICENSE'
        source.parent.mkdir()
        source.write_text('changed')
        monkeypatch.setattr(licenses, 'LICENSE_SOURCES', tmp_path)
    if change != 'valid':
        with pytest.raises(RuntimeError, match='supplemental|Missing license originals'):
            licenses.python_licenses([('module', str(module), 'PYMODULE')], tmp_path / 'out')
    else:
        packages = licenses.python_licenses([('module', str(module), 'PYMODULE')], tmp_path / 'out')
        assert packages[0]['files'][0]['sha256'] == licenses.PYTHON_SUPPLEMENTS[name, version]['sha256']
        assert (tmp_path / 'out/python/LICENSE.txt').read_bytes() == Path(sys.base_prefix, 'LICENSE.txt').read_bytes()


def test_web_embedded_build_tools_are_collected(licenses, npm_tree, tmp_path, monkeypatch):
    monkeypatch.setattr(licenses, 'WEB_BUNDLED_BUILD_TOOLS', {'node_modules/dev-only'})
    packages = licenses.web_licenses(npm_tree, tmp_path / 'out')
    assert 'dev-only' in {p['name'] for p in packages}


def test_shipped_notices_have_no_build_machine_paths():
    root = Path(__file__).resolve().parents[1] / 'installer'
    assert_no_build_machine_paths(root / 'licenses')
    content = (root / 'THIRD-PARTY-NOTICES.txt').read_text(encoding='utf-8')
    assert not re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:home|Users)/|~[\\/]', content)
    assert str(Path.home()) not in content
    assert Path.home().as_posix() not in content
