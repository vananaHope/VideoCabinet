# omp 이슈 지휘 절차

Orca 대신 herdr-app(herdr-core `hc`)과 omp로 여러 이슈를 동시에 처리하는 절차다. 이슈 저장소·병합·구현 제약·테스트·추가 완료 조건·실창 검사의 기준은 `orchestration.md`와 `common-findings.md`를 그대로 따르고, 이 문서는 누가 어떻게 띄우고 주고받는지만 정한다.

## 구성

| 역할 | 실행 위치 | 모델 |
| --- | --- | --- |
| 관리자 | herdr-app 터미널 안의 omp 세션. 코드를 직접 쓰지 않는다 | omp 기본(`modelRoles.default`) |
| 구현 작업자 | 이슈마다 `hc run --bg`로 띄운 omp 세션 하나. 이슈 worktree에서 일하고 AGENTS.md를 직접 읽는다 | 아래 "배치" |
| 교차 검토자 | 관리자의 omp 하위 에이전트(`task` 도구). 구현자와 다른 계열 | 아래 "배치" |

준비 조건:
- 관리자 세션의 `HC_TERMINAL_ID`가 있어야 한다. 없으면 herdr-app에서 터미널을 열고 `omp -c`로 이어 간다. 작업자가 관리자의 자식이 되어야 `hc wait --children`과 `hc send` 보고가 동작한다.
- 사용자 범위 에이전트 `~/.omp/agent/agents/claude-reviewer.md`: 내장 `reviewer`(`omp agents unpack`)를 복사해 `name: claude-reviewer`, `model: "@plan"`으로 바꾼 것. 내장 `reviewer`는 `@slow`(Codex)다.

## 배치

| 일 | 작업자 실행 | 검토자 |
| --- | --- | --- |
| UI 작업(`orchestration.md` "UI 작업") | `omp --model anthropic/claude-opus-5-5 --thinking high` | `reviewer`(Codex) |
| 그 밖 | `omp --model openai-codex/gpt-6-astra --thinking high` | `claude-reviewer` |

동시성·잠금·프로세스 수명을 다루는 일은 작아 보여도 위 표 그대로 `high`로 띄운다. `orchestration.md`의 "등급별 배치", "작업자 실패 알림", "Codex fast"는 vstack 스킬(Orca) 전용이라 쓰지 않는다. 한도는 `omp usage`로 본다.

## 작업 파일

메인 폴더 `.local/orchestration/issue-<번호>/`(Git 제외)에 둔다.

| 파일 | 쓰는 쪽 | 내용 |
| --- | --- | --- |
| `task.md` | 관리자 | 작업 명세(아래 "명세") |
| `state.md` | 관리자 | 첫 줄 단계(`구현 중` → `검토 중` → `수정 중` → `끝`), 둘째 줄 모델·검토자·PR |
| `report.md` | 작업자 | 완료 보고. 수정할 때마다 절을 더한다 |
| `review-<k>.md` | 관리자 | 검토 결과와 판정, 수정 지시 |
| `pr.md` | 관리자 | PR 본문 |

실창 차례는 `.local/orchestration/desktop.lock.md` 한 줄(`실창: 비어 있음` 또는 `실창: issue-<번호> 사용 중`)로 기록한다.

## 단계

### 1. 고르기

`orchestration.md` "이슈 저장소"대로 `ready-for-agent`이고 선행 이슈가 모두 닫힌 이슈 중, 뒤에 기다리는 이슈 사슬이 가장 긴 것부터 고른다. 진행 중인 이슈와 같은 파일 영역을 크게 건드리면 함께 띄우지 않는다. 한 번에 2~3개로 시작한다.

### 2. worktree와 명세

- worktree는 사용자 공통 지시의 "이슈 worktree" 절대로 만든다. 준비 명령(`scripts/setup.ps1 -Worktree`)은 작업자가 첫 단계로 돌린다.
- `task.md`에 다음 절을 쓴다.
  - **먼저 읽을 것**: `gh issue view <번호> --comments`, 완료 기준은 이슈의 "Acceptance criteria", `orchestration.md` "스펙과 먼저 읽을 문서".
  - **Target / Change**: 다룰 영역, 완료 기준 요약, 해당하면 `orchestration.md` "추가 완료 조건".
  - **Constraints**: `orchestration.md` "구현 제약", 범위 밖 이슈 번호와 기능, 한국어 커밋(영어 머리말 없이), push·PR·병합 금지, worktree 밖 파일 금지, `hc`로 다른 에이전트를 띄우지 않음(omp 하위 에이전트는 허용).
  - **실창 검사**: 아래 "실창 차례" 절차.
  - **Ownership**: 동시에 도는 이슈와 겹칠 수 있는 공용 파일.
  - **테스트 실행**: 관련 시험만. 전체 시험은 완료 기준이 요구할 때만. 시간 초과는 다시 돌리지 말고 보고.
  - **자기 점검**: `common-findings.md` 유형별 "해당 없음 / 확인함(방법) / 남김(이유)".
  - **완료 보고**: `report.md`에 커밋, 시험 결과, 완료 기준별 근거, 설치한 것, 사람이 확인할 항목, 판단한 것을 쓰고 `hc send <관리자 ID> "issue-<번호> 완료: <한 줄>"`. 질문은 `hc send <관리자 ID> "issue-<번호> 질문: ..."` 뒤 답을 기다린다.

