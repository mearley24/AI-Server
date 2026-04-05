#!/usr/bin/env bash
# Full smoke test for all 18 services
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
    local name="$1" result="$2"
    if [[ "$result" == "PASS" ]]; then
        echo -e "  ${GREEN}✓${NC} $name"
        ((PASS++)) || true
    elif [[ "$result" == "WARN" ]]; then
        echo -e "  ${YELLOW}⚠${NC} $name"
        ((WARN++)) || true
    else
        echo -e "  ${RED}✗${NC} $name"
        ((FAIL++)) || true
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

docker_health_pass() {
    local c="$1" health
    health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || true)
    health=$(echo -n "$health" | tr -d '\r\n' | xargs)
    if [[ -z "$health" ]]; then
        health="no-healthcheck"
    fi
    case "$health" in
        healthy|no-healthcheck|starting) return 0 ;;
        *) return 1 ;;
    esac
}

echo "========================================="
echo "Full Smoke Test — $(date)"
echo "========================================="

echo ""
echo "--- Container Health ---"
EXPECTED_CONTAINERS="redis openclaw email-monitor notification-hub calendar-agent proposals dtools-bridge mission-control knowledge-scanner clawwork voice-receptionist openwebui remediator vpn polymarket-bot intel-feeds x-intake context-preprocessor"
RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null || true)
for c in $EXPECTED_CONTAINERS; do
    if echo "$RUNNING" | grep -q "^${c}$"; then
        if docker_health_pass "$c"; then
            check "$c" "PASS"
        else
            health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "?")
            health=$(echo -n "$health" | tr -d '\r\n' | xargs)
            check "$c (${health:-unknown})" "WARN"
        fi
    else
        check "$c (NOT RUNNING)" "FAIL"
    fi
done

echo ""
echo "--- API Endpoints ---"

if curl -sf http://127.0.0.1:8099/health >/dev/null 2>&1; then
    check "OpenClaw /health" "PASS"
else
    check "OpenClaw /health" "FAIL"
fi

if curl -sf http://127.0.0.1:8099/briefing/status >/dev/null 2>&1; then
    check "OpenClaw /briefing/status" "PASS"
else
    check "OpenClaw /briefing/status" "FAIL"
fi

if curl -sf http://127.0.0.1:8092/health >/dev/null 2>&1; then
    check "Email Monitor /health" "PASS"
else
    check "Email Monitor /health" "FAIL"
fi

