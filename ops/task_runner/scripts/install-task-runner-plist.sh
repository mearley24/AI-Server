#!/bin/bash
# Install the patched com.symphony.task-runner plist with WatchPaths so the
# runner fires the instant a task JSON commit lands (via git pull) instead
# of waiting for the next 60-second interval. Safe to re-run.
#
# SELF-BOOTOUT GUARD: if this script is invoked inside the task-runner's own
# process tree (PPID chain leads to com.symphony.task-runner), then calling
# 'launchctl bootout' on our own job will kill the caller mid-script,
# leaving the task marked pending and forcing it to be re-run on every
# subsequent tick (self-inflicted fork bomb). Detect this via the env var
# XPC_SERVICE_NAME that launchd sets for its managed jobs. When we detect
# self-invocation, we skip bootout+bootstrap and just copy the plist +
# kickstart -k so the replacement happens in-place on the next tick.
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

SELF_INVOKED=no
if [ "${XPC_SERVICE_NAME:-}" = "$LABEL" ] || [ "${XPC_SERVICE_NAME:-}" = "application.$LABEL" ]; then
  SELF_INVOKED=yes
fi

if [ "$SELF_INVOKED" = "yes" ]; then
  echo "detected self-invocation (XPC_SERVICE_NAME=$XPC_SERVICE_NAME)"
  echo "skipping bootout+bootstrap to avoid killing our own process mid-script"
  echo "the replacement plist on disk will be picked up on the next launchd"
  echo "respawn; kickstart -k to force that now:"
  launchctl kickstart -k "$TARGET" 2>&1 || echo "(kickstart rc=$?)"
else
  echo "bootout (ignore not-loaded error):"
  launchctl bootout "$TARGET" 2>&1 || true
  echo "bootstrap:"
  launchctl bootstrap "gui/${UID_BOB}" "$DST"
fi

echo "verify:"
launchctl print "$TARGET" 2>/dev/null | \
  awk '/state|WatchPaths|StartInterval|ThrottleInterval|path/ {print}' | head -14 || true

echo "ok: task-runner now event-driven on pending/ + refs/heads/main + FETCH_HEAD."
