#!/usr/bin/env bash
# =============================================================================
# install_openclaw.sh
# OpenClaw installation script for Bob the Conductor — Mac Mini M4 (hostname: Bob)
# Symphony Smart Homes AI Orchestrator
#
# Run as the regular user (not sudo). Homebrew and npm will handle privilege
# escalation where needed.
#
# Usage:
#   chmod +x install_openclaw.sh
#   ./install_openclaw.sh
# =============================================================================

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}\n"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
header "Pre-flight checks"

# Must NOT run as root
if [[ "$EUID" -eq 0 ]]; then
  error "Do not run this script as root. Run as your normal user account."
  exit 1
fi

# Confirm we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
  error "This script is designed for macOS (Mac Mini M4). Detected: $(uname)"
  exit 1
fi

# Confirm Apple Silicon
ARCH=$(uname -m)
if [[ "$ARCH" != "arm64" ]]; then
  warn "Expected arm64 (Apple Silicon) but detected: $ARCH. Continuing anyway."
else
  success "Apple Silicon (arm64) confirmed."
fi

success "Running as user: $(whoami)"
success "Hostname: $(hostname)"

# ── Step 1: Homebrew ──────────────────────────────────────────────────────────
header "Step 1: Homebrew"

if command -v brew &>/dev/null; then
  success "Homebrew is already installed: $(brew --version | head -1)"
