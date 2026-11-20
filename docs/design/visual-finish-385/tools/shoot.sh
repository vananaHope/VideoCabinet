#!/bin/bash
# #299와 같은 범위로 다시 찍는다. 저장소 루트에서: bash docs/design/visual-finish-385/tools/shoot.sh
# 출력은 .local/s385/<변형>/{1100,max}, 요약은 .local/s385/summary.txt. '@'로 시작하는 스크립트는 relax.py 사본이다.
set -u
REPO=$(cd "$(dirname "$0")/../../../.." && pwd); OUT=$REPO/.local/s385; TOOLS=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"; source "$REPO/.venv/bin/activate"
python "$TOOLS/relax.py" "$REPO" "$OUT/relaxed" >/dev/null || exit 1
run() {
  IFS='|' read -r tag script args <<< "$1"
  case $script in @*) script=$OUT/relaxed/${script#@} ;; *) script=scripts/$script ;; esac
  rm -rf "$OUT/$tag"; mkdir -p "$OUT/$tag"; cd "$REPO"
  MVM_SHOT_MAX_DIR=$OUT/$tag/max MVM_SHOT_FONT_LOG=$OUT/$tag/fonts.log timeout 600 \
    python scripts/linux_offscreen_check.py "$script" --offscreen $args --output "$OUT/$tag/1100" > "$OUT/$tag/log.txt" 2>&1
  echo "$tag rc=$? n1100=$(ls "$OUT/$tag/1100" | grep -c png) nmax=$(ls "$OUT/$tag/max" 2>/dev/null | grep -c png)" >> "$OUT/summary.txt"
}
export -f run; export OUT REPO
xargs -d '\n' -P 3 -I{} bash -c 'run "$@"' _ {} < "$TOOLS/variants.txt"
python "$TOOLS/select.py" "$OUT" "$REPO/docs/design/visual-finish-299/screens" "$REPO/docs/design/visual-finish-385/screens" "$TOOLS/extra.txt"
