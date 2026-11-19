#!/bin/bash
# Claude Code 클라우드(Linux) 세션에서 pytest와 frontend 검사를 바로 돌릴 수 있게 준비한다.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# stdout은 hook 결과 JSON 전용으로 남기고, 나머지 출력은 stderr로 보낸다.
exec 3>&1 1>&2

# 클라우드 전용 스킬(.claude/cloud-skills)을 개인 스킬 위치로 복사한다.
# 로컬 클론에서는 .claude/cloud-skills가 스킬 탐색 경로가 아니라서 보이지 않는다.
SKILLS_SRC="$CLAUDE_PROJECT_DIR/.claude/cloud-skills"
SKILLS_DEST="$HOME/.claude/skills"
mkdir -p "$SKILLS_DEST"
for skill in "$SKILLS_SRC"/*/; do
  name="$(basename "$skill")"
  rm -rf "${SKILLS_DEST:?}/$name"
  cp -r "$skill" "$SKILLS_DEST/$name"
done
# 스킬 탐색은 보통 SessionStart hook보다 먼저 끝나므로, 이후 단계가 실패해도 다시 읽게 한다.
trap 'echo "{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"reloadSkills\":true}}" >&3' EXIT

# PySide6(QtWebEngine)가 offscreen에서도 요구하는 시스템 라이브러리.
QT_LIBS="libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libnss3"
if ! dpkg -s $QT_LIBS >/dev/null 2>&1; then
  apt-get install -y -q $QT_LIBS >/dev/null 2>&1 \
    || { apt-get update -q >/dev/null && apt-get install -y -q $QT_LIBS >/dev/null; }
fi

# 생성 타입의 유니코드 표가 저장소 기준(Python 3.10)과 같도록 3.10 가상 환경을 쓴다.
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 10))'; then
  rm -rf .venv
  uv venv -q .venv -p 3.10
fi
uv pip install -q -p .venv -e ".[dev]"

# 웹 셸 파일(src/my_video_manager/web)을 만들어 둔다.
(cd frontend && npm install --no-audit --no-fund --loglevel=error && npm run build >/dev/null)

echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\"" >> "$CLAUDE_ENV_FILE"
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
