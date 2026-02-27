#!/usr/bin/env bash
# =============================================================================
# setup_ollama_worker.sh
# Symphony Smart Homes — Ollama Worker Node Setup
# Target: 2019 iMac (Intel Core i3, 64GB RAM, macOS Sonoma or Sequoia)
#
# This script sets up the 64GB Intel iMac as a dedicated LLM inference worker
# for Bob the Conductor (Mac Mini M4) running OpenClaw.
#
# What this script does:
#   1. Installs Homebrew
#   2. Installs Ollama via Homebrew
#   3. Creates a launchd service for auto-start on boot
#   4. Loads environment variables from ollama_worker.env
#   5. Pulls required base models (llama3.2:3b, llama3.1:8b, mistral:7b)
#   6. Builds custom models (bob-classifier, bob-summarizer)
#   7. Verifies everything is working
#
# Run as regular user (not sudo):
#   chmod +x setup_ollama_worker.sh
#   ./setup_ollama_worker.sh
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-flight ────────────────────────────────────────────────────────────────
header "Pre-flight checks"

[[ "$EUID" -eq 0 ]] && { error "Do not run as root."; exit 1; }
[[ "$(uname)" != "Darwin" ]] && { error "macOS only."; exit 1; }

ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  warn "This machine appears to be Apple Silicon (arm64). This script is optimized"
  warn "for the Intel iMac (x86_64). Continuing anyway — Ollama supports both."
else
  success "Intel x86_64 confirmed."
fi

RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if [[ "$RAM_GB" -lt 32 ]]; then
  warn "Only ${RAM_GB}GB RAM detected. Recommended: 64GB for full model suite."
  warn "Models will still run but performance may be limited."
else
  success "RAM: ${RAM_GB}GB — sufficient for full model suite."
fi

success "User: $(whoami) | Hostname: $(hostname)"

# ── Step 1: Homebrew ──────────────────────────────────────────────────────────
header "Step 1: Homebrew"

if command -v brew &>/dev/null; then
  success "Homebrew: $(brew --version | head -1)"
else
  info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  success "Homebrew installed."
fi

# ── Step 2: Install Ollama ────────────────────────────────────────────────────
header "Step 2: Ollama"

if command -v ollama &>/dev/null; then
  OLLAMA_VER=$(ollama --version 2>/dev/null || echo 'unknown')
  success "Ollama already installed: $OLLAMA_VER"
else
  info "Installing Ollama via Homebrew..."
  brew install ollama
  success "Ollama installed: $(ollama --version 2>/dev/null || echo 'check PATH')"
fi

# ── Step 3: Environment variables ─────────────────────────────────────────────
header "Step 3: Environment configuration"

ENV_FILE="$SCRIPT_DIR/ollama_worker.env"
if [[ ! -f "$ENV_FILE" ]]; then
  error "ollama_worker.env not found at $ENV_FILE"
  error "Copy it from the repo: cp ~/AI-Server/setup/ollama_worker/ollama_worker.env $SCRIPT_DIR/"
  exit 1
fi

# Source the env file to use variables in this script
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

success "Environment loaded from $ENV_FILE"
info "  OLLAMA_HOST=$OLLAMA_HOST"
info "  OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL"
info "  OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS"

# ── Step 4: launchd service ──────────────────────────────────────────────────
header "Step 4: launchd service (auto-start on boot)"

OLLAMA_BIN="$(command -v ollama)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCH_AGENTS_DIR/com.ollama.plist"
LOG_DIR="$HOME/Library/Logs"

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

# Parse env file into launchd EnvironmentVariables XML
# Extract non-comment, non-empty KEY=VALUE lines
ENV_XML=""
while IFS= read -r line; do
  # Skip comments and empty lines
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "$(echo "$line" | tr -d '[:space:]')" ]] && continue
  # Match KEY=VALUE
  if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]]; then
    KEY="${BASH_REMATCH[1]}"
    VAL="${BASH_REMATCH[2]}"
    # Strip inline comments
    VAL="$(echo "$VAL" | sed 's/[[:space:]]*#.*$//')"
    ENV_XML+="        <key>${KEY}</key>\n"
    ENV_XML+="        <string>${VAL}</string>\n"
  fi
done < "$ENV_FILE"

cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ollama</string>

  <key>ProgramArguments</key>
  <array>
    <string>${OLLAMA_BIN}</string>
    <string>serve</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
$(echo -e "$ENV_XML")
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/ollama_worker.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/ollama_worker_error.log</string>

  <key>ThrottleInterval</key>
  <integer>30</integer>

</dict>
</plist>
PLIST

success "Created launchd plist: $PLIST_FILE"

# Unload if already running
if launchctl list | grep -q 'com.ollama'; then
  warn "Ollama service already running. Stopping..."
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  sleep 2
fi

launchctl load "$PLIST_FILE"
success "Ollama service loaded and started."

