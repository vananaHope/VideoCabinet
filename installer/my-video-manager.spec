from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
stage = root / 'build' / 'bundle-assets'
datas = collect_data_files('my_video_manager', includes=['web/**', 'web_tokens.json'])
datas += collect_data_files('faster_whisper') + copy_metadata('my-video-manager')
datas += [(str(root / 'installer' / 'THIRD-PARTY-NOTICES.txt'), '.'),
          (str(root / 'installer' / 'licenses'), 'licenses')]
datas += [(str(stage / 'build-version.txt'), 'my_video_manager'),
          (str(stage / 'app.ico'), 'my_video_manager')]
# 외부 프로그램은 공식 배포 폴더 그대로 동봉한다.
datas += [(str(stage / 'ffmpeg'), 'ffmpeg'), (str(root / '.runtime' / 'mpv'), 'mpv')]
a = Analysis([str(root / 'installer' / 'entry.py')], pathex=[str(root / 'src')],
             binaries=[], datas=datas, hiddenimports=['faster_whisper', 'ctranslate2',
                                                     'my_video_manager.runtime_fingerprint'],
             excludes=['nvidia', 'torch', 'pytest', 'tkinter', 'PyQt5', 'PyQt6'],
             hookspath=[str(root / 'installer' / 'hooks')], runtime_hooks=[], noarchive=False)
# 네이티브 의존성 탐색이 빌드 PC의 CUDA를 발견해도 설치 파일에 섞지 않는다.
cuda_prefixes = ('cublas', 'cudnn', 'nvblas', 'cudart', 'nvrtc', 'cusparse', 'cufft', 'curand')
# QML 디버거·가상 키보드·Qt 이미지 PDF 판독기는 웹 셸에서 사용하지 않는다.
# QtWebEngineCore 내부 PDF 지원은 이 별도 QtPdf 모듈과 무관하다.
unused_qt = {'Qt6Quick3DUtils.dll', 'Qt6VirtualKeyboard.dll', 'Qt6Pdf.dll',
             'QtPdf.pyd', 'QtVirtualKeyboard.pyd', 'qpdf.dll', 'qtvirtualkeyboardplugin.dll'}
# Qt TLS 훅은 빌드 셸 PATH의 OpenSSL 3(예: Git의 mingw64\bin)을 찾으면 넣는다. 셸마다 동봉 파일과
# 런타임 지문이 달라지므로 넣지 않는다. Python은 자체 OpenSSL 1.1을, Qt는 schannel 백엔드를 쓴다.
path_openssl = {'libssl-3-x64.dll', 'libcrypto-3-x64.dll'}
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith(cuda_prefixes)
              and Path(entry[0]).name not in unused_qt
              and Path(entry[0]).name.lower() not in path_openssl
              and '/qmltooling/' not in Path(entry[0]).as_posix()]
# QML은 위 훅에서 수집하지 않는다. Qt의 release 리소스와 ko/en-US만 남긴다.
def keep_data(entry):
    path = Path(entry[0])
    normalized = path.as_posix().lower()
    if not normalized.startswith('pyside6/'):
        return True
    if '.debug.' in path.name.lower() or '/qml/' in normalized:
        return False
    if '/qtwebengine_locales/' in normalized:
        return path.name in ('ko.pak', 'en-US.pak')
    if '/translations/' in normalized:
        return path.stem.endswith(('_ko', '_en', '_en_US'))
    return True

a.datas = [entry for entry in a.datas if keep_data(entry)]
# Analysis 이후 실제 동봉 파일과 wheel 메타데이터를 대조한다.
sys.path.insert(0, str(root / 'scripts'))
from bundle_licenses import collect_bundle_licenses
a.datas += collect_bundle_licenses(a, root, stage)
from bundle_fingerprint import write_bundle_fingerprint
fingerprint = write_bundle_fingerprint(stage, root / '.runtime' / 'mpv', root / 'installer' / 'hooks',
                                       bundle_files=[entry[0] for entry in a.binaries + a.datas])
a.datas.append((fingerprint.name, str(fingerprint), 'DATA'))
pyz = PYZ(a.pure)
# windowed도 부모가 연결한 stdout/stderr 파이프는 유지한다. 설치판 자식 JSON으로 검증한다.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='my-video-manager',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, contents_directory='.',
          icon=str(stage / 'app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='my-video-manager')
