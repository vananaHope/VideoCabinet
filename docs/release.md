# 릴리스 문서

설치 파일과 패치를 만들고 GitHub Release로 발행하는 방법, 업데이트 매니페스트와 서명 키를 설명합니다. 환경 준비는 [개발 문서](development.md)를 먼저 따르세요.

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
Windows OCR의 함수 내부 지연 import도 PyInstaller가 분석합니다. 별도 OCR 어댑터만
불러오는 Analysis에서 pywinrt 7개 배포판의 pyd와 `winrt/MSVCP140.dll` 수집을 확인했으므로
추가 hiddenimports는 필요하지 않습니다. Windows OCR 자체와 언어 팩은 OS 구성 요소로
동봉하지 않습니다. wheel에서 빠진 MIT 원문은 공식 `v3.2.1` 태그의 LICENSE를
`installer/license-sources/`에 보관하고, `bundle_licenses.py`가 배포판별 버전·해시를
검사해 포함합니다. VC 런타임의 별도 이용 조건은 `THIRD-PARTY-NOTICES.txt`에 고지합니다.
`-Version 0.2.0`은 소스를 바꾸지 않고 설치 파일과 앱 표시 버전을 함께 지정합니다(Release DryRun용).
이미 만든 실행 폴더로 설치 파일만 다시 만들 때는 `-SkipPyInstaller -AppDirectory <실행 폴더>`를 사용합니다.

앱 아이콘은 `assets/icon/`의 벡터 원본(`app-icon.svg`)과 16·20·24·32px 손본 PNG가 원본입니다.
원본을 바꾸면 `python scripts/app_icon.py`로 산출물(`src/my_video_manager/app.ico`, `frontend/src/assets/app-icon.png`,
`assets/icon/build-manifest.json`)을 다시 만들어 함께 커밋합니다. 개발 실행과 설치본이 같은 `app.ico`를 창 아이콘으로 읽고,
실행 파일·설치 프로그램·설치된 앱 목록도 이 파일을 씁니다. 트레이 아이콘은 같은 폴더의 16·20·24·32px 손본 PNG
(`tray-icon-<크기>.png`)가 원본이고(벡터 원본 없음), 같은 명령이 `src/my_video_manager/tray.ico`를 만들어 매니페스트에 함께 적습니다.
트레이가 이 파일을 읽고 설치본에도 실립니다. 빌드의 생성 검사는 `scripts/app_icon.py --check`로
앱·트레이 아이콘의 원본 내용 해시와 픽셀 규칙(DESIGN.md "App Icon")을 확인하고 어긋나면 멈춥니다.

설치 프로그램 제목·시작 메뉴·바탕 화면 바로 가기·"설치된 앱" 목록 이름은 `app_version.DISPLAY_NAME`(VideoCabinet)을 따릅니다.
`build.ps1`은 Inno 컴파일 직전에 `scripts/installer_metadata.py`로 UTF-8(BOM) `build/bundle-assets/display-name.iss`를 만들고
`/DDisplayNameInclude=<ASCII 절대 경로>`로 넘겨 `.iss`가 `#include`로 읽습니다(한글을 `/D` 값으로 넘기지 않습니다).
덮어 설치와 패치 설치 모두 `[InstallDelete]`로 옛 이름 `My Video Manager.lnk`·`상영실.lnk`를 지우고, 설치 전에 바탕 화면 바로 가기가
있던 사용자는 작업 선택과 무관하게 새 이름 바탕 화면 바로 가기 하나를 더 만듭니다. 이전 작업 선택은 기억하지 않아
(`UsePreviousTasks=no`) 지운 바로 가기를 설치가 되살리지 않습니다. 바로 가기 아이콘은 설치 폴더의
`my_video_manager\app.ico`를 가리켜 패치로 아이콘 파일만 바뀌어도 따라갑니다. 실행 파일 버전 정보(제품 이름·파일 설명)도
같은 이름과 앱 버전으로 `prepare_bundle.py`가 만든 `build/bundle-assets/version-info.txt`에서 들어갑니다.
`installer/my-video-manager.iss`는 옛 바로 가기 이름(`상영실.lnk`)이 한글이라 UTF-8(BOM)으로 저장합니다(BOM이 없으면 ISCC가 ANSI로 읽어 한글 경로가 깨집니다). `tests/test_bundle_packaging.py`가 BOM을 확인합니다.

