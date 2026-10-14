# my-video-manager

## 작성 규칙

- 커밋 메시지, PR 제목·본문, 이슈 등 git/GitHub에 남기는 메시지는 모두 한국어로 작성한다. 코드 식별자·파일 경로·기술 용어는 원문 그대로 둔다.

## 웹 UI 완료 조건

- `frontend/` 변경은 해당 폴더에서 `npm run lint`, `npm run typecheck`, `npm run build`가 모두 통과해야 완료다.
- 브리지 계약을 바꾸면 `scripts/generate_web_types.py`로 타입을 생성하고 pytest를 실행한다.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (vananaHope/my-video-manager), managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
