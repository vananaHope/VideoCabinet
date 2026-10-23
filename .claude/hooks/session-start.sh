#!/bin/bash
# Claude Code 클라우드(Linux) 세션에서 pytest와 frontend 검사를 바로 돌릴 수 있게 준비한다.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

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
