#!/usr/bin/env bash
# =============================================================================
# setup_ha_integration.sh — Symphony Smart Homes
# Home Assistant Integration Setup for Bob the Conductor
#
# Verifies all connectivity, builds initial device registry, and runs a full
# smoke test before bringing the integration live.
#
# Usage:
#   chmod +x setup_ha_integration.sh
#   ./setup_ha_integration.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

pass() { echo -e "  ${GREEN}✓${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAILURES=$((FAILURES+1)); }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; }
info() { echo -e "  ${BLUE}→${RESET} $1"; }
header() { echo -e "\n${BOLD}${BLUE}$1${RESET}"; echo "──────────────────────────────────────────────────────"; }

FAILURES=0
START_TIME=$(date +%s)

ENV_FILE="${ENV_FILE:-.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
    info "Loaded environment from $ENV_FILE"
else
    warn ".env file not found — using environment variables directly"
fi

check_env_var() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    if [ -z "$var_value" ] || [[ "$var_value" == *"your-"* ]] || [[ "$var_value" == *"PI_IP"* ]]; then
        fail "Environment variable $var_name is not set or still has placeholder value"
        return 1
    fi
    return 0
}

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   Symphony Smart Homes — HA Integration Setup        ║${RESET}"
echo -e "${BOLD}║   Bob the Conductor × Home Assistant                  ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

header "STEP 1: Validating environment variables"

check_env_var "HA_URL"        && pass "HA_URL = $HA_URL"
check_env_var "HA_TOKEN"      && pass "HA_TOKEN is set (${#HA_TOKEN} chars)"
check_env_var "MQTT_BROKER"   && pass "MQTT_BROKER = $MQTT_BROKER"
check_env_var "MQTT_PASSWORD" && pass "MQTT_PASSWORD is set"

if [ $FAILURES -gt 0 ]; then
    echo -e "${RED}Setup cannot continue — fix environment variables first.${RESET}"
    exit 1
fi

header "STEP 2: Checking Python dependencies"

PYTHON_CMD=""
for cmd in python3 python3.11 python3.10 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_VERSION=$("$cmd" --version 2>&1 | awk '{print $2}')
        PYTHON_CMD="$cmd"
        pass "Python found: $cmd ($PYTHON_VERSION)"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    fail "Python 3 not found. Install with: brew install python3"
    exit 1
fi

PYTHON_MINOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.major)")
if [ "$PYTHON_MAJOR" -lt 3 ] || [ "$PYTHON_MINOR" -lt 9 ]; then
    fail "Python 3.9+ required (found $PYTHON_MAJOR.$PYTHON_MINOR)"
    exit 1
fi

PACKAGES="aiohttp asyncio-mqtt paho-mqtt python-dotenv"
if $PYTHON_CMD -m pip install --quiet --upgrade $PACKAGES 2>&1; then
    pass "Python packages installed: $PACKAGES"
else
    warn "pip install had warnings"
fi

for pkg in aiohttp asyncio_mqtt dotenv; do
    if $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
        pass "Import OK: $pkg"
    else
        fail "Cannot import: $pkg — run: pip install $pkg"
    fi
done

header "STEP 3: Network reachability (Raspberry Pi)"

PI_IP=$(echo "$HA_URL" | sed 's|http[s]*://||' | cut -d: -f1)
HA_PORT=$(echo "$HA_URL" | sed 's|http[s]*://[^:]*||' | tr -d '/:' | cut -d/ -f1)
HA_PORT="${HA_PORT:-8123}"
MQTT_PORT_NUM="${MQTT_PORT:-1883}"

if ping -c 2 -W 2 "$PI_IP" &>/dev/null; then
    pass "Pi is reachable: $PI_IP"
else
    warn "Cannot ping Pi at $PI_IP — ping may be firewalled. Trying TCP..."
fi

if timeout 5 bash -c "echo >/dev/tcp/$PI_IP/$HA_PORT" 2>/dev/null; then
    pass "HA port $HA_PORT is open"
else
    fail "Cannot reach HA at $PI_IP:$HA_PORT — is Home Assistant running?"
fi

if timeout 5 bash -c "echo >/dev/tcp/$MQTT_BROKER/$MQTT_PORT_NUM" 2>/dev/null; then
    pass "MQTT port $MQTT_PORT_NUM is open"
else
    fail "Cannot reach MQTT broker at $MQTT_BROKER:$MQTT_PORT_NUM"
fi

header "STEP 4: Testing Home Assistant API connection"

HA_API_RESPONSE=$(curl -sf \
    -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    "$HA_URL/api/" 2>/dev/null || echo "ERROR")

if [ "$HA_API_RESPONSE" = "ERROR" ]; then
    fail "HA API unreachable at $HA_URL/api/ — check HA_URL and HA_TOKEN"
