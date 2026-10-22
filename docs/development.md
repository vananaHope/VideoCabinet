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

웹 데이터 계약은 `web_library_data.py`, 슬롯·신호·작업 계약은 페이지별 `web_<name>_contract.py`, 탭은 `web_tabs.py`가 원본이며 `web_contract.py`가 이를 `CONTRACTS`로 조립합니다.
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
검색 조건의 태그 영역은 공용 `components/tag-picker.tsx`(여러 개 고름·즉시 실행, 뺄 태그 ID)이며
태그 목록은 `AppCore.tag_usage()`가 붙은 영상 수 순서와 검색용 정규화 이름(`key`)을 함께 보냅니다.
입력한 질의의 key는 `lib/tag-name-key.ts`가 동기로 만듭니다. 이 함수는 `generate_web_types.py`가 코어 `tags.tag_name_key_tables()`에서
생성한 `lib/tag-name-key-data.ts`(Python Unicode 버전의 할당 범위·제거 문자·공백·casefold 표)만 적용하며,
검사 스크립트가 전체 코드 포인트와 문맥에서 코어 `tag_name_key`와 같은지 비교합니다. 규칙을 바꿀 때는 `tags.py`를 고치고 다시 생성합니다.
즉시 실행·뺄 태그는 태그 편집 대화상자가 씁니다. 대화상자 데이터(`DialogData.tags`)에 같은 `tag_usage()` 목록을 싣고
붙은 태그(`rows`)를 뺄 태그로 넘기며, `listAll`로 전체 목록을 늘 펼치고 `onCreate`로 없는 이름을 새 태그로 붙입니다.
대화상자의 Esc는 `tagPickerKeepsEscape`로 조각이 먼저 처리할 Esc를 넘겨받지 않습니다. 조각 단독 동작은 `frontend/checks/tag-picker-fixture.tsx` 검사 번들로도 확인합니다.
`scripts/check_web_tag_picker.py --offscreen`은 `.local/screens-195/`에 태그 0개·몇 개·300개·검색·모두 보기·
고른 태그 40개 화면과 패널 배치 측정을 남기고, `--verify`는 데스크톱 잠금 안의 실창에서
키보드만으로 검색 → 고르기 → 칩 빼기와 실제 한국어 IME 조합 중 Enter 무시를 확인합니다.
`scripts/check_web_tag_dialog.py --offscreen`은 `.local/screens-191/`에 태그 편집 대화상자의 등록 태그 0개·모두 붙음·몇 개·300개·긴 이름
화면과 배치 측정, 붙이기·새 태그·조합 중 Enter·Esc 순서를 확인하고, `--verify`는 데스크톱 잠금 안의 실창에서 키보드만으로
고르기·새 태그 만들기·Esc 순서와 실제 한국어 IME 조합 중 Enter 무시를 확인합니다.
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
`release.ps1`은 전체 빌드 후 이전 Release와 지문을 비교하고, 같을 때만
`-SkipPyInstaller -PatchOnly`로 이미 검증한 번들의 패치를 추가 압축합니다.
`-PatchOnly`는 전체 설치 파일과 웹/PyInstaller 빌드를 반복하지 않으며 `-SkipPyInstaller`가 필수입니다.

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

소스 저장소(`origin`, `vananaHope/my-video-manager`)는 비공개이므로 토큰 없이 요청하는 앱은 그 Release를 볼 수 없습니다.
그래서 설치 파일·체크섬·매니페스트·서명은 공개 **배포 저장소** `vananaHope/my-video-manager-releases`에만 발행합니다.
`origin`에는 지금처럼 버전 커밋과 `v<version>` 태그만 push하고, 이전 Release 조회·같은 태그의 Release 확인·
`gh release create`·실패 시 안내 명령은 모두 배포 저장소를 씁니다. 배포 저장소 이름은 앱의
`src/my_video_manager/app_version.py`의 `RELEASE_REPOSITORY`와 `release.ps1`의 `-ReleaseRepository` 기본값에 있으며
테스트가 두 값이 같은지 검사합니다. 배포 저장소에 이전 Release가 없으면 첫 릴리스(전체 설치만)로 처리하며,
소스 저장소에 남은 옛 Release(v0.5.0·v0.5.1)는 조회하지 않습니다.

첫 서명 릴리스는 다음 순서로 준비합니다.

1. 아래 키 생성 도구로 기본 경로 `%APPDATA%\my-video-manager\release-keys\update-ed25519.pem`에 키를 생성하고 ACL을 확인한 뒤 안전하게 백업합니다.
2. 공개 키를 `src/my_video_manager/update_manifest.py`의 `UPDATE_PUBLIC_KEY`에 반영하고 커밋합니다.
3. `release.ps1 -Version <다음 버전> -DryRun -Build`로 실제 번들과 발행 계획을 확인합니다.
4. 실제 발행에서 전체 설치만 올라가는지, 노트에 전체 설치가 한 번 필요하다는 문구가 있는지 확인합니다.
5. 다음 릴리스부터 이전 매니페스트 서명이 검증되고 런타임 지문이 같으면 패치를 발행할 수 있습니다.

```powershell
# 검사와 계획 출력만: 버전·커밋·태그·원격·원격 추적 ref를 바꾸지 않음
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.4.2 -DryRun
# 위 동작에 빌드 추가: pyproject.toml 수정 없이 -Version을 build.ps1에 전달
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.4.2 -DryRun -Build
# 실제 릴리스
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.4.2
```

실제 실행은 먼저 개인 키를 읽고 앱에 내장된 공개 키와 일치하는지 검사합니다.
키가 없거나 공개 키가 자리 표시 값이거나 키가 다르면 버전 커밋·빌드 전에 멈춥니다.
기본 키 경로는 아래 "사람이 한 번 준비할 키"와 같으며 `-PrivateKey <경로>`로 바꿀 수 있습니다.
암호는 `MVM_UPDATE_SIGNING_PASSWORD` 환경 변수 → 대화형 터미널에서만 질문 순서이며,
대화형 입력은 실행당 한 번입니다. 암호는 메모리에 보관하고 키 검사·서명 하위 프로세스의
환경 변수로만 잠시 전달하며 명령줄·로그에 넣지 않습니다. 빌드·Git·gh에는 전달하지 않고,
성공·실패 시 환경 변수를 지웁니다(호출한 PowerShell 프로세스에 설정한 값도 제거).
서명 시에도 동일 키 검사를 다시 합니다.

