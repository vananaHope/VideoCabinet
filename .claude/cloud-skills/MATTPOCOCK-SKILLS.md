# mattpocock/skills 출처

아래 38개 스킬 폴더는 https://github.com/mattpocock/skills 의
`abeeaf95660ba9e8b7c753eb38f441ca707a8823` 커밋(2026-11-19)에서 그대로 복사했다.
원 저장소는 MIT 라이선스이며 전문은 `LICENSE.mattpocock-skills`에 있다.

- engineering: ask-matt, matt-code-review(원래 code-review), codebase-design, diagnosing-bugs, domain-modeling, grill-with-docs, implement, implement-spec, improve-codebase-architecture, pr, prototype, research, retro, setup-matt-pocock-skills, tdd, to-spec, to-tickets, triage, wayfinder, wizard
- productivity: grill-me, grilling, handoff, teach, to-questionnaire, wait-what, writing-for-agents
- misc: git-guardrails-claude-code, migrate-to-shoehorn, scaffold-exercises, setup-pre-commit
- in-progress(원 저장소에서 베타): chief-of-staff, claude-handoff, loop-me, setup-ts-deep-modules, software-factory, writing-beats, writing-fragments, writing-shape

## 위치와 로드 방식

이 스킬들은 Claude Code 클라우드(웹) 세션에서만 쓴다. 그래서 스킬 탐색 경로인 `.claude/skills/`가 아니라 `.claude/cloud-skills/`에 둔다. 로컬 클론에서 Claude Code를 열면 이 폴더를 읽지 않으므로 스킬이 보이지 않는다.

클라우드 세션에서는 `.claude/hooks/session-start.sh`가 `CLAUDE_CODE_REMOTE=true`일 때만 각 스킬 폴더를 `~/.claude/skills/`로 복사하고, hook 출력의 `reloadSkills: true`로 스킬 목록을 다시 읽게 한다. 로컬에서도 쓰고 싶은 스킬이 생기면 그 폴더만 `.claude/skills/`로 옮긴다.

## 갱신

원 저장소의 같은 경로에서 폴더를 다시 복사해 `.claude/cloud-skills/` 아래에 덮어쓰고 위 커밋 해시를 바꾼다. `.claude/skills/`에 넣지 않는다.
원본 `code-review`는 Claude Code 내장 `/code-review`를 가리지 않도록 `matt-code-review`로 이름을 바꿨다(폴더, `name:`, ask-matt·implement·implement-spec·tdd의 참조). 갱신할 때 이 이름 변경을 다시 적용한다.
