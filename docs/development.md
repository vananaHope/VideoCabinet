# 개발 문서

소스에서 앱을 준비·실행·테스트하는 방법, CI, 웹 개발 서버와 새 웹 페이지 추가 방법을 설명합니다. 요약은 [README](../README.md)를 보세요.

| 문서 | 내용 |
|---|---|
| [릴리스 문서](release.md) | 설치 파일·패치 빌드, Release 발행, 업데이트 매니페스트와 서명 키 |
| [검증 문서](verification.md) | 화면 검사 스크립트(`scripts/check_*.py`)와 실창에서 직접 확인할 항목 |
| [내부 동작](internals/README.md) | 모듈 구조, 코어 API, DB 이전, 기능별 구현 메모 |
| [사용 설명서](user-guide.md) | 사용자가 보는 기능과 동작 |
| [GLOSSARY.md](../GLOSSARY.md) · [docs/adr/](adr/) | 도메인 용어 · 설계 결정 기록 |

## 자주 쓰는 명령

| 할 일 | 명령 |
|---|---|
| 실행 | `.venv/Scripts/python -m my_video_manager` |
| 웹 개발 서버로 실행 | `npm --prefix frontend run dev` 뒤 `$env:MVM_WEB_DEV_URL='http://127.0.0.1:5173/'`로 실행 |
| 테스트 | `.venv/Scripts/python -m pytest -n auto` |
| 웹 검사 | `npm --prefix frontend run lint` · `typecheck` · `build` |
| 브리지 타입 생성 | `.venv/Scripts/python scripts/generate_web_types.py`(검사만: `--check`) |
| 설치 파일 빌드 | `powershell -ExecutionPolicy Bypass -File scripts/build.ps1` |
| Release 발행 | `powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version x.y.z`(먼저 `-DryRun`, 빌드 전에 전체 테스트 실행) |

## 완료 조건

- `frontend/`를 바꾸면 lint·typecheck·build가 모두 통과해야 합니다.
- 브리지 계약을 바꾸면 타입을 생성하고 pytest를 돌립니다.
- 화면은 `scripts/check_web_*.py --offscreen`으로 1100×720을 확인합니다.

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

화면 자막은 Windows 내장 OCR을 사용합니다. Windows에만 설치되는 pywinrt 3.2.1의
`winrt-runtime` 및 `Windows.Media.Ocr`, `Windows.Graphics.Imaging`,
`Windows.Storage.Streams`, `Windows.Globalization`, `Windows.Foundation`,
`Windows.Foundation.Collections` 투영 패키지는 `pyproject.toml`에 고정돼 있습니다.
읽을 언어의 Windows 언어 팩(광학 문자 인식 포함)은 별도로 설치해야 합니다:
설정 > 시간 및 언어 > 언어 및 지역 > 언어 추가. 앱이나 설치 프로그램은 언어 팩을 내려받지 않습니다.
`onscreen_subtitles.OcrEngine` 경계는 영역 이미지·언어를 글자로 바꾸는 계약이며,
`windows_ocr.WindowsOcrEngine`이 구현합니다. UI의 언어 확인과 작업자 QThread의 읽기를
분리하고, 읽기 스레드마다 이벤트 루프·언어별 인식기를 재사용합니다.

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

### 테스트

테스트는 각 작업자에서 `tests/conftest.py`가 `QT_QPA_PLATFORM=offscreen`과
`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`를 기본으로 적용하며, 사용자가 지정한 값은 유지합니다.
`-n auto`는 CPU 수에 맞춰 작업자를 만들고, 여러 작업이 같은 PC를 쓸 때는 `-n 2`처럼 수를 줄일 수 있습니다.
직렬 실행은 `-n auto`를 빼고 `.venv/Scripts/python -m pytest`로 실행합니다.
자식 프로세스 성공 경로의 대기 한도는 `tests/wait_helpers.py`의 `CHILD_READY_TIMEOUT`(기본 90초)이며 `MVM_TEST_CHILD_TIMEOUT` 환경 변수로 조정합니다. 조건이 충족되면 즉시 진행하고, 짧은 timeout 동작 검사는 별도 한도를 유지합니다. 실패를 빨리 보려면 단독 실행에서 `MVM_TEST_CHILD_TIMEOUT` 값을 낮춥니다.
건너뛴 테스트와 이유까지 비교하려면 직렬·병렬 명령에 각각 `-rs`를 붙입니다.

