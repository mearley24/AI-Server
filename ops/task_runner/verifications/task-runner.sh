#!/bin/bash
# Verification dump for the task runner itself. Proves to a remote agent
# (Perplexity Computer, future Cline session) that the control plane is alive.
set -u

cd /Users/bob/AI-Server

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
whoami
git rev-parse --short HEAD
echo

echo "=== 1. launchd status ==="
launchctl list | grep task-runner || echo "no task-runner agent loaded"
echo

echo "=== 2. heartbeat ==="
cat data/task_runner/heartbeat.txt 2>/dev/null || echo "no heartbeat yet"
echo

echo "=== 3. lock file ==="
ls -la data/task_runner/.runner.lock 2>/dev/null || echo "no lock file"
echo

echo "=== 4. last 30 lines of launchd stdout ==="
tail -30 data/task_runner/launchd.out.log 2>/dev/null || echo "no launchd.out.log"
echo

echo "=== 5. last 30 lines of launchd stderr ==="
tail -30 data/task_runner/launchd.err.log 2>/dev/null || echo "no launchd.err.log"
echo

echo "=== 6. work_queue directory counts ==="
for d in pending completed failed rejected; do
  dir="ops/work_queue/$d"
  n=$(ls -1 "$dir" 2>/dev/null | wc -l | tr -d ' ')
  echo "$d: $n"
done
echo

echo "=== 7. last 10 completed tasks ==="
ls -lt ops/work_queue/completed/ 2>/dev/null | head -11 || echo "none"
echo

echo "=== 8. last 10 failed tasks ==="
ls -lt ops/work_queue/failed/ 2>/dev/null | head -11 || echo "none"
echo

echo "=== 9. last 10 rejected tasks ==="
ls -lt ops/work_queue/rejected/ 2>/dev/null | head -11 || echo "none"
echo

echo "=== 10. recent verification results ==="
ls -lt ops/verification/ 2>/dev/null | head -11 || echo "none"
echo

echo "=== 11. authorized keys (names only; pubkeys truncated) ==="
awk 'NF && !/^#/{printf "%s %s…\n", $1, substr($2,1,12)}' \
  ops/work_queue/AUTHORIZED_KEYS.txt 2>/dev/null \
  || echo "no AUTHORIZED_KEYS.txt"
echo

echo "=== 12. recent runner commits ==="
git log --oneline -n 10 --author='Perplexity Computer' -- ops/ data/task_runner/ \
  2>/dev/null || echo "no matching commits yet"
echo

echo "=== 13. remote sync state ==="
git fetch origin main --quiet 2>&1 || true
git log --oneline origin/main...HEAD 2>/dev/null | head -5 \
  || echo "in sync with origin/main"
