#!/bin/bash
set -euo pipefail

ICLOUD_BASE="/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Bob_Library"
LOG="$HOME/AI-Server/logs/bob-scan.log"

LOCAL_BASE="$HOME/AI-Server/knowledge"
STATE_DIR="$LOCAL_BASE/state"
SEEN_DB="$STATE_DIR/seen_sha256_library.txt"

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
  [[ "$lower" == "bob_master_index.md" ]] && return 1
  [[ "$lower" == *.pdf ]] && return 0
  return 1
}

scan_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0

  find "$dir" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' f; do
    should_ingest "$f" || continue
    stat -f%z "$f" >/dev/null 2>&1 || { log "Skip (not readable yet): $f"; continue; }

    digest="$(sha_file "$f")"
    seen_has "$digest" && continue

    log "NEW PDF: $f"
    /bin/bash -lc "$HOME/AI-Server/tools/bob_ingest_new.sh \"${f}\" auto" >> "$LOG" 2>&1 || true
    seen_add "$digest"
  done
}

log "Library scan started"
scan_dir "$ICLOUD_BASE/Proposals"
scan_dir "$ICLOUD_BASE/Manuals"
log "Library scan finished"
