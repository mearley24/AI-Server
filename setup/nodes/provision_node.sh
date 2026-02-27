#!/usr/bin/env bash
# =============================================================================
# provision_node.sh — Symphony Smart Homes AI Network Node Provisioner
# =============================================================================
# Provisions a macOS machine as a Symphony AI network node.
# Run this on the TARGET machine (the node being provisioned), not on Bob.
#
# Usage:
#   chmod +x provision_node.sh
#   ./provision_node.sh --hostname virtuoso --role full_worker --bob-ip 192.168.1.10
#
# Roles:
#   hq           — Bob only. OpenClaw + Ollama + Docker + registry API
#   llm_worker   — Ollama only. Recommended for Intel with large RAM (e.g. Maestro)
#   browser_node — Chrome + HARPA only. No LLM. For nodes with <16GB RAM.
#   full_worker  — Ollama + Docker + HARPA. Default for new Apple Silicon nodes.
#
# Requirements:
#   - macOS 13+ (Ventura, Sonoma, Sequoia)
#   - Internet access (for Homebrew, Ollama, model downloads)
#   - Run as an admin user (sudo will be invoked as needed)
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

log()   { echo -e "${BLUE}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[✓ OK]${RESET}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
err()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()   { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
HOSTNAME_ARG=""
ROLE="full_worker"
BOB_IP=""
SKIP_MODELS=false
DRY_RUN=false

print_usage() {
    cat <<EOF
Usage: $0 --hostname NAME --role ROLE --bob-ip IP [options]

Required:
  --hostname NAME    Hostname for this node (e.g. virtuoso, crescendo)
  --role ROLE        Node role: hq | llm_worker | browser_node | full_worker
  --bob-ip IP        Bob's LAN IP address (e.g. 192.168.1.10)

Optional:
  --skip-models      Skip pulling Ollama models (useful for re-runs)
  --dry-run          Print what would be done without executing
  --help             Show this help

Examples:
  ./provision_node.sh --hostname virtuoso --role full_worker --bob-ip 192.168.1.10
  ./provision_node.sh --hostname maestro  --role llm_worker  --bob-ip 192.168.1.10
  ./provision_node.sh --hostname stagehand --role browser_node --bob-ip 192.168.1.10
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hostname)  HOSTNAME_ARG="$2"; shift 2 ;;
        --role)      ROLE="$2";         shift 2 ;;
        --bob-ip)    BOB_IP="$2";       shift 2 ;;
        --skip-models) SKIP_MODELS=true; shift ;;
        --dry-run)   DRY_RUN=true;      shift ;;
        --help|-h)   print_usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ -z "$HOSTNAME_ARG" ]] && die "--hostname is required"
[[ -z "$BOB_IP" ]]       && die "--bob-ip is required"
[[ "$ROLE" =~ ^(hq|llm_worker|browser_node|full_worker)$ ]] || \
    die "Invalid role: $ROLE. Must be one of: hq llm_worker browser_node full_worker"

# ---------------------------------------------------------------------------
# Derived flags from role
# ---------------------------------------------------------------------------
INSTALL_OLLAMA=false
INSTALL_DOCKER=false
INSTALL_CHROME=false
INSTALL_HARPA_GUIDE=false
INSTALL_REGISTRY_API=false
INSTALL_OPENCLAW=false

case "$ROLE" in
    hq)
        INSTALL_OLLAMA=true
        INSTALL_DOCKER=true
        INSTALL_CHROME=true
        INSTALL_HARPA_GUIDE=true
        INSTALL_REGISTRY_API=true
        INSTALL_OPENCLAW=true
        ;;
    llm_worker)
        INSTALL_OLLAMA=true
        INSTALL_CHROME=true
        INSTALL_HARPA_GUIDE=true
        ;;
    browser_node)
        INSTALL_CHROME=true
        INSTALL_HARPA_GUIDE=true
        ;;
    full_worker)
        INSTALL_OLLAMA=true
        INSTALL_DOCKER=true
        INSTALL_CHROME=true
        INSTALL_HARPA_GUIDE=true
        ;;
esac