이전 메타데이터는 배포 저장소의 `releases/latest`가 가리키는 정식(비 draft·비 prerelease)
Release에서 읽습니다. 태그는 `vX.Y.Z`여야 하며 새 버전 이상이면 발행을 중단합니다.
매니페스트와 `.sig`가 함께 있으면 앱 내장 공개 키로 정확한 바이트를 검증한 후 읽습니다.
서명 없는 이전 매니페스트는 지문을 신뢰하지 않고 "패치 불가(이전 매니페스트 서명 없음)"으로 전체 설치만 발행합니다.
서명·형식·태그와 매니페스트 버전 일치 검증이 실패하면 이전 지문을 신뢰하지 않고
"패치 불가(이전 매니페스트 검증 실패)" 이유와 함께 전체 설치만 발행합니다.
접근 거부·네트워크·다운로드 실패는 메타데이터 부재로 간주하지 않고 중단합니다.

이후 `pyproject.toml` 버전을 올려 한국어로 커밋하고 전체 설치 파일을 빌드합니다.
새 번들의 실제 런타임 지문을 검사해 이전 지문과 같을 때만 패치를 만들고,
설치 파일 체크섬·`update-manifest.json`·Ed25519 서명을 생성합니다.
이전 Release나 매니페스트가 없으면 첫 릴리스로 취급해 `patch = null`입니다.
런타임 지문이 달라져도 패치를 만들거나 업로드하지 않습니다(남아 있는 옛 패치 파일도 제외).
전체 설치만 가능한 경우 노트에 "이번 버전은 전체 설치 파일로 한 번 설치해야 합니다"를 넣습니다.
특히 v0.4.1 이전 설치본에는 지문 파일이 없으므로 전체 설치를 한 번 거쳐야 합니다.
#140에서 `cryptography`를 번들에 포함하는 변경도 실제 지문 비교가 자동으로 감지합니다.

모든 파일 생성·서명이 성공하면 `v<version>` 태그와 main을 `origin`에 atomic push하고,
배포 저장소에는 그 태그가 없으므로 `gh release create --target main`으로 배포 저장소 기본 브랜치에 같은 이름의 태그를 만들며
전체 설치 파일·체크섬·매니페스트·서명과 해당하는 패치를 게시합니다.
노트는 현재 main에 포함된 가장 높은 버전 태그 이후의 커밋 제목입니다(태그가 없으면 전체).
설치 파일은 `dist/installer/MyVideoManager-Setup-<version>.exe`, 체크섬은 그 옆의 `.exe.sha256`입니다.
패치는 `dist/installer/MyVideoManager-Patch-<version>.exe`, 메타데이터는
`dist/installer/<version>/update-manifest.json`과 `update-manifest.json.sig`에 보존합니다.
GitHub Release 자산 이름에는 버전 하위 폴더가 붙지 않습니다. 기존 메타데이터가 있으면
덮어쓰지 않고 중단하므로 실패 후 재시도 전 해당 버전 파일을 확인·보관하세요.
기존 태그·Release를 덮어쓰거나 강제 push하지 않습니다.
빌드 실패나 원격에서 거부한 push는 로컬 버전 커밋과 이번에 만든 태그를 자동 복구합니다.
다른 파일 변경이나 불확실한 원격 상태가 있으면 보존하고 복구 명령을 안내합니다.
push 뒤 Release 생성이 실패하면 `origin`의 main과 태그를 유지하며 배포 저장소 기준의 Release 확인·생성·자산 추가 명령을 안내합니다.
안내된 `gh release upload` 목록에는 매니페스트·서명과 해당하는 패치도 포함됩니다.
이미 올라간 자산은 그대로 두고 목록에서 **누락된 파일만 골라** 업로드합니다(`--clobber` 사용 안 함).
자동 재발행하지 않으므로 안내에 따라 상태를 확인하세요.
Ctrl+C로 빌드를 중단하면 PowerShell이 실패 복구 catch를 건너뛸 수 있습니다.
`git status`와 `git log --oneline`으로 확인하고, 보존할 작업을 저장한 뒤 이번 버전 커밋만
`git revert <버전 커밋>`으로 되돌리세요. 다른 작업 이후의 HEAD를 시작 커밋으로 reset하지 마세요.
`-DryRun -Build`의 빌드 산출물은 Git에서 제외된 폴더에 남으며 tracked 파일과 커밋은 그대로입니다.
`-DryRun`은 개인 키를 읽거나 암호를 묻지 않고 "실제 발행 시 서명 키 필요"를 표시합니다.
이전 지문·새 지문·판정 근거·생성 및 업로드할 자산을 출력하며, 빌드 없이 읽은 기존 번들의
판정은 다음 실제 빌드에서 다시 확인합니다. 번들 폴더가 없으면 새 지문은 "미정"입니다.
이전 Release나 매니페스트가 없으면 "첫 릴리스: 패치 없음, 전체 설치만"으로 확정하며,
서명 없음·검증 실패도 패치를 제외합니다. 신뢰할 이전 지문이 있을 때만 패치 여부를 "미정"으로
표시하고 `-DryRun -Build`를 안내합니다. 폴더가 있는데 지문이 없거나 손상되었으면 중단합니다.
`-DryRun -Build`는 전체 설치와 조건에 맞는 패치까지 만들지만 매니페스트·서명·체크섬은
실제 발행 단계에서 생성합니다. 두 DryRun 모두 버전·커밋·태그·원격을 변경하지 않습니다.


## 업데이트 매니페스트와 서명 키 (#138)

`scripts/generate_update_key.py`와 `scripts/generate_update_manifest.py`는 로컬에서
키·매니페스트·서명을 만드는 독립 도구입니다. `release.ps1`은 이 도구의 키·서명 검사를
재사용하고 `release_metadata.py`를 통해 이전 Release 조회·패치 판정·발행 자산 생성을 연결합니다.
앱 안 업데이트 확인·다운로드는 별도 작업입니다.
런타임 검증 의존성은 `cryptography==50.0.2`로 고정합니다.

### 사람이 한 번 준비할 키

**실제 릴리스 키는 사람이 생성·보관하고 공개 키만 코드에 반영합니다.** 현재
`src/my_video_manager/update_manifest.py`의 `UPDATE_PUBLIC_KEY = b''`는 의도적으로
검증을 항상 실패시키는 자리 표시 값입니다. 키 생성 도구는 교체할 상수 선언을 출력하며
소스는 직접 수정하지 않습니다. 개인 키나 암호를 코드·Git·로그·이슈에 붙여 넣지 마세요.

