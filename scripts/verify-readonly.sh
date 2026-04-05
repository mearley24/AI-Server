#!/usr/bin/env bash
# AI-Server Non-Destructive Verification — run on Bob
# Usage: bash scripts/verify-readonly.sh
set -uo pipefail

cd ~/AI-Server || { echo "FATAL: ~/AI-Server not found"; exit 1; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    local name="$1" result="$2"
    if [[ "$result" == "PASS" ]]; then
        echo -e "  ${GREEN}✓${NC} $name"; ((PASS++)) || true
    elif [[ "$result" == "WARN" ]]; then
        echo -e "  ${YELLOW}⚠${NC} $name"; ((WARN++)) || true
    else
        echo -e "  ${RED}✗${NC} $name"; ((FAIL++)) || true
    fi
}

# Normalize docker health: missing Health / empty -> no-healthcheck; starting -> OK for verify
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
echo "AI-Server Read-Only Verification"
echo "$(date)"
echo "========================================="

# ── 1. Redis ──
echo ""
echo "--- Redis ---"
REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env 2>/dev/null | cut -d= -f2- | tr -d '\r')
if [[ -z "$REDIS_PASS" ]]; then
    check "REDIS_PASSWORD in .env" "FAIL"
else
    if docker exec redis redis-cli -a "$REDIS_PASS" ping 2>/dev/null | grep -q PONG; then
        check "Redis auth (PONG)" "PASS"
    else
        check "Redis auth" "FAIL"
    fi
    if docker exec redis redis-cli ping 2>/dev/null | grep -q PONG; then
        check "Redis NO-auth (SHOULD FAIL)" "FAIL"
    else
        check "Redis rejects unauthenticated" "PASS"
    fi
    COST_KEYS=$(docker exec redis redis-cli -a "$REDIS_PASS" KEYS "llm:costs:*" 2>/dev/null | wc -l | tr -d ' ')
    check "llm:costs:* keys: $COST_KEYS" "PASS"
    DRAFT_LEN=$(docker exec redis redis-cli -a "$REDIS_PASS" LLEN email:drafts 2>/dev/null | tr -d ' ')
    check "email:drafts length: $DRAFT_LEN" "PASS"
fi

# ── 2. Port Security ──
echo ""
echo "--- Port Security ---"
EXPOSED=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep "0.0.0.0" || true)
if [[ -z "$EXPOSED" ]]; then
    check "All ports 127.0.0.1" "PASS"
else
    check "EXPOSED PORTS: $EXPOSED" "FAIL"
fi

# ── 3. Container Health ──
echo ""
echo "--- Container Health ---"
for c in redis openclaw email-monitor notification-hub mission-control polymarket-bot \
         context-preprocessor voice-receptionist openwebui remediator vpn \
         calendar-agent proposals dtools-bridge knowledge-scanner x-intake intel-feeds; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${c}$"; then
        if docker_health_pass "$c"; then
            check "$c" "PASS"
        else
            health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "?")
            health=$(echo -n "$health" | tr -d '\r\n' | xargs)
            check "$c (${health:-unknown})" "WARN"
        fi
    else
        check "$c (NOT RUNNING)" "WARN"
    fi
done

# ── 4. API Endpoints ──
echo ""
echo "--- API Endpoints ---"
curl -sf http://127.0.0.1:8099/health >/dev/null 2>&1 && check "OpenClaw /health" "PASS" || check "OpenClaw /health" "FAIL"
curl -sf http://127.0.0.1:8099/api/llm-costs >/dev/null 2>&1 && check "OpenClaw /api/llm-costs" "PASS" || check "OpenClaw /api/llm-costs" "WARN"
curl -sf http://127.0.0.1:8092/health >/dev/null 2>&1 && check "Email Monitor /health" "PASS" || check "Email Monitor /health" "FAIL"
curl -sf http://127.0.0.1:8098/health >/dev/null 2>&1 && check "Mission Control /health" "PASS" || check "Mission Control /health" "WARN"
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
curl -sf http://127.0.0.1:8430/health >/dev/null 2>&1 && check "Polymarket Bot /health" "PASS" || check "Polymarket Bot /health" "FAIL"

