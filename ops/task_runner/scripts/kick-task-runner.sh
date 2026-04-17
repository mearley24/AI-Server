#!/bin/bash
# Manual force-tick of the task-runner. Rarely needed once WatchPaths is
# installed — useful only if launchd's watcher is stuck or you want to run
# a tick immediately for debugging.
set -euo pipefail

LABEL="com.symphony.task-runner"
UID_BOB="$(id -u bob)"
TARGET="gui/${UID_BOB}/${LABEL}"

echo "kicking $TARGET"
launchctl kickstart -kp "$TARGET"

echo "state:"
launchctl print "$TARGET" 2>/dev/null | awk '/state|pid|last exit code/ {print}' | head -6 || true

echo "last 20 launchd stdout lines:"
tail -20 /Users/bob/AI-Server/data/task_runner/launchd.out.log 2>/dev/null || echo "(no log yet)"