앱 부분만 담은 패치도 만들려면 `scripts/build.ps1 -Patch`를 사용합니다. 전체 설치 파일과 함께 `dist/installer/MyVideoManager-Patch-<version>.exe`를 만듭니다.
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
설치 테스트 전용 `/DIsolatedTest` ISCC define은 제거 프로그램·등록·이전 설치 경로 재사용을 끕니다. `build.ps1`은 이 define을 전달하지 않습니다.
바로 가기는 실제 사용자 시작 메뉴·바탕 화면을 건드리지 않도록 `/DShortcutRoot=<임시 폴더>` 아래 `Programs`·`Desktop`으로 돌려
`tests/test_patch_installer.py`가 이 구성과 임시 `/DIR=`로 실제 조용한 덮어 설치·패치 설치·거부 경로와 바로 가기 교체를 검사합니다.
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

### 설치 파일에 담기는 라이선스

빌드 시 PyInstaller가 실제 동봉한 Python 배포물의 원문을 `licenses/python/<패키지>/`에,
npm production 의존성(전이 의존성 포함)의 원문을 `licenses/web/`에 모읍니다.
각 `manifest.json`에 버전·원문 경로·SHA-256이 있으며, Python 배포물에 원문이 없으면
`metadata_only`와 해당 패키지의 `NOTICE.txt`에 라이선스 이름·URL을 남깁니다.
`check_bundle.py`는 대표 원문·고지와 manifest의 모든 원문 해시를 검사합니다.
GPLv3 원문은 FFmpeg와 독립적인 `licenses/GPL-3.0.txt`에도 있습니다.

## 새 버전 올리기

`scripts/release.ps1`은 로컬 릴리스용입니다. Git for Windows, GitHub CLI의 `gh auth login`,
"설치 파일 만들기"의 빌드 extra 설치까지 먼저 마쳐야 합니다.
`release.ps1`은 의존성을 설치하지 않고 `build.ps1`을 호출합니다. `main`에서만 실행하며 작업 트리가 깨끗하고 `main`,
`origin/main`, 실제 원격 main이 모두 같아야 합니다. 기존 로컬/원격 태그나 GitHub Release가 있으면 멈춥니다.