# ---------------------------------------------------------------------------
# Dry-run wrapper
# ---------------------------------------------------------------------------
run() {
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY-RUN] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Step 0: Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Symphony Node Provisioner${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo "  Hostname : $HOSTNAME_ARG"
echo "  Role     : $ROLE"
echo "  Bob IP   : $BOB_IP"
echo "  Ollama   : $INSTALL_OLLAMA"
echo "  Docker   : $INSTALL_DOCKER"
echo "  Chrome   : $INSTALL_CHROME"
echo "  HARPA    : $INSTALL_HARPA_GUIDE"
[[ "$DRY_RUN" == true ]] && echo "  Mode     : DRY RUN (no changes will be made)"
echo ""
read -r -p "Proceed? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
echo ""

# ---------------------------------------------------------------------------
# Step 1: Set hostname
# ---------------------------------------------------------------------------
log "Step 1/11: Setting hostname to '$HOSTNAME_ARG'..."
run sudo scutil --set ComputerName  "$(echo "$HOSTNAME_ARG" | sed 's/./\u&/')"
run sudo scutil --set HostName      "$HOSTNAME_ARG"
run sudo scutil --set LocalHostName "$HOSTNAME_ARG"
run sudo dscacheutil -flushcache
run sudo killall -HUP mDNSResponder 2>/dev/null || true
ok "Hostname set to '$HOSTNAME_ARG'"

# ---------------------------------------------------------------------------
# Step 2: Enable SSH
# ---------------------------------------------------------------------------
log "Step 2/11: Enabling SSH (Remote Login)..."
run sudo systemsetup -setremotelogin on 2>/dev/null || \
    warn "Could not enable SSH via systemsetup. Enable manually: System Settings → Sharing → Remote Login"
ok "SSH enabled"

# ---------------------------------------------------------------------------
# Step 3: Install Homebrew
# ---------------------------------------------------------------------------
log "Step 3/11: Installing Homebrew..."
if command -v brew &>/dev/null; then
    ok "Homebrew already installed: $(brew --version | head -1)"
else
    run /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for the rest of this script
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
fi

# ---------------------------------------------------------------------------
# Step 4: Install software by role
# ---------------------------------------------------------------------------
log "Step 4/11: Installing role-specific software (role: $ROLE)..."

# --- Ollama ---
if [[ "$INSTALL_OLLAMA" == true ]]; then
    if command -v ollama &>/dev/null; then
        ok "Ollama already installed: $(ollama --version 2>&1 | head -1)"
    else
        log "  Installing Ollama..."
        run brew install ollama
        ok "Ollama installed"
    fi
fi

# --- Docker ---
if [[ "$INSTALL_DOCKER" == true ]]; then
    if command -v docker &>/dev/null; then
        ok "Docker already installed"
    else
        log "  Installing Docker Desktop..."
        run brew install --cask docker
        ok "Docker Desktop installed (launch it manually once to complete setup)"
    fi
fi

# --- Google Chrome ---
if [[ "$INSTALL_CHROME" == true ]]; then
    if [[ -d "/Applications/Google Chrome.app" ]]; then
        ok "Chrome already installed"
    else
        log "  Installing Google Chrome..."
        run brew install --cask google-chrome
        ok "Chrome installed"
    fi
fi

# ---------------------------------------------------------------------------
# Step 5: Configure Ollama for remote access
# ---------------------------------------------------------------------------
if [[ "$INSTALL_OLLAMA" == true ]]; then
    log "Step 5/11: Configuring Ollama for remote access (0.0.0.0:11434)..."
    OLLAMA_ENV_DIR="$HOME/.ollama"
    OLLAMA_ENV_FILE="$OLLAMA_ENV_DIR/ollama.env"
    run mkdir -p "$OLLAMA_ENV_DIR"
    if [[ "$DRY_RUN" == false ]]; then
        cat > "$OLLAMA_ENV_FILE" << 'OLLAMA_ENV'
OLLAMA_HOST=0.0.0.0
OLLAMA_KEEP_ALIVE=24h
OLLAMA_MAX_LOADED_MODELS=2
OLLAMA_ENV
    else
        echo "[DRY-RUN] Would write $OLLAMA_ENV_FILE with OLLAMA_HOST=0.0.0.0"
    fi
    ok "Ollama configured: OLLAMA_HOST=0.0.0.0, KEEP_ALIVE=24h, MAX_LOADED=2"
else
    log "Step 5/11: Skipping Ollama config (not installed for this role)"
fi

# ---------------------------------------------------------------------------
# Step 6: Create Ollama launchd plist (auto-start)
# ---------------------------------------------------------------------------
if [[ "$INSTALL_OLLAMA" == true ]]; then
    log "Step 6/11: Creating Ollama launchd service for auto-start..."
    PLIST_PATH="$HOME/Library/LaunchAgents/com.symphony.ollama.plist"
    OLLAMA_BIN=$(command -v ollama 2>/dev/null || echo "/opt/homebrew/bin/ollama")
    SYMPHONY_LOG_DIR="$HOME/.symphony/logs"

    run mkdir -p "$HOME/Library/LaunchAgents"
    run mkdir -p "$SYMPHONY_LOG_DIR"

    if [[ "$DRY_RUN" == false ]]; then
        cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.ollama</string>
    <key>ProgramArguments</key>
    <array>
        <string>$OLLAMA_BIN</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>0.0.0.0</string>
        <key>OLLAMA_KEEP_ALIVE</key>
        <string>24h</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key>
        <string>2</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SYMPHONY_LOG_DIR/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>$SYMPHONY_LOG_DIR/ollama_error.log</string>
</dict>
</plist>
PLIST
        run launchctl unload "$PLIST_PATH" 2>/dev/null || true
        run launchctl load -w "$PLIST_PATH"
    else
        echo "[DRY-RUN] Would create launchd plist at $PLIST_PATH"
    fi
    ok "Ollama launchd service configured (auto-starts on login)"
else
    log "Step 6/11: Skipping Ollama launchd (not installed)"
fi

# ---------------------------------------------------------------------------
# Step 7: Pull base Ollama models
# ---------------------------------------------------------------------------
if [[ "$INSTALL_OLLAMA" == true && "$SKIP_MODELS" == false ]]; then
    log "Step 7/11: Pulling base Ollama models..."
    log "  (This is the slow step — depends on internet speed and model size)"

    # Wait for Ollama to be ready
    log "  Waiting for Ollama to start..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            ok "  Ollama is responding"
            break
        fi
        sleep 2
        if [[ $i -eq 30 ]]; then
            warn "  Ollama not responding after 60s. Trying to pull anyway..."
        fi
    done

    # Determine which models to pull based on role
    declare -a MODELS_TO_PULL
    case "$ROLE" in
        hq)
            MODELS_TO_PULL=("llama3.2:3b" "nomic-embed-text")
            ;;
        llm_worker)
            MODELS_TO_PULL=("llama3.1:8b" "mistral:7b" "nomic-embed-text")
            ;;
        full_worker)
            MODELS_TO_PULL=("llama3.2:3b" "llama3.1:8b" "nomic-embed-text")
            ;;
    esac

    for model in "${MODELS_TO_PULL[@]:-}"; do
        log "  Pulling $model..."
        run ollama pull "$model"
        ok "  Pulled $model"
    done
    ok "Base models pulled"
