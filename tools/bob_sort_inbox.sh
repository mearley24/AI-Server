#!/bin/bash
set -euo pipefail

ICLOUD_BASE="/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Bob_Library"
INBOX="$ICLOUD_BASE/Bob_Inbox"
LOG="$HOME/AI-Server/logs/bob-sorter.log"

LOCKDIR="$HOME/AI-Server/.bob_sort_lock"
STAMP="$LOCKDIR/last_run"
DEBOUNCE_SEC=2

mkdir -p "$HOME/AI-Server/logs" "$LOCKDIR"
mkdir -p "$ICLOUD_BASE"/{Proposals,Manuals,Drawings,Markups,Standards,Field-Lessons,Templates,Bob_Inbox}

ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG" >/dev/null; }

# Debounce bursts from fswatch
now="$(date +%s)"
last="0"
[[ -f "$STAMP" ]] && last="$(cat "$STAMP" 2>/dev/null || echo 0)"
if [[ $((now-last)) -lt $DEBOUNCE_SEC ]]; then
  exit 0
fi
echo "$now" > "$STAMP"

# Wait for iCloud hydration: require stable size for a moment
wait_stable_file() {
  local f="$1"
  local s1 s2
  # up to ~5 seconds total
  for _ in 1 2 3 4 5; do
    [[ -f "$f" ]] || { sleep 0.3; continue; }
    s1="$(stat -f%z "$f" 2>/dev/null || echo 0)"
    sleep 0.3
    s2="$(stat -f%z "$f" 2>/dev/null || echo 0)"
    if [[ "$s1" == "$s2" && "$s2" != "0" ]]; then
      return 0
    fi
  done
  # still allow processing of 0-byte test files
  [[ -f "$f" ]] && return 0
  return 1
}

classify() {
  local f="$1"
  local name lower ext
  name="$(basename "$f")"
  lower="$(echo "$name" | tr '[:upper:]' '[:lower:]')"
  ext="${lower##*.}"

  case "$ext" in
    dwg|dxf|rvt) echo "Drawings"; return 0 ;;
    png|jpg|jpeg|tif|tiff|gif|webp)
      if [[ "$lower" == *"markup"* || "$lower" == *"bluebeam"* || "$lower" == *"flattened"* || "$lower" == *"revised"* ]]; then
        echo "Markups"; return 0
      fi
      echo "Drawings"; return 0
      ;;
  esac

  if [[ "$lower" == *"manual"* || "$lower" == *"installation"* || "$lower" == *"spec"* || "$lower" == *"datasheet"* || "$lower" == *"integration report"* ]]; then
    echo "Manuals"; return 0
  fi

  if [[ "$lower" == *"markup"* || "$lower" == *"bluebeam"* || "$lower" == *"flattened"* || "$lower" == *"revised"* ]]; then
    echo "Markups"; return 0
  fi

  if [[ "$lower" == *"plan"* || "$lower" == *"layout"* || "$lower" == *"electrical"* || "$lower" == *"site plan"* || "$lower" == *"wiring"* || "$lower" == *"distribution"* ]]; then
    echo "Drawings"; return 0
  fi

  if [[ "$lower" == *"proposal"* || "$lower" == *"quote"* || "$lower" == *"estimate"* || "$lower" == *"dttools"* || "$lower" == p-*.pdf || "$lower" == q-*.pdf ]]; then
    echo "Proposals"; return 0
  fi

  if [[ "$ext" == "pdf" || "$ext" == "docx" || "$ext" == "numbers" || "$ext" == "xlsx" ]]; then
    echo "Proposals"; return 0
  fi

  echo "Standards"
}

move_one() {
  local src="$1"
  [[ -f "$src" ]] || return 0

  local bucket destdir base target
  bucket="$(classify "$src")"
  destdir="$ICLOUD_BASE/$bucket"
  mkdir -p "$destdir"

  base="$(basename "$src")"
  target="$destdir/$base"

  if [[ -e "$target" ]]; then
    local stem ext i
    stem="${base%.*}"
    ext="${base##*.}"
    i=2
    while [[ -e "$destdir/${stem} (${i}).${ext}" ]]; do
      i=$((i+1))
    done
    target="$destdir/${stem} (${i}).${ext}"
  fi

  mv "$src" "$target"
  log "Moved: $(basename "$src") -> $bucket/$(basename "$target")"
  echo "$target"
}

log "Sorter run started"

shopt -s nullglob
for f in "$INBOX"/*; do
  bn="$(basename "$f")"
  if [[ "$bn" == ._* || "$bn" == *.tmp || "$bn" == *.download ]]; then
    continue
  fi

  if ! wait_stable_file "$f"; then
    log "Skipped (not hydrated yet): $bn"
    continue
  fi

  moved="$(move_one "$f" || true)"
  if [[ -n "$moved" && -x "$HOME/AI-Server/tools/bob_ingest_new.sh" ]]; then
    /bin/bash -lc "$HOME/AI-Server/tools/bob_ingest_new.sh \"${moved}\" auto" >> "$LOG" 2>&1 || true
  fi
done

log "Sorter run finished"
