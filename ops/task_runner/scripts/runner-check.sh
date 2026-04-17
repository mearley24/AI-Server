#!/bin/bash
# Snapshot current task-runner state + logs into a committed verification
# file so we can see why it's not ticking. Paste-free.
set -uo pipefail

cd /Users/bob/AI-Server || exit 2
git pull --ff-only origin main 2>&1 | tail -3 || true

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
OUT="ops/verification/${STAMP}-runner-check.txt"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== runner-check @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="

  echo; echo "--- launchctl print full ---"
  launchctl print "gui/$(id -u)/com.symphony.task-runner" 2>&1 | head -80

  echo; echo "--- last 60 lines of launchd.out.log ---"
  tail -60 data/task_runner/launchd.out.log 2>/dev/null || echo "(no log)"

  echo; echo "--- last 30 lines of launchd.err.log ---"
  tail -30 data/task_runner/launchd.err.log 2>/dev/null || echo "(no log)"

  echo; echo "--- heartbeat ---"
  cat data/task_runner/heartbeat.txt 2>/dev/null

  echo; echo "--- python version / cryptography import test ---"
  /opt/homebrew/bin/python3 -c "import cryptography; print('cryptography', cryptography.__version__)" 2>&1

  echo; echo "--- manual task_runner.py --help (does it even import?) ---"
  /opt/homebrew/bin/python3 /Users/bob/AI-Server/scripts/task_runner.py --help 2>&1 | head -20

  echo; echo "--- manual single-tick smoke test (blocks up to 60s) ---"
  timeout 60 /opt/homebrew/bin/python3 /Users/bob/AI-Server/scripts/task_runner.py 2>&1 | tail -40
  echo "exit=$?"

  echo; echo "--- heartbeat after manual tick ---"
  cat data/task_runner/heartbeat.txt 2>/dev/null

  echo; echo "--- done ---"
} | tee "$OUT"

git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" add "$OUT"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" commit -m "ops: runner-check diagnostic ${STAMP}"
git push origin main
