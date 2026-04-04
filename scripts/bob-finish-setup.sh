#!/usr/bin/env bash
# All-in-one host setup + verification for Bob (Mac Mini).
# Run once after the latest code is deployed:
#   cd ~/AI-Server && ./scripts/bob-finish-setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "============================================"
echo "  Symphony AI-Server — Bob Host Setup"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. Pull latest + rebuild containers that changed
# ------------------------------------------------------------------
echo "--- 1. Git pull + rebuild ---"
git pull --ff-only 2>/dev/null || echo "(pull skipped — may be dirty)"
docker compose build openclaw mission-control dtools-bridge
docker compose up -d
echo ""

# ------------------------------------------------------------------
# 2. Install backup cron (idempotent — won't duplicate)
# ------------------------------------------------------------------
echo "--- 2. Backup cron ---"
CRON_LINE="0 4 * * * ${ROOT}/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1"
( crontab -l 2>/dev/null | grep -v "backup-data.sh"; echo "$CRON_LINE" ) | crontab -
echo "Installed: $CRON_LINE"
echo ""

# ------------------------------------------------------------------
# 3. Load launchd plists (idempotent — ignores already-loaded)
# ------------------------------------------------------------------
echo "--- 3. Launchd plists ---"
for plist in \
  setup/launchd/com.symphony.smoke-test.plist \
  setup/launchd/com.symphony.learning.plist; do
  if [ -f "$plist" ]; then
    dest="$HOME/Library/LaunchAgents/$(basename "$plist")"
    cp "$plist" "$dest"
    launchctl load "$dest" 2>/dev/null && echo "Loaded $dest" || echo "Already loaded: $(basename "$plist")"
  fi
done
echo ""

# ------------------------------------------------------------------
# 4. Configure always-on (pmset — needs sudo, skip if denied)
# ------------------------------------------------------------------
echo "--- 4. Always-on power settings ---"
if sudo -n true 2>/dev/null; then
  sudo pmset -c sleep 0 disksleep 0 displaysleep 15 womp 1 autorestart 1
  echo "Power settings applied."
else
  echo "Skipped (needs sudo). Run manually: sudo ./setup/nodes/configure_bob_always_on.sh"
fi
echo ""

# ------------------------------------------------------------------
# 5. Wait for containers to stabilize
# ------------------------------------------------------------------
echo "--- 5. Waiting 60s for services to stabilize ---"
sleep 60

# ------------------------------------------------------------------
# 6. Smoke test
# ------------------------------------------------------------------
echo "--- 6. Smoke test ---"
chmod +x scripts/smoke-test.sh 2>/dev/null || true
./scripts/smoke-test.sh
echo ""

# ------------------------------------------------------------------
# 7. Service health (Mission Control)
# ------------------------------------------------------------------
echo "--- 7. Mission Control services ---"
curl -sS http://127.0.0.1:8098/api/services 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    hc = d.get('healthy_core', '?')
    tc = d.get('total_core', '?')
    oh = d.get('optional_healthy', '?')
    ot = d.get('optional_total', '?')
    print(f'Core: {hc}/{tc}   Optional: {oh}/{ot}')
    for s in d.get('services', []):
        tag = ' (optional)' if s.get('optional') else ''
        icon = '✓' if s['status'] == 'healthy' else '✗'
        print(f'  {icon} {s[\"name\"]:20s} :{s[\"port\"]}  {s[\"status\"]}{tag}')
except Exception as e:
    print(f'Could not parse /api/services: {e}')
" || echo "Mission Control unreachable"
echo ""

# ------------------------------------------------------------------
# 8. D-Tools Bridge
# ------------------------------------------------------------------
echo "--- 8. D-Tools Bridge ---"
curl -sS --max-time 5 http://127.0.0.1:8096/health 2>/dev/null | python3 -m json.tool || echo "D-Tools Bridge unreachable on 8096"
echo ""

# ------------------------------------------------------------------
# 9. Redis events
# ------------------------------------------------------------------
echo "--- 9. Redis events:log (last 5) ---"
docker exec redis redis-cli LRANGE events:log 0 4 2>/dev/null || echo "Redis unreachable"
echo ""

# ------------------------------------------------------------------
# 10. DB population check
# ------------------------------------------------------------------
echo "--- 10. SQLite DBs ---"
docker exec openclaw python3 -c "
import sqlite3, os, glob
data = '/app/data'
for pattern in ['*.db', '**/*.db']:
    for db in glob.glob(os.path.join(data, pattern), recursive=True):
        try:
            conn = sqlite3.connect(db)
            tables = [t[0] for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
            total = sum(conn.execute(f'SELECT COUNT(*) FROM \"{t}\"').fetchone()[0] for t in tables)
            conn.close()
            name = os.path.relpath(db, data)
            print(f'  {name}: {len(tables)} tables, {total} rows')
        except Exception as e:
            print(f'  {os.path.relpath(db, data)}: {e}')
" 2>/dev/null || echo "OpenClaw not running"
echo ""

# ------------------------------------------------------------------
# 11. Env flags
# ------------------------------------------------------------------
echo "--- 11. Key env flags ---"
docker exec openclaw printenv 2>/dev/null | grep -E "AUTO_RESPONDER|DTOOLS_API_KEY|APPROVAL_BRIDGE|REDIS_URL" | sed 's/=.*=.*/=***/' || echo "OpenClaw not running"
echo ""

# ------------------------------------------------------------------
# 12. Quick local tool tests
# ------------------------------------------------------------------
echo "--- 12. Local tools ---"
python3 openclaw/task_board.py status 2>/dev/null || echo "task_board: needs DATA_DIR"
python3 tools/bob_maintenance.py --dry 2>/dev/null | tail -2 || echo "bob_maintenance: error"
echo ""

echo "============================================"
echo "  Done. Review output above for any ✗ marks"
echo "  or missing data. See orchestrator/"
echo "  WORK_IN_PROGRESS.md for queued items."
echo "============================================"
