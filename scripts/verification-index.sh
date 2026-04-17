#!/usr/bin/env bash
# scripts/verification-index.sh — regenerate ops/verification/INDEX.txt.
# Produces a cheap, grep-friendly summary of the newest artifact per topic
# and a tail of the last 30 artifacts. Safe to run repeatedly.
# Low-risk repo hygiene. Bounded. No external network.
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
VERIF="$ROOT/ops/verification"
OUT="$VERIF/INDEX.txt"

[ -d "$VERIF" ] || { echo "no $VERIF"; exit 0; }

{
  echo "# ops/verification/ INDEX"
  echo "# Generated: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "# Artifact count: $(ls "$VERIF" | wc -l | tr -d ' ')"
  echo ""
  echo "## Newest artifact per topic"
  # Strip the timestamp prefix to derive a topic slug, then print the
  # newest artifact for each unique slug. Works even with oddly-named files.
  ls -1t "$VERIF" 2>/dev/null \
    | grep -E '^[0-9]{8}-[0-9]{6}' \
    | awk -F- '
        {
          topic=""
          for (i=3; i<=NF; i++) {
            if (i==3) topic=$i; else topic=topic"-"$i
          }
          if (!(topic in seen)) { seen[topic]=$0; print $0 }
        }
      ' \
    | sort
  echo ""
  echo "## Last 30 artifacts (newest first)"
  ls -1t "$VERIF" 2>/dev/null | head -n 30
} > "$OUT"

echo "wrote $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)"
