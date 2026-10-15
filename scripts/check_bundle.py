"""Inno에 넘기기 전 필수 자산과 CUDA 제외를 확인한다."""
import argparse
from pathlib import Path


def check_bundle(directory: Path):
    required = (
        'my-video-manager.exe', 'my_video_manager/web/index.html',
        'my_video_manager/web_tokens.json', 'my_video_manager/app.ico',
        'my_video_manager/build-version.txt', 'ffmpeg/ffmpeg.exe', 'ffmpeg/ffprobe.exe',
        'mpv/libmpv-2.dll', 'PySide6/QtWebEngineProcess.exe',
        'PySide6/resources/icudtl.dat', 'PySide6/resources/qtwebengine_resources.pak',
    )
    missing = [name for name in required if not (directory / name).is_file()]
    if not list(directory.glob('PySide6/translations/qtwebengine_locales/*.pak')):
        missing.append('Qt WebEngine locales')
    cuda = [str(path.relative_to(directory)) for path in directory.rglob('*.dll')
            if path.name.lower().startswith(('cublas', 'cudnn', 'nvblas', 'cudart', 'nvrtc', 'cusparse', 'cufft', 'curand'))]
    if missing or cuda:
        raise RuntimeError(f'설치판 자산 검사 실패: missing={missing}, CUDA={cuda}')
    print('필수 자산·WebEngine 로캘 확인, CUDA DLL 없음')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    check_bundle(parser.parse_args().directory)
