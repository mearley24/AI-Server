#!/bin/bash
# Read-only probe of the meeting analysis dependencies:
#   - Ollama server at 192.168.1.189:11434 (what returns 404, which endpoints work)
#   - Launchd env for OPENAI_API_KEY on the audio-intake daemon
#   - Recent worker.log lines showing the actual OpenAI error
# Exploratory — never short-circuit; dump everything.
set -u

OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.189:11434}"
OLLAMA_MODEL="${OLLAMA_MEETING_MODEL:-qwen3:8b}"
WORKER_LOG="/Users/bob/AI-Server/data/audio_intake/worker.log"

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
whoami
echo "ollama_host: $OLLAMA_HOST"
echo "ollama_model: $OLLAMA_MODEL"
echo

echo "=== 1. ollama root (HTTP status only) ==="
curl -sS -o /dev/null -w "http_code=%{http_code}  time_total=%{time_total}s\n" \
  --max-time 10 "$OLLAMA_HOST/" || echo "curl_failed"
echo

echo "=== 2. ollama GET /api/tags (list pulled models) ==="
curl -sS --max-time 15 "$OLLAMA_HOST/api/tags" 2>&1 | head -60 || true
echo

echo "=== 3. ollama GET /api/version ==="
curl -sS --max-time 10 "$OLLAMA_HOST/api/version" 2>&1 | head -5 || true
echo

echo "=== 4. ollama POST /api/chat minimal probe ==="
# Exact shape the worker uses, but with a trivial prompt and short timeout.
payload=$(cat <<JSON
{"model":"$OLLAMA_MODEL","messages":[{"role":"user","content":"ping"}],"stream":false,"options":{"temperature":0}}
JSON
)
curl -sS --max-time 30 -w "\n---\nhttp_code=%{http_code}  time_total=%{time_total}s\n" \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$OLLAMA_HOST/api/chat" 2>&1 | head -60 || true
echo

echo "=== 5. ollama POST /api/chat with a known-pullable fallback model (llama3.2:3b) ==="
payload2=$(cat <<JSON
{"model":"llama3.2:3b","messages":[{"role":"user","content":"ping"}],"stream":false,"options":{"temperature":0}}
JSON
)
curl -sS --max-time 30 -w "\n---\nhttp_code=%{http_code}  time_total=%{time_total}s\n" \
  -H "Content-Type: application/json" \
  -d "$payload2" \
  "$OLLAMA_HOST/api/chat" 2>&1 | head -30 || true
echo

echo "=== 6. launchd env for com.symphony.audio-intake ==="
# Whether OPENAI_API_KEY is actually exported to the daemon (not just shell).
label="com.symphony.audio-intake"
pid=$(launchctl list 2>/dev/null | awk -v l="$label" '$3==l {print $1}')
echo "pid: ${pid:-<not running>}"
if [ -n "${pid:-}" ] && [ "$pid" != "-" ]; then
  # /proc equivalent on macOS: use ps + launchctl procinfo (may require root for full env; try both).
  echo "--- ps ---"
  ps -p "$pid" -o pid,etime,command 2>/dev/null || true
  echo "--- launchctl procinfo (may be truncated without sudo) ---"
  launchctl procinfo "$pid" 2>&1 | grep -iE "OPENAI|OLLAMA|PATH" | head -20 || true
fi
echo
echo "--- plist OPENAI/OLLAMA entries ---"
plist="/Users/bob/Library/LaunchAgents/com.symphony.audio-intake.plist"
if [ -f "$plist" ]; then
  /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables" "$plist" 2>/dev/null | grep -iE "OPENAI|OLLAMA" || echo "no OPENAI/OLLAMA env keys in plist"
else
  echo "plist missing: $plist"
fi
echo

echo "=== 7. worker.log: recent meeting_openai_failed / meeting_ollama_failed / meeting_analysis_failed ==="
if [ -f "$WORKER_LOG" ]; then
  grep -nE "meeting_openai_failed|meeting_ollama_failed|meeting_analysis_failed" "$WORKER_LOG" 2>/dev/null | tail -20 || echo "no matches"
else
  echo "worker.log missing at $WORKER_LOG"
fi
echo

echo "=== 8. shell-level OPENAI_API_KEY presence (masked) ==="
# Only report whether it's set + length + last 4 chars. Never print the key.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  keylen=${#OPENAI_API_KEY}
  keytail="${OPENAI_API_KEY: -4}"
  echo "OPENAI_API_KEY: set (len=$keylen, tail=****$keytail)"
else
  echo "OPENAI_API_KEY: NOT set in this shell"
fi
echo

echo "=== 9. summary hints ==="
cat <<'EOF'
If /api/chat returned 404 on qwen3:8b but /api/tags shows other models:
  -> the model isn't pulled on that host. Fix: `ollama pull qwen3:8b` on 192.168.1.189.
If /api/chat returned 404 on both models but /api/tags works:
  -> API surface mismatch (old Ollama version). Check /api/version.
If /api/tags itself 404s:
  -> that's not an Ollama server, or wrong port. Check what's at :11434.
If OPENAI_API_KEY absent from launchd env but set in shell:
  -> daemon needs the key baked into the plist's <EnvironmentVariables> block,
     or loaded from a file at startup. Shell export won't reach launchd.
EOF
