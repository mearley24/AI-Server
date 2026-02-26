#!/bin/bash
set -euo pipefail

RAW="/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Bob_Library/Raw_Projects/Projects"
LOG="$HOME/AI-Server/logs/bob-rawscan.log"

LOCAL_BASE="$HOME/AI-Server/knowledge"
STATE_DIR="$LOCAL_BASE/state"
SEEN_DB="$STATE_DIR/seen_sha256_rawprojects.txt"

mkdir -p "$HOME/AI-Server/logs" "$STATE_DIR"
touch "$LOG" "$SEEN_DB"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG" >/dev/null; }

sha_file() { shasum -a 256 "$1" | awk '{print $1}'; }
seen_has() { grep -q "^${1}$" "$SEEN_DB" 2>/dev/null; }
seen_add() { echo "$1" >> "$SEEN_DB"; }

should_ingest() {
  local f="$1"
  local bn lower
  bn="$(basename "$f")"
  lower="$(echo "$bn" | tr '[:upper:]' '[:lower:]')"
  [[ "$bn" == ._* ]] && return 1
  [[ "$lower" == *.tmp || "$lower" == *.download ]] && return 1
  [[ "$lower" == *.pdf ]] && return 0
  return 1
}

ingest_one() {
  local file="$1"
  /bin/bash -lc "$HOME/AI-Server/tools/bob_ingest_new.sh \"${file}\" auto" >> "$LOG" 2>&1 || true
}

[[ -d "$RAW" ]] || { log "Missing raw folder: $RAW"; exit 0; }

log "Raw Projects scan started: $RAW"

find "$RAW" -type f -print0 | while IFS= read -r -d '' f; do
  should_ingest "$f" || continue
  stat -f%z "$f" >/dev/null 2>&1 || { log "Skip (not readable yet): $f"; continue; }

  digest="$(sha_file "$f")"
  seen_has "$digest" && continue

  log "NEW PDF: $f"
  ingest_one "$f"
  seen_add "$digest"
done

log "Raw Projects scan finished"
