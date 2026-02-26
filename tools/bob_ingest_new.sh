#!/bin/bash
set -euo pipefail

LOCAL_BASE="$HOME/AI-Server/knowledge"
LOCAL_INDEX="$LOCAL_BASE/Bob_Master_Index.md"
LOCAL_KB="$LOCAL_BASE/Extracted_Knowledge"
LOG="$HOME/AI-Server/logs/bob-ingest.log"

PDFTOTEXT="/opt/homebrew/bin/pdftotext"
QPDF="/opt/homebrew/bin/qpdf"
MUTOOL="/opt/homebrew/bin/mutool"

mkdir -p "$LOCAL_KB"/{proposals,manuals,drawings,markups} "$HOME/AI-Server/logs" "$LOCAL_BASE/state"
touch "$LOG"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG" >/dev/null; }

sha_file() { shasum -a 256 "$1" | awk '{print $1}'; }
safe_slug() { echo "$1" | tr '/' '_' | tr -cs '[:alnum:]._ -' '_' | sed 's/^_//;s/_$//'; }

ensure_local_index() {
  if [[ ! -f "$LOCAL_INDEX" ]]; then
    cat > "$LOCAL_INDEX" <<'TEMPLATE'
# Bob Master Knowledge Index

Local-first canonical index.

## Proposal Patterns
## Common Scope Blocks
## Common Assumptions
## Common Exclusions
## Product Standards
## Field Lessons

## Intake Log
TEMPLATE
  fi
  if ! grep -q "^## Intake Log" "$LOCAL_INDEX"; then
    echo "" >> "$LOCAL_INDEX"
    echo "## Intake Log" >> "$LOCAL_INDEX"
  fi
}

append_index_entry() {
  local kind="$1" filename="$2" digest="$3" summary="$4"
  ensure_local_index
  {
    echo "- $(ts) | $kind | $filename | sha256:$digest"
    [[ -n "$summary" ]] && echo "  $summary"
  } >> "$LOCAL_INDEX"
}

extract_signals_from_text() {
  local txt="$1" outjson="$2"

  local models headings
  models="$(grep -Eo '\b[A-Z0-9][A-Z0-9\-]{3,40}\b' "$txt" \
    | grep -E '[0-9]' 
    | grep -vE '^(CAT[0-9]+|OM[0-9]+|DIN|NEMA|UL|IAPMO|ANSI|ASTM|NFPA|NEC|FCC|IC|IP[0-9]+|LED|HDMI|USB|RJ45|POE|VLAN|TCP|UDP|HTTP|HTTPS|WIFI|SSID)$' \
    | grep -E '^(CORE[135](-WM)?|EA-|CA-|IOX|TS-|AMS[0-9]+|PAMP[0-9]+|RSP-|AN-[0-9]+-|LUT-|LUTRON|HQP|QSX|RR-|RA2|RA3|T3|T4|CAM|NVR)' \
    | sort -u | head -n 400 || true)"
  headings="$(grep -E '^(Scope|SCOPE|Assumptions|ASSUMPTIONS|Exclusions|EXCLUSIONS|Networking|NETWORKING|Audio|AUDIO|Video|VIDEO|Lighting|LIGHTING|Shades|SHADES|Security|SECURITY|Cameras|CAMERAS|Warranty|WARRANTY)' "$txt" \
    | head -n 200 || true)"

  python3 - <<PY > "$outjson"
import json
models = """$models""".strip().splitlines() if """$models""".strip() else []
headings = """$headings""".strip().splitlines() if """$headings""".strip() else []
print(json.dumps({"models_or_skus_guess": models, "headings_guess": headings}, indent=2))
PY
}

