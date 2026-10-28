# My Video Manager

Windows용 개인 영상 라이브러리입니다. 폴더의 영상을 모아 썸네일로 보여 주고, 창 안에서 재생하며, **자막을 자동으로 만들고 번역·다듬기**까지 합니다.

- 화면: Python + PySide6, 웹 UI(React·shadcn)
- 재생: libmpv
- 받아쓰기: faster-whisper large-v3-turbo(GPU)

**최신 버전 받기 → [GitHub Releases](https://github.com/vananaHope/my-video-manager-releases/releases/latest)**

## 주요 기능

| 기능 | 설명 |
|---|---|
| 라이브러리 | 감시 폴더를 하위 폴더까지 검사해 썸네일·제목·해상도를 표시합니다. 시리즈를 자동으로 묶고 태그를 붙입니다. |
| 재생 | mpv로 창 안에서 재생합니다(HEVC·AC3·DTS 등). 이어 보기, 배속, 키 배치 변경을 지원합니다. |
| 하이라이트 | 재생 중 지점·구간을 표시하고 메모와 태그를 남깁니다. 모아보기로 복습합니다. |
| 자동 자막 | GPU 받아쓰기로 원어 자막을 만듭니다. 대기열과 자동 규칙(폴더·태그)을 둡니다. |
| 번역 | Codex·Claude CLI 또는 OpenCode Go(API)로 한국어 자막을 만듭니다. 맥락 줄과 용어집으로 일관성을 높입니다. |
| 한국어 다듬기 | 한국어 영상은 띄어쓰기·문장부호·오인식을 고친 **다듬은 자막**을 따로 만듭니다. |
| 외부 자막 | 영상 옆 SRT·VTT·SMI를 가져와 함께 검색합니다. |
| 검색 | 원어·번역·외부 자막의 대사로 장면을 찾아 그 위치부터 재생합니다. |
| 통계 | 시청 시간, 일별 차트, 많이 본 영상, 라이브러리 구성(길이·형식·해상도)을 보여 줍니다. |
| 백업 | 라이브러리를 ZIP으로 백업하고 되돌립니다. DB 형식을 올리기 전에는 자동으로 백업합니다. |
| 트레이 | 창을 닫으면 트레이로 숨고, 한 번만 실행됩니다. 긴급 탈출 키나 트레이 **창 숨기기**로 일시정지하고 바로 숨길 수 있습니다. |

## 설치해서 쓰기

1. [Releases](https://github.com/vananaHope/my-video-manager-releases/releases/latest)에서 `MyVideoManager-Setup-<버전>.exe`를 받아 실행합니다. 관리자 권한은 필요 없습니다.
2. 시작 메뉴에서 **My Video Manager**를 엽니다.
3. **폴더 관리(Ctrl+7) → 감시 폴더 추가**로 영상 폴더를 등록합니다.

- **처음 자동 자막을 만들 때** CUDA 라이브러리와 Whisper large-v3-turbo 모델(합계 약 2.9 GB)을 내려받습니다. NVIDIA GPU와 드라이버가 필요합니다.
- **번역**에는 Codex·Claude CLI 가운데 하나를 설치해 로그인하거나, OpenCode Go 키를 등록해야 합니다(설정 → 번역).
- 코드 서명을 하지 않아 SmartScreen 경고가 뜰 수 있습니다. Release의 `.sha256`으로 파일을 검증할 수 있습니다.
- 업데이트나 제거 전에는 트레이에서 **완전 종료**하세요. 새 버전을 덮어 설치해도 데이터는 남습니다.

| 위치 | 내용 |
|---|---|
| `%LOCALAPPDATA%\Programs\MyVideoManager` | 설치 폴더. 제3자 라이선스는 `THIRD-PARTY-NOTICES.txt`, `licenses/`에 있습니다. |
| `~\.my-video-manager` | 데이터 폴더: 라이브러리 DB, 썸네일, 모델, `backups/`, `logs/`. 제거해도 남습니다. |

## 기본 조작

| 키 | 화면 이동 |
|---|---|
| Ctrl+1 ~ 8 | 라이브러리 · 추천 · 모아보기 · 검색 · 자막 대기열 · 통계 · 폴더 관리 · 설정 |
| Alt+S | 설정(재생 중에는 설정 메뉴) |
| F1 | 키 안내: 앱 전체 키와 지금 화면의 키(웹 화면은 탭 줄의 ⌨ 단추로도 열림) |
| Esc | 재생을 끝내고 직전 화면으로 |
| Ctrl+Shift+H | 긴급 탈출: 일시정지하고 창을 트레이로 숨김(키 배치에서 바꿀 수 있음, 트레이 열기로 같은 장면에 복귀) |
| Ctrl+Shift+R | 영상 전체에서 무작위 재생(키 배치에서 바꿀 수 있음, 대화상자·IME 조합 중 무시) |

| 키 | 재생 화면(설정 → 키 배치에서 바꿀 수 있음) |
|---|---|
| Enter | 재생 / 일시정지 |
| ← / → · `,` | 5초 뒤로 / 앞으로 · 3초 뒤로 |
| ↑ / ↓ | 속도 +0.25 / −0.25 |
| Insert / Delete | 지점 하이라이트 / 구간 하이라이트 시작·끝 |
| Home / End | 이전 / 다음 하이라이트 |
| PgUp / PgDn | 이전 / 다음 영상(시리즈에서는 이전 / 다음 화) |
| `/` · `.` | 자막 켜기·끄기 · 원어 ↔ 번역(다듬은) 자막 전환 |
| `;` | 하이라이트 패널 접기 / 펴기 |

재생 화면 아래 조작 줄의 ⏮ ⏸ ⏭·◆ 지점·【 구간·속도 목록·자막·⌨ 키 안내·⛶ 전체 화면 단추도 같은 명령을 실행하며, 툴팁에 지금 키가 보입니다. 재생 메뉴(⋯)의 **설정**은 Alt+S와 같습니다.

자세한 사용법은 **[사용 설명서](docs/user-guide.md)**를 보세요. 기능별 동작, 시청 상태 판정, 자막 검수와 SRT 내보내기, 백업 복원 등을 설명합니다.

## 개발

### 환경 준비

Windows x64, 64비트 Python 3.10 이상, Node.js 22.12 이상, `winget`이 필요합니다. 저장소 루트의 PowerShell에서 실행합니다.

```powershell
# 처음 쓰는 PC: uv·FFmpeg·7-Zip·libmpv 준비, 웹 빌드, 전체 테스트까지
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
# 도구가 이미 있는 PC의 새 worktree(빠른 모드)
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Worktree
```

### 자주 쓰는 명령

| 할 일 | 명령 |
|---|---|
| 실행 | `.venv/Scripts/python -m my_video_manager` |
| 웹 개발 서버로 실행 | `npm --prefix frontend run dev` 뒤 `$env:MVM_WEB_DEV_URL='http://127.0.0.1:5173/'`로 실행 |
| 테스트 | `.venv/Scripts/python -m pytest -n auto` |
| 웹 검사 | `npm --prefix frontend run lint` · `typecheck` · `build` |
| 브리지 타입 생성 | `.venv/Scripts/python scripts/generate_web_types.py`(검사만: `--check`) |
| 설치 파일 빌드 | `powershell -ExecutionPolicy Bypass -File scripts/build.ps1` |
| Release 발행 | `powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version x.y.z`(먼저 `-DryRun`) |

### 완료 조건

- `frontend/`를 바꾸면 lint·typecheck·build가 모두 통과해야 합니다.
- 브리지 계약을 바꾸면 타입을 생성하고 pytest를 돌립니다.
- 화면은 `scripts/check_web_*.py --offscreen`으로 1100×720을 확인합니다.

### 문서

| 문서 | 내용 |
|---|---|
| [개발 문서](docs/development.md) | 환경 준비 상세, 테스트, 설치 파일 빌드, Release, 새 웹 페이지 추가, 웹 검증 스크립트, 직접 확인할 항목 |
| [사용 설명서](docs/user-guide.md) | 기능별 상세 동작과 내부 API |
| [GLOSSARY.md](GLOSSARY.md) | 도메인 용어 |
| [docs/adr/](docs/adr/) | 설계 결정 기록 |
| [AGENTS.md](AGENTS.md) | 작업 규칙(커밋·PR 메시지는 한국어) |
