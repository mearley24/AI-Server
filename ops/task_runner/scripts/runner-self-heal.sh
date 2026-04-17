#!/bin/bash
# runner-self-heal: for when the task-runner is stuck because its working
# tree has uncommitted mods blocking 'git pull --ff-only'. Stashes local
# changes, pulls, re-bootstraps the runner plist, kickstarts.
#
# Safe to run standalone. Paper-trails everything to
# ops/verification/YYYYMMDD-HHMMSS-runner-self-heal.txt.
set -uo pipefail

ROOT="/Users/bob/AI-Server"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$ROOT/ops/verification/${STAMP}-runner-self-heal.txt"
LABEL="com.symphony.task-runner"
UID_BOB="$(id -u)"
TARGET="gui/${UID_BOB}/${LABEL}"

mkdir -p "$(dirname "$OUT")"
cd "$ROOT"

{
  echo "=== runner self-heal ==="
  echo "stamp: $STAMP"
  echo ""
  echo "--- pre status ---"
  git status --porcelain=v1
  echo ""
  echo "--- HEAD ---"
  git log -1 --format="%h %ci %s"
  echo ""
  echo "--- stash (if dirty) ---"
  if [ -n "$(git status --porcelain=v1)" ]; then
    git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
      stash push -u -m "runner-self-heal ${STAMP}" 2>&1 || echo "(stash rc=$?)"
  else
    echo "(clean)"
  fi
  echo ""
  echo "--- pull ---"
  git pull --ff-only origin main 2>&1 || echo "(pull rc=$?)"
  echo ""
  echo "--- re-bootstrap runner plist ---"
  bash "$ROOT/ops/task_runner/scripts/install-task-runner-plist.sh" 2>&1 || echo "(install rc=$?)"
  echo ""
  echo "--- kickstart (force immediate tick) ---"
  launchctl kickstart -k "$TARGET" 2>&1 || echo "(kick rc=$?)"
  echo ""
  echo "--- post state ---"
  launchctl print "$TARGET" 2>&1 | awk '/state|path/' | head -10
  echo ""
  echo "--- HEAD after ---"
  git log -1 --format="%h %ci %s"
} | tee "$OUT"

# Commit the verification file so it's visible from sandbox.
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  add "$OUT" 2>&1 || true
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  commit -m "ops: runner-self-heal ${STAMP}" 2>&1 || echo "(commit rc=$?)"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  push origin main 2>&1 || echo "(push rc=$?)"

echo "ok: self-heal done. report at $OUT"
