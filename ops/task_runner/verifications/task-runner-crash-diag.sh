#!/bin/bash
# Post-mortem diagnostic for the task-runner's own state: launchd logs,
# last N lines of stderr/stdout, process status, lock file, git status,
# and recent preflight gaps. Helps catch silent crashes.
set -u

ROOT="/Users/bob/AI-Server"
LABEL="com.symphony.task-runner"
STDOUT_LOG="$ROOT/data/task_runner/launchd.out.log"
STDERR_LOG="$ROOT/data/task_runner/launchd.err.log"
LOCK="$ROOT/data/task_runner/.runner.lock"
HB="$ROOT/data/task_runner/heartbeat.txt"

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
whoami
echo

echo "=== 1. process status ==="
pid=$(launchctl list 2>/dev/null | awk -v l="$LABEL" '$3==l {print $1}')
rc=$(launchctl list 2>/dev/null | awk -v l="$LABEL" '$3==l {print $2}')
echo "  pid: ${pid:-<none>}"
echo "  last exit: ${rc:-<none>}"
if [ -n "${pid:-}" ] && [ "$pid" != "-" ]; then
  ps -p "$pid" -o pid,etime,pcpu,pmem,command 2>/dev/null
fi
echo

echo "=== 2. heartbeat + lock ==="
if [ -f "$HB" ]; then
  cat "$HB"
  echo ""
  # age of heartbeat
  hb_epoch=$(stat -f %m "$HB" 2>/dev/null || stat -c %Y "$HB" 2>/dev/null)
  now=$(date +%s)
  age=$((now - hb_epoch))
  echo "  age_seconds: $age"
fi
if [ -f "$LOCK" ]; then
  echo "  lock present:"
  ls -la "$LOCK"
  cat "$LOCK" 2>/dev/null | head -5
else
  echo "  no lock file"
fi
echo

echo "=== 3. launchd stdout log tail (60 lines) ==="
if [ -f "$STDOUT_LOG" ]; then
  wc -l "$STDOUT_LOG"
  tail -60 "$STDOUT_LOG"
else
  echo "  missing: $STDOUT_LOG"
fi
echo

echo "=== 4. launchd stderr log tail (60 lines) ==="
if [ -f "$STDERR_LOG" ]; then
  wc -l "$STDERR_LOG"
  tail -60 "$STDERR_LOG"
else
  echo "  missing: $STDERR_LOG"
fi
echo

echo "=== 5. launchctl print (state, last exit, throttle backoff) ==="
UID_BOB="$(id -u bob)"
launchctl print "gui/${UID_BOB}/${LABEL}" 2>&1 | \
  awk '/state|last exit|runs|spawns|path|WatchPaths|StartInterval|ThrottleInterval|LimitLoadToSessionType|program/ {print}' | \
  head -40
echo

echo "=== 6. git state around ops/ ==="
cd "$ROOT"
git status --short 2>&1 | head -20
echo
git log --oneline -5 2>&1
echo

echo "=== 7. pending queue ==="
ls -la "$ROOT/ops/work_queue/pending/" 2>/dev/null | head -10
echo

echo "=== 8. last 3 preflight result timestamps ==="
ls -t "$ROOT/ops/verification/"*-preflight.txt 2>/dev/null | head -3 | while read p; do
  stat -f '%Sm  %N' "$p" 2>/dev/null || stat -c '%y  %n' "$p" 2>/dev/null
done
echo

echo "=== 9. any python task_runner.py processes ==="
ps auxww | grep task_runner | grep -v grep | head -5
