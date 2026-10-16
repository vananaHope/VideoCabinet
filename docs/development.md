# 개발 문서

환경 준비, 테스트, 설치 파일 빌드, Release, 내부 구조를 설명합니다. 요약은 [README](../README.md)를 보세요.

## 환경 준비

Windows x64, **64비트 Python 3.10 이상**, **Node.js 22.12 이상**, `winget`, 인터넷 연결이 필요합니다.
저장소 루트의 PowerShell에서 실행합니다. Python 3.10.6으로 검증했습니다.
Node는 [공식 다운로드](https://nodejs.org/en/download)에서 22 LTS 이상을 설치하고
새 터미널의 `node --version`, `npm --version`으로 확인합니다.
이미 실행 중인 앱은 종료한 뒤 설치 스크립트를 실행하세요(DLL을 교체합니다).

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

스크립트는 `uv venv`로 worktree별 `.venv`를 만들고
`uv pip install --link-mode hardlink -e '.[dev,cuda]'`로 사용자 uv 캐시의 패키지를 하드링크합니다.
`uv`가 없으면 winget의 `astral-sh.uv` **0.8.15**(2025-09-03 출시)를 설치합니다.
이미 설치된 uv는 그대로 사용합니다. 캐시와 worktree가 다른 드라이브에 있는 등 하드링크가
불가능하면 uv가 경고를 출력하고 복사로 전환합니다. 하드링크된 `.venv` 패키지 파일을
직접 수정하지 마세요. 의존성 변경은 각 worktree에서 uv로 설치합니다. 이어서 `frontend/`에서
`npm ci`, lint, 타입 검사, 빌드를 실행합니다. PySide6 6.10.2에 WebEngine과 WebChannel이 포함돼 있습니다.
FFmpeg가 없으면 winget의 `Gyan.FFmpeg` **9.0.2**를 설치하며,
7-Zip이 없으면 `7zip.7zip` **26.04**를 설치합니다(관리자 권한 확인이 표시될 수 있습니다).
FFmpeg를 이미 별도로 설치했다면 `-SkipFFmpeg`를 붙일 수 있습니다.
winget 설치 후 기존 bash에서 `uv: command not found`가 나오면 IDE와 터미널을 다시 열어
사용자 PATH를 반영하세요. PowerShell의 `Get-Command uv`로 위치를 확인할 수 있습니다.
마지막으로 libmpv를 준비하고 FFmpeg·CUDA를 확인한 뒤 `pytest -n auto`로 테스트를 병렬 실행합니다.

이미 도구가 설치된 PC의 새 worktree에서는 빠른 모드를 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Worktree
```

빠른 모드는 전체 pytest, 프런트 lint·타입 검사, FFmpeg·7-Zip의 winget 설치를 건너뜁니다.
`npm ci`, `npm run build`, 브리지 타입 생성 검사(`--check`), WebEngine·FFmpeg·CUDA 확인은 유지합니다.
FFmpeg/ffprobe나 7-Zip이 없으면 전체 모드를 먼저 실행하라는 안내와 함께 실패합니다.
제출 전에는 별도로 전체 `pytest -n auto`와 프런트 lint·타입 검사를 실행하세요.
`-Worktree` 없이 실행하면 이 검사들을 모두 포함한 전체 준비 절차를 실행합니다.

libmpv는 [mpv 공식 설치 안내](https://mpv.io/installation/)에 연결된
[shinchiro Windows 빌드](https://github.com/shinchiro/mpv-winbuild-cmake/releases/tag/20261013)의
`mpv-dev-x86_64-20261013-git-9d144e57b6.7z`를 사용합니다.
`scripts/install_libmpv.py`에 고정 URL과 SHA-256이 있으며, 해시가 다르면 설치를 중단합니다.
검증한 압축 파일은 `%LOCALAPPDATA%\my-video-manager\cache\libmpv\`에 보관합니다.
재사용할 때도 SHA-256을 다시 검사하며 손상된 캐시는 버리고 다시 받습니다.
프로세스 간 잠금과 임시 파일의 원자 교체로 동시 준비 및 다운로드 중단을 처리합니다.
다른 프로세스가 캐시를 사용 중이면 30초마다 안내하며 잠금이 풀릴 때까지 기다립니다.
이전 준비 도구가 남긴 `.runtime/mpv-dev-*.7z`는 더 이상 사용하지 않으므로 직접 삭제해도 됩니다.
`.runtime/mpv/libmpv-2.dll`은 실행에 필요하므로 유지하세요.
캐시는 worktree를 삭제해도 남으며, 각 worktree의 DLL은 `.runtime/mpv/libmpv-2.dll`에만 둡니다. 아카이브의 BCJ2 필터 때문에 7-Zip이 필요합니다.
바이너리와 가상환경은 Git에서 제외합니다. 빌드 교체 시 URL과 SHA-256을 함께 갱신하세요.

`uv` 대신 `pip`만으로 수동 준비할 수도 있습니다(패키지를 복사하므로 디스크를 더 사용합니다):

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e '.[dev,cuda]'
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
winget install --id Gyan.FFmpeg --version 9.0.2 --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id 7zip.7zip --version 26.04 --exact --source winget --accept-package-agreements --accept-source-agreements
.venv/Scripts/python scripts/install_libmpv.py
.venv/Scripts/python -m pytest -n auto
```

테스트는 각 작업자에서 `tests/conftest.py`가 `QT_QPA_PLATFORM=offscreen`과
`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`를 기본으로 적용하며, 사용자가 지정한 값은 유지합니다.
`-n auto`는 CPU 수에 맞춰 작업자를 만들고, 여러 작업이 같은 PC를 쓸 때는 `-n 2`처럼 수를 줄일 수 있습니다.
직렬 실행은 `-n auto`를 빼고 `.venv/Scripts/python -m pytest`로 실행합니다.
자식 프로세스 성공 경로의 대기 한도는 `tests/wait_helpers.py`의 `CHILD_READY_TIMEOUT`(기본 90초)이며 `MVM_TEST_CHILD_TIMEOUT` 환경 변수로 조정합니다. 조건이 충족되면 즉시 진행하고, 짧은 timeout 동작 검사는 별도 한도를 유지합니다. 실패를 빨리 보려면 단독 실행에서 `MVM_TEST_CHILD_TIMEOUT` 값을 낮춥니다.
건너뛴 테스트와 이유까지 비교하려면 직렬·병렬 명령에 각각 `-rs`를 붙입니다.

## 웹 빌드와 개발 서버

배포용 빌드는 `src/my_video_manager/web/`에 생성되며 package-data로 포함됩니다.
이 폴더와 `node_modules`는 커밋하지 않습니다. 소스 체크아웃이나 패키징 전에
`scripts/setup.ps1` 또는 `npm --prefix frontend ci`와 `npm --prefix frontend run build`를 실행하세요.
빌드된 앱은 CDN이나 개발 서버 없이 오프라인으로 실행됩니다.

개발 시 첫 터미널에서 `npm --prefix frontend run dev`를 실행하고 다른 터미널에서 연결합니다.

```powershell
$env:MVM_WEB_DEV_URL = 'http://127.0.0.1:5173/'
.venv/Scripts/python -m my_video_manager
# 오프라인 빌드로 돌아가기
Remove-Item Env:MVM_WEB_DEV_URL
```

웹 데이터 계약은 `web_library_data.py`, 슬롯·신호·작업·탭 계약은 `web_contract.py`가 원본입니다.
웹은 생성된 `publicShellBridge()`·`publicLibraryBridge()` 래퍼만 사용하며 QObject 내부 메서드는 공개 API에 포함하지 않습니다.
`connectBridge()`가 이 공개 래퍼들의 묶음(`{ shell, library }`)을 돌려줍니다.
`web_tokens.json`은 웹 CSS와 네이티브 재생 화면에서 공유하는 색·간격·글꼴의 단일 원본입니다.
Python에서는 `web_tokens.web_tokens()`로 읽습니다.
변경 후 `.venv/Scripts/python scripts/generate_web_types.py`로 TypeScript 계약과 CSS 토큰을 생성합니다.
`--check`는 생성 파일이 원본과 다르면 실패하며 setup과 pytest가 이를 확인합니다.
썸네일 주소는 `mvm-thumb://video/<id>`이며 코어가 아는 해당 영상의 썸네일만 읽습니다.
외부 페이지로의 이동과 패키지 자산·썸네일·설정한 개발 서버 외 요청은 차단합니다.

ESLint 9는 공식 flat config와 TypeScript parser로 shadcn 6규칙을 함께 검사하기 쉬워 선택했습니다.
TanStack Virtual은 행 단위 가상화·overscan·scrollToIndex를 제공하면서 카드의 DOM과 디자인을 강제하지 않아 선택했습니다.

### 라이브러리 화면 검증

폴더·복합 필터·카드 크기는 `scripts/check_web_library_views.py --offscreen --count 5000`으로
1100×720 화면과 캐시 조건 판정/Settings 저장·JSON 응답을 포함한 브리지 시간을 확인합니다.
`--count 0`은 빈 상태, `--source <읽기 전용 영상 파일>`은 실제 320px/640px 디스크 크기 비교를 추가합니다.
`--verify --source <영상 파일>`은 데스크톱 잠금 안에서 실창 트리 키보드·mpv Enter/Esc 왕복 상태를 검사합니다.
앱 데이터는 worktree 밖 임시 폴더이고 출력은 `.local/screens-114/`입니다.
조건은 `library_views.py`에서 `LibrarySnapshot`의 공용 시청 결과와 자막 존재 인덱스를 사용합니다.
웹은 생성 계약의 보기 조건을 보내고 결과 ID·칩·폴더 트리를 표시합니다. 조건 변경은 자막 본문이나
영상 상세를 읽지 않으며 목록 갱신에서 만든 인덱스를 재사용합니다.
썸네일 크기 버전은 `.640.jpg` 파일명, 실패 진행 커서는 공용 Settings의 `thumbnail.cursor`에 저장합니다.
기존 `videos.thumbnail` 열과 Settings 형식은 그대로이며 대기 대상 부분 인덱스만 추가하므로 DB 버전은 v4를 유지합니다.

화면 검증과 대량 목록 측정은 Windows에서 `scripts/check_web_library.py`를 사용합니다.
`--prepare --count 24 --source <테스트 영상 폴더>`는 원본을 `.local/issue46/`로 복사하고 데모 데이터를 등록합니다.
`--prepare --count 5000`은 합성 영상 5,000개를 공개 코어 API로 등록합니다.
`--count`를 지정하면 웹 기본 상태의 1100×720 스크린샷과 측정 JSON을
`.local/screens-46/`에 남깁니다. `--verify`는 웹 키보드·composition 이벤트·복사본 mpv 복귀를 추가 확인합니다.
`--verify-shell`은 각 탭 스크린샷과 웹/mpv 왕복을, `--long-content`는 긴 제목·태그를 확인합니다.
실제 Windows 한국어 IME의 조합·후보 선택은 사람이 별도로 확인해야 합니다.
`--verify-library --count 24 --long-content`는 테스트 복사본으로 하이라이트 0·32개,
시각 재생·Esc 복귀·기존 편집 저장을 확인합니다. 이 검사는 `.local/issue46/`의 데모
하이라이트를 다시 구성합니다. `--output .local/screens-48`로 증거 저장 위치를 지정할 수 있습니다.
`--profile-refresh`는 Python 처리, 라이브러리 JSON 파싱, 파싱 뒤 웹 프레임 대기를 나누어 기록합니다.


## 설치 파일 만들기

환경 준비를 마친 뒤 빌드 extra와 [Inno Setup 6.5.4](https://jrsoftware.org/files/is6.5-whatsnew.htm)를 설치합니다.
Inno Setup 6.5.4는 2025-09-24 공개된 고정 버전입니다.
`ISCC.exe`를 PATH에 넣거나 `-InnoCompiler '설치 경로/ISCC.exe'`로 지정할 수 있습니다.

```powershell
uv pip install --python .venv/Scripts/python.exe --link-mode hardlink -e '.[build]'
winget install --id JRSoftware.InnoSetup --version 6.5.4 --exact --source winget --silent --accept-package-agreements --accept-source-agreements
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

`setup.ps1`이 만든 `.venv`에는 pip이 없어도 됩니다. 위 명령은 uv로 해당 환경에 빌드 도구를 추가합니다.
웹 빌드 → 생성 검사 → PyInstaller 6.16.0 onedir → Inno Setup 순서입니다.
버전은 `pyproject.toml`에서 읽고 `dist/installer/MyVideoManager-Setup-<version>.exe`로 만듭니다.
실행 폴더는 `dist/my-video-manager/`이며 웹·디자인 토큰·아이콘·Qt WebEngine 리소스와 로캘,
libmpv·FFmpeg·ffprobe를 포함합니다. CUDA·Whisper 모델은 넣지 않습니다.
`-Version 0.2.0`은 소스를 바꾸지 않고 설치 파일과 앱 표시 버전을 함께 지정합니다(Release DryRun용).
이미 만든 실행 폴더로 설치 파일만 다시 만들 때는 `-SkipPyInstaller -AppDirectory <실행 폴더>`를 사용합니다.

앱 부분만 담은 패치도 만들려면 `scripts/build.ps1 -Patch`를 사용합니다.
전체 설치 파일과 함께 `dist/installer/MyVideoManager-Patch-<version>.exe`를 만듭니다.
기본 빌드는 패치를 추가 압축하지 않습니다. 기존 번들에서는 `-SkipPyInstaller -Patch`를 함께 쓰며,
`-Version`은 번들의 `my_video_manager/build-version.txt`와 같아야 합니다.
릴리스 자동화 연결·업데이트 매니페스트·서명·업로드는 별도 작업입니다.

패치는 PYZ를 포함한 exe 전체와 앱 데이터·웹 자산·앱 `.dist-info`·라이선스·지문 문서를 교체합니다.
파일 경계는 `runtime_fingerprint.py`의 `APP_OWNED_PATHS` 한 곳에서 정의하고
`scripts/patch_payload.py`가 Inno 파일 목록과 오래된 앱 디렉터리 정리 목록을 생성합니다.
앱 패키지를 PYZ 밖으로 옮기지 않으므로 기존 PyInstaller 부트로더/PYZ 구성을 유지하며,
Python·PyInstaller·의존성 호환성은 런타임 지문으로 제한합니다.
동봉 런타임 DLL·ffmpeg·mpv와 사용자 데이터는 패치에 포함하지 않습니다.
삭제된 웹 청크·모듈·옛 `.dist-info`가 남지 않도록 앱 소유 디렉터리를 비운 뒤 새 파일을 설치합니다.
이 디렉터리에 개인 파일을 저장하지 마세요. 설치 중 디스크 오류·강제 종료까지 원자적으로 복구하는
업데이트 트랜잭션은 제공하지 않으며, 중단 후에는 전체 설치 파일로 복구합니다.

패치와 전체 설치는 같은 `AppId`, 사용자 단위 설치, Inno Restart Manager의 실행 중 앱 닫기,
라이선스 파일 동봉 규칙을 사용합니다. 패치는 설치 전 `PrepareToInstall`에서 exe 존재와 지문 JSON의
schema·입력·해시를 빌드 시 검증한 지문과 대조합니다. 공백·키 순서·설명 문구 변경은 허용하지만
지문 불일치·누락·손상·지원하지 않는 schema·중복 키는 거부합니다. 외부 경로를 덮어쓰거나 지우지 않도록
설치 트리의 junction/symlink도 거부합니다. 검증 실패 시 앱 종료나 설치 파일·등록 정보 변경 전에
“전체 설치 파일을 사용하세요”를 안내하며 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`에서는
0이 아닌 종료 코드와 `/LOG=<파일>`에 안내를 남깁니다. 설치 경로를 직접 지정하려면 `/DIR=<기존 설치 폴더>`를 사용합니다.
이 검사는 호환성 검사이며, 실제 런타임 파일 내용의 무결성 검사나 서명 검증은 아닙니다.

비GUI 실행 확인은 `my-video-manager.exe --version`으로 합니다. 배포 exe는 `console=False`라 콘솔이 없으므로(`--help`도 같음) stdout을 연결하지 않고 실행하면 argparse가 출력을 쓰지 못해 오류 창이 뜹니다. 파이프나 리다이렉션으로 출력을 받아야 합니다.
설치 테스트 전용 `/DIsolatedTest` ISCC define은 제거 프로그램·등록·바로가기 생성을 끄고
이전 설치 경로 재사용도 끕니다. `build.ps1`은 이 define을 전달하지 않습니다.
`tests/test_patch_installer.py`는 이 구성과 임시 `/DIR=`로 실제 조용한 설치·거부 경로를 검사합니다.
사람이 확인할 때는 별도 시험 PC에서 실제 마법사·앱 닫기·설치 등록·제거 프로그램 동작을 확인하세요.

실행 폴더 루트의 `runtime-fingerprint.json`은 실제 동봉 Python 배포판의 고정 버전 목록(앱 자체 제외), Python·PyInstaller·hooks 버전, ffmpeg·ffprobe·mpv와 커스텀 hook의 SHA-256, 필터링 후 동봉 바이너리·데이터의 대상 경로 목록(`bundle_files`)을 기록합니다. 대상 경로는 Windows 기준 소문자·`/` 구분자로 정규화하고 정렬·중복 제거하며 앱 소유 경로는 제외합니다. hook은 CRLF를 LF로 바꾼 뒤 해시합니다. schema 2는 파일 집합을 기록하지 않던 schema 1을 허용하지 않으므로 기존 번들은 다시 빌드해야 합니다. 입력 정책과 이유는 `runtime_fingerprint.py` 한 곳에 있으며 앱 코드·앱 버전·웹 자산·`.spec` 전체는 입력에서 제외합니다.
`installed_runtime_fingerprint()`는 설치본 지문을 읽고 개발 환경·누락·손상 파일에는 `None`을 돌려줍니다. `-SkipPyInstaller`는 기존 지문과 동봉 바이너리를 검증하며 지문이 없는 예전 번들은 다시 빌드해야 합니다.

설치판 FFmpeg는 PATH와 무관하게 Gyan `9.0.2 essentials` 배포본을 사용합니다.
고정 URL·SHA-256은 `scripts/bundle_ffmpeg.py`에 있으며 `%LOCALAPPDATA%/my-video-manager/cache/ffmpeg/`의
공용 아카이브를 빌드마다 재검증합니다. `ffmpeg.exe`·`ffprobe.exe`만 추출하고 `source.json`에 출처와
실행 파일 해시를 기록합니다. `check_bundle.py`는 이 해시와 두 도구의 `-version`을 검사·출력합니다.
Qt는 웹 셸에 쓰지 않는 QML 트리와 debug 리소스를 제외하고 로캘은 ko·en-US만 포함합니다.
WebEngine이 참조하는 Qml·Quick 기반 DLL과 소프트웨어 렌더러는 유지합니다.
실행 파일은 콘솔 창을 만들지 않는 `windowed` 모드입니다. 받아쓰기·GPU 감지는 같은 exe의
`transcription` 하위 명령을 사용하며 부모가 연결한 stdout/stderr 파이프를 보존합니다.
설치 진입점은 이 자식 출력의 인코딩을 UTF-8로 지정해 한국어 JSON을 전달합니다.

새 `src/` 하위 프로세스 호출은 Windows에서 `CREATE_NO_WINDOW`를 사용해야 하며 정적 회귀 테스트로 검사합니다.
FFmpeg 원본 `LICENSE`·`README.txt`도 함께 추출합니다. 번들은 불필요한 Qt 모듈과 950,000,000 bytes 상한을 검사합니다.


## 새 버전 올리기

`scripts/release.ps1`은 로컬 릴리스용입니다. Git for Windows, GitHub CLI의 `gh auth login`,
"설치 파일 만들기"의 빌드 extra 설치까지 먼저 마쳐야 합니다.
`release.ps1`은 의존성을 설치하지 않고 `build.ps1`을 호출합니다. `main`에서만 실행하며 작업 트리가 깨끗하고 `main`,
`origin/main`, 실제 원격 main이 모두 같아야 합니다. 기존 로컬/원격 태그나 GitHub Release가 있으면 멈춥니다.

```powershell
# 검사와 계획 출력만: 버전·커밋·태그·원격·원격 추적 ref를 바꾸지 않음
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.2.0 -DryRun
# 위 동작에 빌드 추가: pyproject.toml 수정 없이 -Version을 build.ps1에 전달
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.2.0 -DryRun -Build
# 실제 릴리스
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.2.0
```

실제 실행은 `pyproject.toml` 버전을 올려 한국어로 커밋하고 설치 파일을 빌드합니다.
설치 파일의 SHA-256 파일을 만든 뒤 `v<version>` 태그와 main을 atomic push하고,
`gh release create --verify-tag`로 설치 파일과 체크섬을 함께 게시합니다.
노트는 현재 main에 포함된 가장 높은 버전 태그 이후의 커밋 제목입니다(태그가 없으면 전체).
설치 파일은 `dist/installer/MyVideoManager-Setup-<version>.exe`, 체크섬은 그 옆의 `.exe.sha256`입니다.
기존 태그·Release를 덮어쓰거나 강제 push하지 않습니다.
빌드 실패나 원격에서 거부한 push는 로컬 버전 커밋과 이번에 만든 태그를 자동 복구합니다.
다른 파일 변경이나 불확실한 원격 상태가 있으면 보존하고 복구 명령을 안내합니다.
push 뒤 Release 생성이 실패하면 원격 main과 태그를 유지하며 Release 확인·생성·자산 추가 명령을 안내합니다.
자동 재발행하지 않으므로 안내에 따라 상태를 확인하세요.
Ctrl+C로 빌드를 중단하면 PowerShell이 실패 복구 catch를 건너뛸 수 있습니다.
`git status`와 `git log --oneline`으로 확인하고, 보존할 작업을 저장한 뒤 이번 버전 커밋만
`git revert <버전 커밋>`으로 되돌리세요. 다른 작업 이후의 HEAD를 시작 커밋으로 reset하지 마세요.
`-DryRun -Build`의 빌드 산출물은 Git에서 제외된 폴더에 남으며 tracked 파일과 커밋은 그대로입니다.


## 자막 기능 준비 API

작업자 스레드에서
`AppCore.prepare_subtitle_support(cancellation=Event(), progress=callback)`을 호출하면
CUDA와 Whisper large-v3를 같은 흐름에서 준비합니다.
독립 어댑터 `SubtitlePreparation(data_directory, adapter=RuntimeDownloadAdapter(), gpu_available=...)`도
사용할 수 있으며 `prepare()`가 CUDA 디렉터리들과 모델 경로를 반환합니다.
콜백은 `PreparationProgress(phase, asset, completed, total)`을 받습니다.
download/verify/extract는 파일별 바이트, reuse/ready는 완료 개수, probe는 GPU 확인입니다.
추가 필드 `file_index`, `file_count`, `overall_completed`, `overall_total`은 전체 파일 순서와
누적 바이트 진행률입니다. `AppCore.subtitle_support_status()`는 이전 결과와 완료 manifest만 읽습니다.
취소 토큰은 청크마다 검사하며 네트워크 무응답 제한 시간은 10초입니다.
**진행률 콜백은 예외를 던지지 않아야 합니다.** 화면 갱신 실패 등 콜백 내부의 오류는 호출자가 처리합니다.

`PreparationError.kind`는 `gpu_unavailable`, `network`, `hash_mismatch`, `disk_full`,
`cancelled`, `invalid_archive`, `storage`, `preparation_required`를 구별하고 한국어 안내와 별도 `detail`을 제공합니다.
NVIDIA 드라이버는 사용자가 설치해야 합니다.
다운로드·해시 검증·추출과 공간 검사는 어댑터에서 주입할 수 있습니다.
GPU 감지는 최대 15초의 별도 Python 자식(`transcription --probe-cuda`)에서 실행하므로 앱 프로세스에
`ctranslate2`를 올리지 않습니다. 설치판은 같은 실행 파일의 `transcription --probe-cuda`를 사용합니다.
frozen 받아쓰기 자식은 `prepared()`로 완료 결과만 읽고, 없으면 `preparation_required`로 바로 실패합니다.
준비 다운로드는 명시적인 `prepare_subtitle_support()` 흐름에서만 실행합니다.

CUDA 버전은 기존 `cuda` extra와 같고 Windows x64 공식 PyPI 휠 URL·SHA-256은
`runtime_assets.py`에 고정했습니다. Whisper도 같은 파일의 revision과 SHA-256으로 검증합니다.
CUDA는 `data_directory/runtime/cuda/<wheel-sha256>/`에 DLL만,
모델은 기존 `data_directory/models/` 아래 `large-v3/<revision>/`에 둡니다.
소스 실행의 `models/models--Systran--faster-whisper-large-v3/snapshots/<revision>/`가 있으면
고정 파일 전체의 크기와 SHA-256을 한 번 확인해 `ready.json`을 만들고 그 경로를 그대로 재사용합니다.
맞지 않는 HF 캐시는 보존하고 앱 전용 폴더에 다시 받습니다.
반쯤 받은 `.part`와 추출 중 `.partial` 폴더는 다음 시도에서 지웁니다.
HF 캐시를 재사용할 때도 현재 revision의 앱 전용 `.partial`은 먼저 정리합니다.
이전 버전의 완료 런타임·모델은 실행 중인 DLL과 구버전으로 되돌리기를 보호하기 위해 자동 삭제하지 않습니다.
고정 버전을 바꾼 뒤 새 판 받아쓰기까지 확인했다면, 모든 앱을 완전히 종료하고
`runtime/cuda/<이전 wheel-sha256>`와 `models/large-v3/<이전 revision>` 및 이전 `.partial`만 수동으로 지울 수 있습니다.
현재 해시·revision은 `runtime_assets.py`가 원본입니다. 공유 Hugging Face 캐시는 자동으로 정리하지 않습니다.
완료 표시와 파일 크기가 맞으면 다시 받지 않으며, 같은 데이터 폴더의 준비 작업은 프로세스 사이에서도 직렬화합니다.
소스 받아쓰기는 기존 `.venv` CUDA와 Hugging Face 모델 캐시를 계속 사용합니다.

공식 CUDA 휠 실측(2026-10-15): cuBLAS 567,544,208바이트 / DLL 788,719,104바이트,
cuDNN 684,630,375바이트 / DLL 1,007,375,176바이트입니다.
모델 파일과 다운로드·추출 중 임시 공간은 별도로 필요합니다.


## 구조와 테스트

### 웹 모아보기·검색 검증

영상 상세의 정보 탭에는 외부 자막 파일 이름, 언어별 줄 수와 읽기 경고가 나옵니다.
파일이 없으면 짧은 안내를 표시하고, 일부 블록만 읽힌 파일은 줄 수와 경고를 함께 표시합니다.
긴 파일 이름은 말줄임하며 마우스를 올리면 전체 이름을 확인할 수 있습니다.
검색의 외부 자막 결과에는 출처와 언어 칩(확인할 수 없으면 **언어 모름**)을 표시합니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_external_subtitles.py --offscreen
```

이 검사는 `.local/screens-66/`에 1100×720 화면(0개·여러 언어·실패·부분 성공·긴 이름·30개 파일·검색 선택/복귀)을 저장하고,
재검사 갱신과 검색 키보드 재생·복귀를 확인합니다. 실제 mpv 검사는 데스크톱 잠금 아래
`--verify`로 실행하며 실창 스크린샷은 찍지 않습니다.

모아보기(`Ctrl+2`)와 검색(`Ctrl+3`)도 웹 페이지입니다.
모아보기는 기존 `ReelControls`의 재생·반복·복습 흐름을 쓰며, 검색은 장면 재생 후
`Esc`로 돌아왔을 때 검색어·결과·선택을 보존합니다. 검색 입력의 `↓`/`Enter`는
결과로 이동하고, 목록의 `Enter`는 선택한 장면을 재생합니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_reel_search.py --offscreen
.venv/Scripts/python.exe scripts/check_web_reel_search.py --verify --no-screenshots
```

첫 명령은 `.local/screens-49/`에 1100×720 웹 화면을
만듭니다(모아보기 0·2·503개·긴 메모/태그, 검색 입력 전·결과 없음·색인 준비·2개·500개 상한).
모아보기 완료 안내와 검색 오류 안내도 웹에서 확인합니다. 긴 메모는 목록에서 3줄로
줄여 보이며, 이 모아보기 페이지에 전체 메모를 펼치는 동작은 없습니다. 전체 메모는
라이브러리의 해당 영상 하이라이트 편집에서 확인할 수 있습니다.
두 번째 명령은 짧은 검증 영상을 작업 폴더에 생성해 실제 mpv 왕복, 키보드 조작,
조합 이벤트 중 검색 억제, 자동 전환·반복·복습을 검사합니다. 여러 작업자가 같은
데스크톱을 쓰는 환경에서는 반드시 관리자의 `desktop_lock.py run --owner issue-49 --`
아래에서 두 번째 명령을 실행합니다. 실제 한국어 IME 자판 입력과 다중 모니터·배율별
포커스 복귀는 별도 수동 확인 항목입니다.

웹의 일치 강조는 `search_matching.py`의 `match_spans`를 공유하고, 비동기 색인 준비는
`search_preparation.py`가 담당합니다. `search.py`는 Qt 의존성 없이 출처 이름과 결과 상한을
정의하며, 웹은 상한을 payload의 `limit`으로 받습니다.

### 새 웹 페이지 추가하는 법

웹 뷰·프로필·채널·요청 차단·썸네일·탭 이동·포커스·재생 중 설정 메뉴·상태 알림은
`web_shell.py`의 `WebShellHost`가 소유합니다. 페이지 컨트롤러는 자기 데이터·작업·갱신만 맡고
`host.register_page(self)`로 등록합니다. `MainWindow.home_page`는 화면에 표시하는 웹 호스트이고, `library_page`는 라이브러리 작업 담당입니다.
웹 컨트롤러의 QWidget 부모는 QObject 소유권과 이벤트 수명주기를 위한 것이며 자체 화면은 표시하지 않습니다.

예를 들어 새 탭을 추가할 때(아래는 `search`를 예로 듭니다) 다음 순서로 작업합니다.

1. `src/my_video_manager/web_contract.py`에 불변 `SEARCH = BridgeContract(name='search',
   interface='SearchBridge', slots=..., signals=..., aliases=..., constants=..., data_types=...)`를 선언하고
   `CONTRACTS`에 `SEARCH` 한 줄을 추가합니다. 슬롯 인수는 `Argument`, 문자열 유니온은 `TypeAlias`,
   페이지 고유 상수는 `Constant`로 선언합니다. 필요하면 새 데이터 모듈에 TypedDict를 정의하고
   `data_types`에 넣습니다. 공용 TypedDict는 소유 계약에 한 번만 등록합니다.
2. 새 `src/my_video_manager/web_search_page.py`에 QObject 브리지와 `WebPageController`를 구현합니다
   (브리지가 커지면 `web_search_bridge.py`로 분리). `@SEARCH.slot('find')`,
   `SEARCH.signal('resultsChanged')`처럼 계약으로 Qt 표면을 선언합니다.
   컨트롤러의 `tab = 'search'`, `bridge`, `refresh()`를 구현하고 초기화 마지막에
   `host.register_page(self)`를 호출합니다. 필요하면 기본 빈 함수인 `activated()`와 `deactivated()`를
   구현합니다. 호스트는 탭 이동, 재생 왕복, 호스트 표시·숨김 때 활성 컨트롤러를 바꾸며,
   이전 컨트롤러의 `deactivated()` 뒤 새 컨트롤러의 `activated()`를 호출합니다.
   `activated()`는 가볍게 유지하고, 무거운 계산은 지연하거나 취소할 수 있게 합니다(트레이 복원 때 잠깐 다른 탭이 활성화될 수 있습니다).
   재생에서 복귀할 때는 시청 종료 후 `activated()`가 호출되므로 통계 등을 다시 계산할 수 있습니다.
   활성 상태는 `is_active()`로 확인합니다. QWidget의 `isVisible()`은 자체 화면 표시 여부입니다.
   복귀 시 기본 `return_from_playback()`은 `refresh()`와 포커스 복원을 수행하며,
   라이브러리는 이를 재정의해 기존 `refresh(focus_gems=...)` 경로를 유지합니다.
   자체 포커스가 필요하면 `default_focus`와
   `focus_requested` 신호를 지정하고, 웹 첫 렌더 후 호출하는 `ready` 슬롯에서
   `self.page.frontend_ready()`를 호출합니다. 포커스 요청은 호스트가 준비될 때까지 보존합니다.
3. `web_page_registry.py`에 컨트롤러를 import하고 `WEB_PAGES`에 한 줄 등록합니다.
   새 탭이면 `web_contract.py`의 `TABS`에도 추가합니다. 모든 탭은 웹 컨트롤러로 등록합니다.
4. 새 `frontend/src/pages/SearchPage.tsx`를 작성합니다. `connectBridge()`에서
   `{ search, shell }`을 받아 생성된 공개 메서드만 사용하고, 효과를 정리할 때 신호 구독을 해제합니다.
   페이지 사이 브리지 호출은 공통 `shell` 외에는 하지 않습니다.
   페이지는 숨겨져도 마운트를 유지하므로 선택·검색어·스크롤을 보존할 수 있습니다.
   `pages/index.ts`에 컴포넌트 import와 `search: SearchPage` 한 줄을 추가합니다. 웹 페이지만 등록하고 `null` 항목은 두지 않습니다.
5. `.venv/Scripts/python scripts/generate_web_types.py`로 재생성한 뒤 `--check`, 전체 pytest,
   `frontend/`의 `npm run lint`, `npm run typecheck`, `npm run build`를 실행합니다.
   `scripts/check_web_library.py`로 1100×720 화면·단축키·Qt/mpv 왕복도 확인합니다.
   스크린샷은 `--offscreen`으로 찍고, 실창 입력 검사는 `--no-screenshots`로 캡처 없이 실행할 수 있습니다.

호스트·생성기·`App.tsx`·`bridge.ts`·`ui.py`는 새 페이지 때문에 고칠 필요가 없습니다.
채널 이름은 `TABS`의 `library`, `reel`, `search`, `queue`, `statistics`, `folders`, `settings`와 같고,
공통 객체만 `shell`입니다. 통계 페이지도 같은 등록부를 사용합니다.
`tests/test_web_generator.py`는 예시 계약을 앞·중간·뒤에 추가해도 기존 페이지 출력이 그대로인지,
`tests/test_web_pages.py`는 새 컨트롤러의 브리지·갱신·포커스 연결과 양쪽 등록부 일치를 확인합니다.
탭 누락·중복은 Qt 시작 또는 테스트에서 실패합니다. 웹 등록부 오타는 typecheck가, Python 등록부와의 누락·불일치는 계약 테스트가 검출합니다.
추가만 하는 Python·웹 등록부 두 파일에는 `.gitattributes`의 `merge=union`을 적용해 양쪽 추가 항목을 합칩니다.
`web_contract.py`는 일반 병합을 유지합니다. 새 계약 선언·`CONTRACTS` 항목의 추가 충돌은 양쪽을 보존하고
`CONTRACTS`는 하나의 튜플로 합칩니다. 충돌 블록 밖의 공통 꼬리 부분까지 확인해 각 계약 선언이 완전한 문장이 되게 합니다.
기존 계약의 같은 슬롯·신호·상수를 양쪽에서 수정했다면 내용을 검토해 하나로 결정합니다.
dict의 중복 키가 조용히 덮어써질 수 있으므로 계약 파일에 union 병합을 적용하지 않습니다.
생성 파일 충돌은 원본 계약을 합친 뒤 생성기로 다시 만듭니다.
`CONTRACTS`, Python·웹 등록부는 한 줄에 한 항목을 유지합니다.
공용 JSON 직렬화는 `web_json.py`, 셸 데이터는 `web_shell_data.py`가 소유합니다.
생성 파일은 직접 수정하지 않습니다. 페이지 객체로 나뉘어 `library` 신호 접두어는 기술적으로
필수가 아니지만 기존 호출부와 병렬 작업의 호환성을 위해 유지합니다.

### 웹 대화상자 (#53)

태그 편집·모든 태그 관리, 시리즈, 하이라이트 목록·편집,
자막 만들기·원어 지정, 자막 검수·구간 재생성·SRT 저장, 번역 CLI 선택을 웹으로 엽니다.
`web_dialogs_entries.py`의 진입 어댑터는 웹 대화상자만 엽니다. 제목 변경·영상 제외도 웹에서 처리하며, 제외 목록·관심 없음 복원은 폴더 관리의 해당 구역으로 이동합니다.
번역 CLI 선택지와 표시 이름은 `translation_cli.TRANSLATION_CLI_CHOICES`에서 읽습니다.

`web_dialogs_host.py`는 기존 웹 뷰 한 개의 대화상자 수명과 포커스를 관리하고,
`web_dialogs_models.py`는 `AppCore` 공개 메서드를 호출합니다. `web_contract.py`의
`DIALOGS` 계약을 생성하면 웹 `DialogsLayer`가 같은 데이터·명령을 사용합니다.
태그 변경은 즉시 저장하고, 나머지 편집은 저장·취소로 확정합니다. 태그 후보를
명시적으로 선택하지 않은 Enter는 입력한 이름을 추가하며, IME 조합 Enter는 추가하지 않습니다.
검수 중에는 줄 ID·선택·스크롤을 유지하고 재생성 대기·진행 중에는 수정을 잠급니다.
부분 번역 내보내기는 경고 시점의 스냅샷을 Windows 기본 `QFileDialog`로 저장합니다.

웹 셸이 보일 때는 페이지 위의 React 모달 층을 사용합니다. 재생처럼 셸이
숨겨진 경우에는 같은 웹 뷰를 메인 창 소유의 window-modal `QDialog`에 잠시 옮깁니다.
mpv는 계속 재생하며 검수 장면 이동도 가능합니다. 닫으면 뷰를 원래 레이아웃에 돌려놓고
페이지 상태를 복원하며, 재생 중이면 `PlaybackPage.focus_content()`를 호출합니다.
React가 보고한 콘텐츠 크기로 컨테이너를 맞추고 메인 창 크기를 넘지 않습니다.
숨은 페이지의 레이아웃 크기는 고정해 가상화 격자의 재측정·스크롤 이동을 막습니다.
셸이 다시 보이면 열린 대화상자를 유지한 채 뷰를 즉시 셸로 돌려놓습니다.
추가 `QWebEngineView`, 프로필, 페이지를 만들지 않습니다.

`ShellModals`는 페이지 구현을 수정하지 않고 열린 `dialog`·`alertdialog`를 감지해
`dialogs.modalState()`로 알립니다. 실제 모달만 `Ctrl+1~7`·`Alt+S`의 셸 동작을 막고 키 이벤트는 입력·키 캡처로 전달하며,
Esc·Tab·Enter는 해당 모달이 처리합니다. 탐색·재생 진입·웹 재로드는 이전 모달 상태를 비웁니다.
`highlight-range`는 웹 구간 표시와 Qt 재생 진행 막대가 함께 쓰는 의미 색 토큰입니다.

검사는 독립 합성 데이터만 만들며 사용자 라이브러리를 변경하지 않습니다.
생성한 임시 영상·DB는 종료 시 정리합니다. 공용 모달 검사는 `frontend/checks/`에서
실제 Radix Dialog·Popover와 `ConfirmDialog`를 별도로 빌드해 사용하며 제품 번들에는 포함하지 않습니다.

```powershell
.venv/Scripts/python scripts/check_web_dialogs.py --offscreen
# 실창은 공유 데스크톱 잠금 안에서만 실행
.venv/Scripts/python C:/Users/Rho/orca/projects/my-video-manager/.local/orchestration/desktop_lock.py run --owner issue-53 -- .venv/Scripts/python scripts/check_web_dialogs.py --real
```

1100×720 웹 화면과 검사 JSON은 `.local/screens-53/`에 남습니다. 실창 검사는
mpv 진행·재생 키 복귀·단일 뷰·라이브러리 선택/스크롤·Windows 저장창 열기/취소와
working set, 재부모화, DOM 커밋·레이아웃·프레임 시점을 측정합니다. 프레임 콜백은
화면 출력 기회이므로 모니터에 실제로 표시된 첫 픽셀이나 순간 깜빡임을 증명하지 않습니다.
`--windows-ime`를 더하면 실제 한국어 레이아웃에서 OS 키 입력을 추가 검사합니다.
OS가 자동화 키를 전달하지 않는 환경에서는 이 검사가 실패하며, 합성 composition 검사는
기본 실행에서 계속 검증합니다. 실제 IME·한자 후보·순간 깜빡임·저장창 덮어쓰기는 사람이 확인합니다.

- `core.py`: 앱 코어 공개 API인 `AppCore`, 기능별 위임, SQLite 연결, 키 명령·속도 범위 정책.
- `__init__.py`: Python 패키지 선언.
- `__main__.py`: 실행 진입점, 데이터 폴더·어댑터 준비와 앱 시작.
- `web_shell.py`, `web_shell_bridge.py`, `web_page_registry.py`: 단일 웹 뷰·채널·페이지 등록·탭/재생 왕복.
- `web_*_page.py`, `web_*_bridge.py`, `web_*_data.py`: 페이지별 작업과 공개 JSON 계약.
- `web_dialogs_entries.py`, `web_dialogs_host.py`, `web_dialogs_models.py`: 웹 업무 대화상자 진입·모달 수명주기·명령.
- `library_operations.py`, `library_controls.py`: 검사 작업자·라이브러리 관리 명령·파일 선택 연결.
- `reel_controls.py`: 모아보기 재생 엔진 전환과 재생 화면 상태 연결.
- `qt_keys.py`: 재생과 웹 설정 키 캡처가 공유하는 Qt 키 이름 변환.
- `time_display.py`: 웹 대화상자와 네이티브 재생 화면이 공유하는 시각 표시.
- `ui.py`: 페이지 연결, 창 내부 키 전달, 재생 시작·종료와 트레이 연결을 담당하는 메인 셸.
- `theme.py`: 웹 토큰 기반 네이티브 재생·트레이·공용 경고의 팔레트와 스타일.
- `library_details.py`: 선택 영상의 상세 요약 결과. `AppCore.library_details`는 자막·번역·하이라이트 소유 모듈에서 한 영상만 조회한다.
- `playback_page.py`: 영상 중심 재생 배치·아래쪽 바·작업 메뉴와 `show_position`·`show_reel` 표시 API. 전체 화면의 임시 바와 Esc 우선순위를 처리한다.
- `playback_help.py`: F1으로 켜는 별도 반투명 안내 창. 현재 키 배치·모아보기 키 의미·하이라이트 색 범례를 mpv 위에 표시한다.
- `settings.py`: JSON 값을 저장하는 공용 `Settings` 저장소. 라이브러리·번역·키 배치 설정이 함께 사용하며 키 배치는 `keys.bindings`에 저장.
- `single_instance.py`: 데이터 폴더별 중복 실행 방지와 기존 창 활성화 요청.
- `tray.py`: 트레이 숨기기·복귀·완전 종료와 대기열 완료 알림.
- `library.py`: `Video`·`Location`·`WatchedFolder`, 지문·검사 캐시, 위치·파일 없음·제외, DB v1→v2 이전.
- `adapters.py`: ffprobe 정보 읽기, ffmpeg 썸네일 캡처, python-mpv를 통한 libmpv 제어.
- `media.py`: ffprobe JSON 파싱 및 정지 이미지·영상 판정 순수 함수.
- `playback.py`: 재생 시작·위치·종료를 코어 기능에 알리는 공용 계약.
- `viewing.py`: 시청 구간 합집합·분류·이어볼 위치, 시청 전용 SQLite 테이블과 주기 저장·복구.
- `series.py`: 제목 틀·번호 추출, 자동 묶기, 사용자 편집 보존, 시리즈 순서와 이전·다음 영상 결정.
- `highlights.py`: 지점·구간 하이라이트, 메모 저장·편집·삭제, 열린 구간 종료와 이전·다음 탐색 규칙.
- `highlight_editing.py`: 하이라이트 시각 입력의 범위 제한과 수정하지 않은 정밀도 보존.
- `highlight_ui.py`: 재생 진행 막대와 읽기 전용 하이라이트 패널·현재 위치 따라가기.
- `reel.py`: 모아보기 자연 정렬·순서·반복·영상 단위 이동, 재생 지시와 복습 판정.
- `revisit.py`: 하이라이트별 마지막 복습 저장과 영상별 조회.
- `hidden_gems.py`: 숨겨진 보석 선정·순위·시리즈별 후보와 관심 없음 상태.
- `tags.py`: 태그 이름 정규화, 공유 태그·연결 저장, 자동 완성과 태그별 조회.
- `tag_editing.py`: 직접 입력한 이름과 명시적으로 고른 자동 완성 후보의 확정 규칙.
- `subtitles.py`: 영속 자막 대기열, 원어·원어 자막 저장, 받아쓰기 Protocol과 SRT 변환.
- `subtitle_queue.py`: 자동 자막 규칙, 요청 순서·앞당기기와 영상별 대기열 상태.
- `transcription.py`: 별도 프로세스의 faster-whisper large-v3 GPU 어댑터.
- `cuda_runtime.py`: 첫 자막 요청의 CUDA·Whisper 다운로드, 해시 검증, 취소와 완료 파일 재사용.
- `windows_job.py`: 앱 종료 시 받아쓰기 프로세스 트리를 정리하는 Windows Job 어댑터.
- `subtitle_controls.py`: 웹 자막 요청 진입, 백그라운드 처리, 완료된 자막의 플레이어 연결.
- `translation.py`: 번역 자막과 줄별 참조, 묶음 진행 저장·원자적 교체, 보류·재시도, 재생 중 언어 선택.
- `translation_cli.py`: 읽기 전용 구독 CLI 어댑터, 구조화 응답 검증과 오류 판정 순수 함수.
- `opencode_go.py`: OpenCode Go 연결과 번역 요청 어댑터.
- `secret_store.py`: Windows 사용자별 DPAPI로 비밀 값을 암호화해 데이터 폴더에 보관.
- `translation_models.py`: 번역 모델 목록과 모델 선택 계약.
- `translation_controls.py`: 번역 작업자와 웹 CLI 선택·재시도 진입.
- `review.py`: 원어·번역 검수, 구간 재생성·보호와 SRT 내보내기.
- `key_bindings.py`: 명령 목록·키 정규화·충돌 검사와 키 배치 변경분 저장.
- `key_display.py`: 방향키 기호 등 화면 표시용 키 이름 변환. 한 글자 기호 키는 이름을 함께 보여 준다(예: `' (작은따옴표)`).
- `search.py`: 검색 결과와 검색어 정규화, 원어·번역 출처를 구분하는 자막 FTS5 색인.

- `tests/test_core.py`: 임시 실제 파일·임시 DB, 가짜 미디어 어댑터·시계로 코어 공개 동작만 검증.
- `tests/test_settings.py`: 공용 설정의 손상된 저장 값·기본값·재저장 검증.
- `tests/test_key_bindings.py`: 공개 코어 API로 즉시 반영·재실행·충돌·복원·새 기본 명령 추가를 검증.
- `tests/test_library.py`: 이동·복사·파일 없음·제외·길이 설정·캐시와 이전 DB의 기록 보존 검증.
- `tests/test_library_return_ui.py`: 웹 셸에서 트레이 복귀와 모아보기 전환 뒤 라이브러리 갱신 검증.
- `tests/test_library_details.py`: 공개 AppCore API로 상세 요약과 파일 없음·제외 시 기록 보존 검증.
- `tests/test_playback_page_ui.py`: 재생 페이지의 키 우선순위, 전체 화면·키 안내·메뉴와 창 상태 복원, 아래쪽 바 표시 검증.
- `tests/test_media.py`: 고정 ffprobe JSON으로 미디어 판정을 검증.
- `tests/test_series.py`: 번호·제목 틀 순수 함수와 공개 코어 API로 묶기·복사본·편집·재검사·탐색 검증.
- `tests/test_viewing.py`: 순수 구간 계산과 코어 공개 동작으로 분류·탐색·배속·이어보기·복구를 검증.
- `tests/test_highlights.py`: 키 명령, 종료·전환·되감기, 탐색 경계, 메모·시각 편집과 저장 보존을 공개 코어 API로 검증.
- `tests/test_reel.py`: 공개 코어 API로 자동 전환·키 의미·복습 시계·시청 비간섭·저장 보존을 검증.
- `tests/test_hidden_gems.py`: 숨겨진 보석 선정·정렬·시리즈 예외와 관심 없음·재실행 보존 검증.
- `tests/test_tags.py`: 공개 코어 API로 태그 추가·떼기·정규화·자동 완성·이름 변경·삭제·필터·재실행 보존을 검증.
- `tests/test_subtitles.py`: 가짜 받아쓰기와 실제 임시 DB로 요청·FIFO·언어·재생성·재시작·실패 복구를 검증.
- `tests/test_subtitle_queue.py`: 자동 규칙·직접 요청 우선순위·앞당기기·취소·완료 알림 검증.
- `tests/test_queue_review.py`: 재등록·태그 부착·일괄 재시도·진행 보고와 대기열 회귀 검증.
- `tests/test_transcription.py`: GPU 없이 가짜 스크립트로 JSON·오류·취소·부모 강제 종료 시 자식 정리를 검증.
- `tests/test_translation.py`, `tests/test_translation_cli.py`: 코어 공개 동작과 순수 함수로 번역 대상,
  줄 일대일 대응, 원어 재생성, 한도 보류, 재시작·재시도, 부분 번역, CLI 프로세스 정리와 `.` 전환을 검증.
- `tests/test_review.py`: 자막 검수·구간 재생성·동시 응답 보호·부분 번역과 SRT 내보내기 검증.
- `tests/test_search.py`: 검색 범위, 부분 일치, 갱신·재실행, 장면 재생과 이어보기 규칙을 코어 공개 API로 검증.

시청 기본값은 `AppCore(viewing_settings=ViewingSettings(...))`로 주입합니다.
`finished_ratio`, `abandoned_ratio`, `favorite_count`, `resume_rewind`, `save_interval`을 바꿀 수 있으며
설정 화면은 후속 범위입니다. 재생 어댑터는 mpv의 `time-pos`를 보고하고 `seek`부터
`playback-restart`까지는 구간을 연결하지 않습니다. 화면은 이 보고를 UI 스레드에서
`core.playback.report(position, seeked=...)`로 전달합니다.
`core.playback.start(video_id, position, record_viewing=False)`로 시작하면 시청 기록이 생기지 않아
후속 하이라이트 모아보기에서도 같은 재생 연결을 사용할 수 있습니다.

태그 공개 API는 `AppCore.tags(prefix="")`, `create_tag(name)`, `rename_tag(tag_id, name)`,
`delete_tag(tag_id)`입니다. `add_video_tag(video_id, name)`과 `add_highlight_tag(highlight_id, name)`은
이름으로 기존 태그를 재사용하거나 만들고 연결합니다. `video_tags(video_id)`·`highlight_tags(highlight_id)`로
붙은 태그를 읽고 `remove_video_tag(video_id, tag_id)`·`remove_highlight_tag(highlight_id, tag_id)`로 뗍니다.
후속 기능은 `videos_for_tag(tag_id)`와 `highlights_for_tag(tag_id)`로 대상 객체를 조회할 수 있습니다.
태그별 영상은 제목·ID 순, 하이라이트는 영상 ID·시작 시각·ID 순입니다.

```powershell
.venv/Scripts/python -m pytest -n auto -q
```

영상 지문은 `v1:파일크기:SHA256`입니다. 앞·중앙·뒤에서 각각 최대 64 KiB를 읽습니다.
동일 내용의 복사본은 하나의 영상과 여러 위치로 저장됩니다. 전체 파일 해시가 아니므로
같은 크기이고 샘플 부분이 같은 파일은 구별하지 못할 수 있습니다(ADR-0002의 절충).
제목은 최초 등록 위치의 확장자를 제외한 파일 이름입니다.
파일 확장자에 제한을 두지 않고 ffprobe가 실제 영상 스트림과 양수 길이를 확인합니다.
GIF·정지 이미지 형식과 단일 프레임, 첨부 그림은 새 영상으로 등록하지 않습니다.
새 영상에는 최소 길이 필터를 적용합니다. 경로·파일 크기·나노초 수정 시각이 그대로인
등록 위치는 미디어 정보와 지문을 다시 읽지 않으며, 비영상 파일도 ffprobe로 다시 읽지 않습니다.
크기나 수정 시각이 달라지면 재판정합니다. 크기와 수정 시각까지 강제로 동일하게 유지한 변경은 감지하지 못합니다.
검사를 마치면 이번 감시 폴더 범위에서 사라진 경로의 비영상·짧은 파일 캐시를 정리합니다.
검사 범위 밖과 접근 오류로 확인하지 못한 폴더의 캐시는 유지합니다.
손상된 영상이나 썸네일 생성 실패는 검사 결과에 알리고 나머지는 계속 등록합니다.
디렉터리 열거 오류도 검사 결과로 알리며 다른 폴더는 계속 검사합니다.
정션·심볼릭 링크 등 재분석 지점은 건너뛰고 이미 검사한 실제 디렉터리는 다시 들어가지 않습니다.

실시간 파일 감시는 제공하지 않으므로 파일을 옮기거나 드라이브를 연결한 뒤 **다시 검사**를 누릅니다.
코어의 `AppCore.scan(folders=[Path(...)])`은 지정한 감시 폴더 또는 그 하위 폴더만 재귀 검사합니다.
`folders`에는 `watched_folders()`가 돌려준 경로 아래 폴더의 `Path` 목록을 넘깁니다. 밖이거나
감시 해제된 경로는 건너뛰고 로그만 남기며, 경로 하나(문자열·`PathLike`)를 그대로 넘기면 `TypeError`입니다.
같은 폴더를 다른 표기(subst 드라이브 등)로 넘겨도 실제 경로로 해석해 범위 안으로 판정합니다.
새 영상 등록·빠른 경로·지문 기준 연결·자동 자막 규칙과 `ScanResult`는 전체 검사와 같습니다.
위치의 파일 없음 처리, 오래된 검사 캐시 정리, 외부 자막 갱신은 지정 범위에만 적용합니다.
감시 폴더 밖(감시 해제된 폴더 포함)과 정션·심볼릭 링크를 거치는 입력은 로그를 남기고 건너뜁니다.
빈 목록이나 유효한 경로가 없는 목록은 빈 결과를 반환하며, 중복·상하위 경로는 한 번만 순회합니다.
이동한 영상은 새 위치에서 기존 지문에 연결하고, 검사 범위 밖의 옛 위치는 다음 해당 폴더 검사나
전체 검사 때 정리합니다. `reconnected` 안내는 검사 시작 때 이미 파일 없음이던 영상에만 적용됩니다.
인자 없는 `scan()`은 감시 폴더 전체와 직접 추가한 위치를 지금처럼 검사합니다.
전체/지정 폴더 검사는 자동 자막 규칙 조회부터 후처리까지 앱 코어의 잠금으로 직렬 실행합니다.
기존 DB는 최초 실행 때 라이브러리 테이블을 v4로 이전합니다(`PRAGMA user_version = 4`).
영상 ID와 다른 기능 테이블은 그대로 유지하며, 이전 위치는 첫 검사에서 캐시 정보를 채웁니다.
이전 직전에는 원래 버전 DB의 자동 백업을 남깁니다. v3은 가로·세로 및 해상도 확인 상태 열을,
v4는 번역 작업의 용어집과 최근 사용 순서를 저장하는 테이블을 추가합니다.
새 등록과 파일 변경 검사 때 ffprobe의 첫 일반 영상 스트림 크기를 저장하며 display matrix와
구형 rotate 태그의 90/270도 회전을 반영합니다. 해상도 미확인 기존 영상은 유휴 시간에
한 번에 한 개씩 약 1초 간격으로 읽습니다. 재생·받아쓰기·검사가 시작되면 채우기를 취소하고,
종료·재시작 후 미처리 항목부터 이어갑니다. 파일 없음·실패 항목은 알 수 없음으로 남기며
**다시 검사** 또는 파일 다시 연결로 재시도합니다. 실패한 항목을 시작할 때마다 반복하지 않습니다.
통계의 라이브러리 구성은 짧은 변 기준 SD(<720), 720p, 1080p, 1440p, 4K 이상(≥2160),
알 수 없음 분포를 표시합니다. 각 구간의 최소값을 넘으면 해당 구간에 포함합니다.
검수 기록과 구간 요청은 별도 테이블을 쓰며 기존 테이블 구조·DB 버전은 바꾸지 않습니다.


## 직접 확인할 항목

자동 테스트는 실제 mpv 화면을 포함하지 않습니다. 변경 후 아래를 실제 창에서 확인합니다.

- 한글·공백이 있는 감시 폴더와 하위 폴더를 추가해 썸네일과 제목이 표시되는지.
- MKV/HEVC 영상 및 AC3·DTS 음성이 창 안에서 영상·소리와 함께 재생되는지.
- 마우스 더블클릭과 방향키 + Enter로 영상을 열 수 있는지.
- 재생 중 표의 모든 키, Esc로 목록 복귀, 다른 앱에 포커스를 옮긴 뒤 키 입력이 이 앱을 조작하지 않는지.
- 종료·재실행 후 라이브러리와 감시 폴더가 유지되는지.
- 감시 폴더 해제·직접 추가·파일 다시 연결·제외와 복원·제목 변경·최소 길이 설정이 다음 실행에도 유지되는지.
- 테스트 파일을 이름 변경·이동하거나 치운 뒤 검사하면 같은 영상으로 연결되거나 파일 없음으로 표시되는지.
- Insert/Delete 표시가 진행 막대와 목록에 반영되고 Home/End로 이동하는지.
- 열린 구간에서 Esc·창 닫기를 실행한 뒤 다시 열면 마지막 위치까지 저장되어 있는지.
- 하이라이트 목록에서 한글 메모, 시각 편집, 삭제와 재실행 후 보존을 확인하고 편집 중 Delete/Home/End가 글 편집에만 쓰이는지.
- 영상과 하이라이트의 태그 입력에서 자동 완성, Enter 추가, Tab 이동·Space 버튼 조작과 태그 떼기가 동작하는지.
- 전체 태그 이름 변경·삭제가 양쪽에 반영되고, 태그 필터와 재실행 후 저장이 유지되는지.
- 실제로 5% 이상 본 뒤 목록의 보다 만 표시와 3초 전 이어보기, 다 본 뒤 처음부터 재생되는지.
- 앞으로 건너뛰기·되감기·배속·일시정지를 섞어도 시청 비율과 마지막 정지 위치가 구별되는지.
- 테스트용 데이터로 재생 중 강제 종료한 뒤 마지막 저장분과 이어볼 위치가 복구되는지.
- 영상에서 자막 요청 → 재생 중 처리 완료 → `/` 표시 전환 → 원어 지정 후 다시 생성되는지.
- 번역 전 `.` 안내, 번역 완료 후 `.` 원어/한국어 전환과 `/` 표시 전환이 각각 동작하는지.
- 번역 CLI 선택을 바꾼 뒤 재시작해도 유지되고, 실패·보류 재시도가 저장한 묶음부터 이어지는지.
- 긴 실제 영상과 평소 배속에서도 GPU 받아쓰기를 함께 켰을 때 재생이 매끄러운지.

- 번호 붙은 영상의 시리즈 표시와 편집 저장·재검사, 새 화 추가 후 순서를 확인하는지.
- PgUp/PgDn으로 시리즈와 일반 목록을 이동하고 경계에서 유지되며 이어보기·열린 구간 종료가 적용되는지.
- 모아보기 태그 필터와 Home/End 항목 이동, 같은 영상의 자동 전환·반복이 깜박임 없이 이어지는지.
- 지점 길이·구간 끝·영상 EOF(마지막 10초 안의 지점 포함)에서 다음 항목·영상으로 자동 전환되는지(webm·DTS mkv 포함).
- PgDn은 다음 영상의 첫 하이라이트, PgUp은 현재 영상의 첫 하이라이트로 이동하고 이미 첫 항목이면 이전 영상으로 이동하는지.
- 한국어 자판의 `₩`(백슬래시) 키로 반복을 켜고 끌 수 있고 상태 표시가 바뀌며, 끄거나 모아보기를 나갈 때까지 유지되는지.
- 항목 전환에도 배속·자막 표시가 유지되고, 원어/번역 선택은 같은 영상에서 유지되며 다른 영상은 원어부터 시작하는지.
- 모아보기 중 Enter·방향키·쉼표·슬래시가 동작하고, Insert/Delete로 만든 하이라이트가 목록 갱신 뒤 나타나며 열린 구간은 전환 때 닫히는지.
- Esc가 재생 → 모아보기 목록 → 라이브러리 순서로 돌아가고, 3초 재생 또는 짧은 항목 완주 뒤 마지막 복습 시각만 갱신되며 다 봄·보다 만·이어볼 위치는 그대로인지.
- 제외한 영상의 하이라이트는 숨겨지고 되돌리면 다시 나타나며, 일반 재생의 Home/End·PgUp/PgDn 동작은 유지되는지.

ffmpeg/ffprobe를 찾지 못하면 설치 후 새 터미널을 열거나 PATH를 확인하세요.
앱은 winget 기본 설치 경로도 탐색하므로 설치 직후 기존 터미널에서도 실행할 수 있습니다.
`libmpv-2.dll` 오류는 `scripts/install_libmpv.py`를 다시 실행하고 Python과 DLL이 모두 x64인지 확인하세요.