기본 개인 키 경로는 `%APPDATA%\my-video-manager\release-keys\update-ed25519.pem`이며,
`APPDATA`가 없으면 `~/.config/my-video-manager/release-keys/update-ed25519.pem`입니다.
`--private-key <경로>`로 바꿀 수 있지만 저장소·worktree 안 경로와 UNC·매핑된 네트워크 드라이브는 거부합니다.
심볼릭 링크·정션을 해석한 실제 경로와 입력 경로를 모두 검사하며 기존 키는 덮어쓰지 않습니다.
사용자만 접근할 수 있는 로컬 폴더를 선택하고 별도의 안전한 백업을 유지하세요.
Windows에서는 이번 실행이 새로 만든 키 전용 폴더에만 ACL 상속을 끊고 현재 사용자와
SYSTEM이 모든 권한을 갖도록 설정합니다. 재귀 옵션은 사용하지 않으며 Administrators는 허용하지 않습니다.
기존 폴더와 하위 항목의 ACL은 변경하지 않고 폴더·키 파일의 ACL을 검사합니다.
검사에 실패하면 암호 없는 키는 오류로 끝나고 암호화 키는 경고 후 진행하며,
완성된 키는 표시된 경로에 보존합니다. 수동 설정 명령을 안내하므로 기존 내용에 미치는
상속 영향을 검토한 뒤 적용하세요. 기본 경로는 키 전용 폴더로 유지합니다.
`os.open(..., 0o600)`은 Windows에서 읽기 전용 비트만 반영하므로 접근 제어를 대신하지 않습니다.

PowerShell에서 직접 확인·설정하려면 다음 명령을 사용합니다(실제 키 전용 경로로 바꾸세요).

```powershell
$keyFolder = Join-Path $env:APPDATA 'my-video-manager/release-keys'
$keyFile = Join-Path $keyFolder 'update-ed25519.pem'
$keyUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $keyFolder
icacls $keyFile
icacls $keyFolder /grant:r "*${keyUserSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' /inheritance:r
icacls $keyFile /grant:r "*${keyUserSid}:F" '*S-1-5-18:F' /inheritance:r
# 현재 사용자와 SYSTEM 외 주체의 명시적 권한이 남으면 해당 SID마다 실행합니다.
# icacls $keyFolder /remove '*S-1-5-21-실제SID'
# icacls $keyFile /remove '*S-1-5-21-실제SID'
icacls $keyFolder
icacls $keyFile
```

현재 사용자와 SYSTEM 외 주체가 남지 않았는지 최종 출력을 확인하세요.
서명 도구도 폴더·파일을 검사하며, 다른 주체가 남거나 확인할 수 없으면 경고합니다.
암호 없는 키는 오류로 중단하고 암호화된 키는 경고 후 진행합니다.
`--no-password` 키는 같은 PC의 다른 계정(작업자 샌드박스 포함)이 읽을 수 있으면 키가 노출됩니다.

```powershell
# 기본: 암호화 PKCS8 PEM. 터미널에서 암호와 확인 암호를 숨겨 입력합니다.
.venv/Scripts/python.exe scripts/generate_update_key.py

# 선택: 암호 없는 PKCS8 PEM. 파일 접근 권한·백업 보호에 전적으로 의존합니다.
.venv/Scripts/python.exe scripts/generate_update_key.py --no-password
```

두 명령 중 하나만 실행합니다. 출력의 `UPDATE_PUBLIC_KEY = bytes.fromhex('...')` 선언을
앱 코드의 자리 표시 값과 교체하고, 공개 키 변경을 검토·커밋한 뒤 앱을 빌드합니다.
기존 키를 잃거나 바꾸면 기존 공개 키로 새 서명을 검증할 수 없으므로 임의로 재생성하지 마세요.
공개 키를 반영한 앱으로 테스트용 매니페스트를 검증한 뒤 실제 발행에 사용합니다.

암호화 키는 파일만 유출돼도 암호가 추가로 필요하지만 자동화에서 암호를 공급해야 합니다.
생성·서명 도구는 `MVM_UPDATE_SIGNING_PASSWORD` 환경 변수를 먼저 읽고, 값이 없으면
대화형 터미널에서만 암호를 묻습니다. 비대화형에서는 환경 변수가 없다는 오류로 멈춥니다.
관리자 에이전트가 비대화형 PowerShell로 릴리스할 때는 비밀 저장소에서 이 프로세스의 환경에
암호를 주입하거나, 사람이 선택한 `--no-password` 키를 사용하세요. 암호를 명령행 인수나
저장소의 `.env` 파일에 넣지 않습니다. 도구는 암호나 개인 키 내용을 출력하지 않습니다.

### 매니페스트 만들기

전체·패치 설치 파일과 빌드가 만든 `runtime-fingerprint.json`을 입력합니다.
이전 릴리스의 지문은 그 릴리스의 보관된 빌드 산출물을 사용하며 현재 환경에서 재계산하지 않습니다.

```powershell
# 최초 릴리스: 이전 지문·패치 인수를 생략합니다.
.venv/Scripts/python.exe scripts/generate_update_manifest.py --version 0.5.0 --runtime-fingerprint dist/my-video-manager/runtime-fingerprint.json --full dist/installer/MyVideoManager-Setup-0.5.0.exe

# 이전 릴리스와 지문이 같은 경우: 패치 파일이 필수입니다.
.venv/Scripts/python.exe scripts/generate_update_manifest.py --version 0.5.1 --runtime-fingerprint dist/my-video-manager/runtime-fingerprint.json --previous-runtime-fingerprint C:/release-archive/0.5.0/runtime-fingerprint.json --full dist/installer/MyVideoManager-Setup-0.5.1.exe --patch dist/installer/MyVideoManager-Patch-0.5.1.exe
```

