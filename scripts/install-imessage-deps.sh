#!/usr/bin/env bash
# One-shot deps for the native iMessage bridge (avoids Homebrew PEP 668 issues).
# Usage: bash scripts/install-imessage-deps.sh
#    or: ~/AI-Server/scripts/install-imessage-deps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${IMESSAGE_VENV:-$ROOT/.venv-imessage}"
REQ="$ROOT/scripts/requirements-imessage.txt"

echo "==> iMessage bridge deps"
echo "    repo: $ROOT"
echo "    venv: $VENV"

python3 -m venv "$VENV"
"$VENV/bin/python3" -m pip install -U pip -q
"$VENV/bin/python3" -m pip install -r "$REQ"

echo ""
echo "OK — run the bridge with:"
echo "  $VENV/bin/python3 $ROOT/scripts/imessage-server.py"
echo ""
echo "LaunchAgent: copy scripts/com.symphony.imessage-bridge.plist.example → ~/Library/LaunchAgents/com.symphony.imessage-bridge.plist"
echo "  cp \"$ROOT/scripts/com.symphony.imessage-bridge.plist.example\" ~/Library/LaunchAgents/com.symphony.imessage-bridge.plist"
echo "  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.symphony.imessage-bridge.plist"
