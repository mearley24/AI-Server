#!/bin/bash
# Install the patched com.symphony.task-runner plist with WatchPaths so the
# runner fires the instant a task JSON commit lands (via git pull) instead
# of waiting for the next 60-second interval. Safe to re-run.
set -euo pipefail

LABEL="com.symphony.task-runner"
SRC="/Users/bob/AI-Server/ops/task_runner/${LABEL}.plist"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_BOB="$(id -u bob)"
TARGET="gui/${UID_BOB}/${LABEL}"

[ -f "$SRC" ] || { echo "missing src: $SRC"; exit 2; }

echo "copying plist: $SRC -> $DST"
cp "$SRC" "$DST"
chmod 644 "$DST"

echo "bootout (ignore not-loaded error):"
launchctl bootout "$TARGET" 2>&1 || true

echo "bootstrap:"
launchctl bootstrap "gui/${UID_BOB}" "$DST"

echo "verify:"
launchctl print "$TARGET" 2>/dev/null | \
  awk '/state|WatchPaths|StartInterval|ThrottleInterval|path/ {print}' | head -14 || true

echo "ok: task-runner now event-driven on pending/ + refs/heads/main + FETCH_HEAD."
