"""빌드 버전은 pyproject.toml에서 생성하고 소스 실행은 배포 메타데이터를 읽는다."""
from importlib.metadata import version
from pathlib import Path

RELEASES_URL = 'https://github.com/vananaHope/my-video-manager/releases'


def current_version():
    bundled = Path(__file__).with_name('build-version.txt')
    return bundled.read_text(encoding='utf-8').strip() if bundled.is_file() else version('my-video-manager')
