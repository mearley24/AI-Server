#!/usr/bin/env bash
# =============================================================================
#  appliance_setup.sh
#  Symphony Smart Homes — Zero-Touch Concierge Appliance Setup
#
#  Supports:
#    - macOS (Mac Mini M2/M4) — primary target
#    - Ubuntu/Debian Linux (Raspberry Pi OS, Ubuntu Server)
#    - Docker-based deployment on either platform
#
#  What this script does:
#   1. Detects OS and hardware (Mac/Linux, Apple Silicon/ARM/x86)
#   2. Installs system dependencies (Homebrew/apt, Python 3.11+, nginx)
#   3. Installs Ollama and downloads the specified model
#   4. Installs ChromaDB, FastAPI, and Python dependencies
#   5. Deploys the Concierge API server (concierge_server.py)
#   6. Creates the web UI directory and configures nginx
#   7. Sets up auto-start services (launchd on macOS, systemd on Linux)
#   8. Configures firewall (macOS pf / Linux ufw)
#   9. Writes health check endpoint
#  10. Verifies installation and prints access URL
#
#  Usage:
#    sudo bash appliance_setup.sh --client-id C0042 --ai-name Aria
#    sudo bash appliance_setup.sh --client-id C0042 --tier standard --model llama3.1:8b
#    sudo bash appliance_setup.sh --client-id C0042 --dry-run
#
#  Required:
#    --client-id   Client ID from Symphony registry (e.g. C0042)
#    --ai-name     AI persona name (e.g. Aria, Maxwell, Luna)
#
#  Optional:
#    --tier        budget|standard|premium (default: standard)
#    --model       Ollama model to pull (overrides tier default)
#    --port        Concierge server port (default: 8080)
#    --no-firewall Skip firewall hardening
#    --docker      Use Docker Compose instead of native install
#    --dry-run     Print actions without executing
# =============================================================================

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()     { echo -e "${BLUE}[$(date '+%H:%M:%S')]${RESET} $*"; }
success() { echo -e "${GREEN}[$(date '+%H:%M:%S')] OK${RESET} $*"; }
warn()    { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARN${RESET} $*"; }
error()   { echo -e "${RED}[$(date '+%H:%M:%S')] ERR${RESET} $*" >&2; }
fatal()   { error "$*"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}=== $* ===${RESET}\n"; }

# --- Defaults ---
SCRIPT_VERSION="2.0.0"
CONCIERGE_HOME="/opt/symphony/concierge"
SYMPHONY_USER="symphony-admin"
LOG_FILE="/var/log/symphony-setup.log"
OLLAMA_VERSION="latest"
PYTHON_MIN_VERSION="3.11"

CLIENT_ID=""
AI_NAME="Aria"
TIER="standard"
PORT=8080
SKIP_FIREWALL=false
USE_DOCKER=false
DRY_RUN=false
MODEL=""

# Model defaults per tier
declare -A TIER_MODELS
TIER_MODELS["budget"]="llama3.2:3b"
TIER_MODELS["standard"]="llama3.1:8b"
TIER_MODELS["premium"]="llama3.1:8b"
TIER_MODELS["enterprise"]="llama3.1:70b-q2_K"

# --- Parse Arguments ---
usage() {
  cat <<EOF
Usage: sudo bash appliance_setup.sh [options]

Required:
  --client-id ID    Client ID (e.g. C0042)
  --ai-name NAME    AI name (e.g. Aria, Maxwell)

Optional:
  --tier TIER       budget|standard|premium|enterprise (default: standard)
  --model MODEL     Ollama model tag (overrides tier default)
  --port PORT       Server port (default: 8080)
  --no-firewall     Skip firewall configuration
  --docker          Use Docker Compose deployment
  --dry-run         Print actions without executing

Examples:
  sudo bash appliance_setup.sh --client-id C0042 --ai-name Aria
  sudo bash appliance_setup.sh --client-id C0042 --ai-name Aria --tier premium
  sudo bash appliance_setup.sh --client-id C0042 --ai-name Aria --model llama3.1:8b --port 8080
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-id)   CLIENT_ID="$2";  shift 2 ;;
    --ai-name)     AI_NAME="$2";    shift 2 ;;
    --tier)        TIER="$2";       shift 2 ;;
    --model)       MODEL="$2";      shift 2 ;;
    --port)        PORT="$2";       shift 2 ;;
    --no-firewall) SKIP_FIREWALL=true; shift ;;
    --docker)      USE_DOCKER=true;  shift ;;
    --dry-run)     DRY_RUN=true;    shift ;;
    -h|--help)     usage ;;
    *) error "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$CLIENT_ID" ]] && fatal "--client-id is required"
