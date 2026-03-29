#!/bin/bash
# Install Bob's workspace autostart LaunchAgent
# Usage: bash ~/AI-Server/scripts/install_autostart.sh

set -e

PLIST_NAME="com.symphony.bob.workspace.plist"
SRC="$(cd "$(dirname "$0")" && pwd)/bob_autostart.plist"
DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "Installing Bob's workspace autostart..."

# Ensure LaunchAgents directory exists
mkdir -p "$HOME/Library/LaunchAgents"

# Unload existing if present
if launchctl list | grep -q "com.symphony.bob.workspace"; then
    echo "Unloading existing agent..."
    launchctl unload "$DEST" 2>/dev/null || true
fi

# Copy plist
cp "$SRC" "$DEST"
echo "Copied plist to $DEST"

# Load agent
launchctl load "$DEST"
echo "LaunchAgent loaded."

echo ""
echo "Bob's workspace will now auto-start on login."
echo "To disable: launchctl unload $DEST"
echo "Logs: /tmp/bob-workspace.log"
