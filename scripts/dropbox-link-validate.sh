#!/usr/bin/env bash
# scripts/dropbox-link-validate.sh — Lesson #4 validator.
# Fails (exit 1) if any input contains a Dropbox /preview/ URL.
# Client-facing Dropbox links MUST use the scl/fi/ share format.
#
# Usage:
#   bash scripts/dropbox-link-validate.sh <file1> [<file2> ...]
#   echo "some text" | bash scripts/dropbox-link-validate.sh
#   bash scripts/dropbox-link-validate.sh --staged        # check files in git staging
#
# Safe to wire into pre-commit or CI. Read-only.
set -euo pipefail

# Matches dropbox.com/<user>/preview/... (case-insensitive)
PREVIEW_RE='(https?://[A-Za-z0-9._-]*dropbox\.com[^[:space:])"<>]*/preview/)'
PROB_COUNT=0

check_stream() {
  local label="$1"
  local content="$2"
  if printf '%s' "$content" | grep -iE "$PREVIEW_RE" >/dev/null 2>&1; then
    echo "FAIL: $label contains /preview/ Dropbox link(s):"
    printf '%s' "$content" | grep -inE "$PREVIEW_RE" | head -n 5
    echo ""
    PROB_COUNT=$((PROB_COUNT + 1))
  fi
}

if [ "${1:-}" = "--staged" ]; then
  # Check every file in git staging.
  mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACMR)
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
      check_stream "$f" "$(cat "$f")"
    fi
  done
elif [ $# -gt 0 ]; then
  for f in "$@"; do
    if [ -f "$f" ]; then
      check_stream "$f" "$(cat "$f")"
    else
      echo "skip: $f (not a regular file)"
    fi
  done
else
  # stdin
  content="$(cat)"
  check_stream "(stdin)" "$content"
fi

if [ "$PROB_COUNT" -gt 0 ]; then
  echo "dropbox-link-validate: $PROB_COUNT input(s) contain forbidden /preview/ links."
  echo "Fix: replace with the scl/fi/... share-link format."
  exit 1
fi

echo "dropbox-link-validate: OK (no /preview/ links found)"
exit 0
