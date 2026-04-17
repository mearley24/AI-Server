#!/usr/bin/env bash
# scripts/backup-cortex-dbs.sh — snapshot the important SQLite DBs.
# Uses sqlite3 .backup (safe with WAL, doesn't block writers).
# Dry-run by default. Pass --execute to actually write.
# Targets (high-value):
#   - data/cortex/brain.db
#   - data/openclaw/decision_journal.db
#   - data/openclaw/jobs.db
#   - data/email-monitor/follow_ups.db
#   - data/email-monitor/emails.db
# Skipped (low-value / redundant):
#   - data/openclaw/cost_tracker.db  (sparse)
#   - data/openclaw/price_monitor.db (stale pipeline)
#   - data/openclaw/openclaw_memory.db (redundant vs brain.db)
#
# Output: backups/sqlite/YYYYMMDD-HHMMSS/<basename>.db
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"

EXECUTE=0
if [ "${1:-}" = "--execute" ]; then EXECUTE=1; fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
DEST="backups/sqlite/$STAMP"

TARGETS=(
  "data/cortex/brain.db"
  "data/openclaw/decision_journal.db"
  "data/openclaw/jobs.db"
  "data/email-monitor/follow_ups.db"
  "data/email-monitor/emails.db"
)

echo "backup-cortex-dbs stamp=$STAMP execute=$EXECUTE dest=$DEST"
echo ""

if [ "$EXECUTE" = "0" ]; then
  echo "(dry-run) would create $DEST and write the following:"
  for t in "${TARGETS[@]}"; do
    if [ -f "$t" ]; then
      sz="$(du -h "$t" | awk '{print $1}')"
      echo "  - $t ($sz)"
    else
      echo "  - $t (MISSING, would skip)"
    fi
  done
  echo ""
  echo "Pass --execute to actually run."
  exit 0
fi

mkdir -p "$DEST"

TOTAL=0
for t in "${TARGETS[@]}"; do
  if [ ! -f "$t" ]; then
    echo "skip: $t (missing)"
    continue
  fi
  out="$DEST/$(basename "$t")"
  if /usr/bin/sqlite3 "$t" ".backup '$out'"; then
    sz="$(du -h "$out" | awk '{print $1}')"
    echo "wrote: $out ($sz)"
    TOTAL=$((TOTAL + 1))
  else
    echo "FAIL: $t (sqlite3 .backup returned non-zero)"
  fi
done

echo ""
echo "total snapshots: $TOTAL"
echo "destination: $DEST"