else
    log "Step 7/11: Skipping model pulls (SKIP_MODELS=$SKIP_MODELS)"
fi

# ---------------------------------------------------------------------------
# Step 8: Set up ~/.symphony directory structure
# ---------------------------------------------------------------------------
log "Step 8/11: Creating ~/.symphony directory structure..."
SYMPHONY_DIR="$HOME/.symphony"

run mkdir -p "$SYMPHONY_DIR/registry"
run mkdir -p "$SYMPHONY_DIR/logs"
ok "~/.symphony/ structure created"

# ---------------------------------------------------------------------------
# Step 9: Set up heartbeat cron
# ---------------------------------------------------------------------------
log "Step 9/11: Setting up heartbeat cron (pings Bob every 60s)..."
HEARTBEAT_SCRIPT="$SYMPHONY_DIR/heartbeat.sh"
HEARTBEAT_LOG="$SYMPHONY_DIR/logs/heartbeat.log"

if [[ "$DRY_RUN" == false ]]; then
    # Get current node's IP
    NODE_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "UNKNOWN")
    NODE_HOSTNAME=$(hostname)

    cat > "$HEARTBEAT_SCRIPT" << HBSCRIPT
#!/usr/bin/env bash
# Symphony heartbeat — runs on cron every 60s
NODE_IP=\$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "UNKNOWN")
TIMESTAMP=\$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s -m 5 \\
  -X POST \\
  -H "Content-Type: application/json" \\
  -d "{\\"node_id\\":\\"$HOSTNAME_ARG\\",\\"ip\\":\\"\$NODE_IP\\",\\"timestamp\\":\\"\$TIMESTAMP\\"}" \\
  "http://$BOB_IP:8765/api/heartbeat" >> "$HEARTBEAT_LOG" 2>&1 || true
HBSCRIPT

    chmod +x "$HEARTBEAT_SCRIPT"

    # Add to crontab (idempotent)
    CRON_LINE="* * * * * bash $HEARTBEAT_SCRIPT"
    ( crontab -l 2>/dev/null | grep -v "$HEARTBEAT_SCRIPT"; echo "$CRON_LINE" ) | crontab -
    ok "Heartbeat cron set: every minute → Bob at $BOB_IP:8765"
else
    echo "[DRY-RUN] Would create $HEARTBEAT_SCRIPT and add cron entry"
fi

# ---------------------------------------------------------------------------
# Step 10: Self-register with Bob's registry API
# ---------------------------------------------------------------------------
log "Step 10/11: Attempting self-registration with Bob's registry API..."
NODE_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "UNKNOWN")

