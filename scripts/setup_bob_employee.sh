#!/bin/bash
# Bob Employee Upgrade — Install smux, Hermes Agent, OpenClaw Memory
# Run on Bob's Mac Mini: bash ~/AI-Server/scripts/setup_bob_employee.sh

set -e
echo "🤖 Bob Employee Upgrade Starting..."
echo ""

# ═══════════════════════════════════════════════════════
# 1. smux — Agent-to-Agent Terminal Communication
# ═══════════════════════════════════════════════════════
echo "📺 Installing smux (tmux + agent communication)..."
if command -v tmux-bridge &>/dev/null; then
    echo "  smux already installed. Updating..."
    smux update 2>/dev/null || true
else
    curl -fsSL https://shawnpana.com/smux/install.sh | bash
fi
echo "  ✓ smux ready"
echo ""

# ═══════════════════════════════════════════════════════
# 2. Hermes Agent — Multi-Platform AI Agent
# ═══════════════════════════════════════════════════════
echo "🧠 Installing Hermes Agent (multi-platform AI)..."
if command -v hermes &>/dev/null; then
    echo "  Hermes already installed. Updating..."
    hermes update 2>/dev/null || true
else
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
    # Reload shell
    source ~/.zshrc 2>/dev/null || source ~/.bashrc 2>/dev/null || true
fi
echo "  ✓ Hermes installed"
echo ""

# Configure Hermes with OpenAI if API key exists
if [ -n "$OPENAI_API_KEY" ]; then
    echo "  Configuring Hermes with OpenAI..."
    # Create config directory
    mkdir -p ~/.hermes
    cat > ~/.hermes/config.yaml << EOF
provider: openai
model: gpt-4o-mini
api_key_env: OPENAI_API_KEY

# MCP servers for tool access
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN:-}"
EOF
    echo "  ✓ Hermes configured with OpenAI"
else
    echo "  ⚠ OPENAI_API_KEY not set — run 'hermes model' to configure manually"
fi
echo ""

# ═══════════════════════════════════════════════════════
# 3. OpenClaw Memory Plugin
# ═══════════════════════════════════════════════════════
echo "🧩 Installing OpenClaw Memory Plugin..."
if command -v openclaw &>/dev/null; then
    # Check if plugin already installed
    if openclaw plugins list 2>/dev/null | grep -q "byterover"; then
        echo "  Memory plugin already installed."
    else
        echo "  Installing ByteRover memory plugin..."
        openclaw plugins install @byterover/byterover 2>/dev/null || \
            curl -fsSL https://byterover.dev/openclaw-setup.sh | sh 2>/dev/null || \
            echo "  ⚠ Could not install — run manually: openclaw plugins install @byterover/byterover"
    fi
else
    echo "  ⚠ OpenClaw not found — install it first, then run:"
    echo "    openclaw plugins install @byterover/byterover"
fi
echo ""

# ═══════════════════════════════════════════════════════
# 4. Setup smux workspace for Bob's agents
# ═══════════════════════════════════════════════════════
echo "📋 Creating Bob's agent workspace script..."
cat > ~/AI-Server/scripts/start_bob_workspace.sh << 'WORKSPACE'
#!/bin/bash
# Start Bob's multi-agent workspace in smux/tmux
# Run: bash ~/AI-Server/scripts/start_bob_workspace.sh

# Kill existing session if any
tmux kill-session -t bob 2>/dev/null || true

# Create new session with 4 panes
tmux new-session -d -s bob -n agents

# Pane 0: iMessage Bridge
tmux send-keys -t bob:agents.0 "PYTHONUNBUFFERED=1 /opt/homebrew/bin/python3 ~/AI-Server/scripts/imessage-server.py" Enter
tmux-bridge name bob:agents.0 "imessage" 2>/dev/null || true

# Pane 1: Trading Bot Logs
tmux split-window -h -t bob:agents
tmux send-keys -t bob:agents.1 "docker logs polymarket-bot -f 2>&1 | grep --line-buffered 'executed\|exit\|cleanup\|bankroll\|New Trade\|Halted'" Enter
tmux-bridge name bob:agents.1 "trader" 2>/dev/null || true

# Pane 2: Bot Status Monitor
tmux split-window -v -t bob:agents.1
tmux send-keys -t bob:agents.2 "watch -n 60 'curl -s http://localhost:8430/status | python3 -c \"import sys,json; d=json.load(sys.stdin)[\\\"strategies\\\"][\\\"copytrade\\\"]; print(f\\\"Positions: {d[\\\\\\\"open_positions\\\\\\\"]} | Trades: {d[\\\\\\\"daily_trades\\\\\\\"]} | Bank: \\\\\\\${d[\\\\\\\"bankroll\\\\\\\"]:.0f}\\\")\"'" Enter
tmux-bridge name bob:agents.2 "status" 2>/dev/null || true

# Pane 3: Research Agent (Hermes or manual)
tmux split-window -v -t bob:agents.0
if command -v hermes &>/dev/null; then
    tmux send-keys -t bob:agents.3 "hermes --continue 2>/dev/null || hermes" Enter
    tmux-bridge name bob:agents.3 "researcher" 2>/dev/null || true
else
    tmux send-keys -t bob:agents.3 "echo 'Hermes not installed. This pane is available for manual research.'" Enter
    tmux-bridge name bob:agents.3 "research" 2>/dev/null || true
fi

# Attach to session
tmux select-layout -t bob:agents tiled
echo "Bob's workspace started! Attach with: tmux attach -t bob"
WORKSPACE
chmod +x ~/AI-Server/scripts/start_bob_workspace.sh
echo "  ✓ Workspace script created at scripts/start_bob_workspace.sh"
echo ""

# ═══════════════════════════════════════════════════════
echo "═══════════════════════════════════════════"
echo "✅ Bob Employee Upgrade Complete!"
echo ""
echo "To start Bob's workspace:"
echo "  bash ~/AI-Server/scripts/start_bob_workspace.sh"
echo "  tmux attach -t bob"
echo ""
echo "To configure Hermes:"
echo "  hermes model    # Choose LLM provider"
echo "  hermes gateway  # Connect Telegram/Discord/etc"
echo ""
echo "Agents can communicate via:"
echo "  tmux-bridge read researcher 20   # Read researcher pane"
echo "  tmux-bridge type trader 'status' # Send to trader pane"
echo "═══════════════════════════════════════════"
