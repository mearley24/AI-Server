#!/usr/bin/env bash
# scripts/task-queue-stats.sh — quick forensics snapshot of the work_queue.
# Read-only. Prints counts for each queue state and newest filename in each.
# Useful between agent handoffs or when diagnosing a stuck runner.
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
QUEUE="$ROOT/ops/work_queue"

echo "=== task-queue-stats ($(date '+%Y-%m-%d %H:%M:%S %Z')) ==="
echo ""

if [ ! -d "$QUEUE" ]; then
  echo "no $QUEUE"
  exit 0
fi

for state in pending completed failed rejected; do
  dir="$QUEUE/$state"
  if [ ! -d "$dir" ]; then
    printf "%-10s: (missing)\n" "$state"
    continue
  fi
  count="$(find "$dir" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
  newest="$(ls -1t "$dir" 2>/dev/null | head -n 1 || true)"
  if [ -z "$newest" ]; then newest="(none)"; fi
  printf "%-10s: count=%-5s newest=%s\n" "$state" "$count" "$newest"
done

echo ""
echo "--- heartbeat ---"
HB="$ROOT/data/task_runner/heartbeat.txt"
if [ -f "$HB" ]; then
  cat "$HB"
else
  echo "(no heartbeat file)"
fi

echo ""
echo "--- authorized signers ---"
KEYS="$QUEUE/AUTHORIZED_KEYS.txt"
if [ -f "$KEYS" ]; then
  awk 'NF && $1 !~ /^#/ { print $1 }' "$KEYS"
else
  echo "(no AUTHORIZED_KEYS.txt)"
fi

echo ""
echo "--- launchd ---"
if launchctl list 2>/dev/null | grep -q com.symphony.task-runner; then
  launchctl list | grep com.symphony.task-runner
else
  echo "com.symphony.task-runner NOT loaded"
fi
