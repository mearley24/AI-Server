#!/usr/bin/env bash
# scripts/verification-prune.sh — prune old ops/verification/ artifacts.
# Default: DRY-RUN. Pass --execute to actually delete.
# Preserves any file whose basename contains:
#   - "-final."
#   - "-campaign-"
#   - "-blocker-"
# so summary, campaign trackers, and explicit blocker reports survive.
# Low-risk repo hygiene. Bounded. Idempotent.
#
# Usage:
#   bash scripts/verification-prune.sh                # dry-run, 90 days
#   bash scripts/verification-prune.sh --days 30      # dry-run, 30 days
#   bash scripts/verification-prune.sh --execute      # actually delete
#   DAYS=60 EXECUTE=1 bash scripts/verification-prune.sh
set -euo pipefail

ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
VERIF="$ROOT/ops/verification"
DAYS="${DAYS:-90}"
EXECUTE="${EXECUTE:-0}"

while [ $# -gt 0 ]; do
  case "$1" in
    --execute) EXECUTE=1; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -d "$VERIF" ] || { echo "no $VERIF"; exit 0; }

echo "verification-prune: days=$DAYS execute=$EXECUTE dir=$VERIF"
echo ""

# BSD find syntax (macOS). -mtime +N matches files older than N days.
CANDIDATES="$(find "$VERIF" -maxdepth 1 -type f -mtime "+$DAYS" 2>/dev/null || true)"

if [ -z "$CANDIDATES" ]; then
  echo "nothing older than $DAYS days. Exit."
  exit 0
fi

KEEP_COUNT=0
DELETE_COUNT=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  base="$(basename "$f")"
  case "$base" in
    *-final.*|*-campaign-*|*-blocker-*)
      echo "KEEP   $base"
      KEEP_COUNT=$((KEEP_COUNT + 1))
      ;;
    *)
      if [ "$EXECUTE" = "1" ]; then
        rm -- "$f"
        echo "DELETE $base"
      else
        echo "WOULD  $base"
      fi
      DELETE_COUNT=$((DELETE_COUNT + 1))
      ;;
  esac
done <<< "$CANDIDATES"

echo ""
echo "summary: keep=$KEEP_COUNT delete=$DELETE_COUNT execute=$EXECUTE"
if [ "$EXECUTE" = "0" ] && [ "$DELETE_COUNT" -gt 0 ]; then
  echo "Pass --execute to actually delete."
fi
