"""빌드 버전은 pyproject.toml에서 생성하고 소스 실행은 배포 메타데이터를 읽는다."""
from importlib.metadata import version
from pathlib import Path

# 소스 저장소는 비공개라 설치 파일·서명 매니페스트는 공개 배포 저장소에만 발행한다.
RELEASE_REPOSITORY = 'vananaHope/my-video-manager-releases'
RELEASES_URL = f'https://github.com/{RELEASE_REPOSITORY}/releases'
# 사용자에게 보이는 앱 이름. 창·트레이·경고·웹 셸이 이 값만 읽는다. 식별자(설치 AppId·데이터 폴더·패키지 이름)는 바꾸지 않는다.
DISPLAY_NAME = '상영실'


def current_version():
    bundled = Path(__file__).with_name('build-version.txt')
    return bundled.read_text(encoding='utf-8').strip() if bundled.is_file() else version('my-video-manager')
