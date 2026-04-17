#!/bin/bash
# Force an immediate run of the audio_intake worker without waiting for its
# StartInterval or WatchPaths trigger. Uses launchctl kickstart -k to stop
# any in-flight instance and start a fresh one. Safe under the worker's
# single-instance lock.
set -euo pipefail

LABEL="com.symphony.audio-intake"
UID_BOB="$(id -u bob)"
TARGET="gui/${UID_BOB}/${LABEL}"

echo "kicking $TARGET"
launchctl kickstart -kp "$TARGET"

echo ""
echo "launchctl print (status line):"
launchctl print "$TARGET" 2>/dev/null | awk '/state|pid|last exit code/ {print}' | head -6 || true

echo ""
echo "last 20 worker log lines:"
tail -20 /Users/bob/AI-Server/data/audio_intake/worker.log 2>/dev/null || echo "(no worker log yet)"
