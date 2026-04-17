#!/bin/bash
# Pull qwen3:8b into Bob's local Ollama (192.168.1.189 = Bob's LAN IP = this host).
# Idempotent: Ollama no-ops when the model is already pulled. ~5GB first time.
# Keeps a log. Fails loudly if Ollama isn't running.
set -uo pipefail

MODEL="qwen3:8b"
OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.189:11434}"
LOG_DIR="/Users/bob/AI-Server/data/ollama"
LOG_FILE="$LOG_DIR/pull.log"

mkdir -p "$LOG_DIR"

{
  echo "=== pull-qwen3-8b @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="
  echo "model: $MODEL"
  echo "host: $OLLAMA_HOST"

  echo
  echo "--- 0. pre-check: /api/tags ---"
  pre=$(curl -sS --max-time 10 "$OLLAMA_HOST/api/tags" 2>&1)
  echo "$pre"
  if echo "$pre" | grep -q "\"name\":\"$MODEL\""; then
    echo
    echo "already pulled. skipping."
    echo "exit=0"
    exit 0
  fi

  echo
  echo "--- 1. pulling $MODEL (this may take several minutes) ---"
  # Use the API directly so we don't depend on the CLI being on PATH for the
  # task-runner's restricted PATH. Stream=false returns once complete.
  # NOTE: /api/pull streams progress; we discard progress events but keep errors.
  pull_rc=0
  curl -sS --max-time 1800 -N \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL\",\"stream\":true}" \
    "$OLLAMA_HOST/api/pull" \
    | tee -a "$LOG_FILE" \
    | awk 'BEGIN{last=""} {
        if (match($0, /"status":"[^"]*"/)) {
          s = substr($0, RSTART+10, RLENGTH-11)
          if (s != last) { print s; last = s }
        }
        if (match($0, /"error":"[^"]*"/)) {
          e = substr($0, RSTART+9, RLENGTH-10)
          print "ERROR: " e
        }
      }' \
    || pull_rc=$?

  echo
  echo "--- 2. post-check: /api/tags ---"
  post=$(curl -sS --max-time 10 "$OLLAMA_HOST/api/tags" 2>&1)
  echo "$post"

  if echo "$post" | grep -q "\"name\":\"$MODEL\""; then
    echo
    echo "--- 3. chat smoke test on $MODEL ---"
    curl -sS --max-time 60 -w "\nhttp_code=%{http_code}\n" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with exactly one word: ok\"}],\"stream\":false,\"options\":{\"temperature\":0}}" \
      "$OLLAMA_HOST/api/chat" | head -30
    echo
    echo "ok: $MODEL is pulled and responsive."
    echo "exit=0"
    exit 0
  else
    echo
    echo "FAIL: $MODEL not in /api/tags after pull (rc=$pull_rc)."
    echo "exit=1"
    exit 1
  fi
} 2>&1 | tee -a "$LOG_FILE"
