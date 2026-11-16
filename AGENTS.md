# my-video-manager

This codebase is yours: what it's for and how it's built are your call, and you'll keep building on it.

## 작성 규칙

- 사용자에게 하는 답변은 질문 언어와 상관없이 항상 한국어로 작성한다. 코드 식별자·파일 경로·명령어·기술 용어는 원문 그대로 둔다.
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

이 스킬은 vstack 플러그인의 `/vstack:orchestrate-issues`이고 Orca에서 쓴다(herdr app, omp, T3 Code로는 지휘하지 않는다).

- `orchestration.md`의 모든 절과 `common-findings.md`를 따른다.
- worktree 정리·생성은 스킬의 실행 환경 문서(Orca)를 따른다. 이 저장소의 worktree 준비 명령은 `scripts/setup.ps1 -Worktree`다.
- 문서의 `~/.agent-orchestra/bin/desktop_lock.py run ... -- <명령>`은 이 스크립트가 없으면 `<명령>`만 실행한다. 실창 검사는 한 번에 하나만 돌린다.