웹 입력 시험은 Qt 이벤트 전송이나 창 표시만으로 완료를 판단하지 않습니다. 카드 클릭은 **선택 변경**까지,
긴급 탈출 복귀는 **웹 입력란 초점·대화상자 재표시**까지 조건 대기합니다. 이미 초점이 있는 격자를 다시
클릭할 때 초점만 기다리면 아직 전달 중인 클릭을 놓칩니다. 고정 시간 대기나 시간 제한 증가로 대신하지 않습니다.
전환 중 입력 시험은 시험용 CSS로 전환을 시작부터 멈추고 실제 `animationstart`와 제품의 이름·길이·불투명도를 확인한 뒤 입력하며,
DOM 부착만 확인하거나 전환이 끝날 때까지 기다리는 검사로 바꾸지 않습니다.
이와 별도로 애니메이션을 붙잡거나 시작을 기다리지 않고 F1 직후 숨기는 시험에서 복귀 후 Esc와 배경 단축키 차단을 확인합니다.
Qt는 주 창이 숨거나 최소화된 동안에도 모달 열림·닫힘을 수신 순서대로 기록하여 트레이 무작위 재생과 복귀 초점 판단에 씁니다.
재생 화면이 웹 셸 자체를 가린 경우에는 늦은 열림 알림이 차단을 되살리지 않습니다.
`ShellModals`는 문서가 다시 보일 때 DOM이 같아도 현재 상태를 재전송하며, Qt는 이 최신 알림으로 이전 기록을 갱신합니다.
재전송은 visible 복귀에만 적용합니다. hidden 전환에서는 마지막 알림을 유지하여, 숨은 동안 `show_status()`가
작업 알림을 붙이거나 지워도 이미 열린 모달의 셸 동작 차단이 풀리지 않는지 별도로 확인합니다.
숨김 완료를 기다리는 조건과, 300ms 뒤에도 재생 대화상자가 다시 뜨지 않았는지 확인하는 관찰 구간은 구분합니다.
후자는 준비 완료를 추측하는 고정 대기가 아니라 지연된 콜백에 의한 재표시를 검출하는 지속 확인입니다.

## CI

`.github/workflows/windows-tests.yml`(**Windows tests**)은 PR과 `main` push마다 GitHub 호스팅 Windows 러너에서
Windows 전용 테스트를 포함한 전체 pytest를 돌립니다. 수동 실행(`workflow_dispatch`)도 됩니다.
`docs/`, `*.md`, `LICENSE*`만 바꾼 변경은 건너뛰며, 같은 PR에 새 커밋이 오면 이전 실행을 취소합니다. 필수 체크는 아닙니다.

- 전체를 한 러너에서 돌리면 오래 걸려 10개 조각으로 나눠 동시에 돌립니다. 조각은 `MVM_TEST_SHARD=i/n`
  (예: `3/10`)으로 고르며, `tests/conftest.py`의 수집 훅이 수집한 테스트 가운데 i번째 조각만 남깁니다.
  하위 pytest에는 물려주지 않습니다. 로컬에서도 같은 값으로 한 조각만 재현할 수 있습니다.
- 러너(4 vCPU)에서 작업자를 4개 띄우면 Qt 대기 시간이 초과돼 조각마다 `-n 2`로 돌립니다.
- CI에서만 `pytest-timeout`을 설치해 5분(`--timeout=300`) 넘게 멈춘 테스트를 이름과 스택과 함께 실패로 남깁니다.
- FFmpeg는 choco로 설치하되 shim이 아닌 패키지 안의 실제 `ffmpeg.exe` 폴더를 PATH 맨 앞에 둡니다.
  shim만 종료되면 자식 ffmpeg가 파이프를 쥔 채 남아 프로세스 정리 테스트가 멈춥니다.
- 실창 검사(`MVM_REAL_WINDOW_TESTS`)와 CUDA는 러너에서 확인할 수 없어 로컬 Windows에서 확인합니다.
- 조각별 JUnit 결과(`pytest-results-<조각>`)를 7일 동안 Actions 산출물로 남깁니다.

`.github/workflows/frontend.yml`(**Frontend checks**)은 `frontend/`가 바뀐 PR과 `main` push 때 Linux 러너에서 `npm run lint`와 `npm run typecheck`를 돌립니다(빌드는 Windows tests가 테스트 준비로 합니다).

테스트는 `tests/conftest.py`의 autouse 픽스처가 테스트에서 여는 SQLite 연결에 `PRAGMA synchronous = OFF`를 걸어
디스크 동기화를 끕니다. 잠금 중이거나 DB가 아닌 파일이면 그 연결만 기본 동기화로 둡니다. 앱 코드의 설정은 바꾸지 않습니다.

