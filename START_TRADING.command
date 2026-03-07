#!/bin/bash
# START_TRADING.command — Launch trading dashboard
# Double-click to run on macOS

set -euo pipefail

cd "$(dirname "$0")" || exit 1
source .env 2>/dev/null || true

ensure_launch_agent() {
  local label="$1"
  local plist="$HOME/Library/LaunchAgents/${label}.plist"
  if launchctl list | awk '{print $3}' | grep -qx "$label"; then
    return
  fi
  if [ -f "$plist" ]; then
    launchctl load "$plist" 2>/dev/null || true
  fi
}

api_status() {
  local url="$1"
  local name="$2"
  if curl -fsS "$url" >/dev/null 2>&1; then
    echo "   ✅ $name up ($url)"
  else
    echo "   ❌ $name down ($url)"
  fi
}

echo "=========================================="
echo "📊 TRADING SYSTEM DASHBOARD"
echo "=========================================="
echo ""

# Ensure APIs are available for dashboards/commands.
ensure_launch_agent "com.symphony.mobile-api"
ensure_launch_agent "com.symphony.trading-api"

python3 trading/trading_dashboard.py --overview 2>/dev/null

echo ""
echo "=========================================="
echo "🎯 TOP RECOMMENDATIONS"
echo "=========================================="
echo ""

python3 trading/strategy_engine.py --recommend 2>/dev/null | head -35

echo ""
echo "=========================================="
echo ""
echo "Quick commands:"
echo "  python3 trading/strategy_engine.py --recommend  # Trade recs"
echo "  python3 trading/risk_manager.py --check         # Risk check"
echo "  python3 trading/backtest.py --compare           # Backtest"
echo ""
echo "Telegram: /dash /opps /recommend /risk /backtest"
echo ""
echo "Start all daemons: ./START_ALL_DAEMONS.command"
echo ""
echo "API Status:"
api_status "http://127.0.0.1:8420/health" "Work API"
api_status "http://127.0.0.1:8421/health" "Trading API"
echo "=========================================="
