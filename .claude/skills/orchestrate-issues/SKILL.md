---
name: orchestrate-issues
description: GitHub 이슈를 Orca 위에서 "Codex 구현 → Claude 교차 검토 → PR·병합" 흐름으로 지휘한다. 이슈 구현·다음 이슈 진행·다음 묶음(wave) 진행을 요청받았을 때 사용.
---

# 이슈 지휘

너는 **관리자**다. 코드는 직접 쓰지 않는다. 이슈를 작업 명세로 바꿔 Codex 작업자에게 맡기고, Claude 검토자로 교차 검토하고, 판정하고, 병합한다.

Orca 명령의 정확한 사용법은 이 문서에 없다. Orca 명령을 처음 쓰기 전에 `orchestration` 스킬을 불러 그 안내대로 `orca skills get orchestration`을 읽는다(버전에 맞는 안내가 그쪽에 있다).

## 고정 규칙

- **동시 구현 작업자는 최대 3명.** 검토자는 이 수에 넣지 않는다.
- **구현은 Codex, 검토는 Claude.** 구현한 쪽과 다른 에이전트가 검토하는 것이 교차 검토다.
  - 예외: **UI 다듬기**(사용자 요청, 2026-10-14)는 관리자(Claude)가 직접 한다. 시점은 그 화면 묶음의 Codex 구현 이슈가 모두 병합된 뒤다. 작업은 별도 worktree에서 offscreen 스크린샷을 보며 하고, 교차 검토는 Codex 검토자가 맡는다. 사용자에게는 전후 스크린샷을 보고한다.