if [[ "$DRY_RUN" == false ]]; then
    REGISTRATION_PAYLOAD=$(cat << JSON
{
  "node_id": "$HOSTNAME_ARG",
  "display_name": "$(echo "$HOSTNAME_ARG" | sed 's/./\u&/')",
  "role": "$ROLE",
  "ip": "$NODE_IP",
  "hostname": "$HOSTNAME_ARG.local",
  "services": {
    "ollama": $INSTALL_OLLAMA,
    "ollama_port": 11434,
    "docker": $INSTALL_DOCKER,
    "harpa": $INSTALL_HARPA_GUIDE
  },
  "registered_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
JSON
)

    # Save registration payload locally
    echo "$REGISTRATION_PAYLOAD" > "$SYMPHONY_DIR/registry/self_registration.json"
    ok "Self-registration payload saved to ~/.symphony/registry/self_registration.json"

    # Try to register with Bob
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -m 10 \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$REGISTRATION_PAYLOAD" \
        "http://$BOB_IP:8765/api/nodes/register" 2>/dev/null || echo "000")

    if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "201" ]]; then
        ok "Self-registered with Bob's registry API (HTTP $HTTP_STATUS)"
    else
        warn "Could not reach Bob's registry API (HTTP $HTTP_STATUS). This is OK — Bob will discover this node via heartbeat."
        warn "Update nodes_registry.json on Bob manually with IP: $NODE_IP"
    fi
else
    echo "[DRY-RUN] Would POST registration to http://$BOB_IP:8765/api/nodes/register"
fi

# ---------------------------------------------------------------------------
# Step 11: Save HARPA setup instructions
# ---------------------------------------------------------------------------
if [[ "$INSTALL_HARPA_GUIDE" == true ]]; then
    log "Step 11/11: Saving HARPA setup instructions..."
    HARPA_INSTRUCTIONS="$SYMPHONY_DIR/harpa_setup_instructions.txt"

    if [[ "$DRY_RUN" == false ]]; then
        cat > "$HARPA_INSTRUCTIONS" << 'HARPA'
HARPA AI Chrome Extension — Setup Guide
========================================

HARPA AI cannot be installed via CLI (it's a Chrome extension).
Complete this setup manually after provision_node.sh finishes.

Step 1: Open Google Chrome
  - Chrome should already be installed by provision_node.sh
  - Launch from Applications or Spotlight

Step 2: Install HARPA AI extension
  - Go to: https://chrome.google.com/webstore/detail/harpa-ai/
  - Click "Add to Chrome" → "Add extension"
  - The HARPA icon will appear in your Chrome toolbar

Step 3: Create / Log in to HARPA account
  - Click the HARPA icon in Chrome toolbar
  - Create a free account or log in with an existing account
  - This links the extension to the HARPA Grid for remote task receiving

Step 4: Enable HARPA Grid (remote automation)
  - In HARPA settings, enable "HARPA Grid" or "Remote Commands"
  - This allows Bob (OpenClaw) to send automation tasks to this node
  - Your node ID in HARPA Grid should match the node hostname (e.g. 'maestro')

Step 5: Log in to D-Tools Cloud (if this is an llm_worker or browser_node)
  - Open D-Tools Cloud in Chrome: https://cloud.d-tools.com
  - Log in with Symphony Smart Homes credentials
  - Keep Chrome open (HARPA needs an active Chrome session to run tasks)

Step 6: Set Chrome to auto-start on login
  - System Settings → General → Login Items
  - Add Google Chrome.app
  - This ensures HARPA is always available when the node boots

Step 7: Verify from Bob
  After completing the above, verify from Bob:
    python3 ~/.symphony/node_health_monitor.py --node [this_node_hostname]

HARPA
    fi
    ok "HARPA setup instructions saved to ~/.symphony/harpa_setup_instructions.txt"
else
    log "Step 11/11: Skipping HARPA guide (not applicable for role: $ROLE)"
fi

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo -e "${BOLD}${GREEN}  Provisioning complete!${RESET}"
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo ""
echo "  Node      : $HOSTNAME_ARG ($ROLE)"
echo "  IP        : $(ipconfig getifaddr en0 2>/dev/null || echo 'unknown')"
echo ""
echo "  Next steps:"

if [[ "$INSTALL_OLLAMA" == true ]]; then
    echo "  [1] Verify Ollama is running: curl http://localhost:11434/api/tags"
fi
if [[ "$INSTALL_HARPA_GUIDE" == true ]]; then
    echo "  [2] Complete HARPA setup: cat ~/.symphony/harpa_setup_instructions.txt"
fi
echo "  [3] From Bob, verify this node:"
echo "        python3 ~/.symphony/node_health_monitor.py --node $HOSTNAME_ARG"
echo "  [4] Update nodes_registry.json on Bob with this node's IP if needed"
echo "  [5] Add this node to openclaw_workers.json on Bob"
echo ""
echo -e "  ${BLUE}Setup log: All output above${RESET}"
echo ""