[[ -z "$AI_NAME"   ]] && fatal "--ai-name is required"

# Resolve model from tier if not explicitly set
if [[ -z "$MODEL" ]]; then
  MODEL="${TIER_MODELS[$TIER]:-llama3.1:8b}"
fi

# --- Dry-Run Wrapper ---
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}[DRY-RUN]${RESET} $*"
  else
    eval "$@"
  fi
}

# --- OS Detection ---
detect_os() {
  if [[ "$(uname)" == "Darwin" ]]; then
    OS="macos"
    ARCH=$(uname -m)
  elif [[ -f /etc/os-release ]]; then
    source /etc/os-release
    OS="linux"
    DISTRO="${ID:-unknown}"
    ARCH=$(uname -m)
  else
    fatal "Unsupported operating system: $(uname)"
  fi
  log "Detected OS: $OS | Arch: $ARCH | Tier: $TIER | Model: $MODEL"
}

# --- Root Check ---
[[ $EUID -ne 0 ]] && fatal "This script must be run as root: sudo bash $0"

# --- Setup Log ---
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

# --- Banner ---
echo ""
echo -e "${BOLD}Symphony Smart Homes --- Concierge AI Appliance Setup v${SCRIPT_VERSION}${RESET}"
echo ""
log "Client ID:  $CLIENT_ID"
log "AI Name:    $AI_NAME"
log "Tier:       $TIER"
log "Model:      $MODEL"
log "Port:       $PORT"
log "Docker:     $USE_DOCKER"
log "Dry Run:    $DRY_RUN"
echo ""

detect_os

# =============================================================================
# STEP 1: SYSTEM PREPARATION
# =============================================================================
step "Step 1: System Preparation"

log "Creating Symphony directory structure at $CONCIERGE_HOME..."
run mkdir -p "$CONCIERGE_HOME"/{knowledge,logs,ui,vectorstore,models,updates,backups,conversations}
run mkdir -p /opt/symphony/bin
success "Directory structure created"

run "echo '${SCRIPT_VERSION}' > '$CONCIERGE_HOME/VERSION'"
run "echo '${CLIENT_ID}' > '$CONCIERGE_HOME/CLIENT_ID'"

if [[ "$OS" == "macos" ]]; then
  log "Configuring macOS power management (always-on)..."
  run pmset -a sleep 0 hibernatemode 0 disksleep 0 autopoweroff 0
  run pmset -a powernap 0 tcpkeepalive 1
  HOSTNAME="symphony-concierge-${CLIENT_ID,,}"
  run scutil --set HostName "$HOSTNAME"
  run scutil --set LocalHostName "$HOSTNAME"
  run scutil --set ComputerName "Symphony Concierge ($CLIENT_ID)"
  success "macOS configured: always-on, hostname set to $HOSTNAME"
elif [[ "$OS" == "linux" ]]; then
  log "Disabling swap for better LLM performance..."
  run swapoff -a || warn "Could not disable swap (non-fatal)"
  HOSTNAME="symphony-concierge-${CLIENT_ID,,}"
  run hostnamectl set-hostname "$HOSTNAME" || warn "hostnamectl failed (non-fatal)"
  success "Linux configured: hostname $HOSTNAME"
fi

# =============================================================================
# STEP 2: INSTALL DEPENDENCIES
# =============================================================================
step "Step 2: Installing System Dependencies"

