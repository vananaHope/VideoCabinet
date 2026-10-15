"""설치 입력의 출처 검증·실패 복구와 배포 필수 자산 계약."""
import hashlib
import importlib
import io
import json
import os
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
        for name in module.EXECUTABLES:
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
    assert {p.name for p in destination.iterdir()} == {'ffmpeg.exe', 'ffprobe.exe', 'source.json'}
    manifest = json.loads((destination / 'source.json').read_text())
    assert manifest['url'] == ffmpeg.URL
    assert manifest['files']['ffmpeg.exe'] == hashlib.sha256(b'ffmpeg.exe').hexdigest()
    (cache / ffmpeg.NAME).write_bytes(b'corrupt')
    (cache / (ffmpeg.NAME + '.part')).write_bytes(b'abandoned')
    ffmpeg.prepare(destination, cache, '7z')
    assert len(calls) == 2
    assert not list(cache.glob('*.part'))


@pytest.mark.parametrize('failure', ['hash', 'network', 'timeout', 'cancel', 'extract', 'missing'])
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

    monkeypatch.setattr(ffmpeg.urllib.request, 'urlopen', download)
    if failure in ('extract', 'missing'):
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
    for name in bundle.EXECUTABLES: (stage/name).write_bytes(b'executable')
bundle.urllib.request.urlopen=download
bundle.subprocess.run=extract
bundle.prepare(Path(sys.argv[3]), cache, '7z')
'''
    cache = tmp_path / 'cache'
    processes = [subprocess.Popen([sys.executable, '-c', code, str(scripts), str(cache), str(tmp_path / str(i))],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    try:
        for process in processes:
            out, err = process.communicate(timeout=30)
            assert process.returncode == 0, (out, err)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=30)
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
        'ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe',
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'asset')
    (tmp_path / 'ffmpeg/source.json').write_text(json.dumps({
        'version': ffmpeg.VERSION, 'url': ffmpeg.URL, 'sha256': ffmpeg.SHA256,
        'files': {name: ffmpeg.digest(tmp_path / 'ffmpeg' / name) for name in ffmpeg.EXECUTABLES}}))
    monkeypatch.setattr(checker.subprocess, 'run', lambda args, **kw: subprocess.CompletedProcess(args, 0,
        f'{Path(args[0]).stem} version {ffmpeg.VERSION}-essentials_build-www.gyan.dev Copyright\n', ''))
    return checker, tmp_path


def test_bundle_logs_pinned_ffmpeg_version(bundle, capsys):
    checker, directory = bundle
    checker.check_bundle(directory)
    assert 'ffmpeg version 9.0.2-essentials_build' in capsys.readouterr().out


@pytest.mark.parametrize('name', ['PySide6/QtWebEngineProcess.exe', 'PySide6/resources/v8_context_snapshot.bin',
    'PySide6/translations/qtwebengine_locales/ko.pak', 'PySide6/translations/qtwebengine_locales/en-US.pak'])
def test_bundle_missing_required_runtime_fails(bundle, name):
    checker, directory = bundle
    (directory / name).unlink()
    with pytest.raises(RuntimeError, match='missing='):
        checker.check_bundle(directory)


@pytest.mark.parametrize('name', ['PySide6/qml/QtQuick/qmldir', 'PySide6/resources/v8_context_snapshot.debug.bin',
    'PySide6/resources/qtwebengine_resources.debug.pak', 'PySide6/translations/qtwebengine_locales/fr.pak',
    'cublas64_12.dll'])
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
    result = subprocess.run([sys.executable, '-c', code, str(entry)], capture_output=True, timeout=30,
                            env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
    assert result.returncode == 0
    assert json.loads(result.stdout.decode('utf-8')) == {'text': '한국어 자막'}
    assert json.loads(result.stderr.decode('utf-8')) == {'detail': '준비 필요'}
