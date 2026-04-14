#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_SERVER_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.symphony.mobile-api"
PLIST_SRC="$SCRIPT_DIR/launchd/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "Installing Mobile Gateway..."

pip3 install --break-system-packages -r "$AI_SERVER_DIR/api/requirements.txt" --quiet 2>/dev/null || pip3 install -r "$AI_SERVER_DIR/api/requirements.txt" --quiet

sed "s|/Users/bob/AI-Server|$AI_SERVER_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

mkdir -p "$AI_SERVER_DIR/logs"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Mobile Gateway running on port 8420"
echo "Test: curl http://localhost:8420/health"
echo "Logs: $AI_SERVER_DIR/logs/mobile_api.log"