else
  info "Homebrew not found. Installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Add Homebrew to PATH for Apple Silicon (if not already there)
  if [[ -f "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    # Persist into shell profile
    SHELL_PROFILE="$HOME/.zprofile"
    if ! grep -q 'homebrew' "$SHELL_PROFILE" 2>/dev/null; then
      echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$SHELL_PROFILE"
      info "Added Homebrew to $SHELL_PROFILE"
    fi
  fi
  success "Homebrew installed."
fi

# ── Step 2: Node.js ───────────────────────────────────────────────────────────
header "Step 2: Node.js"

if command -v node &>/dev/null; then
  NODE_VERSION=$(node --version)
  success "Node.js is already installed: $NODE_VERSION"

  # Warn if too old (OpenClaw requires Node 18+)
  NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
  if [[ "$NODE_MAJOR" -lt 18 ]]; then
    warn "Node.js $NODE_VERSION may be too old. OpenClaw requires Node 18+."
    info "Upgrading Node.js via Homebrew..."
    brew upgrade node || brew install node
    success "Node.js upgraded: $(node --version)"
  fi
else
  info "Node.js not found. Installing via Homebrew..."
  brew install node
  success "Node.js installed: $(node --version)"
fi

# Confirm npm is available
if command -v npm &>/dev/null; then
  success "npm: $(npm --version)"
else
  error "npm not found after Node.js install. Check your PATH."
  exit 1
fi

# ── Step 3: Install OpenClaw ──────────────────────────────────────────────────
header "Step 3: Install OpenClaw (global)"

info "Installing openclaw@latest globally via npm..."
npm install -g openclaw@latest

if command -v openclaw &>/dev/null; then
  success "OpenClaw installed: $(openclaw --version 2>/dev/null || echo 'version unavailable')"
else
  error "openclaw command not found after install. Check npm global bin path."
  NPM_BIN=$(npm root -g)/../bin
  info "npm global bin should be at: $NPM_BIN"
  info "Try adding it to your PATH: export PATH=\"\$PATH:$NPM_BIN\""
  exit 1
fi

# ── Step 4: Create workspace directories ─────────────────────────────────────
header "Step 4: Workspace directories"

OPENCLAW_DIR="$HOME/.openclaw"
declare -a WORKSPACES=(
  "$OPENCLAW_DIR/workspace-bob"
  "$OPENCLAW_DIR/workspace-proposals"
  "$OPENCLAW_DIR/workspace-dtools"
)

for WS in "${WORKSPACES[@]}"; do
  if [[ -d "$WS" ]]; then
    success "Already exists: $WS"
  else
    mkdir -p "$WS"
    success "Created: $WS"
  fi
done

# ── Step 5: Copy config and personality files ─────────────────────────────────
header "Step 5: Deploy configuration files"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# openclaw.json → ~/.openclaw/openclaw.json
if [[ -f "$SCRIPT_DIR/openclaw.json" ]]; then
  cp "$SCRIPT_DIR/openclaw.json" "$OPENCLAW_DIR/openclaw.json"
  success "Deployed: openclaw.json → $OPENCLAW_DIR/openclaw.json"
else
  warn "openclaw.json not found in $SCRIPT_DIR — skipping. Copy it manually."
fi

# SOUL.md → ~/.openclaw/workspace-bob/SOUL.md
if [[ -f "$SCRIPT_DIR/SOUL.md" ]]; then
  cp "$SCRIPT_DIR/SOUL.md" "$OPENCLAW_DIR/workspace-bob/SOUL.md"
  success "Deployed: SOUL.md → $OPENCLAW_DIR/workspace-bob/SOUL.md"
else
  warn "SOUL.md not found in $SCRIPT_DIR — skipping."
fi

# AGENTS.md → ~/.openclaw/workspace-bob/AGENTS.md
if [[ -f "$SCRIPT_DIR/AGENTS.md" ]]; then
  cp "$SCRIPT_DIR/AGENTS.md" "$OPENCLAW_DIR/workspace-bob/AGENTS.md"
  success "Deployed: AGENTS.md → $OPENCLAW_DIR/workspace-bob/AGENTS.md"
else
  warn "AGENTS.md not found in $SCRIPT_DIR — skipping."
fi

# ── Step 6: Edit API keys ─────────────────────────────────────────────────────
header "Step 6: API key reminder"

CONFIG_FILE="$OPENCLAW_DIR/openclaw.json"
if [[ -f "$CONFIG_FILE" ]]; then
  warn "Before running the daemon, open $CONFIG_FILE and replace:"
  warn "  YOUR_ANTHROPIC_API_KEY  → your real Anthropic key"
  warn "  YOUR_TELEGRAM_BOT_TOKEN → your Telegram bot token"
  warn "  YOUR_OPENAI_API_KEY     → your OpenAI key (optional)"
  warn "  YOUR_TELEGRAM_USER_ID   → your numeric Telegram user ID"
fi

# ── Step 7: Onboard wizard + daemon ──────────────────────────────────────────
header "Step 7: OpenClaw onboard wizard"

echo ""
echo "  This will launch the interactive OpenClaw onboard wizard."
echo "  It will validate your config and install the macOS LaunchAgent daemon."
echo ""
read -rp "  Ready to run 'openclaw onboard --install-daemon'? [Y/n] " CONFIRM
CONFIRM="${CONFIRM:-Y}"

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
  openclaw onboard --install-daemon
  success "Onboard wizard complete."
else
  warn "Skipped onboard wizard. Run it manually when ready:"
  warn "  openclaw onboard --install-daemon"
fi

# ── Next steps ────────────────────────────────────────────────────────────────
header "Installation complete — Next steps"

cat <<EOF
${BOLD}1. Edit your API keys${NC}
   nano ~/.openclaw/openclaw.json
   Replace all YOUR_*_KEY placeholders with real values.

${BOLD}2. Set up your Telegram bot${NC}
   See: setup_telegram_bot.md
   Add your bot token and Telegram user ID to openclaw.json.

${BOLD}3. Start OpenClaw (if daemon not yet running)${NC}
   openclaw start
   # — or — use the LaunchAgent installed above:
   launchctl load ~/Library/LaunchAgents/com.openclaw.plist

${BOLD}4. Check status${NC}
   openclaw status

${BOLD}5. Test via Telegram${NC}
   DM your new bot: "Hello, Bob — are you there?"

${BOLD}6. Monitor logs${NC}
   openclaw logs --tail
   # — or —
   tail -f ~/.openclaw/logs/bob.log

${BOLD}7. Review the migration plan${NC}
   See: migration_plan.md

${BOLD}Note:${NC} Your existing Docker stack (Open WebUI, remediator) is untouched.
OpenClaw runs alongside it. Open WebUI remains available at its usual port.
EOF

echo ""
success "Done. Bob the Conductor is ready to be configured."