- **웹 UI 이슈(ADR-0004)의 완료 조건**
  - `npm run lint`(@shadcn/lint 6규칙, 인라인 비활성 금지), `typecheck`, `build`가 통과해야 한다.
  - 기본 창 1100×720에서 Qt 화면과 나란히 찍은 스크린샷을 남긴다.
  - 데이터 개수별(0·적음·최대·긴 텍스트) 배치를 확인한다.
  - lint는 배치와 정보 밀도를 막지 못하므로(#43에서 확인), 명세와 검토 양쪽에 이 조건을 넣는다.
- **병합 권한은 관리자.** 교차 검토가 통과하면 사용자 승인 없이 `main`에 병합하고 결과를 보고한다(#2만 예외였다).
- **메시지는 한국어.** 작업 명세, 커밋, PR, 이슈 댓글 모두.
- 작업 파일(명세, 검토 보고서)은 메인 저장소의 `.local/orchestration/issue-<n>/`에 둔다. Git에서 제외되는 위치다.
- 사람이 확인할 때 쓸 테스트 영상 묶음: `.local/테스트 라이브러리/` (HEVC+AC3, H.264+DTS, VP9+Opus, 복사본, jpg/srt/txt 포함).

## 단계

### 1. 프런티어 고르기

열린 이슈 중 `ready-for-agent` 라벨이 있고, 선행 이슈가 모두 닫혔고(`issue_dependencies_summary.blocked_by == 0`), 지금 진행 중이 아닌 것이 프런티어다. 남은 자리(3 − 진행 중 구현 작업자 수)만큼 **임계 경로**에 있는 것부터 고른다. 뒤에 이어지는 이슈 사슬이 가장 긴 이슈가 먼저이고, 같으면 번호가 작은 것이 먼저다.

**완료 기준**: 고른 이슈 목록과, 고르지 않은 프런티어 이슈가 있으면 그 이유를 사용자에게 한 줄로 알렸다.

### 2. 구현 맡기기

이슈마다:

1. [task-template.md](task-template.md)를 채워 `.local/orchestration/issue-<n>/task.md`로 저장한다. 명세 파일은 Write 도구로 쓴다(셸 heredoc을 거친 python 스크립트로 만들면 한국어가 깨진다). 이슈의 범위 밖 항목(다른 이슈가 맡은 기능)을 명세에 구체적으로 적는다.
2. Run이 없으면 만든다(이번 지휘 세션 전체에 Run 하나).
3. `worker-start --spec "<명세>" --worktree new-top-level --name issue-<n>-<slug> --base-branch main --agent codex`로 시작한다.
4. **입력이 실제로 제출됐는지 확인한다.** 작업자 화면을 읽어 `draft`에 `[Pasted Content ...]`가 남아 있으면 붙여넣기만 되고 제출되지 않은 것이다. 이때는 같은 명세를 다시 보내지 말고 `orca terminal send --terminal <handle> --enter`로 Enter만 보낸다. 특히 기존 터미널을 재사용할 때(`--terminal`) 잘 생긴다.

동시에 맡긴 이슈들이 같은 연결 지점(예: 재생 위치 보고)을 각자 만들 것 같으면, 관리자가 그 **공용 계약** 파일을 `.local/orchestration/`에 직접 써서 "내용 그대로 복사"하라고 모두에게 보낸다. 같은 내용의 파일은 병합 때 충돌하지 않는다. #4·#5·#7의 `playback.py`가 첫 사례다.

**완료 기준**: 맡긴 이슈마다 작업자 화면에서 "Working"이 보인다.

### 3. 기다리며 메시지 처리

`check --run <run> --wait --types "worker_done,escalation,question"`을 백그라운드로 돌려 **깨어나는 신호로만** 쓴다. 그 출력은 파일로 받든 grep을 거치든 한국어가 깨진다. 깨어나면 내용은 `check --run <run> --json | PYTHONIOENCODING=utf-8 python -I -c "..."`처럼 python으로 바로 넘겨 다시 읽는다. ack하기 전까지는 같은 묶음이 다시 나온다.

- **heartbeat**: ack하고 계속 기다린다. 사용자에게는 단계만 한 줄로 알린다.
- **question**: 이슈, 스펙 #1, `CONTEXT.md`, ADR에 답이 있으면 답한다. 사용자만 정할 수 있는 결정이면 사용자에게 묻고, 받은 답을 전달한다.
- **worker_done**: 4단계로 간다.

메시지를 처리하기 전에는 ack하지 않는다.

### 4. 교차 검토

구현 작업자가 끝나면 그 작업자를 `worker-retain`으로 남겨 둔다(수정 지시에 재사용). 그다음 [review-template.md](review-template.md)를 채워 새 Claude 작업자를 **같은 worktree**(`--worktree "id:<worktree id>"`, `--agent claude`)에 띄운다.

**완료 기준**: 검토 보고서 파일이 생겼고, 결론이 "통과" 또는 "수정 필요"다.

### 5. 판정

지적마다 셋 중 하나로 정한다.

- **지금 고침**: 차단·중요 지적 전부. 사소한 지적 중 고치는 비용이 작은 것.
- **다른 이슈로 넘김**: 다른 이슈의 범위에 속하는 것. 그 이슈에 댓글로 근거와 함께 기록한다.
- **사용자에게 물음**: 제품 방향을 정해야 하는 것(예: GIF를 영상으로 볼지).

고칠 것이 있으면 남겨 둔 Codex 터미널에 수정 명세를 보낸다(`worker-start --spec ... --worktree "id:..." --terminal <codex handle>`). 명세에는 검토 보고서 경로, 고칠 지적 목록, 고치지 않을 지적 목록을 적는다. 수정이 끝나면 같은 검토자 터미널에 **재검토**를 맡긴다(수정분 `git diff <이전 커밋>..HEAD`, 고친 지적의 재현 절차 재실행). 통과할 때까지 반복한다.

**완료 기준**: 마지막 검토 결론이 "통과"이고, 넘긴 지적은 모두 해당 이슈에 댓글로 남았다.

### 6. PR과 병합

1. 브랜치를 push하고 [pr-template.md](pr-template.md)로 PR을 만든다(`Closes #<n>`).
2. `main`이 그사이 앞으로 갔으면, 해당 Codex 작업자에게 `main` 위로 rebase하고 테스트를 다시 돌리라고 맡긴다. 충돌 해결도 작업자가 한다. "main 변경" 안내는 **진행 중인 Dispatch가 구현 작업일 때만** 보낸다. 검토 중인 이슈는 그 검토가 끝난 뒤 다음 구현 지시에 rebase를 넣는다(검토자에게 rebase 안내를 보내지 않는다).
3. `gh pr merge <PR> --merge --subject "<한국어 제목> (#<n>)"`로 병합하고, 원격 브랜치를 지우고, 메인 저장소의 `main`을 pull한다.
4. 작업자들을 `worker-release`로 정리한다. 재사용한 터미널은 `retained`(`user_takeover` 등)로 남을 수 있다. `worker-list --run <run> --terminal-state reclaimable`이 0이면 정리가 끝난 것이다.

**완료 기준**: 이슈가 닫혔고, `main`이 원격과 일치하고, 정리할 작업자가 0명이다.

### 7. 보고하고 다음 묶음

사용자에게 이슈마다 결과(PR 링크, 테스트 수, 검토 횟수와 주요 지적, 넘긴 지적, 시스템 변경)와 **사람이 직접 확인할 항목**을 모아 보고한다. 사용자가 확인할 때는 `.local/테스트 라이브러리/`를 쓰도록 안내한다. 그다음 1단계로 돌아가 새 프런티어를 채운다.

**완료 기준**: 열린 `ready-for-agent` 이슈가 없거나, 사용자가 멈추라고 했다.