런타임이 바뀐 경우에는 이전 지문 인수를 주되 `--patch`는 생략합니다.
버전은 릴리스 도구와 같은 `X.Y.Z` 형식이며, 파일은 한 번씩 스트리밍하여 바이트 크기와 SHA-256을 계산합니다.
기본 출력은 `dist/installer/update-manifest.json`과 `update-manifest.json.sig`입니다.
`--output <매니페스트 경로>`를 바꾸면 서명은 그 경로에 `.sig`를 붙입니다.
기존 출력은 덮어쓰지 않으며 쓰기 실패 시 이번 실행이 새로 만든 파일만 정리합니다.
서명 도구는 기본으로 앱 내장 `UPDATE_PUBLIC_KEY`와 서명 키가 일치하는지 확인하고,
앱의 기본 검증 함수로도 서명을 검증합니다. 자리 표시 값이나 다른 공개 키이면 출력 전에 실패합니다.
일회성 시험 키로만 작업할 때는 `--allow-unpinned-key-for-tests`로 이 검사를 명시적으로
우회할 수 있습니다. 이 옵션은 경고를 출력하며 실제 릴리스 발행에는 사용하지 않습니다.
강제 종료로 파일 하나만 남았으면 그 실행의 산출물을 확인·제거한 뒤 재실행합니다.

schema 1의 필드는 다음과 같습니다. 모르는 필드와 일관되지 않은 조합도 거부합니다.

| 필드 | 의미 |
|---|---|
| `schema_version` | 정수 `1`; 모르는 버전은 거부 |
| `version` | 릴리스 버전 `X.Y.Z` |
| `runtime_fingerprint` | 이번 빌드의 검증된 SHA-256 런타임 지문 |
| `previous_runtime_fingerprint` | 이전 릴리스 지문; 최초 릴리스는 `null` |
| `full` | `filename`, 양의 정수 `size`(바이트), 소문자 64자리 `sha256` |
| `patch` | 같은 구조의 패치 자산; 지문 변경·최초 릴리스는 `null` |
| `patch_available` | 이전 릴리스와 지문이 같으면 `true`이며 이때 `patch` 필수 |

`patch_available`은 이전 릴리스와 비교한 **패치 발행 여부**입니다. 실제 설치 가능 여부는
사용자의 **설치본 지문과 이번 지문이 같은지**로 판단해야 합니다. 두 버전 이상 앞선 설치본도
지문이 같으면 패치를 적용할 수 있으며, 바로 이전 버전이라는 이유만으로 허용하면 안 됩니다.

서명 파일은 base64가 아닌 **64바이트 raw Ed25519 서명**입니다. 서명 대상은 출력 JSON의
정확한 바이트 전체이므로 공백·줄바꿈을 바꾸거나 JSON을 다시 저장하면 검증에 실패합니다.
`verify_manifest(data: bytes, signature: bytes)`는 앱의 공개 키로 **서명 확인 → UTF-8 디코딩 →
JSON 파싱 → schema 검증** 순서로 처리하고 불변 `UpdateManifest`를 반환합니다.
명시적 `public_key=`는 테스트·오프라인 검증 도구용이며 다운로드한 매니페스트의 키를 전달하지 않습니다.

거부 시 `ManifestError.kind`는 `invalid_public_key`, `invalid_signature_format`,
`invalid_signature`, `invalid_json`, `unsupported_schema`, `invalid_format`을 구별합니다.
다른 키의 서명·변조·길이는 맞지만 깨진 서명은 암호학적으로 구별할 수 없으므로 모두
`invalid_signature`입니다. 잘못된 서명 길이는 `invalid_signature_format`입니다.
실패하면 업데이트 확인 호출부는 매니페스트 필드를 사용하지 않아야 합니다.

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

### 재생 조작 줄 검증

재생 화면은 Qt이므로 조작 줄은 웹 검사 대신 아래 검사로 확인합니다.

```powershell
.venv/Scripts/python.exe scripts/check_playback_controls.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_playback_controls.py --real
```

첫 명령은 가짜 플레이어와 코어의 받아쓰기·다듬기 결과로 1100×720 창의 기본 줄이 글자를 줄이지 않고 넘치지 않는지,
가장 넓은 줄(열린 구간 '구간 끝내기'·목록 밖 긴 속도 99.75×·다듬은 자막·자막 꺼짐·일시정지)과 1040 폭의 줄이 `compact_order` 순서(하이라이트·속도 단추 먼저)로만 줄여
넘치지 않는지, 줄인 단추에도 툴팁·접근성 이름이 있는지 확인하고 `.local/playback-controls/`에 위젯 이미지를 남깁니다.
모아보기 중의 가장 넓은 줄(⇤ ⇥ ↻ 반복 켜짐·구간 끝내기·99.75×·다듬은 자막)은 1100 폭에서, 같은 줄에 '모아보기 목록'·'⛶ 전체 화면 끄기'가 더해진 전체 화면 구성은 1100·1280 폭에서(일반 재생 가장 넓은 줄의 전체 화면 구성도 1100에서) 재며,
시간 표시와 단추가 눌려 잘리지 않는지 보고,
상태별 남은 폭을 결과 JSON의 `slack`에, 글자를 더 줄여 확보할 수 있는 폭을 `reducible`에 남깁니다.
뒤 이슈가 조작 줄에 단추(🔀)를 더하면 `compact_order`에 자리를 정하고 이 검사의 가장 넓은 상태에 그 단추를 넣습니다.
두 번째 명령은 합성 영상과 실제 mpv, Windows 마우스·키 입력으로 단추 클릭 뒤 재생 키, Tab 이동과 단추 초점에서의 →·Enter(재생 명령)·Space(단추 누르기),
키 안내 닫기 단추(앱 창 활성 유지), 전체 화면 조작 줄의 '전체 화면 끄기'·'목록으로'를 확인합니다. 실창 스크린샷은 찍지 않습니다.

영상 클릭은 실제 mpv 위에서 따로 확인합니다.

```powershell
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_video_click.py
```

mpv는 `wid`로 넣은 자기 창을 비활성(`WS_DISABLED`)으로 만들어 마우스 입력을 부모인 Qt 영상 표면에 넘깁니다.
그래서 클릭은 mpv 입력 바인딩이 아니라 표면의 Qt 마우스 이벤트로 받고, 한 번/두 번 클릭은 `video_click.py`의 판정기가
Windows 두 번 클릭 판정 시간으로 가릅니다(Windows는 두 번째 누름을 `MouseButtonDblClick`으로만 보냅니다).
메뉴가 열린 채 영상을 누르면 Qt가 메뉴를 닫은 뒤 같은 `timestamp`를 단 누름을 표면에 다시 보내므로(replay), 그 누름은 클릭으로 세지 않습니다.
검사는 창 모드·전체 화면의 한 번/두 번 클릭, 클릭 뒤 재생 키, 전체 화면 커서 이동 → 조작 줄,
키 안내·재생 메뉴·속도 목록이 열린 상태의 클릭, 영상 전환 직후의 클릭, 클릭 직후 긴급 탈출 → 빠른 복원을 확인하고
mpv 영상 창이 비활성인지 단언합니다. 결과는 `.local/video-click/real-result.json`에 남깁니다.
대기 중인 한 번 클릭은 누름을 받은 엔진에 속하며, 창을 숨기거나 최소화하거나 목록으로 돌아가면 버립니다.

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

