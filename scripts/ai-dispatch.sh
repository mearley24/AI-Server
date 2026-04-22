#!/usr/bin/env bash
# ai-dispatch.sh — stable autonomous execution entry point.
#
# Modes:
#   status                  Show host role, claude CLI, model smoke status,
#                           detected local LLM CLIs, and latest artifacts.
#   models                  List model lanes and smoke-test status.
#   run-priority1           Invoke scripts/run-priority1-1m.sh (Priority 1).
#   run-prompt <file>       Run prompt file through Claude Code (1M preferred,
#                           falls back to claude-sonnet-4-20250514).
#   local-prompt <file>     Run prompt file through a detected local LLM
#                           (ollama / llama.cpp). No git operations.
#
# Safety:
#   - Never inspects or prints secrets.
#   - Every invocation logged to ops/verification/dispatch-<ts>-<mode>.txt.
#   - Bounded: single-shot; no daemons, no scheduling, no outbound messages.

set -euo pipefail

MODE="${1:-status}"
ARG1="${2:-}"

MODEL_1M="claude-sonnet-4-6[1m]"
MODEL_FALLBACK="claude-sonnet-4-20250514"

# --- repo root ------------------------------------------------------------
resolve_repo_root() {
  if [ -d "${HOME}/AI-Server/.git" ]; then
    echo "${HOME}/AI-Server"
    return 0
  fi
  local here dir
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  dir="$here"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/.git" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

REPO_ROOT="$(resolve_repo_root)" || {
  echo "[ai-dispatch] ERROR: could not locate AI-Server repo root" >&2
  exit 1
}
cd "$REPO_ROOT"

# --- logging --------------------------------------------------------------
TS="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$REPO_ROOT/ops/verification"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dispatch-$TS-$MODE.txt"

log() {
  local line="[ai-dispatch] $*"
  printf '%s\n' "$line" >&2
  printf '%s\n' "$line" >> "$LOG_FILE"
}

section() {
  printf '\n=== %s ===\n' "$*" >> "$LOG_FILE"
  printf '\n=== %s ===\n' "$*" >&2
}

# --- host role detection --------------------------------------------------
detect_role() {
  local host
  host="$(hostname 2>/dev/null || echo unknown)"
  # Bob heuristic: macOS + canonical ~/AI-Server path, or hostname match.
  if [ -d "${HOME}/AI-Server/.git" ] && [[ "$host" == *[Bb]ob* || "$host" == *mac-mini* || "$host" == *M4* ]]; then
    echo "bob"
    return
  fi
  if [ -d "${HOME}/AI-Server/.git" ]; then
    echo "bob-likely"
    return
  fi
  echo "non-bob (${host})"
}

ROLE="$(detect_role)"

# --- model smoke ----------------------------------------------------------
claude_available() { command -v claude >/dev/null 2>&1; }

smoke_model() {
  # Returns 0 if the model echoes the sentinel we expect.
  local model="$1" sentinel="$2"
  local out
  out="$(claude --model "$model" -p "respond exactly: $sentinel" 2>&1 || true)"
  printf '%s' "$out" | grep -q "$sentinel"
}

# --- local LLM detection --------------------------------------------------
detect_local_llms() {
  local any=0
  if command -v ollama >/dev/null 2>&1; then
    any=1
    log "local LLM: ollama detected ($(ollama --version 2>/dev/null | head -n1))"
    if ollama list >/dev/null 2>&1; then
      {
        echo "ollama models:"
        ollama list 2>/dev/null | sed -n '1,20p'
      } >> "$LOG_FILE"
    fi
  fi
  if command -v llama-cli >/dev/null 2>&1; then
    any=1
    log "local LLM: llama-cli (llama.cpp) detected"
  fi
  if command -v llama >/dev/null 2>&1 && ! command -v llama-cli >/dev/null 2>&1; then
    any=1
    log "local LLM: 'llama' binary detected (llama.cpp variant)"
  fi
  if [ "$any" -eq 0 ]; then
    log "local LLM: none detected (ollama / llama-cli not on PATH)"
  fi
  return 0
}

run_local_prompt() {
  local prompt_file="$1"
  [ -f "$prompt_file" ] || { log "ERROR: prompt file not found: $prompt_file"; exit 2; }

  if command -v ollama >/dev/null 2>&1; then
    local first_model
    first_model="$(ollama list 2>/dev/null | awk 'NR==2 {print $1}')"
    if [ -z "$first_model" ]; then
      log "ollama installed but no models pulled. Try: ollama pull llama3.2:3b"
      exit 3
    fi
    log "running local prompt via ollama model: $first_model"
    section "ollama output"
    # shellcheck disable=SC2002
    cat "$prompt_file" | ollama run "$first_model" 2>&1 | tee -a "$LOG_FILE"
    return $?
  fi

  if command -v llama-cli >/dev/null 2>&1; then
    log "llama-cli detected but requires a --model <gguf-path> flag; no model auto-selected."
    log "run manually, e.g.: llama-cli -m <model.gguf> -p \"\$(cat $prompt_file)\""
    exit 4
  fi

  log "no local LLM CLI detected. Install hints:"
  log "  ollama: https://ollama.com (then 'ollama pull llama3.2:3b')"
  log "  llama.cpp: https://github.com/ggerganov/llama.cpp"
  exit 5
}

# --- modes ---------------------------------------------------------------
mode_status() {
  section "host"
  log "role: $ROLE"
  log "repo: $REPO_ROOT"
  log "hostname: $(hostname 2>/dev/null || echo unknown)"
  log "uname: $(uname -a 2>/dev/null || echo unknown)"

  section "claude CLI"
  if claude_available; then
    log "claude: $(claude --version 2>/dev/null | head -n1 || echo 'version unknown')"
    if smoke_model "$MODEL_1M" SONNET_1M_READY; then
      log "model $MODEL_1M: OK"
    else
      log "model $MODEL_1M: FAIL (will fall back to $MODEL_FALLBACK for run-prompt)"
    fi
    if smoke_model "$MODEL_FALLBACK" SONNET_FALLBACK_READY; then
      log "model $MODEL_FALLBACK: OK"
    else
      log "model $MODEL_FALLBACK: FAIL"
    fi
  else
    log "claude CLI not on PATH — install: https://claude.com/code"
  fi

  section "local LLMs"
  detect_local_llms

  section "latest artifacts (ops/verification)"
  ls -1t "$LOG_DIR" 2>/dev/null | head -n 5 | while read -r f; do
    log "  $f"
  done
}

mode_models() {
  section "model lanes"
  if ! claude_available; then
    log "claude CLI missing"
    exit 1
  fi
  if smoke_model "$MODEL_1M" SONNET_1M_READY; then
    log "lane A (direct 1M) $MODEL_1M: OK"
  else
    log "lane A (direct 1M) $MODEL_1M: FAIL"
  fi
  if smoke_model "$MODEL_FALLBACK" SONNET_FALLBACK_READY; then
    log "lane B (fallback)  $MODEL_FALLBACK: OK"
  else
    log "lane B (fallback)  $MODEL_FALLBACK: FAIL"
  fi
  log "lane C (Cline): 200k context — small tasks only, driven by IDE, not this script"
  section "local lanes"
  detect_local_llms
}

mode_run_priority1() {
  section "run-priority1"
  if [ ! -x scripts/run-priority1-1m.sh ]; then
    log "ERROR: scripts/run-priority1-1m.sh missing or not executable"
    exit 1
  fi
  log "exec: bash scripts/run-priority1-1m.sh"
  # Tee the child output into the dispatch log.
  bash scripts/run-priority1-1m.sh 2>&1 | tee -a "$LOG_FILE"
}

mode_run_prompt() {
  local prompt_file="$1"
  [ -n "$prompt_file" ] || { log "ERROR: usage: run-prompt <file>"; exit 2; }
  [ -f "$prompt_file" ] || { log "ERROR: prompt file not found: $prompt_file"; exit 2; }

  if ! claude_available; then
    log "ERROR: claude CLI missing"
    exit 1
  fi

  local model="$MODEL_1M"
  if ! smoke_model "$MODEL_1M" SONNET_1M_READY; then
    log "1M smoke failed — falling back to $MODEL_FALLBACK"
    model="$MODEL_FALLBACK"
    if ! smoke_model "$MODEL_FALLBACK" SONNET_FALLBACK_READY; then
      log "ERROR: both lanes failed smoke test"
      exit 1
    fi
  fi

  log "run-prompt file=$prompt_file model=$model bytes=$(wc -c < "$prompt_file")"
  section "claude output"
  claude --model "$model" -p "$(cat "$prompt_file")" 2>&1 | tee -a "$LOG_FILE"
}

mode_local_prompt() {
  local prompt_file="$1"
  [ -n "$prompt_file" ] || { log "ERROR: usage: local-prompt <file>"; exit 2; }
  log "local-prompt file=$prompt_file"
  run_local_prompt "$prompt_file"
}

# --- dispatch ------------------------------------------------------------
log "mode=$MODE role=$ROLE ts=$TS"

case "$MODE" in
  status)        mode_status ;;
  models)        mode_models ;;
  run-priority1) mode_run_priority1 ;;
  run-prompt)    mode_run_prompt "$ARG1" ;;
  local-prompt)  mode_local_prompt "$ARG1" ;;
  *)
    cat >&2 <<USAGE
usage: bash scripts/ai-dispatch.sh <mode> [args]

modes:
  status                  Host role, claude CLI, model smoke, local LLMs.
  models                  List model lanes with smoke status.
  run-priority1           Invoke Priority 1 1M runner.
  run-prompt <file>       Run prompt through Claude Code (1M → fallback).
  local-prompt <file>     Run prompt through local LLM (ollama / llama.cpp).
USAGE
    exit 2
    ;;
esac

log "done. log: $LOG_FILE"
