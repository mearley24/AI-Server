#!/usr/bin/env bash
# =============================================================================
# services/file-watcher/run.sh
#
# Native LaunchAgent wrapper for the Symphony File Watcher.
# Sources .env so all secrets are available, then runs main.py directly
# (no Docker — brctl works, iCloud stubs resolve correctly).
#
# Install:
#   cp setup/launchd/com.symphony.file-watcher.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.symphony.file-watcher.plist
#
# Manual test:
#   bash /Users/bob/AI-Server/services/file-watcher/run.sh
# =============================================================================

set -euo pipefail

ENV_FILE="/Users/bob/AI-Server/.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/file-watcher.log"

# ── Load .env (handles values with spaces) ────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip blank lines and comments
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
    # Split on first = only, then strip surrounding quotes from value
    key="${line%%=*}"
    val="${line#*=}"
    val="${val#\"}"; val="${val%\"}"   # strip double quotes
    val="${val#\'}"; val="${val%\'}"   # strip single quotes
    export "$key=$val" 2>/dev/null || true
  done < "$ENV_FILE"
else
  echo "$(date) WARN  run.sh: .env not found at $ENV_FILE" | tee -a "$LOG"
fi

# ── Override URLs for native (non-Docker) access ──────────────────────────────
# Redis is on localhost (Docker maps 6379 to host)
export REDIS_URL="redis://:${REDIS_PASSWORD:-d19c9b0faebeee9927555eb8d6b28ec9}@127.0.0.1:6379"
# Services are on localhost ports
export NOTIFICATION_HUB_URL="http://127.0.0.1:8095"
export OPENCLAW_URL="http://127.0.0.1:8099"
export CORTEX_URL="http://127.0.0.1:8099"
# Explicitly native mode — enables brctl for iCloud stub downloads
export IS_DOCKER="false"
export LOG_PATH="$LOG"

# ── Use virtualenv (created once: python3 -m venv services/file-watcher/.venv) ─
VENV="$SCRIPT_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "$(date) INFO  Creating virtualenv..." | tee -a "$LOG"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
elif ! "$VENV/bin/python" -c "import dropbox" 2>/dev/null; then
  echo "$(date) INFO  Installing Python dependencies into venv..." | tee -a "$LOG"
  "$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
fi

echo "$(date) INFO  Starting Symphony File Watcher (native mode)" | tee -a "$LOG"

exec "$VENV/bin/python" "$SCRIPT_DIR/main.py"