else
    HA_VERSION=$(echo "$HA_API_RESPONSE" | \
        $PYTHON_CMD -c "import sys,json; d=json.load(sys.stdin); print(d.get('version','unknown'))" 2>/dev/null || echo "unknown")
    pass "HA API connected (version: $HA_VERSION)"
fi

ENTITY_COUNT=$(curl -sf \
    -H "Authorization: Bearer $HA_TOKEN" \
    "$HA_URL/api/states" 2>/dev/null | \
    $PYTHON_CMD -c "import sys,json; data=json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")

[ "${ENTITY_COUNT:-0}" -gt 0 ] 2>/dev/null && pass "HA entities accessible: $ENTITY_COUNT total" || warn "Could not count entities"

header "STEP 5: Testing MQTT broker connection"

MQTT_TEST_SCRIPT=$(cat << 'PYEOF'
import os, sys, socket, struct
host = os.environ.get('MQTT_BROKER', 'localhost')
port = int(os.environ.get('MQTT_PORT', '1883'))
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect((host, port))
    client_id = b"symphony-setup-test"
    payload = struct.pack('>H', len(client_id)) + client_id
    var_header = b'\x00\x04MQTT\x04\x02\x00\x3C'
    remain = len(var_header) + 2 + len(payload)
    fixed = bytes([0x10, remain])
    s.send(fixed + var_header + payload)
    resp = s.recv(4)
    s.close()
    if len(resp) >= 4 and resp[3] == 0:
        print("CONNECTED")
    elif len(resp) >= 4 and resp[3] == 5:
        print("AUTH_REQUIRED")
    else:
        rc = resp[3] if len(resp) > 3 else -1
        print(f"REJECTED:{rc}")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

MQTT_RESULT=$($PYTHON_CMD -c "$MQTT_TEST_SCRIPT" 2>/dev/null || echo "ERROR:exception")
case "$MQTT_RESULT" in
    CONNECTED)      pass "MQTT broker is up and accepting connections" ;;
    AUTH_REQUIRED)  pass "MQTT broker is up (authentication required)" ;;
    ERROR:*)        fail "MQTT connection error: ${MQTT_RESULT#ERROR:}" ;;
    REJECTED:*)     warn "MQTT broker rejected connection (code ${MQTT_RESULT#REJECTED:})" ;;
    *)              warn "MQTT result: $MQTT_RESULT" ;;
esac

header "STEP 6: Creating directory structure"

SNAPSHOT_DIR="${CAMERA_SNAPSHOT_DIR:-./snapshots}"
mkdir -p "$SNAPSHOT_DIR" && pass "Snapshot directory: $SNAPSHOT_DIR"
mkdir -p ./logs          && pass "Log directory: ./logs"
mkdir -p ./cache         && pass "Cache directory: ./cache"

header "STEP 7: Building initial device registry"

REGISTRY_SCRIPT=$(cat << 'PYEOF'
import asyncio, json, os, sys, time
from collections import defaultdict
try:
    import aiohttp
    from dotenv import load_dotenv
    load_dotenv()
except ImportError as e:
    print(f"SKIP:{e}", file=sys.stderr)
    sys.exit(0)
HA_URL = os.environ.get("HA_URL", "")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
async def build_registry():
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(f"{HA_URL}/api/states") as resp:
            resp.raise_for_status()
            states = await resp.json()
    by_domain = defaultdict(int)
    cameras, luma_cams = [], []
    vendors = defaultdict(int)
    vendor_keywords = {"lutron": "lutron", "control4": "control4", "sonos": "sonos", "luma": "luma", "araknis": "araknis"}
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        by_domain[domain] += 1
        if domain == "camera":
            cameras.append(eid)
            if "luma" in eid.lower():
                luma_cams.append(eid)
        for vendor, kw in vendor_keywords.items():
            if kw in eid.lower():
                vendors[vendor] += 1
    os.makedirs("./cache", exist_ok=True)
    cache = {"last_refresh": time.time(), "entity_count": len(states),
             "domains": dict(sorted(by_domain.items(), key=lambda x: -x[1])),
             "cameras": cameras, "luma_cameras": luma_cams, "vendor_counts": dict(vendors)}
    with open("./cache/initial_registry.json", "w") as f:
        json.dump(cache, f, indent=2)
    print(f"Entities: {len(states)}")
    if cameras:
        print(f"Cameras: {', '.join(cameras)}")
    return True
asyncio.run(build_registry())
PYEOF
)

REGISTRY_OUTPUT=$($PYTHON_CMD -c "$REGISTRY_SCRIPT" 2>/dev/null || echo "")
if [ -n "$REGISTRY_OUTPUT" ]; then
    while IFS= read -r line; do pass "$line"; done <<< "$REGISTRY_OUTPUT"
    pass "Registry saved to ./cache/initial_registry.json"
else
    warn "Could not build initial registry — will complete on first run"
fi

header "STEP 8: OpenClaw tool registration"