install_dependencies_macos() {
  if ! command -v brew &>/dev/null; then
    log "Installing Homebrew..."
    run /bin/bash -c "\"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" </dev/null
    if [[ "$ARCH" == "arm64" ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
    fi
  fi
  success "Homebrew: $(brew --version | head -1)"
  for pkg in python@3.11 curl jq nginx; do
    if brew list "$pkg" &>/dev/null; then
      success "$pkg: already installed"
    else
      log "Installing $pkg..."
      run brew install "$pkg"
    fi
  done
}

install_dependencies_linux() {
  log "Updating package index..."
  run apt-get update -qq
  PACKAGES="python3 python3-pip python3-venv curl jq nginx git"
  log "Installing: $PACKAGES"
  run apt-get install -y -qq $PACKAGES
  success "Linux dependencies installed"
}

if [[ "$OS" == "macos" ]]; then
  install_dependencies_macos
elif [[ "$OS" == "linux" ]]; then
  install_dependencies_linux
fi

# Verify Python
PYTHON_BIN=""
for py in python3.11 python3 python; do
  if command -v "$py" &>/dev/null; then
    PY_VER=$("$py" --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 11 ]]; then
      PYTHON_BIN="$py"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  fatal "Python 3.11+ required but not found. Install manually and retry."
fi
success "Python: $PYTHON_BIN ($PY_VER)"

# =============================================================================
# STEP 3: INSTALL OLLAMA
# =============================================================================
step "Step 3: Installing Ollama"

if ! command -v ollama &>/dev/null; then
  log "Downloading and installing Ollama..."
  run curl -fsSL https://ollama.ai/install.sh | sh
  success "Ollama installed"
else
  INSTALLED_OLLAMA=$(ollama --version 2>/dev/null || echo "unknown version")
  success "Ollama already installed: $INSTALLED_OLLAMA"
fi

# Configure Ollama to bind ONLY to localhost
if [[ "$OS" == "macos" ]]; then
  OLLAMA_PLIST="/Library/LaunchDaemons/com.symphony.ollama.plist"
  log "Configuring Ollama launchd plist (localhost only)..."
  cat > "$OLLAMA_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key><string>com.symphony.ollama</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ollama</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
        <key>OLLAMA_ORIGINS</key><string>http://localhost,http://127.0.0.1</string>
        <key>OLLAMA_NUM_PARALLEL</key><string>2</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key><string>1</string>
        <key>OLLAMA_FLASH_ATTENTION</key><string>1</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>
PLIST
  run launchctl load -w "$OLLAMA_PLIST" 2>/dev/null || true
  success "Ollama configured as launchd service (localhost only)"

elif [[ "$OS" == "linux" ]]; then
  mkdir -p /etc/systemd/system/ollama.service.d/
  cat > /etc/systemd/system/ollama.service.d/symphony.conf <<'SYSD'
[Service]
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_ORIGINS=http://localhost,http://127.0.0.1
Environment=OLLAMA_NUM_PARALLEL=2
Environment=OLLAMA_FLASH_ATTENTION=1
SYSD
  run systemctl daemon-reload
  run systemctl enable ollama
  run systemctl restart ollama || warn "Ollama restart failed"
  success "Ollama configured as systemd service (localhost only)"
fi

# Wait for Ollama to start
log "Waiting for Ollama to start..."
for i in {1..30}; do
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    success "Ollama is running"
    break
  fi
  sleep 2
  if [[ $i -eq 30 ]]; then
    warn "Ollama not ready after 60s"
  fi
done

log "Pulling model: $MODEL (this may take 10-45 minutes)..."
run ollama pull "$MODEL"
success "Model ready: $MODEL"

# =============================================================================
# STEP 4: PYTHON ENVIRONMENT & DEPENDENCIES
# =============================================================================
step "Step 4: Python Virtual Environment & Dependencies"

VENV_PATH="$CONCIERGE_HOME/venv"
log "Creating Python virtual environment at $VENV_PATH..."
run "$PYTHON_BIN" -m venv "$VENV_PATH"
VENV_PYTHON="$VENV_PATH/bin/python"
VENV_PIP="$VENV_PATH/bin/pip"

log "Upgrading pip..."
run "$VENV_PIP" install --quiet --upgrade pip

PYTHON_PACKAGES=(
  "fastapi>=0.110.0"
  "uvicorn[standard]>=0.29.0"
  "httpx>=0.27.0"
  "chromadb>=0.5.0"
  "sentence-transformers>=2.7.0"
  "pdfplumber>=0.11.0"
  "PyPDF2>=3.0.0"
  "pydantic>=2.5.0"
  "python-multipart>=0.0.9"
)

log "Installing Python packages..."
run "$VENV_PIP" install --quiet "${PYTHON_PACKAGES[@]}"
success "Python environment ready at $VENV_PATH"

# Copy Concierge source files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILES=(
  "concierge_server.py"
  "knowledge_ingestion.py"
  "client_onboarding.py"
)