# ── 5. Strategy Imports ──
echo ""
echo "--- Strategy Imports ---"
docker exec polymarket-bot python3 -c "from strategies.polymarket_copytrade import PolymarketCopyTrader; print('OK')" 2>/dev/null \
    && check "PolymarketCopyTrader import" "PASS" || check "PolymarketCopyTrader import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.weather_trader import WeatherTraderStrategy; print('OK')" 2>/dev/null \
    && check "WeatherTraderStrategy import" "PASS" || check "WeatherTraderStrategy import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.spread_arb import SpreadArbScanner; print('OK')" 2>/dev/null \
    && check "SpreadArbScanner import" "PASS" || check "SpreadArbScanner import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.strategy_manager import StrategyManager; print('OK')" 2>/dev/null \
    && check "StrategyManager import" "PASS" || check "StrategyManager import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker; print('OK')" 2>/dev/null \
    && check "AvellanedaMarketMaker import" "PASS" || check "AvellanedaMarketMaker import" "FAIL"

# ── 6. Email Monitor Checks ──
echo ""
echo "--- Email Monitor ---"
# Glob must run inside the container (host /app/*.py does not exist)
docker exec email-monitor sh -c 'grep -Rq "BODY.PEEK" /app --include="*.py" 2>/dev/null' \
    && check "BODY.PEEK in monitor" "PASS" || check "BODY.PEEK in monitor" "WARN"
BARE_BODY=$(docker exec email-monitor sh -c 'grep -R "BODY\[" /app --include="*.py" 2>/dev/null' | grep -v "PEEK" || true)
[[ -z "$BARE_BODY" ]] && check "No bare BODY[] fetch" "PASS" || check "Bare BODY[] found" "WARN"

# ── 7. Ollama LAN ──
echo ""
echo "--- Ollama LAN ---"
curl -sf http://192.168.1.199:11434/api/tags >/dev/null 2>&1 \
    && check "Ollama reachable from host" "PASS" || check "Ollama NOT reachable from host" "WARN"

# ── 8. Secrets Scan ──
echo ""
echo "--- Secrets Scan (should be empty) ---"
LEAKED=$(grep -rn 'sk-ant-\|sk-proj-\|pplx-' --include="*.py" --include="*.yml" --include="*.yaml" --include="*.json" \
    . 2>/dev/null | grep -v ".env.example" | grep -v "node_modules" | grep -v ".git/" | grep -v ".venv/" \
    | grep -v "# " | grep -v "YOUR_" | grep -v "1234567890" | grep -v "sk-ant-\.\.\." | head -5)
[[ -z "$LEAKED" ]] && check "No leaked API keys in source" "PASS" || check "LEAKED KEYS: $LEAKED" "FAIL"

REDIS_LEAKED=$(grep -rn 'requirepass' --include="*.py" --include="*.yml" \
    . 2>/dev/null | grep -v ".git/" | grep -v "redis.conf" | grep -v ".env" | head -5)
[[ -z "$REDIS_LEAKED" ]] && check "No Redis password in source" "PASS" || check "REDIS PASSWORD IN SOURCE: $REDIS_LEAKED" "FAIL"

# ── 9. Watchdog & Bridge ──
echo ""
echo "--- Host Daemons ---"
launchctl list 2>/dev/null | grep -q "com.symphony.bob-watchdog" \
    && check "Watchdog daemon" "PASS" || check "Watchdog daemon" "WARN"
launchctl list 2>/dev/null | grep -q "com.symphony.imessage-bridge" \
    && check "iMessage bridge daemon" "PASS" || check "iMessage bridge daemon" "WARN"

# ── 10. py_compile Spot Checks ──
echo ""
echo "--- Syntax Checks (py_compile) ---"
for f in openclaw/main.py openclaw/llm_router.py openclaw/llm_cache.py \
         openclaw/auto_responder.py integrations/x_intake/bridge.py \
         integrations/apple_notes/notes_indexer.py tools/cortex_curator.py; do
    if [[ -f "$f" ]]; then
        python3 -m py_compile "$f" 2>/dev/null \
            && check "py_compile $f" "PASS" || check "py_compile $f" "FAIL"
    else
        check "$f (file not found)" "WARN"
    fi
done

# ── Summary ──
echo ""
echo "========================================="
echo -e "  ${GREEN}PASS: $PASS${NC}  ${YELLOW}WARN: $WARN${NC}  ${RED}FAIL: $FAIL${NC}"
echo "========================================="