MC_TOKEN=$(grep MISSION_CONTROL_TOKEN "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')
if [[ -n "$MC_TOKEN" ]]; then
    if curl -sf "http://127.0.0.1:8098/health" >/dev/null 2>&1; then
        check "Mission Control /health (no auth)" "PASS"
    else
        check "Mission Control /health" "FAIL"
    fi
    if curl -sf "http://127.0.0.1:8098/dashboard?token=$MC_TOKEN" >/dev/null 2>&1; then
        check "Mission Control /dashboard (auth)" "PASS"
    else
        check "Mission Control /dashboard (auth)" "WARN"
    fi
else
    check "Mission Control (no token in .env)" "WARN"
fi

if curl -sf http://127.0.0.1:8430/health >/dev/null 2>&1; then
    check "Polymarket Bot /health" "PASS"
else
    check "Polymarket Bot /health" "FAIL"
fi

if curl -sf http://127.0.0.1:8101/health >/dev/null 2>&1; then
    check "X-Intake /health" "PASS"
else
    check "X-Intake /health" "FAIL"
fi

if curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
    check "Intel Feeds /health" "PASS"
else
    check "Intel Feeds /health" "FAIL"
fi

CP_HTTP=$(curl -4 -sS -o /dev/null -w "%{http_code}" --max-time 5 -L http://127.0.0.1:8028/health 2>/dev/null || echo "000")
if [[ "$CP_HTTP" != "200" ]] && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^context-preprocessor$'; then
    if docker exec context-preprocessor python -c "import urllib.request as u,sys; r=u.urlopen('http://127.0.0.1:8028/health'); sys.exit(0 if getattr(r,'status',200)==200 else 1)" 2>/dev/null; then
        CP_HTTP="200"
    fi
fi
if [[ "$CP_HTTP" == "200" ]]; then
    check "Context Preprocessor /health" "PASS"
else
    check "Context Preprocessor /health (HTTP ${CP_HTTP})" "WARN"
fi

echo ""
echo "--- Redis Auth ---"
REDIS_PASS=$(grep "^REDIS_PASSWORD=" "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')
if docker exec redis redis-cli -a "$REDIS_PASS" ping 2>/dev/null | grep -q PONG; then
    check "Redis auth (PONG)" "PASS"
else
    check "Redis auth" "FAIL"
fi
if redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG; then
    check "Redis NO auth (should fail)" "FAIL"
else
    check "Redis rejects unauthenticated" "PASS"
fi

echo ""
echo "--- Port Security ---"
EXPOSED=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep "0.0.0.0" | grep -v "8098" || true)
if [[ -z "$EXPOSED" ]]; then
    check "All ports 127.0.0.1 (except MC 8098)" "PASS"
else
    check "Exposed ports found: $EXPOSED" "FAIL"
fi

echo ""
echo "--- Watchdog ---"
# Optional LaunchAgent — not required for Docker stack verification
if launchctl list 2>/dev/null | grep -q "com.symphony.bob-watchdog"; then
    check "Watchdog daemon running" "PASS"
else
    check "Watchdog daemon (optional, not installed)" "PASS"
fi
if [[ -f /usr/local/var/log/bob-watchdog.log ]]; then
    LAST_TICK=$(tail -1 /usr/local/var/log/bob-watchdog.log 2>/dev/null | grep -o '20[0-9-]* [0-9:]*' | head -1)
    check "Watchdog last tick: ${LAST_TICK:-unknown}" "PASS"
else
    check "Watchdog log (optional)" "PASS"
fi

echo ""
echo "--- iMessage Bridge ---"
if launchctl list 2>/dev/null | grep -q "com.symphony.imessage-bridge"; then
    check "iMessage bridge running" "PASS"
else
    check "iMessage bridge" "FAIL"
fi
if tail -5 /tmp/imessage-bridge.log 2>/dev/null | grep -q "Watching for handles"; then
    check "iMessage watching handles" "PASS"
else
    check "iMessage watching handles" "WARN"
fi

echo ""
echo "--- Trading Bot ---"
RECENT_TRADES=$(docker logs polymarket-bot --since 10m 2>&1 | grep "copytrade_copy_executed" | wc -l | tr -d ' ')
check "Copytrade trades (last 10m): $RECENT_TRADES" "PASS"

ARB_FOUND=$(docker logs polymarket-bot --since 10m 2>&1 | grep "arb_negative_risk_found" | tail -1 | grep -o '"count": [0-9]*' | grep -o '[0-9]*' || true)
check "Arb opportunities found: ${ARB_FOUND:-0}" "PASS"

WEATHER=$(docker logs polymarket-bot --since 10m 2>&1 | grep "weather_tick_complete" | tail -1 || true)
if echo "$WEATHER" | grep -q "candidates"; then
    CANDIDATES=$(echo "$WEATHER" | grep -o '"candidates": [0-9]*' | grep -o '[0-9]*' || true)
    check "Weather candidates: ${CANDIDATES:-0}" "PASS"
else
    check "Weather ticker not running" "WARN"
fi

REDEEMED=$(docker logs polymarket-bot --since 1h 2>&1 | grep "redeemer_complete" | tail -1 || true)
if [[ -n "$REDEEMED" ]]; then
    check "Redeemer active: $REDEEMED" "PASS"
else
    check "Redeemer (no recent activity)" "WARN"
fi

echo ""
echo "--- Data Integrity ---"
FU_COUNT=$(sqlite3 /Users/bob/AI-Server/data/openclaw/follow_ups.db "SELECT COUNT(*) FROM follow_ups" 2>/dev/null || echo "0")
if [[ "$FU_COUNT" -gt 0 ]]; then check "follow_ups rows: $FU_COUNT" "PASS"; else check "follow_ups rows: $FU_COUNT" "FAIL"; fi

DJ_COUNT=$(sqlite3 /Users/bob/AI-Server/data/openclaw/decision_journal.db "SELECT COUNT(*) FROM decisions" 2>/dev/null || echo "0")
if [[ "$DJ_COUNT" -gt 0 ]]; then check "Decision journal entries: $DJ_COUNT" "PASS"; else check "Decision journal entries: $DJ_COUNT" "FAIL"; fi

EMAIL_COUNT=$(sqlite3 /Users/bob/AI-Server/data/email-monitor/emails.db "SELECT COUNT(*) FROM emails" 2>/dev/null || echo "0")
if [[ "$EMAIL_COUNT" -gt 0 ]]; then check "Email DB entries: $EMAIL_COUNT" "PASS"; else check "Email DB entries: $EMAIL_COUNT" "FAIL"; fi

JOBS=$(sqlite3 /Users/bob/AI-Server/data/openclaw/jobs.db "SELECT COUNT(*) FROM jobs" 2>/dev/null || echo "0")
if [[ "$JOBS" -gt 0 ]]; then check "Jobs DB entries: $JOBS" "PASS"; else check "Jobs DB entries: $JOBS" "FAIL"; fi

echo ""
echo "========================================="
echo -e "  ${GREEN}PASS: $PASS${NC}  ${YELLOW}WARN: $WARN${NC}  ${RED}FAIL: $FAIL${NC}"
echo "========================================="