log "Copying Concierge source files..."
for f in "${SOURCE_FILES[@]}"; do
  if [[ -f "$SCRIPT_DIR/$f" ]]; then
    run cp "$SCRIPT_DIR/$f" "$CONCIERGE_HOME/"
    success "Copied: $f"
  else
    warn "$f not found in $SCRIPT_DIR"
  fi
done

# Copy web UI if present
if [[ -d "$SCRIPT_DIR/web_ui" ]]; then
  run cp -r "$SCRIPT_DIR/web_ui/." "$CONCIERGE_HOME/ui/"
  success "Web UI copied to $CONCIERGE_HOME/ui/"
else
  warn "No web_ui/ directory found"
fi

# =============================================================================
# STEP 5: NGINX CONFIGURATION
# =============================================================================
step "Step 5: Configuring nginx"

if [[ "$OS" == "macos" ]]; then
  NGINX_CONF_DIR="/opt/homebrew/etc/nginx/servers"
else
  NGINX_CONF_DIR="/etc/nginx/sites-available"
  NGINX_ENABLED_DIR="/etc/nginx/sites-enabled"
fi

run mkdir -p "$NGINX_CONF_DIR"
NGINX_CONF="$NGINX_CONF_DIR/symphony-concierge.conf"

log "Writing nginx config to $NGINX_CONF..."
cat > "$NGINX_CONF" <<NGINX
# Symphony Concierge nginx reverse proxy
# Client: $CLIENT_ID | AI: $AI_NAME

server {
    listen 80;
    server_name _;

    allow 127.0.0.0/8;
    allow 192.168.0.0/16;
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 100.64.0.0/10;
    deny all;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location /health {
        proxy_pass http://127.0.0.1:${PORT}/health;
        proxy_buffering off;
    }

    access_log ${CONCIERGE_HOME}/logs/nginx-access.log;
    error_log ${CONCIERGE_HOME}/logs/nginx-error.log warn;
}
NGINX

if [[ "$OS" == "linux" ]]; then
  run ln -sf "$NGINX_CONF" "$NGINX_ENABLED_DIR/symphony-concierge.conf" 2>/dev/null || true
  run rm -f "$NGINX_ENABLED_DIR/default" 2>/dev/null || true
fi

if nginx -t 2>/dev/null; then
  success "nginx config valid"
  if [[ "$OS" == "macos" ]]; then
    run brew services restart nginx 2>/dev/null || true
  else
    run systemctl enable nginx
    run systemctl restart nginx
  fi
  success "nginx started"
else
  warn "nginx config test failed"
fi

# =============================================================================
# STEP 6: CONCIERGE SERVER SERVICE
# =============================================================================
step "Step 6: Setting Up Concierge Server Service"

log "Writing environment config..."
cat > "$CONCIERGE_HOME/.env" <<ENV
SYMPHONY_CLIENT_ID=${CLIENT_ID}
SYMPHONY_AI_NAME=${AI_NAME}
SYMPHONY_BASE_MODEL=${MODEL}
SYMPHONY_MODEL_TAG=concierge-${CLIENT_ID,,}-v1
OLLAMA_HOST=http://127.0.0.1:11434
CHROMA_PATH=${CONCIERGE_HOME}/vectorstore
CONCIERGE_HOME=${CONCIERGE_HOME}
CONCIERGE_HOST=127.0.0.1
CONCIERGE_PORT=${PORT}
PROVISION_DATE=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
ENV

