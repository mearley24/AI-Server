#!/usr/bin/env bash
# install_claude_code.sh — Install and configure Claude Code on Mac Mini M4
#
# What this does:
#   1. Verifies Node.js 20+ is installed (required by Claude Code)
#   2. Installs Claude Code globally via npm
#   3. Copies the OpenClaw tool config to the Claude Code config directory
#   4. Prints a verification summary
#
# Usage:
#   bash setup/claude_code/install_claude_code.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")") && pwd)"
OPENCLAW_SRC="$SCRIPT_DIR/openclaw_claude_code_tool.json"
CLAUDE_CONFIG_DIR="$HOME/.claude"
OPENCLAW_DEST="$CLAUDE_CONFIG_DIR/openclaw_claude_code_tool.json"

echo "════════════════════════════════════════════════════════"
echo "  Claude Code Installer — Symphony AI Server"
echo "════════════════════════════════════════════════════════"

# ─── Step 1: Check Node.js ────────────────────────────────────────────────────

echo ""
echo "[1/4] Checking Node.js version..."

if ! command -v node &>/dev/null; then
  echo "[ERROR] Node.js is not installed."
  echo "        Install it via: brew install node"
  exit 1
fi

NODE_VER=$(node -e "process.stdout.write(process.version)")
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1 | tr -d 'v')

if [[ "$NODE_MAJOR" -lt 20 ]]; then
  echo "[ERROR] Node.js $NODE_VER is too old. Claude Code requires Node 20+."
  echo "        Upgrade with: brew upgrade node"
  exit 1
fi

echo "  ✓ Node.js $NODE_VER"

# ─── Step 2: Install Claude Code ─────────────────────────────────────────────

echo ""
echo "[2/4] Installing Claude Code via npm..."
npm install -g @anthropic-ai/claude-code
echo "  ✓ Claude Code installed"

# ─── Step 3: Copy OpenClaw tool config ───────────────────────────────────────

echo ""
echo "[3/4] Configuring OpenClaw tool..."
mkdir -p "$CLAUDE_CONFIG_DIR"
cp "$OPENCLAW_SRC" "$OPENCLAW_DEST"
echo "  ✓ OpenClaw config copied to $OPENCLAW_DEST"

# ─── Step 4: Verify ───────────────────────────────────────────────────────────

echo ""
echo "[4/4] Verifying installation..."

CLAUDE_VER=$(claude --version 2>/dev/null || echo "unknown")
echo "  ✓ Claude Code version: $CLAUDE_VER"
echo "  ✓ Config directory:    $CLAUDE_CONFIG_DIR"
echo "  ✓ OpenClaw tool:       $OPENCLAW_DEST"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Installation complete!"
echo ""
echo "  Start a session:"
echo "    cd /path/to/AI-Server && claude"
echo ""
echo "  CLAUDE.md will be auto-loaded for project context."
echo "════════════════════════════════════════════════════════"
