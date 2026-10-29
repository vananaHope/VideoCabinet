"""빌드 입력을 준비한다. 버전 override는 Release DryRun 전용이며 소스는 바꾸지 않는다."""
import argparse
import json
from pathlib import Path

from bundle_ffmpeg import prepare_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / 'build/bundle-assets'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'build-version.txt').write_text(args.version, encoding='utf-8')
    tools = target / 'ffmpeg'
    prepare_bundle(tools)
    # 앱 아이콘은 저장소에 커밋한 src/my_video_manager/app.ico를 그대로 쓴다(scripts/app_icon.py가 만들고 build.ps1이 검사).
    print(json.dumps({'version': args.version, 'assets': str(target)}))


if __name__ == '__main__':
    main()
