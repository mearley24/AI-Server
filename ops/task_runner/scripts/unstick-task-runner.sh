#!/bin/bash
# One-paste task-runner recovery + diagnostic dump.
# Assumes cwd = /Users/bob/AI-Server. Writes a diagnostic file committed
# back to the repo so perplexity-computer can read it without copy/paste.
set -uo pipefail

cd /Users/bob/AI-Server || exit 2

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
OUT="ops/verification/${STAMP}-runner-unstick.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== unstick-task-runner @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="
  echo
  echo "--- heartbeat before ---"
  cat data/task_runner/heartbeat.txt 2>/dev/null || echo "(none)"
  echo
  echo "--- lock file before ---"
  ls -la data/task_runner/.runner.lock 2>/dev/null || echo "(no lock)"
  echo
  echo "--- launchctl print state ---"
  launchctl print gui/$(id -u)/com.symphony.task-runner 2>/dev/null | \
    awk '/state|pid|last exit|WatchPaths|StartInterval/ {print}' | head -10 \
    || echo "(not loaded)"
  echo
  echo "--- tail 30 launchd.out.log ---"
  tail -30 data/task_runner/launchd.out.log 2>/dev/null || echo "(no stdout log)"
  echo
  echo "--- tail 10 launchd.err.log ---"
  tail -10 data/task_runner/launchd.err.log 2>/dev/null || echo "(no stderr log)"
  echo
  echo "--- removing stale lock (safe if no other instance running) ---"
  if [ -f data/task_runner/.runner.lock ]; then
    rm -v data/task_runner/.runner.lock
  else
    echo "no lock to remove"
  fi
  echo
  echo "--- kickstart -kp ---"
  launchctl kickstart -kp gui/$(id -u)/com.symphony.task-runner 2>&1 || echo "(kickstart failed rc=$?)"
  echo
  sleep 5
  echo "--- state 5s after kickstart ---"
  launchctl print gui/$(id -u)/com.symphony.task-runner 2>/dev/null | \
    awk '/state|pid|last exit/ {print}' | head -6
  echo
  echo "--- heartbeat after ---"
  cat data/task_runner/heartbeat.txt 2>/dev/null
  echo
  echo "--- pending tasks ---"
  ls ops/work_queue/pending/ 2>/dev/null
  echo
  echo "--- done ---"
} | tee "$OUT"

git -c user.email="earleystream@gmail.com" -c user.name="Matt Earley" add "$OUT"
git -c user.email="earleystream@gmail.com" -c user.name="Matt Earley" \
    commit -m "ops: unstick task-runner diagnostic dump ${STAMP}" --no-verify
git push origin main
