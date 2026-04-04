#!/usr/bin/env bash
# Ship-it PHASE 4 — end-to-end smoke for OpenClaw + Mission Control + Redis.
# See: .cursor/prompts/ship-it.md
#
# Optional weekly schedule (macOS host): copy
#   setup/launchd/com.symphony.smoke-test.plist → ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.symphony.smoke-test.plist
# (Sundays 6:30 AM local; logs in /tmp/symphony-smoke-test.log)
#
# Usage:
#   ./scripts/smoke-test.sh
#   SMOKE_REBUILD=1 SMOKE_SLEEP=90 ./scripts/smoke-test.sh   # rebuild + wait before checks
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

if [[ "${SMOKE_REBUILD:-0}" == "1" ]]; then
  docker compose build --no-cache openclaw mission-control
  docker compose up -d openclaw mission-control
  sleep "${SMOKE_SLEEP:-90}"
fi

# grep(1) exit 1 means "no match" — normal for sections 9–10 when healthy
set +e

echo "========== SMOKE TEST =========="

echo ""
echo "--- 1. Orchestrator tick (matches real log strings) ---"
docker logs openclaw 2>&1 | grep -E \
  "Orchestrator tick at|Trading check completed|D-Tools sync: [0-9]+ created|Found [0-9]+ new email|Knowledge scan complete|Consolidating memories|Pipeline: [0-9]+ opportunities" \
  | tail -12
if [[ "${PIPESTATUS[1]:-1}" -ne 0 ]]; then
  echo "(no lines matched — inspect: docker logs openclaw | tail -80)"
fi

echo ""
echo "--- 2. Events flowing ---"
docker exec redis redis-cli LRANGE events:log 0 15

echo ""
echo "--- 3. Decision journal ---"
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/decision_journal.db')
c = conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]
scored = conn.execute('SELECT COUNT(*) FROM decisions WHERE outcome IS NOT NULL').fetchone()[0]
print(f'Decisions: {c} total, {scored} scored')
"

echo ""
echo "--- 4. Jobs DB ---"
docker exec openclaw python3 -c "
import sqlite3, os
for path in ['/app/data/jobs.db', '/app/data/openclaw/jobs.db']:
    if os.path.exists(path):
        print('Using', path)
        conn = sqlite3.connect(path)
        tables = [t[0] for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
        for t in tables:
            c = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            print(f'{t}: {c} rows')
        break
else:
    print('jobs.db not found at /app/data/jobs.db or .../openclaw/jobs.db')
"

echo ""
echo "--- 5. Follow-ups DB ---"
docker exec openclaw python3 -c "
import sqlite3, os
db = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'follow_ups.db')
if os.path.exists(db):
    conn = sqlite3.connect(db)
    for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
        c = conn.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
        print(f'{t[0]}: {c} rows')
else:
    print('follow_ups.db not found')
"

echo ""
echo "--- 6. Mission Control ---"
curl -sS --connect-timeout 5 "http://127.0.0.1:8098/health" && echo ""
curl -sS --connect-timeout 5 "http://127.0.0.1:8098/api/services" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Services (all):', d.get('healthy', '?'), '/', d.get('total', '?'))
hc, tc, oh, ot = d.get('healthy_core'), d.get('total_core'), d.get('optional_healthy'), d.get('optional_total')
if hc is None and isinstance(d.get('services'), list):
    opt_names = frozenset({'Remediator', 'ClawWork'})
    def is_opt(s):
        return bool(s.get('optional')) or (s.get('name') in opt_names)
    svcs = d['services']
    core = [s for s in svcs if not is_opt(s)]
    opt = [s for s in svcs if is_opt(s)]
    hc = sum(1 for s in core if s.get('status') == 'healthy')
    tc = len(core)
    oh = sum(1 for s in opt if s.get('status') == 'healthy')
    ot = len(opt)
print('Services (core):', hc, '/', tc, '| optional:', oh, '/', ot)
"
curl -sS --connect-timeout 5 "http://127.0.0.1:8098/api/intelligence" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Intelligence keys: {list(d.keys())[:8]}')" 2>/dev/null || echo "Intelligence endpoint not reachable"

echo ""
echo "--- 7. Redis persistence ---"
docker exec redis redis-cli CONFIG GET appendonly

echo ""
echo "--- 8. Approval endpoint ---"
curl -sS --connect-timeout 5 "http://127.0.0.1:8099/internal/approval" 2>/dev/null | head -c 300
echo ""

echo ""
echo "--- 9. Silent service check (only if a heartbeat source is quiet) ---"
docker logs openclaw 2>&1 | grep "silent_service" | tail -5
if [[ "${PIPESTATUS[1]:-1}" -ne 0 ]]; then
  echo "(no silent_service warnings — normal when all feeds are healthy)"
fi

echo ""
echo "--- 10. Recent ERROR lines (empty is good; ignores asyncio shutdown noise) ---"
ERR_LINES="$(docker logs openclaw 2>&1 | tail -500 | grep '\[ERROR\]' | grep -viE 'asyncio|httpx|redis|DEBUG|debug' | tail -8)"
if [[ -z "${ERR_LINES// }" ]]; then
  echo "(no recent application [ERROR] lines in last 500 log lines)"
else
  echo "${ERR_LINES}"
fi

echo ""
echo "========== SMOKE TEST COMPLETE =========="
set -e
exit 0