추천(`Ctrl+2`)은 `web_recommend_page.py`의 웹 페이지이며 `AppCore.recommendations()`의 줄 목록을 보여 줍니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_recommend.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-196 -- .venv/Scripts/python.exe scripts/check_web_recommend.py --verify --no-screenshots
```

첫 명령은 `.local/screens-196/`에 1100×720 화면(추천 0개·이어 보기 한 줄·여덟 줄 × 20개 위/아래·취향 맞춤·관심 없음 안내·우클릭 메뉴·
긴 기준 제목/카드 제목/이유·추천 영역을 뺀 라이브러리)과 배치 측정을 남깁니다. 전용 줄(이어 보기·다음 화·하이라이트 복습)의 우선 배정,
넘친 영상의 일반 줄 배정, 표시 순서, 줄 사이 왕복 키 이동·관심 없음·되돌리기를 확인합니다.
같은 종류의 『제목』을 봤다면 세 줄에서도 각 줄의 선택 기억·탭 재진입·가짜 재생 왕복이 섞이지 않는지 확인합니다.
두 번째 명령은 짧은 검증 영상을 만들어 실창에서 `Ctrl+2`, 실제 mpv 재생 왕복, 긴급 탈출 뒤 트레이 열기,
재생 중 창 닫기 뒤 트레이 열기가 같은 탭·같은 카드로 돌아오는지 확인합니다.

추천 기간은 설정의 '추천' 절(`recommendation-periods.tsx`)에서 바꾸며, 이름·설명·기본값·허용 범위는 `RECOMMENDATION_PERIODS`에서 받습니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_settings_recommend.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-204 -- .venv/Scripts/python.exe scripts/check_web_settings_recommend.py --verify
```

첫 명령은 `.local/screens-204/`에 1100×720 화면(기본값·모두 바꾼 값·여러 칸 오류 위/아래·긴 이름과 설명)과 배치 측정을 남기고,
키보드 입력 + Enter 저장, 기본값 단추, 추천 탭 재진입 반영을 확인합니다. 두 번째 명령은 실창에서 `Ctrl+8` → Tab·Enter로
새로 추가됨 기간을 바꾸고 `Ctrl+2`로 추천 탭에 반영되는지, 기본값 단추로 되돌아오는지 확인합니다.

모아보기(`Ctrl+3`)와 검색(`Ctrl+4`)도 웹 페이지입니다.
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
데스크톱을 쓰는 환경에서는 반드시 `~/.agent-orchestra/bin/desktop_lock.py run`
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

1. 새 `src/my_video_manager/web_search_contract.py`에 불변 `SEARCH = BridgeContract(name='search',
   interface='SearchBridge', slots=..., signals=..., aliases=..., constants=..., data_types=...)`를 선언합니다.
   공통 선언은 `web_contract_types.py`에서 import하고 `web_contract.py`나 다른 계약 파일은 import하지 않아 순환을 만들지 않습니다. 슬롯 인수는 `Argument`,
   문자열 유니온은 `TypeAlias`, 페이지 고유 상수는 `Constant`로 선언하고, 그 페이지만 쓰는 Python 상수와
   데이터 모듈 import도 이 파일에 둡니다. 필요하면 새 데이터 모듈에 TypedDict를 정의하고
   `data_types`에 넣습니다. 공용 TypedDict는 소유 계약에 한 번만 등록합니다.
   조립 지점 `web_contract.py`에는 `from .web_search_contract import SEARCH` 한 줄과
   `CONTRACTS`의 `SEARCH,` 한 줄만 추가합니다.
2. 새 `src/my_video_manager/web_search_page.py`에 QObject 브리지와 `WebPageController`를 구현합니다
   (브리지가 커지면 `web_search_bridge.py`로 분리). 계약은 `web_search_contract.py`에서 import하고
   `@SEARCH.slot('find')`,
   `SEARCH.signal('resultsChanged')`처럼 계약으로 Qt 표면을 선언합니다.
   컨트롤러의 `tab = 'search'`, `bridge`, `refresh()`를 구현하고 초기화 마지막에
   `host.register_page(self)`를 호출합니다. 필요하면 기본 빈 함수인 `activated()`와 `deactivated()`를
   구현합니다. 호스트는 탭 이동, 재생 왕복, 호스트 표시·숨김 때 활성 컨트롤러를 바꾸며,
   이전 컨트롤러의 `deactivated()` 뒤 새 컨트롤러의 `activated()`를 호출합니다.
   `activated()`는 가볍게 유지하고, 무거운 계산은 지연하거나 취소할 수 있게 합니다(트레이 복원 때 잠깐 다른 탭이 활성화될 수 있습니다).
   재생에서 복귀할 때는 시청 종료 후 `activated()`가 호출되므로 통계 등을 다시 계산할 수 있습니다.
   활성 상태는 `is_active()`로 확인합니다. QWidget의 `isVisible()`은 자체 화면 표시 여부입니다.
   복귀 시 기본 `return_from_playback()`은 `refresh()`와 포커스 복원을 수행하며,
   라이브러리는 이를 재정의해 `refresh(focus=True)`로 격자 초점을 요청합니다.
   재생 중 창을 닫았다가 트레이로 열 때 라이브러리 대신 출발한 탭으로 돌아와야 하면
   컨트롤러에 `keeps_tab_after_close = True`를 둡니다(추천 탭).
   자체 포커스가 필요하면 `default_focus`와
   `focus_requested` 신호를 지정하고, 웹 첫 렌더 후 호출하는 `ready` 슬롯에서
   `self.page.frontend_ready()`를 호출합니다. 포커스 요청은 호스트가 준비될 때까지 보존합니다.
3. `web_page_registry.py`에 컨트롤러를 import하고 `WEB_PAGES`에 한 줄 등록합니다.
   새 탭이면 `web_tabs.py`의 `TABS`에도 `('search', '검색'),` 한 줄을 추가합니다. 모든 탭은 웹 컨트롤러로 등록합니다.