# Writes extracted text to out_txt and echoes method tag: direct | repaired | mutool | minimal
extract_pdf_text_resilient() {
  local pdf="$1" out_txt="$2"
  local tmpdir repaired errfile out2
  tmpdir="$(mktemp -d)"
  repaired="$tmpdir/repaired.pdf"
  errfile="$tmpdir/pdftotext.err"
  out2="$tmpdir/mutool.txt"

  is_good_text() { [[ -s "$1" ]] && [[ $(wc -c < "$1") -ge 200 ]]; }

  : > "$errfile"
  "$PDFTOTEXT" -layout "$pdf" "$out_txt" 2> "$errfile" || true
  if is_good_text "$out_txt"; then
    rm -rf "$tmpdir"; echo "direct"; return 0
  fi

  if [[ -x "$QPDF" ]]; then
    if "$QPDF" --repair "$pdf" "$repaired" >/dev/null 2>&1; then
      : > "$errfile"
      "$PDFTOTEXT" -layout "$repaired" "$out_txt" 2> "$errfile" || true
      if is_good_text "$out_txt"; then
        rm -rf "$tmpdir"; echo "repaired"; return 0
      fi
    fi
  fi

  if [[ -x "$MUTOOL" ]]; then
    "$MUTOOL" draw -F txt "$pdf" > "$out2" 2>/dev/null || true
    if is_good_text "$out2"; then
      cat "$out2" > "$out_txt"
      rm -rf "$tmpdir"; echo "mutool"; return 0
    fi
  fi

  rm -rf "$tmpdir"
  echo "minimal"
  return 0
}

main() {
  local file="${1:-}"
  local kind="${2:-auto}"

  [[ -n "$file" && -f "$file" ]] || exit 0
  [[ -x "$PDFTOTEXT" ]] || exit 0

  local bn lower ext digest slug outdir txt js method models_count
  bn="$(basename "$file")"
  lower="$(echo "$bn" | tr '[:upper:]' '[:lower:]')"
  ext="${lower##*.}"

  if [[ "$kind" == "auto" ]]; then
    if [[ "$file" == *"/Proposals/"* ]]; then kind="proposal"; fi
    if [[ "$file" == *"/Manuals/"* ]]; then kind="manual"; fi
    if [[ "$file" == *"/Drawings/"* ]]; then kind="drawing"; fi
    if [[ "$file" == *"/Markups/"* ]]; then kind="markup"; fi
    [[ "$kind" == "auto" ]] && kind="file"
  fi

  digest="$(sha_file "$file")"
  slug="$(safe_slug "$bn")__${digest:0:12}"

  case "$kind" in
    proposal) outdir="$LOCAL_KB/proposals" ;;
    manual) outdir="$LOCAL_KB/manuals" ;;
    drawing) outdir="$LOCAL_KB/drawings" ;;
    markup) outdir="$LOCAL_KB/markups" ;;
    *) outdir="$LOCAL_KB" ;;
  esac
  mkdir -p "$outdir"

  if [[ "$ext" == "pdf" ]]; then
    txt="$outdir/${slug}.txt"
    js="$outdir/${slug}.json"
    log "Ingesting $kind PDF: $bn"
    method="$(extract_pdf_text_resilient "$file" "$txt")"

    if [[ "$method" == "minimal" ]]; then
      append_index_entry "$kind" "$bn" "$digest" "PDF ingested but text extraction was minimal (plan sheet or malformed PDF)."
      log "Done (minimal text): $bn"
      exit 0
    fi

    extract_signals_from_text "$txt" "$js" || true
    models_count="$(python3 - <<PY
import json
try:
  d=json.load(open("$js"))
  print(len(d.get("models_or_skus_guess",[])))
except Exception:
  print(0)
PY
)"
    append_index_entry "$kind" "$bn" "$digest" "Extracted text via ${method}. Models/SKUs detected: ${models_count}."
    log "Done."
  else
    log "Non-PDF recorded: $bn"
    append_index_entry "$kind" "$bn" "$digest" "Non-PDF recorded (no text extraction)."
    log "Done."
  fi
}

main "$@"
