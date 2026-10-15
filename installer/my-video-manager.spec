from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
stage = root / 'build' / 'bundle-assets'
datas = collect_data_files('my_video_manager', includes=['web/**', 'web_tokens.json'])
datas += collect_data_files('faster_whisper') + copy_metadata('my-video-manager')
datas += [(str(stage / 'build-version.txt'), 'my_video_manager'),
          (str(stage / 'app.ico'), 'my_video_manager')]
# 외부 프로그램은 공식 배포 폴더 그대로 동봉한다.
datas += [(str(stage / 'ffmpeg'), 'ffmpeg'), (str(root / '.runtime' / 'mpv'), 'mpv')]
a = Analysis([str(root / 'installer' / 'entry.py')], pathex=[str(root / 'src')],
             binaries=[], datas=datas, hiddenimports=['faster_whisper', 'ctranslate2'],
             excludes=['nvidia', 'torch', 'pytest', 'tkinter', 'PyQt5', 'PyQt6'],
             hookspath=[], runtime_hooks=[], noarchive=False)
# 네이티브 의존성 탐색이 빌드 PC의 CUDA를 발견해도 설치 파일에 섞지 않는다.
cuda_prefixes = ('cublas', 'cudnn', 'nvblas', 'cudart', 'nvrtc', 'cusparse', 'cufft', 'curand')
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith(cuda_prefixes)]
pyz = PYZ(a.pure)
# console bootloader의 파이프를 자식 JSON 통신에 사용한다. 앱 소유 콘솔은 즉시 숨긴다.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='my-video-manager',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, hide_console='hide-early', contents_directory='.',
          icon=str(stage / 'app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='my-video-manager')
