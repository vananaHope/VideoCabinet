# my-video-manager

## 작성 규칙

- 커밋 메시지, PR 제목·본문, 이슈 등 git/GitHub에 남기는 메시지는 모두 한국어로 작성한다. 코드 식별자·파일 경로·기술 용어는 원문 그대로 둔다.

## 웹 UI 완료 조건

- 앱은 단일 웹 셸을 기본으로 사용한다. 재생·트레이·공용 네이티브 경고만 Qt로 남긴다.
- 준비·개발 서버 연결·새 웹 페이지 등록은 `docs/development.md`(요약은 README)의 해당 절을 따른다. 페이지 추가 때 Python·React 등록부와 생성 계약을 함께 갱신한다.
- `frontend/` 변경은 해당 폴더에서 `npm run lint`, `npm run typecheck`, `npm run build`가 모두 통과해야 완료다.
- 브리지 계약을 바꾸면 `scripts/generate_web_types.py`로 타입을 생성하고 pytest를 실행한다.
- UI 검사는 `scripts/check_web_*.py --offscreen`으로 1100×720 화면을 확인하고, 실창에서 탭·단축키·mpv 왕복·대화상자·트레이를 확인한다.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (vananaHope/my-video-manager), managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Issue orchestration

Settings for the `orchestrate-issues` skill (vstack plugin). See `docs/agents/orchestration.md` and `docs/agents/common-findings.md`.

이 스킬은 vstack 플러그인의 `/vstack:orchestrate-issues`이고 Orca에서 쓴다(herdr app 실행 환경 문서도 있지만 vstack에서 검증하지 않았다. T3 Code는 다루지 않는다). omp에서는 스킬을 찾지 말고 `docs/agents/omp-orchestration.md`의 절차로 지휘한다.

- `orchestration.md`의 스킬 전용 절(등급별 배치, 작업자 실패 알림, Codex fast)은 omp에서 쓰지 않는다. 배치는 `omp-orchestration.md`를 따른다.
- 나머지 절(이슈 저장소, 병합, 구현 제약, 테스트, 추가 완료 조건, 실창 검사)과 `common-findings.md`는 환경과 관계없이 따른다.
- worktree 정리·생성은 스킬로 지휘하면 스킬의 실행 환경 문서를, omp에서는 `~/.omp/agent/AGENTS.md`의 "이슈 worktree" 절을 따른다. 이 저장소의 worktree 준비 명령은 `scripts/setup.ps1 -Worktree`다.
- 문서의 `~/.agent-orchestra/bin/desktop_lock.py run ... -- <명령>`은 이 스크립트가 없으면 `<명령>`만 실행한다. 실창 검사는 한 번에 하나만 돌리고, omp 지휘에서는 `omp-orchestration.md`의 "실창 차례"로 순서를 정한다.
