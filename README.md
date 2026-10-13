# my-video-manager

Python + PySide6 + libmpv로 만든 Windows 개인 영상 라이브러리입니다.
감시 폴더의 하위 폴더까지 검사해 영상 제목과 썸네일을 표시하고 창 안에서 재생합니다.

## 환경 준비

Windows x64, **64비트 Python 3.10 이상**, `winget`, 인터넷 연결이 필요합니다.
저장소 루트의 PowerShell에서 실행합니다. Python 3.10.6으로 검증했습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

스크립트는 `.venv`를 만들고 Python 의존성을 설치합니다.
FFmpeg가 없으면 winget의 `Gyan.FFmpeg` **9.0.2**를 설치하며,
7-Zip이 없으면 `7zip.7zip` **26.04**를 설치합니다(관리자 권한 확인이 표시될 수 있습니다).
FFmpeg를 이미 별도로 설치했다면 `-SkipFFmpeg`를 붙일 수 있습니다.
마지막으로 libmpv를 내려받아 압축을 풀고 pytest를 실행합니다.

libmpv는 [mpv 공식 설치 안내](https://mpv.io/installation/)에 연결된
[shinchiro Windows 빌드](https://github.com/shinchiro/mpv-winbuild-cmake/releases/tag/20261013)의
`mpv-dev-x86_64-20261013-git-9d144e57b6.7z`를 사용합니다.
`scripts/install_libmpv.py`에 고정 URL과 SHA-256이 있으며, 해시가 다르면 설치를 중단합니다.
DLL은 `.runtime/mpv/libmpv-2.dll`에만 둡니다. 아카이브의 BCJ2 필터 때문에 7-Zip이 필요합니다.
바이너리와 가상환경은 Git에서 제외합니다. 빌드 교체 시 URL과 SHA-256을 함께 갱신하세요.

수동으로 같은 환경을 준비하려면:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e '.[dev]'
winget install --id Gyan.FFmpeg --version 9.0.2 --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id 7zip.7zip --version 26.04 --exact --source winget --accept-package-agreements --accept-source-agreements
.venv/Scripts/python scripts/install_libmpv.py
.venv/Scripts/python -m pytest
```

## 실행과 사용

```powershell
.venv/Scripts/python -m my_video_manager
```

1. **감시 폴더 추가**에서 폴더를 선택하면 자동으로 하위 폴더까지 검사합니다.
2. 영상 제목과 자동 캡처 썸네일이 표시됩니다. 파일 추가 후 **다시 검사**를 누릅니다.
3. 목록에서 더블클릭하거나 방향키로 고른 뒤 Enter를 누르면 재생합니다.
4. 재생 화면에서 아래 키를 사용합니다. Esc 또는 **목록으로** 버튼은 재생을 종료하고 목록으로 돌아갑니다.

| 키 | 재생 화면의 동작 |
|---|---|
| Enter | 재생 / 일시정지 |
| ← / → | 5초 뒤로 / 앞으로 |
| , | 3초 뒤로 |
| ↑ / ↓ | 속도 +0.25 / -0.25 |

목록에서는 방향키와 Enter가 선택·열기로 동작합니다. 단축키는 앱 창이 활성화된 동안만 처리하며,
mpv 자체 키 바인딩은 끕니다. 키 대응표는 `AppCore`의 주입 인자와 `set_key_bindings()`로 교체할 수 있습니다.
설정 화면은 후속 범위입니다. 검사 중에는 창을 닫지 못하도록 안내하며 완료 후 종료할 수 있습니다.

기본 저장 위치는 `%USERPROFILE%/.my-video-manager/library.sqlite3`이며,
썸네일은 같은 폴더의 `thumbnails/`에 저장합니다. 원본 영상에는 쓰지 않습니다.
DB에는 썸네일을 데이터 폴더 기준 상대 이름으로 저장하므로 데이터 폴더 전체를 옮겨도 표시됩니다.
별도 데이터로 실행하려면 다음 명령을 사용합니다.

```powershell
.venv/Scripts/python -m my_video_manager --data-dir .local/demo-data
```

## 구조와 테스트

- `core.py`: 앱 코어 공개 API인 `AppCore`, SQLite 저장, `Video`·`Location`·`WatchedFolder`, 지문·키 명령·속도 범위 정책.
- `adapters.py`: ffprobe 정보 읽기, ffmpeg 썸네일 캡처, python-mpv를 통한 libmpv 제어.
- `media.py`: ffprobe JSON 파싱 및 정지 이미지·영상 판정 순수 함수.
- `ui.py`: PySide6 화면, 검사 작업자 스레드, 창 내부 키 전달.
- `tests/test_core.py`: 임시 실제 파일·임시 DB, 가짜 미디어 어댑터·시계로 코어 공개 동작만 검증.
- `tests/test_media.py`: 고정 ffprobe JSON으로 미디어 판정을 검증.

```powershell
.venv/Scripts/python -m pytest -q
```

영상 지문은 `v1:파일크기:SHA256`입니다. 앞·중앙·뒤에서 각각 최대 64 KiB를 읽습니다.
동일 내용의 복사본은 하나의 영상과 여러 위치로 저장됩니다. 전체 파일 해시가 아니므로
같은 크기이고 샘플 부분이 같은 파일은 구별하지 못할 수 있습니다(ADR-0002의 절충).
제목은 최초 등록 위치의 확장자를 제외한 파일 이름입니다.
파일 확장자에 제한을 두지 않고 ffprobe가 실제 영상 스트림과 양수 길이를 확인합니다.
정지 이미지 형식과 단일 프레임, 첨부 그림은 영상으로 등록하지 않습니다.
짧은 영상도 등록하며, 최소 길이 필터는 이슈 #3 범위입니다.
손상된 영상이나 썸네일 생성 실패는 검사 결과에 알리고 나머지는 계속 등록합니다.
디렉터리 열거 오류도 검사 결과로 알리며 다른 폴더는 계속 검사합니다.
정션·심볼릭 링크 등 재분석 지점은 건너뛰고 이미 검사한 실제 디렉터리는 다시 들어가지 않습니다.

이 골격은 수동 재검사만 제공하며 실시간 파일 감시, 이름 변경·이동 추적, 파일 없음,
제외, 시청 기록, 자막·태그·시리즈는 구현하지 않습니다.

## 직접 확인할 항목

자동 테스트는 실제 mpv 화면을 포함하지 않습니다. 변경 후 아래를 실제 창에서 확인합니다.

- 한글·공백이 있는 감시 폴더와 하위 폴더를 추가해 썸네일과 제목이 표시되는지.
- MKV/HEVC 영상 및 AC3·DTS 음성이 창 안에서 영상·소리와 함께 재생되는지.
- 마우스 더블클릭과 방향키 + Enter로 영상을 열 수 있는지.
- 재생 중 표의 모든 키, Esc로 목록 복귀, 다른 앱에 포커스를 옮긴 뒤 키 입력이 이 앱을 조작하지 않는지.
- 종료·재실행 후 라이브러리와 감시 폴더가 유지되는지.

ffmpeg/ffprobe를 찾지 못하면 설치 후 새 터미널을 열거나 PATH를 확인하세요.
앱은 winget 기본 설치 경로도 탐색하므로 설치 직후 기존 터미널에서도 실행할 수 있습니다.
`libmpv-2.dll` 오류는 `scripts/install_libmpv.py`를 다시 실행하고 Python과 DLL이 모두 x64인지 확인하세요.
