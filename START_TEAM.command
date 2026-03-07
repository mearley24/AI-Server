#!/bin/bash
#
# START_TEAM.command — Launch Symphony AI Team
#
# Double-click to start:
# - Betty (research worker)
# - Periodic Telegram updates
# - Notes watcher (background)
#

set -euo pipefail

cd "$(dirname "$0")"

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
        echo "  ✅ $name up ($url)"
    else
        echo "  ❌ $name down ($url)"
    fi
}

echo "🚀 Starting Symphony AI Team..."
echo ""

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Create log directory
mkdir -p orchestrator/logs

# Ensure both API processes are available for team tools.
ensure_launch_agent "com.symphony.mobile-api"
ensure_launch_agent "com.symphony.trading-api"

# Start Betty worker in background
echo "👤 Starting Betty (research specialist)..."
python3 orchestrator/autonomous_worker.py --worker betty --interval 60 >> orchestrator/logs/betty_worker.log 2>&1 &
BETTY_PID=$!
echo "   PID: $BETTY_PID"

# Start periodic updater in background
echo "📊 Starting periodic updater (every 2h)..."
python3 orchestrator/periodic_updater.py --daemon --interval 2 >> orchestrator/logs/periodic_updater.log 2>&1 &
UPDATER_PID=$!
echo "   PID: $UPDATER_PID"

# Run initial notes check
echo "📝 Checking for new notes..."
python3 tools/notes_watcher.py --check 2>&1 | head -20

echo ""
echo "✅ Team is running!"
echo ""
echo "Logs:"
echo "  - orchestrator/logs/betty_worker.log"
echo "  - orchestrator/logs/periodic_updater.log"
echo ""
echo "To stop: kill $BETTY_PID $UPDATER_PID"
echo "Or: pkill -f autonomous_worker && pkill -f periodic_updater"
echo ""
echo "API Status:"
api_status "http://127.0.0.1:8420/health" "Work API"
api_status "http://127.0.0.1:8421/health" "Trading API"
echo ""
echo "Press Ctrl+C or close window to stop watching (team keeps running)."
echo ""

# Tail logs
tail -f orchestrator/logs/betty_worker.log orchestrator/logs/periodic_updater.log 2>/dev/null
