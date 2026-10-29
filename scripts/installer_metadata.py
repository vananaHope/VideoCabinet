"""설치 프로그램·실행 파일에 넣는 표시 이름과 버전 정보를 앱 원본에서 만든다.

한글 표시 이름을 Inno Setup의 `/D` 명령줄 인자로 넘기면 코드 페이지에 따라 깨질 수 있어,
UTF-8(BOM) include 파일로 만들어 `#include`로 읽는다. 값의 원본은 app_version.DISPLAY_NAME 하나다.
"""
import argparse
import re
from pathlib import Path

from my_video_manager import app_version

EXECUTABLE_NAME = 'my-video-manager'
_VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$')
# Inno Setup의 #define 문자열과 Windows 버전 리소스에 그대로 넣을 수 없는 문자를 막는다.
_UNSAFE_DISPLAY_NAME = '"#\\{}\r\n'


def display_name(value=None):
    """표시 이름을 돌려준다. 지정하지 않으면 앱의 단일 원본을 읽는다."""
    name = app_version.DISPLAY_NAME if value is None else value
    if not name or name != name.strip() or any(character in name for character in _UNSAFE_DISPLAY_NAME):
        raise ValueError(f'설치 프로그램에 넣을 수 없는 표시 이름: {name!r}')
    return name


def display_name_include_text(value=None):
    """Inno Setup 전처리기가 읽을 AppDisplayName 정의를 만든다."""
    return ('; 자동 생성 파일. 표시 이름 원본은 src/my_video_manager/app_version.py의 DISPLAY_NAME이다.\n'
            f'#define AppDisplayName "{display_name(value)}"\n')


def write_display_name_include(target, value=None):
    """UTF-8(BOM) include 파일을 쓴다. Inno Setup 6은 BOM이 있는 UTF-8 스크립트를 읽는다."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'\xef\xbb\xbf' + display_name_include_text(value).encode('utf-8'))
    return target


def version_numbers(version):
    """버전 문자열을 Windows 버전 리소스의 4개 숫자로 바꾼다."""
    match = _VERSION.match(version)
    if not match:
        raise ValueError(f'Inno Setup·실행 파일 버전 정보에 쓸 수 없는 버전: {version!r}')
    numbers = tuple(int(part or 0) for part in match.groups())
    if any(number > 65535 for number in numbers):
        raise ValueError(f'버전 구성 요소가 65535를 넘습니다: {version!r}')
    return numbers


def version_info_text(version, value=None):
    """PyInstaller `EXE(version=...)`가 읽는 버전 정보 파일 내용을 만든다."""
    name = display_name(value)
    fixed = ', '.join(str(number) for number in version_numbers(version))
    return f"""# PyInstaller 실행 파일 버전 정보. scripts/prepare_bundle.py가 만든다.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({fixed}),
    prodvers=({fixed}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', {name!r}),
        StringStruct('FileVersion', {version!r}),
        StringStruct('InternalName', {EXECUTABLE_NAME!r}),
        StringStruct('OriginalFilename', {EXECUTABLE_NAME + '.exe'!r}),
        StringStruct('ProductName', {name!r}),
        StringStruct('ProductVersion', {version!r})
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_version_info(target, version, value=None):
    """버전 정보 파일을 UTF-8로 쓴다."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(version_info_text(version, value), encoding='utf-8')
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--display-name-include', type=Path)
    parser.add_argument('--version-info', type=Path)
    parser.add_argument('--version')
    arguments = parser.parse_args()
    if not arguments.display_name_include and not arguments.version_info:
        parser.error('--display-name-include 또는 --version-info가 필요합니다.')
    if arguments.display_name_include:
        write_display_name_include(arguments.display_name_include)
    if arguments.version_info:
        if not arguments.version:
            parser.error('--version-info에는 --version이 필요합니다.')
        write_version_info(arguments.version_info, arguments.version)


if __name__ == '__main__':
    main()
