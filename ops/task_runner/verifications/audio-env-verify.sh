#!/bin/bash
# Verify that the audio-intake daemon is now running with OPENAI_API_KEY +
# OLLAMA_MEETING_MODEL injected, and that /api/chat works with the configured
# model. Read-only.
set -u

LABEL="com.symphony.audio-intake"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PB="/usr/libexec/PlistBuddy"
OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.189:11434}"

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
whoami
echo

echo "=== 1. installed plist env keys (OPENAI masked) ==="
if [ -f "$DST" ]; then
  $PB -c "Print :EnvironmentVariables" "$DST" 2>/dev/null | \
    awk '/OPENAI_API_KEY/ {
           line=$0; sub(/.* = /, "", line); n=length(line); tail=substr(line, n-3, 4);
           printf "  OPENAI_API_KEY = ****%s (len=%d)\n", tail, n; next
         }
         /OLLAMA|CORTEX|AI_SERVER|PATH/ { print "  " $0 }'
else
  echo "  plist missing at $DST"
fi
echo

echo "=== 2. git-tracked template MUST NOT contain secrets ==="
SRC="/Users/bob/AI-Server/scripts/launchd/${LABEL}.plist"
if grep -q "OPENAI_API_KEY" "$SRC" 2>/dev/null; then
  if grep -A1 "OPENAI_API_KEY" "$SRC" | grep -qE "sk-[a-zA-Z0-9]"; then
    echo "  FAIL: template contains real OPENAI_API_KEY value — SECURITY LEAK"
  else
    echo "  ok: template mentions OPENAI_API_KEY but no secret value"
  fi
else
  echo "  ok: template has no OPENAI_API_KEY key (secrets only in installed copy)"
fi
echo

echo "=== 3. live daemon env (via launchctl procinfo) ==="
pid=$(launchctl list 2>/dev/null | awk -v l="$LABEL" '$3==l {print $1}')
echo "  pid: ${pid:-<not running>}"
if [ -n "${pid:-}" ] && [ "$pid" != "-" ]; then
  launchctl procinfo "$pid" 2>&1 | grep -iE "OPENAI_API_KEY|OLLAMA" | \
    awk '{
      if ($0 ~ /OPENAI_API_KEY/) {
        line=$0; sub(/.*= ?/, "", line); n=length(line);
        tail=substr(line, n-3, 4);
        printf "  OPENAI_API_KEY = ****%s (len=%d)\n", tail, n
      } else {
        print "  " $0
      }
    }'
fi
echo

echo "=== 4. ollama /api/chat with configured model ==="
# Read the model from the installed plist so the verification matches reality.
model=""
if [ -f "$DST" ]; then
  model=$($PB -c "Print :EnvironmentVariables:OLLAMA_MEETING_MODEL" "$DST" 2>/dev/null)
fi
[ -z "$model" ] && model="qwen3:8b"
echo "  model: $model"
payload=$(cat <<JSON
{"model":"$model","messages":[{"role":"user","content":"reply with exactly one word: ok"}],"stream":false,"options":{"temperature":0}}
JSON
)
curl -sS --max-time 60 -w "\n  http_code=%{http_code}  time_total=%{time_total}s\n" \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$OLLAMA_HOST/api/chat" | head -20
echo

echo "=== 5. audio worker throughput (last 30 min of worker.log) ==="
LOG="/Users/bob/AI-Server/data/audio_intake/worker.log"
if [ -f "$LOG" ]; then
  echo "  total log lines: $(wc -l < "$LOG" | tr -d ' ')"
  # cutoff: 30 minutes ago, crude text match on ISO8601-ish timestamp prefix
  cutoff=$(date -v-30M '+%Y-%m-%d %H:%M' 2>/dev/null || date -d '30 minutes ago' '+%Y-%m-%d %H:%M' 2>/dev/null)
  echo "  cutoff: $cutoff"
  echo "  --- transcribing starts (last 30m) ---"
  awk -v c="$cutoff" '$0 >= c && /transcribing/ {print}' "$LOG" | tail -10
  echo "  --- cortex_posted (last 30m) ---"
  awk -v c="$cutoff" '$0 >= c && /cortex_posted/ {print}' "$LOG" | tail -10
  echo "  --- meeting_*_failed (last 30m) ---"
  awk -v c="$cutoff" '$0 >= c && /meeting_.*_failed/ {print}' "$LOG" | tail -10
  echo "  --- any ERROR or WARNING (last 30m) ---"
  awk -v c="$cutoff" '$0 >= c && /\[ERROR\]|\[WARNING\]/ {print}' "$LOG" | tail -15
else
  echo "  worker.log missing at $LOG"
fi
echo

echo "=== 6. audio_intake counts ==="
for sub in incoming processing processed failed; do
  dir="/Users/bob/AI-Server/data/audio_intake/$sub"
  if [ -d "$dir" ]; then
    n=$(ls -1 "$dir" 2>/dev/null | wc -l | tr -d ' ')
    echo "  $sub: $n"
  fi
done
