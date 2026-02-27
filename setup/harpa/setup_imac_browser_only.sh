#!/bin/bash
# =============================================================================
# setup_imac_browser_only.sh
# Symphony Smart Homes — 8GB iMac Minimal Setup (HARPA browser node only)
#
# This script sets up the 8GB Intel iMac as a secondary HARPA browser automation
# node. This machine does NOT run Ollama (not enough RAM).
#
# What this script does:
#   1. Creates necessary directories
#   2. Clones the AI-Server repo (if not present)
#   3. Prints setup instructions for Chrome + HARPA
#   4. Creates a simple health check script
#
# Run as regular user:
#   chmod +x setup_imac_browser_only.sh
#   ./setup_imac_browser_only.sh
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
header()  { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}\n"; }

# ── Pre-flight
header "Pre-flight: 8GB iMac (browser-only node)"
[[ "$(uname)" != "Darwin" ]] && { echo "macOS only"; exit 1; }

RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
info "RAM detected: ${RAM_GB}GB"
if [[ "$RAM_GB" -ge 32 ]]; then
  warn "This machine has ${RAM_GB}GB RAM — consider using setup_imac_harpa.sh instead (includes Ollama)"
fi

success "User: $(whoami) | Hostname: $(hostname)"

# ── Create directories
header "Directories"
mkdir -p ~/AI-Server ~/Library/Logs
success "Directories created."

# ── Clone repo (if not present)
header "AI-Server repository"
if [[ -d ~/AI-Server/.git ]]; then
  success "AI-Server repo already present."
else
  info "Cloning AI-Server repo..."
  git clone https://github.com/mearley24/AI-Server.git ~/AI-Server
  success "Cloned to ~/AI-Server"
fi

# ── Create health check script
header "Health check script"

cat > ~/check_harpa_node.sh << 'HEALTHCHECK'
#!/bin/bash
# Quick health check for 8GB iMac HARPA node
echo "=== 8GB iMac HARPA Node Health Check ==="
echo "Hostname: $(hostname)"
echo "IP (Ethernet): $(ipconfig getifaddr en1 2>/dev/null || echo 'not connected')"
echo "IP (Wi-Fi): $(ipconfig getifaddr en0 2>/dev/null || echo 'not connected')"
echo ""
echo "Chrome running: $(pgrep -x 'Google Chrome' > /dev/null && echo YES || echo NO)"
echo "HARPA Grid port: $(lsof -i :8765 > /dev/null 2>&1 && echo OPEN || echo CLOSED)"
HEALTHCHECK

chmod +x ~/check_harpa_node.sh
success "Health check script: ~/check_harpa_node.sh"

# ── Summary
header "Setup complete — Manual steps required"

cat <<EOF
This machine is configured as a HARPA browser-only node.

${BOLD}Next steps (manual):${NC}

1. Install Google Chrome (if not already installed)
   https://www.google.com/chrome/

2. Create a 'Symphony Automation' Chrome profile
3. Install HARPA AI extension from the Chrome Web Store
4. Enable HARPA Grid in HARPA Settings
5. Import D-Tools commands: ~/AI-Server/setup/harpa/harpa_dtools_commands.json
6. Log into D-Tools Cloud: https://portal.d-tools.com
7. Add Chrome to Login Items (System Preferences > Users & Groups)

Detailed instructions: ~/AI-Server/setup/harpa/imac_node_config.md

Your IP address (for Bob's bridge config):
  Ethernet: $(ipconfig getifaddr en1 2>/dev/null || echo '[not connected]')
  Wi-Fi:    $(ipconfig getifaddr en0 2>/dev/null || echo '[not connected]')
EOF

success "Done."