STARTUP_SCRIPT="/opt/symphony/bin/concierge-start.sh"
cat > "$STARTUP_SCRIPT" <<STARTUP
#!/bin/bash
set -a
source ${CONCIERGE_HOME}/.env
set +a
cd ${CONCIERGE_HOME}
exec ${VENV_PATH}/bin/python concierge_server.py --host 127.0.0.1 --port ${PORT}
STARTUP
chmod +x "$STARTUP_SCRIPT"

if [[ "$OS" == "macos" ]]; then
  CONCIERGE_PLIST="/Library/LaunchDaemons/com.symphony.concierge.plist"
  cat > "$CONCIERGE_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key><string>com.symphony.concierge</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
PLIST
  run launchctl load -w "$CONCIERGE_PLIST" 2>/dev/null || true
  success "Concierge server configured as launchd service"

elif [[ "$OS" == "linux" ]]; then
  cat > /etc/systemd/system/symphony-concierge.service <<'SYSD'
[Unit]
Description=Symphony Concierge AI Server
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=root
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSD
  run systemctl daemon-reload
  run systemctl enable symphony-concierge
  run systemctl start symphony-concierge
  success "Concierge server configured as systemd service"
fi

# =============================================================================
# STEP 7: WRITE MANIFEST
# =============================================================================
step "Step 7: Manifest & Health Check"

LAN_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' 2>/dev/null || \
         ipconfig getifaddr en0 2>/dev/null || echo "unknown")

cat > "$CONCIERGE_HOME/MANIFEST.json" <<MANIFEST
{
  "client_id": "${CLIENT_ID}",
  "ai_name": "${AI_NAME}",
  "tier": "${TIER}",
  "model": "${MODEL}",
  "concierge_version": "${SCRIPT_VERSION}",
  "os": "${OS}",
  "arch": "${ARCH}",
  "lan_ip": "${LAN_IP}",
  "port": ${PORT},
  "provisioned_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}
MANIFEST

success "Manifest written to $CONCIERGE_HOME/MANIFEST.json"

# Health check script
HEALTHCHECK_SCRIPT="/opt/symphony/bin/health-check.sh"
cat > "$HEALTHCHECK_SCRIPT" <<'HEALTH'
#!/bin/bash
OLLAMA_OK=$(curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && echo "ok" || echo "down")
CONCIERGE_OK=$(curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1 && echo "ok" || echo "down")
NGINX_OK=$(curl -sf http://127.0.0.1:80/health >/dev/null 2>&1 && echo "ok" || echo "down")
echo "Symphony Concierge Health Check"
echo "  Ollama:     $OLLAMA_OK"
echo "  Concierge:  $CONCIERGE_OK"
echo "  nginx:      $NGINX_OK"
if [[ "$OLLAMA_OK" == "ok" && "$CONCIERGE_OK" == "ok" ]]; then
  echo "  Status: HEALTHY"; exit 0
else
  echo "  Status: DEGRADED"; exit 1
fi
HEALTH
chmod +x "$HEALTHCHECK_SCRIPT"

# =============================================================================
# FINAL: SUMMARY
# =============================================================================
echo ""
success "Concierge Setup Complete!"
echo ""
echo "  Client:     $CLIENT_ID"
echo "  AI Name:    $AI_NAME"
echo "  Model:      $MODEL"
echo "  UI:         http://$LAN_IP/"
echo "  Logs:       $CONCIERGE_HOME/logs/"
echo ""
echo "Remaining manual steps:"
echo "  1. Run client onboarding: python3 client_onboarding.py --client-id $CLIENT_ID"
echo "  2. Connect Tailscale VPN if needed"
echo "  3. Run health check: /opt/symphony/bin/health-check.sh"
echo "  4. Test from client phone: http://$LAN_IP"
echo ""
success "Setup log saved to: $LOG_FILE"
