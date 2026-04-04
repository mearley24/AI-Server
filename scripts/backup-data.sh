#!/usr/bin/env bash
# Backup SQLite DBs under AI-Server. Run daily via cron (see close-the-loop prompt).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${ROOT}/backups/$(date +%Y-%m-%d)"
mkdir -p "$BACKUP_DIR"

for db in \
  data/decision_journal.db \
  data/cost_tracker.db \
  data/openclaw/jobs.db \
  data/openclaw/openclaw_memory.db \
  data/email-monitor/emails.db \
  data/mission-control/events.db \
  data/polymarket/weather_accuracy.db
do
  if [[ -f "${ROOT}/${db}" ]]; then
    cp "${ROOT}/${db}" "${BACKUP_DIR}/$(basename "$db")"
  fi
done

# Prune backup day folders older than 7 days
find "${ROOT}/backups" -maxdepth 1 -mindepth 1 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true

echo "Backed up to $BACKUP_DIR"

if [[ "${BACKUP_SHOW_CRON:-}" == "1" ]]; then
  echo ""
  echo "=== INSTALL BACKUP CRON ==="
  echo "Run this on the host (not in Docker):"
  echo "  crontab -e"
  echo "  Add this line:"
  echo "  0 4 * * * /Users/bob/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1"
  echo ""
fi
