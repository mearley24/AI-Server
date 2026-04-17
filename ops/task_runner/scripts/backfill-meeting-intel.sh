#!/bin/bash
# Re-analyze meeting markdowns that were saved with a failed LLM analysis.
# For each candidate, call analyze_meeting() from the worker module against
# the embedded transcript and post a fresh cortex memory. Writes a new
# markdown alongside the old and deletes the old on success.
set -uo pipefail

ROOT="/Users/bob/AI-Server"
TRANSCRIPTS="$ROOT/data/transcripts/meetings"
ENV_FILE="$ROOT/.env"

[ -d "$TRANSCRIPTS" ] || { echo "missing: $TRANSCRIPTS"; exit 2; }
[ -f "$ENV_FILE" ] || { echo "missing: $ENV_FILE"; exit 3; }

# Load secrets from .env so the Python subprocess inherits them.
export_env() {
  local key="$1"
  local val
  val=$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | sed -E "s/^${key}=//; s/^[\"']//; s/[\"']$//")
  [ -n "$val" ] && export "$key=$val"
}
export_env OPENAI_API_KEY
export_env OLLAMA_HOST
export_env OLLAMA_MEETING_MODEL
export OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.189:11434}"
export OLLAMA_MEETING_MODEL="${OLLAMA_MEETING_MODEL:-qwen3:8b}"

echo "=== backfill-meeting-intel @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="
echo "OLLAMA_HOST: $OLLAMA_HOST"
echo "OLLAMA_MEETING_MODEL: $OLLAMA_MEETING_MODEL"
if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY: set (len=${#OPENAI_API_KEY})"
else
  echo "OPENAI_API_KEY: NOT set"
fi
echo

PY="/opt/homebrew/bin/python3"
[ -x "$PY" ] || PY="/usr/bin/python3"

# Driver Python: takes candidate markdowns on stdin, one path per line.
find "$TRANSCRIPTS" -maxdepth 1 -type f -name "*llm-analysis-failed-raw-transcript-saved.md" \
  | sort \
  | "$PY" "$ROOT/scripts/backfill_meeting_intel.py"

rc=$?
echo "exit=$rc"
exit $rc