if [ -f "openclaw_ha_tool.json" ]; then
    TOOL_ACTIONS=$($PYTHON_CMD -c \
        "import json; d=json.load(open('openclaw_ha_tool.json')); print(', '.join(d['actions'].keys()))" \
        2>/dev/null || echo "unknown")
    pass "Tool definition found: openclaw_ha_tool.json"
    info "Available actions: $TOOL_ACTIONS"
else
    fail "openclaw_ha_tool.json not found"
fi

OPENCLAW_TOOLS_DIR="${OPENCLAW_TOOLS_DIR:-../tools}"
if [ -d "$OPENCLAW_TOOLS_DIR" ]; then
    cp openclaw_ha_tool.json "$OPENCLAW_TOOLS_DIR/home_assistant.json"
    pass "Tool auto-registered in: $OPENCLAW_TOOLS_DIR/home_assistant.json"
else
    info "Manually copy: cp openclaw_ha_tool.json <openclaw>/tools/home_assistant.json"
fi

header "STEP 9: Testing WebSocket event stream"

WS_TEST_SCRIPT=$(cat << 'PYEOF'
import asyncio, json, os, sys
try:
    import aiohttp
    from dotenv import load_dotenv
    load_dotenv()
except ImportError as e:
    print(f"SKIP:{e}")
    sys.exit(0)
async def test():
    ws_url = os.environ.get("HA_WEBSOCKET_URL", "")
    if not ws_url:
        ha_url = os.environ.get("HA_URL", "http://localhost:8123")
        ws_url = ha_url.replace("http://","ws://").replace("https://","wss://") + "/api/websocket"
    token = os.environ.get("HA_TOKEN", "")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(ws_url, timeout=aiohttp.ClientWSTimeout(ws_receive=5)) as ws:
                msg = await ws.receive_json()
                if msg.get("type") != "auth_required":
                    print(f"UNEXPECTED:{msg.get('type')}")
                    return
                await ws.send_json({"type": "auth", "access_token": token})
                msg = await ws.receive_json()
                if msg.get("type") == "auth_ok":
                    print(f"OK:{msg.get('ha_version','?')}")
                else:
                    print(f"AUTH_FAILED:{msg.get('message','?')}")
    except asyncio.TimeoutError:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERROR:{e}")
asyncio.run(test())
PYEOF
)

WS_RESULT=$($PYTHON_CMD -c "$WS_TEST_SCRIPT" 2>/dev/null || echo "ERROR:exception")
case "$WS_RESULT" in
    OK:*)           pass "WebSocket connected (HA ${WS_RESULT#OK:})" ;;
    SKIP:*)         warn "WebSocket test skipped: ${WS_RESULT#SKIP:}" ;;
    TIMEOUT)        fail "WebSocket connection timed out" ;;
    AUTH_FAILED:*)  fail "WebSocket auth failed: ${WS_RESULT#AUTH_FAILED:}" ;;
    *)              fail "WebSocket error: $WS_RESULT" ;;
esac

header "STEP 10: Camera snapshot test"

CAMERA_TEST_ENTITY=""
if [ -f "./cache/initial_registry.json" ]; then
    CAMERA_TEST_ENTITY=$($PYTHON_CMD -c \
        "import json; d=json.load(open('./cache/initial_registry.json')); \
         cams = d.get('luma_cameras', d.get('cameras', [])); \
         print(cams[0] if cams else '')" 2>/dev/null || echo "")
fi

if [ -n "$CAMERA_TEST_ENTITY" ]; then
    SNAP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $HA_TOKEN" \
        "$HA_URL/api/camera_proxy/$CAMERA_TEST_ENTITY" 2>/dev/null || echo "000")
    [ "$SNAP_CODE" = "200" ] && pass "Camera snapshot accessible: $CAMERA_TEST_ENTITY" || warn "Camera snapshot returned HTTP $SNAP_CODE"
else
    info "No cameras found in registry — skipping camera snapshot test"
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
if [ $FAILURES -eq 0 ]; then
    echo -e "${BOLD}║   ${GREEN}✓ Setup Complete${RESET}${BOLD} — All checks passed! (${DURATION}s)       ║${RESET}"
else
    echo -e "${BOLD}║   ${YELLOW}⚠ Setup Complete with $FAILURES failure(s) (${DURATION}s)${RESET}${BOLD}           ║${RESET}"
fi
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"

echo ""
if [ $FAILURES -eq 0 ]; then
    echo -e "${GREEN}Bob the Conductor is ready to connect to Home Assistant!${RESET}"
fi

echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo "  1. Copy openclaw_ha_tool.json to your OpenClaw tools directory:"
echo "     cp openclaw_ha_tool.json ../tools/home_assistant.json"
echo "  2. Start the Docker stack:"
echo "     docker compose -f docker-compose.ha.yml up -d"
echo "  3. Documentation:  ./README.md"
echo ""

exit $FAILURES
