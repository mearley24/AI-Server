#!/bin/bash
# Install com.symphony.task-runner-watchdog launchd job on Bob.
#
# - Reads MATT_PHONE_NUMBER from /Users/bob/AI-Server/.env (so the number stays
#   out of git; plist template in repo has a placeholder).
# - Copies the plist into ~/Library/LaunchAgents with the placeholder
#   substituted via PlistBuddy (not sed) so XML stays well-formed.
# - Boots out any previous instance, bootstraps the fresh one.
# - Safe to re-run; idempotent.
set -uo pipefail

ROOT="/Users/bob/AI-Server"
LABEL="com.symphony.task-runner-watchdog"
SRC="$ROOT/ops/task_runner/${LABEL}.plist"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_BOB="$(id -u)"
TARGET="gui/${UID_BOB}/${LABEL}"
ENV_FILE="$ROOT/.env"

[ -f "$SRC" ] || { echo "missing src: $SRC"; exit 2; }
[ -f "$ENV_FILE" ] || { echo "missing env: $ENV_FILE"; exit 2; }

echo "sourcing secrets from $ENV_FILE"
set -a
source "$ENV_FILE"
set +a

MATT_PHONE="${MATT_PHONE_NUMBER:-${MATT_PHONE:-${OWNER_PHONE_NUMBER:-}}}"
if [ -z "$MATT_PHONE" ]; then
  echo "ERROR: MATT_PHONE_NUMBER (or MATT_PHONE / OWNER_PHONE_NUMBER) not set in .env"
  exit 3
fi
echo "phone resolved: ${MATT_PHONE:0:4}***${MATT_PHONE: -3}"

echo "copying plist: $SRC -> $DST"
cp "$SRC" "$DST"
chmod 644 "$DST"

echo "injecting MATT_PHONE_NUMBER via PlistBuddy"
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:MATT_PHONE_NUMBER $MATT_PHONE" "$DST"

echo "bootout (ignore not-loaded error):"
launchctl bootout "$TARGET" 2>&1 || true

echo "bootstrap:"
launchctl bootstrap "gui/${UID_BOB}" "$DST"

echo "kickstart (first tick now):"
launchctl kickstart "$TARGET" 2>&1 || true

echo "verify state:"
launchctl print "$TARGET" 2>/dev/null | \
  awk '/state|path|StartInterval|MATT_PHONE_NUMBER/' | head -10 || true

echo ""
echo "verify watchdog heartbeat file gets written within 3 ticks:"
for i in 1 2 3; do
  sleep 3
  if [ -f "$ROOT/data/task_runner/watchdog_heartbeat.txt" ]; then
    echo "  found: $(cat "$ROOT/data/task_runner/watchdog_heartbeat.txt")"
    break
  fi
  echo "  tick $i: not yet"
done

echo ""
echo "recent watchdog log lines:"
tail -15 "$ROOT/data/task_runner/watchdog.log" 2>/dev/null || echo "  (log not yet written)"

echo "ok: watchdog installed and running."
