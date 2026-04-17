#!/usr/bin/env bash
# scripts/cortex-brain-snapshot.sh — read-only informational snapshot of
# cortex/brain.db. Writes to ops/verification/<stamp>-cortex-brain-snapshot.txt
# so agents can consult without poking sqlite directly.
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"
DB="data/cortex/brain.db"
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="ops/verification/${STAMP}-cortex-brain-snapshot.txt"

if [ ! -f "$DB" ]; then
  echo "no $DB"
  exit 0
fi

mkdir -p "$(dirname "$OUT")"

{
  echo "=== cortex/brain.db snapshot ==="
  echo "when: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "db:   $DB"
  echo "size: $(du -h "$DB" | awk '{print $1}')"
  echo ""
  echo "--- row counts ---"
  /usr/bin/sqlite3 "$DB" "SELECT COUNT(*) FROM memories" | awk '{print "total: " $1}'
  echo ""
  echo "--- by category (top 20) ---"
  /usr/bin/sqlite3 -column -header "$DB" \
    "SELECT category, COUNT(*) AS rows FROM memories GROUP BY category ORDER BY rows DESC LIMIT 20"
  echo ""
  echo "--- 5 newest memories ---"
  /usr/bin/sqlite3 -column -header "$DB" \
    "SELECT updated_at, category, substr(title,1,40) AS title FROM memories ORDER BY updated_at DESC LIMIT 5"
  echo ""
  echo "--- importance distribution ---"
  /usr/bin/sqlite3 -column -header "$DB" \
    "SELECT importance, COUNT(*) AS rows FROM memories GROUP BY importance ORDER BY importance DESC"
} > "$OUT" 2>&1

echo "wrote: $OUT"
