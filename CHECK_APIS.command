#!/bin/bash
# CHECK_APIS.command — Quick one-click status for Work + Trading APIs

set -euo pipefail

cd "$(dirname "$0")"

check_launchd() {
    local label="$1"
    if launchctl list | awk '{print $3}' | grep -qx "$label"; then
        echo "  ✅ launchd loaded: $label"
    else
        echo "  ❌ launchd missing: $label"
    fi
}

check_http() {
    local url="$1"
    local name="$2"
    if curl -fsS "$url" >/dev/null 2>&1; then
        echo "  ✅ $name HTTP healthy ($url)"
    else
        echo "  ❌ $name HTTP unreachable ($url)"
    fi
}

echo "=========================================="
echo "🔎 Symphony API Status Check"
echo "=========================================="
echo ""
echo "Launch Agents:"
check_launchd "com.symphony.mobile-api"
check_launchd "com.symphony.trading-api"
echo ""
echo "HTTP Health:"
check_http "http://127.0.0.1:8420/health" "Work API"
check_http "http://127.0.0.1:8421/health" "Trading API"
echo ""
echo "=========================================="
