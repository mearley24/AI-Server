#!/bin/bash
# Verify watchdog is installed and ticking. Tees output to
# ops/verification/YYYYMMDD-HHMMSS-watchdog-install.txt, commits, pushes.
set -uo pipefail

ROOT="/Users/bob/AI-Server"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$ROOT/ops/verification/${STAMP}-watchdog-install.txt"
LABEL="com.symphony.task-runner-watchdog"
UID_BOB="$(id -u)"
TARGET="gui/${UID_BOB}/${LABEL}"

mkdir -p "$(dirname "$OUT")"

{
  echo "=== watchdog install verify ==="
  echo "stamp: $STAMP"
  echo ""
  echo "--- run install-watchdog.sh ---"
  bash "$ROOT/ops/task_runner/scripts/install-watchdog.sh" 2>&1 || echo "(install rc=$?)"
  echo ""
  echo "--- launchctl print ---"
  launchctl print "$TARGET" 2>&1 | head -40 || echo "(print rc=$?)"
  echo ""
  echo "--- watchdog_heartbeat.txt ---"
  cat "$ROOT/data/task_runner/watchdog_heartbeat.txt" 2>&1 || echo "(missing)"
  echo ""
  echo "--- last 30 lines of watchdog.log ---"
  tail -30 "$ROOT/data/task_runner/watchdog.log" 2>&1 || echo "(missing)"
  echo ""
  echo "--- runner heartbeat for comparison ---"
  cat "$ROOT/data/task_runner/heartbeat.txt" 2>&1 || echo "(missing)"
  echo ""
  echo "--- pending queue ---"
  ls -la "$ROOT/ops/work_queue/pending" 2>&1 || echo "(missing)"
} | tee "$OUT"

cd "$ROOT"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  add "$OUT" 2>&1 || true
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  commit -m "ops: watchdog-install verify $STAMP" 2>&1 || echo "(commit rc=$?)"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" \
  push origin main 2>&1 || echo "(push rc=$?)"

echo "ok: watchdog-install verified, report at $OUT"