4. 새 `frontend/src/pages/SearchPage.tsx`를 작성합니다. `connectBridge()`에서
   `{ search, shell }`을 받아 생성된 공개 메서드만 사용하고, 효과를 정리할 때 신호 구독을 해제합니다.
   페이지 사이 브리지 호출은 공통 `shell` 외에는 하지 않습니다.
   페이지는 숨겨져도 마운트를 유지하므로 선택·검색어·스크롤을 보존할 수 있습니다.
   `pages/index.ts`에 컴포넌트 import와 `search: SearchPage` 한 줄을 추가합니다. 웹 페이지만 등록하고 `null` 항목은 두지 않습니다.
   키 안내 '지금 화면'에 보일 이 페이지만의 키는 페이지 파일에 `export const keyGuide: readonly KeyGuideGroup[]`(`@/lib/key-guide`, 키가 없으면 `[]`)로 두고, `pages/index.ts`에 `import { keyGuide as searchKeys } from "./SearchPage"`와 `pageKeyGuides`의 `search: searchKeys,`를 한 줄씩 추가합니다(빠지면 typecheck가 실패합니다). 키 배치로 바꿀 수 있는 키는 여기에 글자로 쓰지 않고 `key_guide.py`가 지금 키 배치에서 읽어 넘깁니다.
5. `.venv/Scripts/python scripts/generate_web_types.py`로 재생성한 뒤 `--check`, 전체 pytest,
   `frontend/`의 `npm run lint`, `npm run typecheck`, `npm run build`를 실행합니다.
   `scripts/check_web_library.py`로 1100×720 화면·단축키·Qt/mpv 왕복도 확인합니다.
   스크린샷은 `--offscreen`으로 찍고, 실창 입력 검사는 `--no-screenshots`로 캡처 없이 실행할 수 있습니다.

호스트·생성기·`App.tsx`·`bridge.ts`·`ui.py`는 새 페이지 때문에 고칠 필요가 없습니다.
채널 이름은 `TABS`의 `library`, `recommend`, `reel`, `search`, `queue`, `statistics`, `folders`, `settings`와 같고,
공통 객체만 `shell`입니다. 통계 페이지도 같은 등록부를 사용합니다.
`tests/test_web_generator.py`는 예시 계약을 앞·중간·뒤에 추가해도 기존 페이지 출력이 그대로인지,
`tests/test_web_pages.py`는 새 컨트롤러의 브리지·갱신·포커스 연결과 양쪽 등록부 일치를 확인합니다.
탭 누락·중복은 Qt 시작 또는 테스트에서 실패합니다. 웹 등록부 오타는 typecheck가, Python 등록부와의 누락·불일치는 계약 테스트가 검출합니다.
추가만 하는 네 파일, 곧 Python·웹 페이지 등록부(`web_page_registry.py`, `pages/index.ts`)와
계약 조립 지점(`web_contract.py`)·탭 목록(`web_tabs.py`)에는 `.gitattributes`의 `merge=union`을 적용해
양쪽 추가 줄을 합칩니다. `tests/test_web_contract_registry.py`가 임시 저장소에서 두 브랜치의 새 계약을 병합해 이를 확인합니다.
union 병합은 충돌 없이 양쪽 줄을 모두 남기므로 이 네 파일에서는 등록 항목을 한 줄에 하나만 두고,
dict처럼 중복 키가 조용히 덮어써지거나 여러 줄 항목이 섞일 수 있는 구조를 두지 않습니다.
union은 서로 다른 항목을 추가할 때 쓰는 규칙입니다.
두 브랜치가 같은 기존 줄을 고치거나 한쪽이 기존 줄을 지우거나 순서를 바꾸면 Git이 충돌 표시 없이 양쪽 줄을 남겨 삭제가 되살아나거나 중복이 생길 수 있으므로, 병합 뒤 해당 파일의 최종 목록을 직접 확인해 하나로 정리하고 생성기·관련 테스트를 다시 실행합니다.
새 항목끼리의 순서는 병합 순서에 따라 정해지므로 탭 순서(`Ctrl+숫자` 단축키)가 중요하면 병합 뒤 확인합니다.
페이지별 계약 파일(`web_<name>_contract.py`)은 일반 병합을 유지합니다. 서로 다른 페이지 작업은 다른 파일을 고치므로
충돌하지 않고, 같은 계약의 슬롯·신호·상수를 양쪽에서 수정했다면 내용을 검토해 하나로 결정합니다.
생성 파일 충돌은 원본 계약을 합친 뒤 생성기로 다시 만듭니다.
공용 JSON 직렬화는 `web_json.py`, 셸 데이터는 `web_shell_data.py`가 소유합니다.
생성 파일은 직접 수정하지 않습니다. 페이지 객체로 나뉘어 `library` 신호 접두어는 기술적으로
필수가 아니지만 기존 호출부와 병렬 작업의 호환성을 위해 유지합니다.

### 날짜 표시 (#232)