### 3. 띄우기

```sh
hc run --bg --outlive-parent --name issue-<번호> --label issue=<번호> --cwd <worktree> \
  omp --model <배치의 모델> --thinking high "<task.md 절대 경로> 를 읽고 그 명세대로 이슈 #<번호>를 구현해. 끝나거나 막히면 명세대로 hc send <관리자 ID> 로 보고해."
```

`--outlive-parent`라서 관리자 세션이 끝나도 작업자는 계속 돈다. 40초쯤 뒤 `hc get issue-<번호>`의 `status.state`가 `working`인지 본다.

### 4. 기다리며 메시지 처리

- `hc wait --children any`로 기다린다. 작업자의 `hc send`는 관리자 입력으로 들어온다.
- **작업자에게 보낼 때**: `hc get`의 상태가 `working`이면 보내지 않는다(일하는 중에 보낸 지시가 사라진 적이 있다). `idle`·`done`일 때 보내고, 몇 초 뒤 `working`으로 바뀌었는지 확인한다. 바뀌지 않으면 `hc read`로 화면을 보고 다시 보낸다.
- **진행 확인**은 읽기 전용으로만 한다: `hc get`, `git -C <worktree> log/status/diff --stat`. 작업자 worktree의 인덱스나 파일을 바꾸는 명령(`git add -N` 등)은 쓰지 않는다.
- **질문**: 이슈·스펙·문서로 답할 수 있으면 근거와 함께 답하고, 제품 방향이면 사용자에게 묻는다.

### 5. 실창 차례

작업자는 실창이 필요하면 `hc send <관리자 ID> "issue-<번호> 실창 차례 요청"`을 보내고 "실창 시작"을 기다린다. 관리자는 `desktop.lock.md`가 비어 있으면 그 작업자에게 "실창 시작"을 보내고 기록한다. 다른 작업자가 쓰는 중이면 "실창 끝"이 올 때까지 미룬다. offscreen 스크린샷은 차례 없이 찍는다.

### 6. 교차 검토와 판정

- 완료 보고가 오면 배치의 검토자를 관리자의 하위 에이전트로 띄운다. **하위 에이전트에는 AGENTS.md가 전달되지 않으므로** 구현 제약·이슈 규칙을 `context`에 직접 적는다. 검토 대상은 worktree 경로와 커밋, 이슈 완료 기준, `report.md`, `common-findings.md`다. 검토자는 파일을 고치거나 빌드·시험을 돌리지 않는다.
- 지적마다 판정한다: **지금 고침**(차단·중요 전부, 싸게 고칠 사소한 것), **다른 이슈로 넘김**(범위 밖이면 `needs-triage` 새 이슈나 해당 이슈 댓글), **사용자에게 물음**(제품 방향).
- 지금 고칠 것이 있으면 `review-<k>.md`에 지적·고칠 방향·회귀 시험 요구(지금 코드에서 실패해야 함)를 쓰고 작업자에게 보낸다. 고친 커밋은 같은 계열 검토자에게 **수정 커밋만** 재검토시킨다. 수정이 새 회귀를 만드는 일이 흔하므로 재검토는 생략하지 않는다.
- 같은 유형의 지적이 두 번째로 나오면 `orchestration.md`의 원칙대로 검사로 막을 수 있는지 먼저 보고, 못 막으면 `common-findings.md`에 더한다.

### 7. rebase

`main`이 앞으로 갔으면 병합 전에 작업자에게 맡긴다: `origin/main` 위로 rebase, **`scripts/setup.ps1 -Worktree` 다시 실행**(다른 이슈가 더한 의존성 반영), 대상 시험과 frontend 검사, 완료 기준이 요구하면 전체 시험. 관리자는 `git range-diff`로 rebase 전후 변경이 같은지 본다.

### 8. PR과 병합

- `pr.md`: `Closes #<번호>`, 요약(사용자 관점 2~3문장과 주요 변경), 검증(구현 모델과 시험 결과, 교차 검토 회차별 결론과 넘긴 지적), 사람이 직접 확인할 항목(체크리스트), 시스템 변경. 서명 줄은 넣지 않는다.
- 관리자가 `git push -u origin HEAD`, `gh pr create --body-file pr.md`, `gh pr checks`, `gh pr merge <PR> --squash --subject "<한국어 제목> (#<번호>)"`.

### 9. 정리와 다음

- `hc kill issue-<번호>`, `hc rm issue-<번호>`.
- worktree와 브랜치는 사용자 공통 지시의 "정리" 절대로 지운다. Windows에서 `git worktree remove`가 실패하고 폴더가 남으면, 변경이 없음을 확인한 뒤 폴더를 지우고 `git worktree prune`을 돌린다.
- 메인 폴더에서 `git pull --ff-only`, `state.md`를 `끝`으로.
- 바로 1단계로 돌아가 빈 자리를 채운다. 사용자에게는 이슈별 PR, 검토 회차와 주요 지적, 넘긴 지적, 사람이 확인할 항목을 보고한다.