실제 발행과 `-DryRun -Build`는 버전 커밋·빌드 전에 `scripts/run_tests.ps1`(전체 `pytest -n auto`)을 실행합니다.
테스트가 실패하거나 작업 트리를 바꾸면 버전·커밋·태그·원격을 바꾸지 않고 멈춥니다. `-DryRun`만 주면 실행하지 않고 계획만 표시합니다.
급할 때는 `-SkipTests`로 건너뛸 수 있습니다. 그때는 발행할 `main` 커밋의 [Windows tests](development.md#ci) 체크가 통과했는지 확인하세요.
Linux 클라우드 세션은 Windows 전용 테스트(웹 셸·트레이·실제 ACL 등)를 건너뛰고, CI는 실창 검사와 CUDA를 확인하지 않습니다.
`run_tests.ps1`은 단독으로도 실행할 수 있으며 추가 인자는 pytest에 넘깁니다.

소스 저장소(`origin`, `vananaHope/VideoCabinet`)는 공개 저장소이며 설치 파일·체크섬·매니페스트·서명도 이 저장소의 Release에 발행합니다.
`origin`에 버전 커밋과 `v<version>` 태그를 push하고, 이전 Release 조회·같은 태그의 Release 확인·
`gh release create`·실패 시 안내 명령은 **Release 저장소**(`RELEASE_REPOSITORY`)를 씁니다. 그 이름은 앱의
`src/my_video_manager/app_version.py`의 `RELEASE_REPOSITORY`와 `release.ps1`의 `-ReleaseRepository` 기본값에 있으며
테스트가 두 값이 같은지 검사합니다. 이전 Release나 매니페스트가 없으면 첫 릴리스(전체 설치만)로 처리합니다.
v0.9.0까지는 별도 배포 저장소 `vananaHope/my-video-manager-releases`에 발행했고, 그 버전을 설치한 앱은 그 저장소에서만 업데이트를 찾습니다.

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
# 실제 릴리스(빌드 전에 전체 테스트 실행)
powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.4.2
# 전체 테스트만 단독 실행
powershell -ExecutionPolicy Bypass -File scripts/run_tests.ps1
```

실제 실행은 먼저 개인 키를 읽고 앱에 내장된 공개 키와 일치하는지 검사합니다.
키가 없거나 공개 키가 자리 표시 값이거나 키가 다르면 버전 커밋·빌드 전에 멈춥니다.
기본 키 경로는 아래 "사람이 한 번 준비할 키"와 같으며 `-PrivateKey <경로>`로 바꿀 수 있습니다.
암호는 `MVM_UPDATE_SIGNING_PASSWORD` 환경 변수 → 대화형 터미널에서만 질문 순서이며,
대화형 입력은 실행당 한 번입니다. 암호는 메모리에 보관하고 키 검사·서명 하위 프로세스의
환경 변수로만 잠시 전달하며 명령줄·로그에 넣지 않습니다. 빌드·Git·gh에는 전달하지 않고,
성공·실패 시 환경 변수를 지웁니다(호출한 PowerShell 프로세스에 설정한 값도 제거).
서명 시에도 동일 키 검사를 다시 합니다.

이전 메타데이터는 Release 저장소의 `releases/latest`가 가리키는 정식(비 draft·비 prerelease)
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
`gh release create`는 push한 그 태그로 Release를 만들며(`--target main`은 태그가 없는 저장소를 지정했을 때만 쓰임)
전체 설치 파일·체크섬·매니페스트·서명과 해당하는 패치를 게시합니다.
노트는 현재 main에 포함된 가장 높은 버전 태그 이후의 커밋 제목입니다(태그가 없으면 전체).
이름이 바뀐 첫 Release에는 노트 맨 앞에 "앱 이름이 My Video Manager에서 VideoCabinet으로 바뀌었고 라이브러리·설정 데이터와 설치 위치는 그대로"라는 안내를 넣습니다(`release.ps1`의 `$RenameNote`·`$IncludeRenameNote`). 이 Release를 발행한 뒤 `$RenameNote`·`$IncludeRenameNote` 선언, 이를 쓰는 DryRun·노트 분기, `tests/test_release_script.py`의 이름 안내 단언, 이 문서 문단을 함께 지웁니다.
설치 파일은 `dist/installer/MyVideoManager-Setup-<version>.exe`, 체크섬은 그 옆의 `.exe.sha256`입니다.
패치는 `dist/installer/MyVideoManager-Patch-<version>.exe`, 메타데이터는
`dist/installer/<version>/update-manifest.json`과 `update-manifest.json.sig`에 보존합니다.
GitHub Release 자산 이름에는 버전 하위 폴더가 붙지 않습니다. 기존 메타데이터가 있으면
덮어쓰지 않고 중단하므로 실패 후 재시도 전 해당 버전 파일을 확인·보관하세요.
기존 태그·Release를 덮어쓰거나 강제 push하지 않습니다.
빌드 실패나 원격에서 거부한 push는 로컬 버전 커밋과 이번에 만든 태그를 자동 복구합니다.
다른 파일 변경이나 불확실한 원격 상태가 있으면 보존하고 복구 명령을 안내합니다.
push 뒤 Release 생성이 실패하면 `origin`의 main과 태그를 유지하며 Release 저장소 기준의 Release 확인·생성·자산 추가 명령을 안내합니다.
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

## 업데이트 매니페스트와 서명 키

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
