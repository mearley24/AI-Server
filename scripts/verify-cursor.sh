#!/usr/bin/env bash
set -euo pipefail
for f in "$@"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
  elif [ "$(wc -l < "$f" | tr -d ' ')" -lt 10 ]; then
    echo "STUB (<10 lines): $f"
  else
    echo "OK ($(wc -l < "$f" | tr -d ' ') lines): $f"
  fi
done
