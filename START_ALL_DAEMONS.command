#!/usr/bin/env bash
# START_ALL_DAEMONS.command — Launch all trading system daemons
# Double-click to start: Telegram bot, Market watcher, Alert system

set -euo pipefail

cd "$(dirname "$0")"
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

echo "🚀 Starting Trading System Daemons"
echo "=================================="

# Ensure both APIs are available before daemon startup.
ensure_launch_agent "com.symphony.mobile-api"
ensure_launch_agent "com.symphony.trading-api"

# Kill any existing instances
echo "🧹 Cleaning up old processes..."
pkill -f "telegram-bob-remote/main.py" 2>/dev/null || true
pkill -f "market_watcher.py.*--daemon" 2>/dev/null || true
pkill -f "alert_system.py.*--daemon" 2>/dev/null || true
pkill -f "market_briefing.py.*--daemon" 2>/dev/null || true
sleep 2

# Start Telegram bot
echo "📱 Starting Telegram bot..."
nohup python3 telegram-bob-remote/main.py > /tmp/telegram_bot.log 2>&1 &
TELEGRAM_PID=$!
echo "   PID: $TELEGRAM_PID"

# Start Market Watcher (5 min interval)
echo "👁️  Starting Market Watcher..."
nohup python3 trading/market_watcher.py --daemon --interval 5 > /tmp/market_watcher.log 2>&1 &
WATCHER_PID=$!
echo "   PID: $WATCHER_PID"

# Start Alert System (5 min interval)
echo "🔔 Starting Alert System..."
nohup python3 trading/alert_system.py --daemon --interval 5 > /tmp/alert_system.log 2>&1 &
ALERT_PID=$!
echo "   PID: $ALERT_PID"

# Start Market Briefing daemon (6 AM, 8 PM)
echo "📰 Starting Briefing Daemon..."
nohup python3 trading/market_briefing.py --daemon > /tmp/briefing_daemon.log 2>&1 &
BRIEFING_PID=$!
echo "   PID: $BRIEFING_PID"

echo ""
echo "=================================="
echo "✅ All daemons started!"
echo ""
echo "📱 Telegram: /tmp/telegram_bot.log"
echo "👁️  Watcher: /tmp/market_watcher.log"
echo "🔔 Alerts: /tmp/alert_system.log"
echo "📰 Briefing: /tmp/briefing_daemon.log"
echo ""
echo "API Status:"
api_status "http://127.0.0.1:8420/health" "Work API"
api_status "http://127.0.0.1:8421/health" "Trading API"
echo ""
echo "To stop all: pkill -f 'trading/|telegram-bob-remote'"
echo "=================================="

# Keep terminal open for a moment
sleep 3