화면의 날짜 모양은 `frontend/src/lib/dates.ts` 한 곳에서만 만듭니다. 날짜 `2026. 10. 21.`, 날짜와 시각
`2026. 10. 21. 15:04`(24시간제), 차트 축 같은 짧은 날짜 `10. 21.`이며 컴퓨터 시간대를 따릅니다.
날짜만 있는 값(`2026-10-21`)은 시간대와 상관없이 그 달력 날짜로 보입니다. 브리지는 화면에 보일 날짜를
ISO 문자열(필터 칩은 `range` 구조)로 넘기고 Python에서 표시용 날짜 문자열을 만들지 않습니다.
시각만 보이는 곳(자동 재시도 `15:04`)과 파일 이름은 예외입니다.
웹 셸은 웹 엔진보다 먼저 `QLocale`을 한국어로 고정하므로 Windows 표시 언어가 영어여도 날짜 입력 칸이
연·월·일 순서입니다. 구분 기호는 Windows의 한국어 간단한 날짜 형식(예: `yyyy-MM-dd`)을 따릅니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_dates.py --offscreen
.venv/Scripts/python.exe scripts/check_web_dates.py --offscreen --videos 0
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-232 -- .venv/Scripts/python.exe scripts/check_web_dates.py --verify
```

영어(미국) `QLocale`에서 시작해 `.local/screens-232/`에 1100×720 화면(카드·상세·필터 칩과 날짜 입력 칸·모아보기·
통계 30일/365일·축 눈금·툴팁·설정의 백업·업데이트·번역 정책 만료 전/뒤)을 남기고, 보이는 글자에 ISO 날짜·`월/일/연`·
`오전/오후` 모양이 없는지 봅니다. `--verify`는 실창에서 날짜 입력 칸에 연·월·일 순서로 타자해 값이 그대로 들어가는지 확인합니다.
번역 정책은 기본 모델 만료일의 전날·다음 날로 찍으므로 검사 날짜와 상관없고, `--now 2026-11-01T03:00:00+00:00`처럼 검사 시각을 정할 수도 있습니다.

### 웹 대화상자 (#53)

태그 편집·모든 태그 관리, 시리즈, 하이라이트 목록·편집,
자막 만들기·원어 지정, 자막 검수·구간 재생성·SRT 저장, 번역 CLI 선택을 웹으로 엽니다.
`web_dialogs_entries.py`의 진입 어댑터는 웹 대화상자만 엽니다. 제목 변경·영상 제외도 웹에서 처리하며, 제외 목록·관심 없음 복원은 폴더 관리의 해당 구역으로 이동합니다.
번역 CLI 선택지와 표시 이름은 `translation_cli.TRANSLATION_CLI_CHOICES`에서 읽습니다.

`web_dialogs_host.py`는 기존 웹 뷰 한 개의 대화상자 수명과 포커스를 관리하고,
`web_dialogs_models.py`는 `AppCore` 공개 메서드를 호출합니다. `web_dialogs_contract.py`의
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
`dialogs.modalState()`로 알립니다. 실제 모달만 `Ctrl+1~8`·`Alt+S`의 셸 동작을 막고 키 이벤트는 입력·키 캡처로 전달하며,
Esc·Tab·Enter는 해당 모달이 처리합니다. 탐색·재생 진입·웹 재로드는 이전 모달 상태를 비웁니다.
`highlight-range`는 웹 구간 표시와 Qt 재생 진행 막대가 함께 쓰는 의미 색 토큰입니다.

검사는 독립 합성 데이터만 만들며 사용자 라이브러리를 변경하지 않습니다.
생성한 임시 영상·DB는 종료 시 정리합니다. 공용 모달 검사는 `frontend/checks/`에서
실제 Radix Dialog·Popover와 `ConfirmDialog`를 별도로 빌드해 사용하며 제품 번들에는 포함하지 않습니다.

```powershell
.venv/Scripts/python scripts/check_web_dialogs.py --offscreen
# 실창은 공유 데스크톱 잠금 안에서만 실행(agent-orchestra 플러그인이 지휘 시작 때 이 경로에 둠)
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-53 -- .venv/Scripts/python scripts/check_web_dialogs.py --real
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
- `playback_page.py`: 영상 중심 재생 배치·아래쪽 바(조작 줄)·작업 메뉴와 `show_position`·`show_reel` 표시 API. 전체 화면의 임시 바와 Esc 우선순위를 처리한다. 재생 키와 조작 줄 단추는 모두 `run_command(command)`로 명령 하나를 실행한다. 새 단추·영상 클릭도 이 함수를 부르며, 좁은 창에서 글자를 줄일 단추는 `compact_order`에 더한다.
- `playback_help.py`: F1·⌨ 단추로 켜는 별도 반투명 안내 창. 현재 키 배치·모아보기 키 의미·하이라이트 색 범례를 mpv 위에 표시한다. 앱 창의 활성 상태와 초점은 가져가지 않고, 닫기 단추로 마우스로도 닫는다.
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
- `recommendation.py`: 추천 후보 줄 만들기, 줄 정의 `ROW_DEFINITIONS`의 표시 순서·전용 여부, 줄 배정 순수 함수 `assign_rows`(전용 줄부터 배정하고 줄마다 최대 20개·영상마다 한 줄), 시리즈별 후보와 관심 없음 상태.
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
- `tests/test_recommendation.py`: 줄 배정·넘침 순수 함수와 추천 줄 선정·정렬·시리즈 예외, 관심 없음·재실행 보존 검증.
- `tests/test_web_recommend_page.py`: 추천 탭 브리지·Ctrl+2·재생 왕복·관심 없음과 되돌리기 검증.
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
설정 화면은 후속 범위입니다. `favorite_count`는 틀어보기를 뺀 시청(다 본 시청·보다 만 시청) 횟수의 기준이고
기본값은 3입니다. 재생 어댑터는 mpv의 `time-pos`를 보고하고 `seek`부터
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


## 무작위 이어 재생 코어 연결

`random_continuous_play.py`의 `RandomPlayScope(kind, video_ids=(), tag_ids=())`는 불변 범위 값입니다.
`kind`는 `all` / `list` / `tags`이고 태그는 OR입니다. 화면은 내부 상태 대신 다음 `AppCore` 공개 API를 씁니다.

- `random_continuous_enabled`, `random_continuous_scope`: 켜짐 여부와 현재 범위(꺼짐은 `None`).
- `playback_video_ids`: 재생을 시작한 목록의 ID 스냅숏. 목록 범위 선택은 이 값을 사용합니다.
- `set_random_continuous_enabled(bool)`: 일반 재생 중에만 켤 수 있습니다. 켜면 시작 목록 범위와 현재 영상부터 새 기록을 만듭니다.
- `set_random_continuous_scope(RandomPlayScope(...))`: 현재 영상·이동 기록·나온 영상 집합은 유지하고 다음 선택에 적용합니다.
- `execute_video_command(command, visible_video_ids)`: PgUp/PgDn 공용 경로. 반환한 ID는 기존 `switch_to`/`MainWindow.play_video`로 재생합니다.
- `advance_random_if_due(session, eof=True)`: 모든 위치 리스너가 보고를 받은 뒤 호출합니다. 지난 세션의 EOF는 무시합니다.
- `take_random_continuous_notice()`: 이동 경계·후보 없음 안내를 한 번 가져옵니다.
- `end_playback()`: 시청을 닫고 이어 재생 범위·기록·시작 목록을 버립니다.