# Give it a moment to start
info "Waiting for Ollama to start..."
sleep 5

# Verify it's running
if curl -s --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1; then
  success "Ollama API responding at http://localhost:11434"
else
  error "Ollama API not responding yet. Check logs: tail -f $LOG_DIR/ollama_worker_error.log"
  warn "Continuing anyway — it may still be starting..."
fi

# ── Step 5: Pull base models ─────────────────────────────────────────────────
header "Step 5: Base model downloads"

warn "This will download approximately 10-11GB of model data."
warn "Estimated time: 20-60 minutes depending on internet speed."
echo ""
read -rp "  Continue with model downloads? [Y/n] " CONFIRM
CONFIRM="${CONFIRM:-Y}"

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
  MODELS=("llama3.2:3b" "llama3.1:8b" "mistral:7b")
  for MODEL in "${MODELS[@]}"; do
    info "Pulling $MODEL ..."
    if ollama pull "$MODEL"; then
      success "Downloaded: $MODEL"
    else
      error "Failed to pull $MODEL — check internet and retry: ollama pull $MODEL"
    fi
  done
else
  warn "Skipping model downloads. Pull manually later:"
  warn "  ollama pull llama3.2:3b && ollama pull llama3.1:8b && ollama pull mistral:7b"
fi

# ── Step 6: Build custom models ───────────────────────────────────────────────
header "Step 6: Custom model builds"

for MF in "Modelfile.bob-classifier" "Modelfile.bob-summarizer"; do
  MF_PATH="$SCRIPT_DIR/$MF"
  MODEL_NAME="${MF#Modelfile.}"  # strip "Modelfile." prefix

  if [[ ! -f "$MF_PATH" ]]; then
    warn "$MF not found in $SCRIPT_DIR — skipping. Copy from repo and re-run."
    continue
  fi

  info "Building custom model: $MODEL_NAME ..."
  if ollama create "$MODEL_NAME" -f "$MF_PATH"; then
    success "Built: $MODEL_NAME"
  else
    error "Failed to build $MODEL_NAME. Base model may not be downloaded yet."
    error "Try after pulling base models: ollama pull llama3.2:3b && ollama pull llama3.1:8b"
  fi
done

# ── Step 7: Verification ─────────────────────────────────────────────────────
header "Step 7: Verification"

# Check API
if curl -s --max-time 5 http://localhost:11434/api/tags | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Models in library: {len(d.get(\"models\", []))}')" 2>/dev/null; then
  success "Ollama API responding correctly."
else
  error "Ollama API check failed. Run: curl http://localhost:11434/api/tags"
fi

# List models
info "Installed models:"
ollama list 2>/dev/null || warn "Could not list models. Ollama may still be starting."

# Quick classification test
info "Running quick classification test..."
RESULT=$(curl -s --max-time 30 -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model": "bob-classifier", "prompt": "Control4 EA-5 Programming Guide", "stream": false}' \
  2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('response','').strip())" 2>/dev/null || echo 'test failed')
echo "  Classification result: \"$RESULT\""
if [[ "$RESULT" == "Manual" ]]; then
  success "Classification test passed!"
else
  warn "Classification result was '$RESULT' (expected 'Manual'). Model may need warm-up."
fi

# ── Get local IP address ──────────────────────────────────────────────────────
header "Network: Local IP address"

ETH_IP=$(ipconfig getifaddr en1 2>/dev/null || echo '')
WIFI_IP=$(ipconfig getifaddr en0 2>/dev/null || echo '')

if [[ -n "$ETH_IP" ]]; then
  success "Ethernet IP (en1): $ETH_IP"
  IMAC_IP="$ETH_IP"
elif [[ -n "$WIFI_IP" ]]; then
  success "Wi-Fi IP (en0): $WIFI_IP"
  IMAC_IP="$WIFI_IP"
  warn "Using Wi-Fi. Ethernet is preferred for stability."
else
  warn "Could not auto-detect IP. Check System Preferences → Network."
  IMAC_IP="[YOUR_IMAC_IP]"
fi

# ── Final summary ────────────────────────────────────────────────────────────
header "Setup complete — Next steps"

cat <<EOF
${BOLD}Ollama is running on this iMac.${NC}

Service management:
  Start:   launchctl load ~/Library/LaunchAgents/com.ollama.plist
  Stop:    launchctl unload ~/Library/LaunchAgents/com.ollama.plist
  Logs:    tail -f ~/Library/Logs/ollama_worker.log

Local API: http://localhost:11434
LAN API:   http://${IMAC_IP}:11434

${BOLD}Now configure Bob (Mac Mini M4):${NC}
  Edit ~/.openclaw/openclaw.json
  Set: "base_url": "http://${IMAC_IP}:11434"

${BOLD}Run the full diagnostic suite:${NC}
  ./test_ollama_worker.sh

${BOLD}Models installed:${NC}
  ollama list
EOF

echo ""
success "Ollama Worker Node setup complete."
