"""Inno에 넘기기 전 필수 자산과 CUDA 제외를 확인한다."""
import argparse
import ctypes
import os
import json
from pathlib import Path
import subprocess

from bundle_licenses import PYTHON_METADATA_ONLY
from bundle_ffmpeg import EXECUTABLES, SHA256, URL, VERSION, digest


MAX_BUNDLE_BYTES = 950_000_000  # MB (decimal), not MiB
UNUSED_QT_PREFIXES = ("qt6quick3d", "qt63d", "qt6charts", "qt6graphs",
                      "qt6multimedia", "qt6virtualkeyboard", "qt6pdf", "qt6location")
REQUIRED_LICENSES = (
    'licenses/GPL-3.0.txt', 'licenses/GPL-2.0.txt', 'licenses/python/python/LICENSE.txt',
    'licenses/shadcn-ui-MIT.txt', 'licenses/python/manifest.json',
    'licenses/python/ctranslate2/LICENSE',
    'licenses/python/faster-whisper/metadata/LICENSE',
    'licenses/python/tokenizers/LICENSE',
    'licenses/python/av/metadata/licenses/LICENSE.txt',
    'licenses/python/onnxruntime/onnxruntime/LICENSE',
    'licenses/python/onnxruntime/onnxruntime/ThirdPartyNotices.txt',
    'licenses/web/THIRD-PARTY-WEB.txt', 'licenses/web/manifest.json',
    'licenses/web/node_modules/react/LICENSE',
    'licenses/web/node_modules/react-dom/LICENSE',
)


def check_licenses(directory):
    for kind in ('python', 'web'):
        base = directory / 'licenses' / kind
        packages = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        if not packages:
            raise RuntimeError(f'Empty {kind} license manifest')
        for package in packages:
            files = package['files']
            if not files and not (kind == 'python' and package.get('metadata_only')
                                  and (package['name'], package.get('version')) in PYTHON_METADATA_ONLY
                                  and package.get('license') and package.get('urls')):
                raise RuntimeError(f'Missing license originals: {package["name"]}')
            for record in files:
                path = (base / record['path']).resolve()
                if not path.is_relative_to(base.resolve()) or not path.is_file() or digest(path) != record['sha256']:
                    raise RuntimeError(f'License file missing or changed: {record["path"]}')

def pyav_versions(directory):
    libraries = directory / 'av.libs'
    codecs = list(libraries.glob('avcodec-*.dll'))
    utils = list(libraries.glob('avutil-*.dll'))
    if len(codecs) != 1 or len(utils) != 1:
        raise RuntimeError('PyAV FFmpeg DLL set missing or ambiguous')
    with os.add_dll_directory(str(libraries.resolve())):
        codec = ctypes.CDLL(str(codecs[0].resolve()))
        codec.avcodec_version.restype = ctypes.c_uint
        version = codec.avcodec_version()
        util = ctypes.CDLL(str(utils[0].resolve()))
        util.av_version_info.restype = ctypes.c_char_p
        return ((version >> 16, (version >> 8) & 255, version & 255),
                util.av_version_info().decode('ascii'))


def check_pyav(directory):
    version, ffmpeg = pyav_versions(directory)
    notices = (directory / 'THIRD-PARTY-NOTICES.txt').read_text(encoding='utf-8')
    if version != (62, 28, 101) or ffmpeg != '8.1.1' or (
            'PyAV 17.1.0 bundled FFmpeg 8.1.1' not in notices):
        raise RuntimeError(f'PyAV FFmpeg notice/version mismatch: {version}, {ffmpeg}')


def check_bundle(directory: Path):
    required = (
        'my-video-manager.exe', 'my_video_manager/web/index.html',
        'my_video_manager/web_tokens.json', 'my_video_manager/app.ico',
        'my_video_manager/build-version.txt', 'ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe',
        'mpv/libmpv-2.dll', 'PySide6/QtWebEngineProcess.exe',
        'PySide6/resources/icudtl.dat', 'PySide6/resources/qtwebengine_resources.pak',
        'PySide6/resources/qtwebengine_resources_100p.pak',
        'PySide6/resources/qtwebengine_resources_200p.pak',
        'PySide6/resources/v8_context_snapshot.bin',
        'PySide6/translations/qtwebengine_locales/ko.pak',
        'PySide6/translations/qtwebengine_locales/en-US.pak',
        'PySide6/plugins/platforms/qwindows.dll', 'PySide6/opengl32sw.dll',
        'ffmpeg/source.json', 'ffmpeg/LICENSE.txt', 'ffmpeg/README.txt',
        'THIRD-PARTY-NOTICES.txt', 'licenses/LGPL-3.0.txt',
    ) + REQUIRED_LICENSES
    missing = [name for name in required if not (directory / name).is_file()
               or not (directory / name).stat().st_size]
    cuda = [str(path.relative_to(directory)) for path in directory.rglob('*.dll')
            if path.name.lower().startswith(('cublas', 'cudnn', 'nvblas', 'cudart', 'nvrtc', 'cusparse', 'cufft', 'curand'))]
    unnecessary = [str(path.relative_to(directory)) for path in (directory / 'PySide6').rglob('*')
                   if path.is_file() and (path.name.lower().startswith(UNUSED_QT_PREFIXES) or '.debug.' in path.name.lower() or 'qml' in path.parts
                   or (path.parent.name == 'qtwebengine_locales' and path.name not in ('ko.pak', 'en-US.pak')))]
    if missing or cuda or unnecessary:
        raise RuntimeError(f'설치판 자산 검사 실패: missing={missing}, CUDA={cuda}, unnecessary={unnecessary}')
    check_licenses(directory)
    check_pyav(directory)
    total_bytes = sum(path.stat().st_size for path in directory.rglob('*') if path.is_file())
    if total_bytes > MAX_BUNDLE_BYTES:
        raise RuntimeError(f'설치판 크기 상한 초과: {total_bytes} > {MAX_BUNDLE_BYTES} bytes')
    print(f'설치판 합계: {total_bytes} bytes (상한 {MAX_BUNDLE_BYTES})')
    manifest = json.loads((directory / 'ffmpeg/source.json').read_text(encoding='utf-8'))
    if (manifest.get('version'), manifest.get('url'), manifest.get('sha256')) != (VERSION, URL, SHA256):
        raise RuntimeError('FFmpeg 고정 출처·버전·SHA-256이 일치하지 않습니다.')
    for name in EXECUTABLES:
        executable = directory / 'ffmpeg' / name
        if manifest.get('files', {}).get(name) != digest(executable):
            raise RuntimeError(f'FFmpeg 실행 파일 SHA-256 불일치: {name}')
        result = subprocess.run([str(executable.resolve()), '-version'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', check=True, timeout=30)
        first_line = result.stdout.splitlines()[0] if result.stdout else ''
        if not first_line.startswith(f'{executable.stem} version {VERSION}-essentials_build-www.gyan.dev'):
            raise RuntimeError(f'FFmpeg 버전 불일치: {first_line}')
        print(first_line)
    print('필수 자산·ko/en-US 로캘·FFmpeg 해시 확인, CUDA DLL·QML·debug 리소스 없음')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    check_bundle(parser.parse_args().directory)
