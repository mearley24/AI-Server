#!/usr/bin/env bash
# Install / refresh the iMessage bridge LaunchAgent (paths from this repo + venv).
# Usage: bash scripts/install-imessage-launchagent.sh
set -euo pipefail

LABEL="com.symphony.imessage-bridge"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${IMESSAGE_VENV:-$ROOT/.venv-imessage}"
PY="$VENV/bin/python3"
SRV="$ROOT/scripts/imessage-server.py"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ ! -x "$PY" ]]; then
  echo "Missing venv Python: $PY"
  echo "Run: bash $ROOT/scripts/install-imessage-deps.sh"
  exit 1
fi
if [[ ! -f "$SRV" ]]; then
  echo "Missing: $SRV"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# Write plist with real paths (avoids hard-coded /Users/bob and invalid hand-edited XML)
cat > "$DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${SRV}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/imessage-bridge.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/imessage-bridge.log</string>
</dict>
</plist>
PLIST

echo "==> plist: $DST"
plutil -lint "$DST"

# Remove stale registration (bootstrap vs legacy load can conflict)
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl unload "$DST" 2>/dev/null || true

# Prefer bootstrap (modern); fall back to load -w (still works for user agents)
if launchctl bootstrap "gui/$(id -u)" "$DST"; then
  echo "==> launchctl bootstrap OK"
else
  echo "==> bootstrap failed, trying launchctl load -w …"
  launchctl load -w "$DST"
  echo "==> launchctl load OK"
fi

launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>/dev/null || true
echo "==> Done. Logs: /tmp/imessage-bridge.log"
echo "    Check: launchctl print gui/$(id -u)/${LABEL} | head -40"
