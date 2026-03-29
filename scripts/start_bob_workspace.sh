#!/bin/bash
# Start Bob's multi-agent workspace in tmux
# Usage: bash ~/AI-Server/scripts/start_bob_workspace.sh

# Ensure HOME is set correctly for launchd context
export HOME=/Users/bob

cd ~/AI-Server || exit 1

# Load environment variables from .env (auto-export all)
set -a
source ~/AI-Server/.env 2>/dev/null
set +a

# Clean up stale processes
tmux kill-session -t bob 2>/dev/null
pkill -f imessage-server 2>/dev/null
sleep 1

# Create new session with 4 panes
tmux new-session -d -s bob -n agents

# Pane 0: iMessage Bridge
tmux send-keys -t bob:agents.0 "lsof -ti :8199 | xargs kill -9 2>/dev/null; sleep 1; PYTHONUNBUFFERED=1 /opt/homebrew/bin/python3 ~/AI-Server/scripts/imessage-server.py" Enter

# Pane 1: Trading Bot Logs
tmux split-window -h -t bob:agents
tmux send-keys -t bob:agents.1 "docker logs polymarket-bot -f 2>&1 | grep --line-buffered 'executed\|Exit\|Cleaned\|New Trade\|Halted\|bankroll_synced\|reentry'" Enter

# Pane 2: Hermes Research Agent with Standing Orders
tmux split-window -v -t bob:agents.1
tmux send-keys -t bob:agents.2 "bash ~/AI-Server/scripts/start_hermes.sh" Enter

# Pane 3: Status Monitor (bash loop instead of watch for macOS compatibility)
tmux split-window -v -t bob:agents.0
tmux send-keys -t bob:agents.3 "while true; do curl -s http://localhost:8430/status 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin)[\\\"strategies\\\"][\\\"copytrade\\\"]; print(f\\\"Pos: {d[\\\\\\\"open_positions\\\\\\\"]} | Trades: {d[\\\\\\\"daily_trades\\\\\\\"]} | Bank: \\\\\\\${d[\\\\\\\"bankroll\\\\\\\"]:.0f}\\\")\" 2>/dev/null || echo \"Bot not running\"; sleep 60; done" Enter

# Tile the layout
tmux select-layout -t bob:agents tiled

echo "Bob's workspace started! Attach with: tmux attach -t bob"
echo "Navigate panes: Option+i/k/j/l"
echo "Panes: iMessage | Trade Logs | Hermes Research | Status"
