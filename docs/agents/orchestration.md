# 이슈 지휘 설정

`orchestrate-issues` 스킬(agent-orchestra 플러그인)이 읽는 이 프로젝트의 설정이다.

## 이슈 저장소

- 종류: GitHub 이슈(vananaHope/my-video-manager)
- 맡길 이슈: 라벨 `ready-for-agent`
- 선행 관계: GitHub 이슈 의존 관계를 먼저 보고, 없으면 본문의 `## Blocked by` 절
- 완료 기준: 본문의 "Acceptance criteria" 절

## 병합

- 기본 브랜치: main
- 병합 방식: 자동
- 병합 방법: squash
- 메인 폴더의 main에 바로 커밋하지 않는다. 브랜치에서 PR을 올려 병합한다.

## 작성 규칙

- 메시지 언어: 한국어(명세·커밋·PR·이슈 댓글 모두). 코드 식별자·파일 경로·기술 용어는 원문 그대로
- PR 서명 줄: 뺌

## 스펙과 먼저 읽을 문서

- `gh issue view 1` : 전체 스펙. 특히 "Implementation Decisions", "Testing Decisions", "Out of Scope".
- `AGENTS.md`, `GLOSSARY.md`(용어집), `docs/adr/`, `README.md`(요약), `docs/development.md`(환경 준비·테스트·빌드 상세)

## 구현 제약

- 기술 스택은 ADR-0001 그대로(Python + PySide6 + mpv). 화면은 ADR-0004의 단일 웹 셸이고, 재생·트레이·공용 네이티브 경고만 Qt로 남긴다.
- 도메인 규칙은 앱 코어에, 외부 세계(미디어 정보, 받아쓰기, 번역, 시계)는 주입 가능한 어댑터로 둔다.
- 코드의 도메인 이름은 `GLOSSARY.md` 용어의 영어 표기를 쓴다. 용어집에 없는 도메인 개념을 새로 만들어야 하면 완료 보고에 적는다.
- 테스트는 앱 코어의 공개 동작(또는 떼어낸 순수 함수)만 검증한다. 내부 테이블이나 private 함수에 묶지 않는다.
- 브리지 계약을 바꾸면 `scripts/generate_web_types.py`로 타입을 생성한다.

## 환경 준비

`scripts/setup.ps1 -Worktree`(빠른 모드)

## 테스트

- 관련 테스트만 `pytest -n auto`로 돌린다. 예: `pytest -n auto tests/test_<영역>*.py -q`
- `frontend/`를 바꿨으면 그 폴더에서 `npm run lint`, `npm run typecheck`, `npm run build`
- 전체 테스트(관리자가 Release 직전 `main`에서 한 번): `pytest -n auto`

## UI 작업

화면 배치, `frontend/` 변경, 대화상자, 알림·안내 표기처럼 사용자가 보는 화면을 바꾸는 이슈.

## 간단한 구현에서 뺄 영역

브리지 계약, DB 버전, 재생/Qt 코드.

## 등급별 배치

| 등급 | 구현 목록(앞부터) | 검토 목록(앞부터) |
| --- | --- | --- |
| `light` | opencode@high → codex@high | codex@medium → 관리자 → claude@high |
| `standard` | opencode@high → codex@high | codex@high → claude@high |
| `hard` | codex@high → claude@high | claude@high → codex@high |
| `UI` | claude | codex@high → claude |

- OpenCode `standard` 크기 상한: 제품 코드 변경 300줄 안팎. 테스트·문서 줄과 파일 수는 세지 않는다.
- 2차 의견: standard 이상
- UI 작업은 등급과 따로 Claude가 구현한다. 위 `hard` 순서는 UI가 아닌 일에만 적용된다.
- 동시성·잠금·프로세스 수명을 다루는 일은 작아 보여도 `standard` 이상으로 정한다(#183에서 `light`로 맡긴 잠금 수정이 새 결함 3개를 만듦).

## Codex fast

관리자가 Codex 작업자를 띄울 때마다 정한다(플러그인 `codex-fast.md`). 이 계정의 Codex 한도는 주간 창 하나뿐이다. 이 프로젝트의 기준:

- 끔(먼저 봄)
  - 주간 사용률 75% 이상
  - 주간 사용률이 40% 이상이면서 창이 지난 비율(`elapsed_percent`)보다 15%p 넘게 높음. 초기화까지 24시간이 안 남았으면 이 조건은 보지 않는다(남은 양은 초기화 때 사라짐).
  - fast로 떠 있는 Codex 작업자가 이미 3명
- 켬(끔에 안 들 때 하나라도)
  - 검토: 주 검토, 2차 의견, 지적 수정 뒤 재검토
  - 병합 직전: 지적 수정, rebase·충돌 해결
  - 임계 경로: 열린 이슈가 이 이슈를 선행으로 기다리고, 지금 진행하거나 시작할 다른 일이 없음
  - 묶음의 마지막 남은 일
  - 사용자가 기다리거나 급하다고 함. 앱을 못 쓰게 만드는 결함(실행 실패, 재생 불가, 라이브러리 데이터 손실) 수정도 여기에 든다(#183 같은 긴급 탈출).
- 그 밖(다른 이슈와 나란히 도는 구현 등)은 끔.

## 추가 완료 조건

웹 UI 이슈(ADR-0004):
- `npm run lint`(@shadcn/lint 6규칙, 인라인 비활성 금지), `typecheck`, `build`가 통과해야 한다.
- 기본 창 1100×720의 웹 화면 스크린샷을 남긴다(`scripts/check_web_*.py --offscreen`). 이전 명세나 이슈 본문에 "Qt 대비 스크린샷"이 있어도 #55 병합 뒤로는 비교할 Qt 화면이 없으므로 웹 화면만 찍으면 충족이다.
- 데이터 개수별(0·적음·최대·긴 텍스트) 배치를 확인한다. lint는 배치와 정보 밀도를 막지 못한다(#43에서 확인).

## 실창 검사

동시 작업자가 실창을 띄우면 서로 가려 캡처와 포커스 검사가 깨진다(#54·#58에서 확인).
- 스크린샷: 웹 화면은 offscreen에서 위젯 자체를 이미지로 뽑는다(`grab()`).
- 실창이 꼭 필요한 검사: 창 활성화, 실제 키보드 포커스, mpv 재생 왕복, 탭·단축키·대화상자·트레이.

## 확인 자료

`.local/테스트 라이브러리/` : HEVC+AC3, H.264+DTS, VP9+Opus, 복사본, jpg/srt/txt 포함. 실제 어댑터(ffmpeg 등) 재현과 사람이 직접 확인할 때 쓴다.
