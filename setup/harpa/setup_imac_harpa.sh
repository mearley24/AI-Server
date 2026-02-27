#!/usr/bin/env bash
# =============================================================================
# setup_imac_harpa.sh
# Symphony Smart Homes — 64GB iMac Full Setup (Ollama + HARPA + bridge)
#
# This script prepares the 64GB Intel iMac for its role as the primary
# automation and inference node in the Bob the Conductor infrastructure.
#
# What this script does:
#   1. Validates hardware (64GB RAM, Intel, macOS)
#   2. Installs Homebrew
#   3. Installs Python 3.11+ (for bob_harpa_bridge.py)
#   4. Clones the AI-Server repo (if not present)
#   5. Installs the Bob HARPA Bridge as a launchd service
#   6. Verifies bridge is running
#   7. Prints Chrome + HARPA manual setup instructions
#
# Ollama setup is handled separately by setup_ollama_worker.sh.
# Run that script first if Ollama is not yet installed.
#
# Run as regular user (not sudo):
#   chmod +x setup_imac_harpa.sh
#   ./setup_imac_harpa.sh
# =============================================================================

set -euo pipefail

# ── Colors
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-flight
header "Pre-flight: 64GB iMac"

[[ "$EUID" -eq 0 ]] && { error "Do not run as root."; exit 1; }
[[ "$(uname)" != "Darwin" ]] && { error "macOS only."; exit 1; }

# Architecture check
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  warn "Apple Silicon detected. This script is optimized for Intel iMac but will continue."
else
  success "Intel x86_64 confirmed."
fi

# RAM check
RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if [[ "$RAM_GB" -lt 32 ]]; then
  warn "Only ${RAM_GB}GB RAM. This script is designed for the 64GB iMac."
  warn "Ollama may have limited capacity. HARPA bridge will still work."
else
  success "RAM: ${RAM_GB}GB"
fi

success "User: $(whoami) | Hostname: $(hostname)"

# ── Step 1: Homebrew
header "Step 1: Homebrew"

if command -v brew &>/dev/null; then
  success "Homebrew: $(brew --version | head -1)"
else
  info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/usr/local/bin/brew shellenv 2>/dev/null || /opt/homebrew/bin/brew shellenv)"
  success "Homebrew installed."
fi

# ── Step 2: Python 3
header "Step 2: Python 3"

if command -v python3 &>/dev/null; then
  PY_VER=$(python3 --version)
  success "Python: $PY_VER"
  PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
  PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
  if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 9 ]]; then
    warn "Python 3.9+ recommended for bridge server. Upgrading..."
    brew install python@3.11
    success "Python 3.11 installed."
  fi
else
  info "Installing Python 3.11 via Homebrew..."
  brew install python@3.11
  success "Python 3.11 installed."
fi

# ── Step 3: AI-Server repo
header "Step 3: AI-Server repository"

if [[ -d ~/AI-Server/.git ]]; then
  success "AI-Server repo already present at ~/AI-Server"
  info "Pulling latest..."
  git -C ~/AI-Server pull --ff-only 2>/dev/null && success "Up to date." || warn "Could not pull (may have local changes)."
else
  info "Cloning AI-Server repo..."
  git clone https://github.com/mearley24/AI-Server.git ~/AI-Server
  success "Cloned to ~/AI-Server"
fi

# ── Step 4: Install Bob HARPA Bridge as launchd service
header "Step 4: Bob HARPA Bridge service"

BRIDGE_SCRIPT="$HOME/AI-Server/setup/harpa/bob_harpa_bridge.py"
if [[ ! -f "$BRIDGE_SCRIPT" ]]; then
  error "bob_harpa_bridge.py not found at $BRIDGE_SCRIPT"
  error "Ensure the AI-Server repo is up to date."
  exit 1
fi

PYTHON_BIN=$(command -v python3)
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCH_AGENTS_DIR/com.symphony.harpa-bridge.plist"
LOG_DIR="$HOME/Library/Logs"

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.symphony.harpa-bridge</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${BRIDGE_SCRIPT}</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>HARPA_GRID_URL</key>
    <string>http://localhost:8765</string>
    <key>HARPA_GRID_API_KEY</key>
    <string>YOUR_HARPA_GRID_API_KEY</string>
    <key>BRIDGE_HOST</key>
    <string>0.0.0.0</string>
    <key>BRIDGE_PORT</key>
    <string>9090</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/harpa_bridge.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/harpa_bridge_error.log</string>

  <key>ThrottleInterval</key>
  <integer>30</integer>

</dict>
</plist>
PLIST

success "Created launchd plist: $PLIST_FILE"
warn "ACTION REQUIRED: Edit $PLIST_FILE and replace YOUR_HARPA_GRID_API_KEY with your actual HARPA Grid API key."
warn "Get the key from: Chrome > HARPA sidebar > Settings > Grid"

# Load the service
if launchctl list | grep -q 'com.symphony.harpa-bridge'; then
  warn "HARPA bridge service already loaded. Reloading..."
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  sleep 1
fi

launchctl load "$PLIST_FILE"
success "HARPA bridge service loaded."

# Wait a moment and test
sleep 3
if curl -s --max-time 3 http://localhost:9090/health | grep -q 'ok'; then
  success "HARPA bridge responding at http://localhost:9090"
else
  warn "Bridge not responding yet (may still be starting, or API key placeholder needs updating)"
fi

# ── Step 5: Get network info
header "Step 5: Network configuration"

ETH_IP=$(ipconfig getifaddr en1 2>/dev/null || echo '')
WIFI_IP=$(ipconfig getifaddr en0 2>/dev/null || echo '')

IMACIP="${ETH_IP:-${WIFI_IP:-[IP_NOT_FOUND]}}"

[[ -n "$ETH_IP" ]] && success "Ethernet IP: $ETH_IP" || true
[[ -n "$WIFI_IP" ]] && success "Wi-Fi IP: $WIFI_IP" || true

# ── Summary
header "Setup complete — Manual steps required"

cat <<EOF
${BOLD}Automated steps complete.${NC}

${BOLD}Manual steps still required:${NC}

1. Update HARPA Grid API key:
   nano $PLIST_FILE
   Replace: YOUR_HARPA_GRID_API_KEY
   Then:    launchctl unload $PLIST_FILE && launchctl load $PLIST_FILE

2. Set up Chrome + HARPA (follow imac_node_config.md):
   - Create 'Symphony Automation' Chrome profile
   - Install HARPA AI extension
   - Enable HARPA Grid in HARPA Settings
   - Import D-Tools commands: ~/AI-Server/setup/harpa/harpa_dtools_commands.json
   - Log into D-Tools Cloud in Chrome

3. On Mac Mini M4 (Bob), update openclaw.json:
   Set: "ollama.base_url": "http://${IMACIP}:11434"
   Set HARPA_GRID_URL in bridge config: http://${IMACIP}:8765

4. Also run Ollama setup (if not done):
   ~/AI-Server/setup/ollama_worker/setup_ollama_worker.sh

Full docs: ~/AI-Server/setup/harpa/imac_node_config.md
EOF

success "64GB iMac HARPA setup complete."