Claude Code 클라우드(Linux) 세션은 `.claude/hooks/session-start.sh`가 Qt 시스템 라이브러리, Python 3.10 `.venv`,
웹 빌드를 준비하므로 바로 `pytest -n auto`와 `frontend/` 검사를 돌릴 수 있습니다.
Linux에서도 DPAPI·폴더 순회 순서 등은 `tests/conftest.py`의 대체 픽스처(`portable_dpapi`, `name_ordered_scandir`)로 돌지만,
웹 셸(Linux offscreen에서 PySide6가 세그폴트), 실제 Windows ACL·DPAPI·파일 잠금·DLL 탐색, Windows OCR 등을 쓰는 테스트는 건너뜁니다.
그 테스트는 위 Windows tests 체크나 로컬 Windows에서 확인합니다.

GitHub Actions에는 이 밖에 Claude 워크플로 두 개가 있습니다. `claude.yml`은 저장소 소유자·멤버·협업자가 쓴 글의
`@claude` 멘션에만 반응하고, `claude-code-review.yml`은 외부 포크에서 온 PR을 건너뜁니다.

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
`web_tokens.json`은 웹 CSS와 네이티브 재생 화면에서 공유하는 색·간격·글꼴, 그리고 웹 전환의 시간·곡선(모션)의 단일 원본입니다.
글꼴 `font-sans`의 첫 이름은 번들 글꼴(Pretendard), 둘째 이름은 대체 글꼴(맑은 고딕)이며 웹과 Qt 화면이 같이 씁니다.
Qt는 woff2를 읽지 못하므로 `npm run build`가 `pretendard` 패키지의 정적 TrueType(`dist/public/static/alternative/*.ttf`)을 굵기마다 `src/my_video_manager/web/qt-fonts/`에 복사하고(`frontend/vite.config.ts`), `MainWindow`가 앱 로그 설정 뒤 `theme.use_bundled_font()`로 Qt 글꼴 데이터베이스에 등록합니다. 소스 실행도 `npm run build`를 한 상태를 전제로 하며, 파일이 없거나 읽지 못하면 맑은 고딕으로 뜨고 `logs/app.log`에 경고를 남깁니다. 설치물 검사(`scripts/check_bundle.py`)는 이 ttf 파일들을 필수로 요구합니다.
번들 글꼴의 굵기는 `bundled-font`가 원본입니다. `frontend/`에서 `npm run fonts`가 굵기마다 첫 렌더용 부분 집합(block)과 그 밖의 글자용 전체 파일(swap)의 `@font-face`를 `frontend/src/fonts.css`로 생성하며, 두 `unicode-range`는 woff2의 cmap에서 계산해 겹치지 않습니다. `npm run build`는 먼저 이 생성 결과와 다르면 실패합니다.
Python에서는 `web_tokens.web_tokens()`로 읽습니다.
변경 후 `.venv/Scripts/python scripts/generate_web_types.py`로 TypeScript 계약과 CSS 토큰을 생성합니다.
`--check`는 생성 파일이 원본과 다르면 실패하며 setup과 pytest가 이를 확인합니다.
썸네일 주소는 `mvm-thumb://video/<id>`이며 코어가 아는 해당 영상의 썸네일만 읽습니다.
외부 페이지로의 이동과 패키지 자산·썸네일·설정한 개발 서버 외 요청은 차단합니다.

ESLint 9는 공식 flat config와 TypeScript parser로 shadcn 6규칙을 함께 검사하기 쉬워 선택했습니다.
TanStack Virtual은 행 단위 가상화·overscan·scrollToIndex를 제공하면서 카드의 DOM과 디자인을 강제하지 않아 선택했습니다.

