#!/bin/bash
# Install the patched com.symphony.audio-intake plist with WatchPaths for
# event-driven triggering. Idempotent: copies the canonical plist from the
# repo to ~/Library/LaunchAgents/, unloads the existing job if present, and
# bootstraps the new one. Keeps StartInterval=600 as a safety net.
set -euo pipefail

LABEL="com.symphony.audio-intake"
SRC="/Users/bob/AI-Server/scripts/launchd/${LABEL}.plist"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_BOB="$(id -u bob)"
TARGET="gui/${UID_BOB}/${LABEL}"

[ -f "$SRC" ] || { echo "missing src: $SRC"; exit 2; }

echo "copying plist: $SRC -> $DST"
cp "$SRC" "$DST"
chmod 644 "$DST"

echo ""
echo "bootout (ignore not-loaded error):"
launchctl bootout "$TARGET" 2>&1 || true

echo ""
echo "bootstrap:"
launchctl bootstrap "gui/${UID_BOB}" "$DST"

echo ""
echo "verify:"
launchctl print "$TARGET" 2>/dev/null | awk '/state|path|WatchPaths|StartInterval|ThrottleInterval/ {print}' | head -10 || true

echo ""
echo "plist now installed. WatchPaths fires worker on any change under"
echo "data/audio_intake/incoming/. ThrottleInterval=30 prevents burst re-runs."
