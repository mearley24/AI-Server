#!/bin/bash
# Stop all Symphony AI processes

set -euo pipefail

cd "$(dirname "$0")"

api_status() {
    local url="$1"
    local name="$2"
    if curl -fsS "$url" >/dev/null 2>&1; then
        echo "  ✅ $name up ($url)"
    else
        echo "  ❌ $name down ($url)"
    fi
}

echo "🛑 Stopping Symphony AI Team..."

# Kill by PID files
for pid_file in orchestrator/pids/*.pid; do
    if [ -f "$pid_file" ]; then
        name=$(basename "$pid_file" .pid)
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping $name (PID: $pid)"
            kill "$pid" 2>/dev/null
        fi
        rm "$pid_file"
    fi
done

# Also kill by process name (fallback)
pkill -f "bob_brain.py" 2>/dev/null
pkill -f "event_server.py" 2>/dev/null
pkill -f "autonomous_worker.py" 2>/dev/null

echo "✅ All processes stopped."
echo ""
echo "API Status:"
api_status "http://127.0.0.1:8420/health" "Work API"
api_status "http://127.0.0.1:8421/health" "Trading API"
