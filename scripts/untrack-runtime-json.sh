#!/usr/bin/env bash
# One-time: stop tracking runtime JSON that breaks git pull (lessons-learned #6).
set -euo pipefail
cd "${SYMPHONY_ROOT:-$HOME/AI-Server}"
F="data/network_watch/dropout_watch_status.json"
if git ls-files --error-unmatch "$F" >/dev/null 2>&1; then
  git rm --cached "$F" 2>/dev/null || true
  echo "Removed $F from git index. Commit this change."
else
  echo "$F is not tracked (OK)."
fi