## 새 웹 페이지 추가하는 법

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
   **다시 보인 탭(#265)**: 탭 이동·트레이 복원으로 탭이 다시 보이면 호스트는 `refresh()` 대신 `reshown()`을 부릅니다.
   기본 `reshown()`은 웹이 마지막으로 전체 상태를 받은 뒤 앱 안의 내용이 바뀌었을 때(`host.content_changed()`)만
   `refresh()`를 부르고, 바뀐 것이 없으면 아무것도 보내지 않습니다. 전체 상태는 `self.publish(신호, 데이터)`로 보냅니다.
   보이는 동안만 보내고, 숨어 있으면 다시 보일 때 한 번 보내도록 표시만 합니다. 여러 탭이 보이는 내용을 바꾸는 작업
   (태그·제목·제외·시청 기록·자막 완료 등)은 `host.content_changed()`를 부릅니다. 알림 없이 바뀌는 상태(대기열처럼 주기적으로 읽는 값)는
   `reshown()`을 재정의해 비교한 뒤 바뀌었을 때만 보냅니다. 늦게 온 메시지를 버려도 잃는 것이 없게 바뀐 행만 담는
   델타가 아니라 매번 전체 상태를 보냅니다(웹이 바뀐 행만 다시 그립니다).
   **세대(#265)**: 페이지 상태 메시지(밀어 보내는 changed와 `snapshot` 등 상태를 담은 요청 응답)는 `self.stamp(데이터)`로 JSON을 만들어
   페이지마다 하나씩 올라가는 `generation`을 붙이고, 데이터 TypedDict는 `GenerationData`를 상속합니다.
   활성 상태는 `is_active()`로 확인합니다. QWidget의 `isVisible()`은 자체 화면 표시 여부입니다.
   복귀 시 기본 `return_from_playback()`은 `refresh()`와 포커스 복원을 수행하며,
   라이브러리는 이를 재정의해 `refresh(focus=True)`로 격자 초점을 요청합니다.
   재생 중 창을 닫았다가 트레이로 열 때 라이브러리 대신 출발한 탭으로 돌아와야 하면
   컨트롤러에 `keeps_tab_after_close = True`를 둡니다(추천 탭).
   자체 포커스가 필요하면 `default_focus`와
   `focus_requested` 신호를 지정하고, 웹 첫 렌더 후 호출하는 `ready` 슬롯에서
   `self.page.frontend_ready()`를 호출합니다. 포커스 요청은 호스트가 준비될 때까지 보존합니다.
   이미 한 번 보인 탭을 다시 보일 때는 기본 위치 대신 `'restore'`를 요청하므로, 웹 페이지의 초점 처리는
   `restorePageFocus(탭, target)`(`@/lib/page-focus`)이 참이 아닐 때만 기본 위치에 초점을 둡니다.
3. `web_page_registry.py`에 컨트롤러를 import하고 `WEB_PAGES`에 한 줄 등록합니다.
   새 탭이면 `web_tabs.py`의 `TABS`에도 `('search', '검색'),` 한 줄을 추가합니다. 모든 탭은 웹 컨트롤러로 등록합니다.
4. 새 `frontend/src/pages/SearchPage.tsx`를 작성합니다. `connectBridge()`에서
   `{ search, shell }`을 받아 생성된 공개 메서드만 사용하고, 효과를 정리할 때 신호 구독을 해제합니다.
   페이지 사이 브리지 호출은 공통 `shell` 외에는 하지 않습니다.
   페이지는 숨겨져도 마운트를 유지하므로 선택·검색어·스크롤을 보존할 수 있습니다. 숨긴 페이지가 잃는 안쪽 스크롤 위치는
   셸이 탭을 떠날 때 저장했다가 다시 보일 때 되살립니다. 상태 메시지는 `useGenerationGuard()`(`@/lib/generation`)가 돌려주는
   함수로 거르고(반영할 메시지면 참), 밀어 보내는 신호와 요청 응답에 같은 가드를 씁니다. 세대는 메시지가 담은 상태마다
   비교합니다. 상태 일부만 담은 응답이 있으면(라이브러리의 보기 응답) 담은 상태마다 가드를 따로 두고, 전체 상태는 각 가드를
   통과한 부분만 반영합니다.
   구역 전환·비동기 준비 완료처럼 툴바·작업 단추의 자리가 바뀌는 상태는 `useLayoutChange(...)`(`@/lib/layout-change`)에 넘겨, 떠 있는 셸 안내 묶음이 그 단추를 피해 모서리를 다시 고르게 합니다(목록 스크롤에는 쓰지 않습니다). 공용 `Notice`·`NoticeStack`은 생기고 사라질 때와 펼치기·접기에서 스스로 신호를 보내므로 안내 상태는 넘기지 않아도 됩니다.
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

## 문제 해결

ffmpeg/ffprobe를 찾지 못하면 설치 후 새 터미널을 열거나 PATH를 확인하세요.
앱은 winget 기본 설치 경로도 탐색하므로 설치 직후 기존 터미널에서도 실행할 수 있습니다.
`libmpv-2.dll` 오류는 `scripts/install_libmpv.py`를 다시 실행하고 Python과 DLL이 모두 x64인지 확인하세요.
