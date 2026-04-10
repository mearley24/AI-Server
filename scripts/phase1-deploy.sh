echo "=== PHASE 1: Pull and Deploy ==="

cd ~/AI-Server && bash scripts/pull.sh

echo ""
echo "=== Building client-portal ==="
docker compose up -d --build client-portal

echo ""
echo "=== Rebuilding openclaw with latest ==="
docker compose up -d --build openclaw

echo ""
echo "=== All container status ==="
docker ps --format "table {{.Names}}\t{{.Status}}" | sort

echo ""
echo "=== Follow-ups count ==="
sqlite3 ./data/openclaw/follow_ups.db "SELECT COUNT(*) FROM follow_ups" 2>/dev/null || echo "follow_ups.db not found or empty"

echo ""
echo "=== Jobs by phase ==="
sqlite3 ./data/openclaw/jobs.db "SELECT COUNT(*), phase FROM jobs GROUP BY phase" 2>/dev/null || echo "jobs.db not found or empty"

echo ""
echo "=== Client portal health ==="
curl -s http://localhost:8096/health 2>/dev/null || echo "client-portal not responding on 8096"

echo ""
echo "=== Email-Linear pipeline check ==="
docker compose logs openclaw --tail 30 2>&1 | grep -i "linear\|comment\|pipeline" || echo "no linear activity in recent logs"

echo ""
echo "=== Duplicate iMessage check ==="
docker compose logs openclaw --tail 50 2>&1 | grep -i "suppress\|dedup\|hash\|skip" || echo "no dedup activity in recent logs"

echo ""
echo "=== Done. Paste output back ==="