새 목록 재생은 `switch_to(..., playback_video_ids=시작목록)`로 꺼진 상태에서 시작합니다.
무작위 진입점은 `pick_random_video(...)`로 첫 영상을 고른 뒤 `random_scope=...`도 전달합니다.
진행 중 이전·다음 이동은 두 인자를 생략해 상태를 유지합니다. 난수는 `AppCore(random_choice=...)`로 주입합니다.
무작위 EOF는 `MainWindow`가 이벤트 루프 다음 차례에 엔진·세션을 다시 확인하고 적용하므로,
같은 입력 안에서 먼저 위치를 읽는 PgDn·목록 복귀·탐색과 겹쳐도 중복 전환하지 않습니다.

```powershell
.venv/Scripts/python scripts/check_web_random_continuous.py --offscreen
$env:MVM_REAL_WINDOW_TESTS = '1'
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-235 -- .venv/Scripts/python scripts/check_web_random_continuous.py --library '<테스트 라이브러리 경로>'
```

offscreen은 1100×720 위젯 이미지만 `.local/issue-235/`에 저장합니다. 실창 검사는 지정 라이브러리를 읽어
짧은 서로 다른 영상 두 편의 실제 mpv 끝 → 다음, PgUp/PgDn, Esc 복귀와 마지막 영상 선택을 검사하며 화면을 캡처하지 않습니다.

## 직접 확인할 항목

자동 테스트는 실제 mpv 화면을 포함하지 않습니다. 변경 후 아래를 실제 창에서 확인합니다.

- 한글·공백이 있는 감시 폴더와 하위 폴더를 추가해 썸네일과 제목이 표시되는지.
- MKV/HEVC 영상 및 AC3·DTS 음성이 창 안에서 영상·소리와 함께 재생되는지.
- 마우스 더블클릭과 방향키 + Enter로 영상을 열 수 있는지.
- 재생 중 표의 모든 키, Esc로 목록 복귀, 다른 앱에 포커스를 옮긴 뒤 키 입력이 이 앱을 조작하지 않는지.
- 창 모드에서 '목록으로'와 Esc로 돌아올 때 영상과 목록 사이에 빈 배경·이전 화면이 끼지 않는지. 하이라이트 목록·자막 등 재생 중 웹 대화상자를 열고 닫은 뒤에도 확인합니다.
- 대화상자를 Esc로 닫고 **같은 호출에서 즉시** 목록으로 돌아오는 경로는 창 모드·최대화 각 10회 확인합니다. 닫은 뒤 안정화하고 복귀하는 검사로 대신하지 않습니다. 대화상자 없는 일반 복귀의 이전 재생 화면 재노출은 10회, 일반·Esc·마지막 시청 정렬의 공백·겹침은 각 5회 이상 확인합니다.
- `scripts/check_return_transition.py`는 실제 mpv와 합성 자료를 만들고 FFmpeg 입력 단계에서 앱 클라이언트 좌표·크기만 잘라 60fps로 녹화합니다. TOPMOST와 활성 창을 검증하며 데스크톱 전체를 저장하지 않습니다. `gdigrab title=`은 GPU 자식 화면 갱신을 놓칠 수 있어 쓰지 않습니다. 아래 명령을 **desktop_lock** 안에서 실행하고, `--maximized` 및 `--kind plain/esc/sorted`를 바꿔 각 경로를 검사합니다. 한 잠금은 15분 안에 끝냅니다.

  ```powershell
  python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-250 -- .venv/Scripts/python.exe scripts/check_return_transition.py --kind dialog --count 10 --output .local/return-window
  .venv/Scripts/python.exe scripts/check_return_transition.py --analyze-only --output .local/return-window
  ```

  프레임 번호를 60으로 나눈 값 대신 녹화의 실제 PTS를 씁니다. `capture.log`의 입력 `start` 시각과 `phases.json`의 `wall_time`으로 복귀 요청을 맞추고, `frame-analysis.json`·`contact.png`를 직접 대조합니다. 자홍색은 합성 영상, 청록색은 목록 썸네일이며 `inspect`는 사람이 확인할 후보입니다. 대화상자를 **여는 동안** 보인 프레임과 **복귀 요청 뒤**의 결함을 구분합니다. 계측 자료는 `.local`에 두고 커밋하지 않습니다.
- 복귀 준비는 rAF 완료와 내용 있는 FBO, raster 덮개 flush, 주 창 UpdateRequest 처리 완료를 구분합니다. Qt UpdateRequest 완료는 DWM의 창별 present 확인 신호가 아니므로 실창 프레임 판정을 생략하지 않습니다. 덮개 도중 새 재생·키 입력·창 크기 변경·최대화·종료를 실행해 덮개가 남거나 초점을 가져가지 않는지도 확인합니다.
- 라이브러리를 아래로 스크롤한 뒤 '마지막 시청' 정렬에서 영상을 재생하고 돌아왔을 때 맨 위가 잠깐 보이지 않고, 기존 규칙대로 선택·스크롤·키보드 초점이 복원되는지.
- 복귀 직후 바로 다른 영상을 재생하거나 앱을 완전 종료해도 종료 중인 mpv가 새 영상·위치 보고에 섞이지 않고 시청이 한 번만 저장되는지. 모아보기 마지막 항목의 자동 복귀도 확인합니다.
- 최대화 → 전체 화면 → 전체 화면 끄기 및 전체 화면 모아보기 완료 복귀에서 창 크기가 중간에 바뀌는지. 이 창 상태 전환은 웹 복귀 준비와 별도로 확인합니다.
- 종료·재실행 후 라이브러리와 감시 폴더가 유지되는지.
- 감시 폴더 해제·직접 추가·파일 다시 연결·제외와 복원·제목 변경·최소 길이 설정이 다음 실행에도 유지되는지.
- 테스트 파일을 이름 변경·이동하거나 치운 뒤 검사하면 같은 영상으로 연결되거나 파일 없음으로 표시되는지.
- Insert/Delete 표시가 진행 막대와 목록에 반영되고 Home/End로 이동하는지.
- 열린 구간에서 Esc·창 닫기를 실행한 뒤 다시 열면 마지막 위치까지 저장되어 있는지.
- 하이라이트 목록에서 한글 메모, 시각 편집, 삭제와 재실행 후 보존을 확인하고 편집 중 Delete/Home/End가 글 편집에만 쓰이는지.
- 영상과 하이라이트의 태그 편집에서 붙지 않은 등록 태그 목록 고르기, 검색, 없는 이름 Enter로 새 태그, Esc 순서, Tab 이동·Space 버튼 조작과 태그 떼기가 동작하는지.
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

