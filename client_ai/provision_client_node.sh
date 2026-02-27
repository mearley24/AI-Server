#!/usr/bin/env bash
# provision_client_node.sh — Zero-touch Symphony Concierge provisioning
#
# Run this script on a fresh Mac Mini M4 after a clean macOS install.
# It installs all dependencies, joins the Tailscale network, launches
# the Ollama + Nginx Docker stack, and pulls the base Llama 3 model.
#
# Usage:
#   bash provision_client_node.sh --client "The Andersons" --tailscale-key tskey-xxxx
#
# Options:
#   --client NAME         Client name (used for Ollama model name + logging)
#   --tailscale-key KEY   Tailscale auth key (one-time use, pre-authorised)
#   --branch BRANCH       Git branch to pull from (default: main)

set -euo pipefail

# ─── Parse arguments ──────────────────────────────────────────────────────────

CLIENT_NAME=""
TAILSCALE_KEY=""
BRANCH="main"
REPO_URL="https://github.com/mearley24/AI-Server.git"

while [[ $# -gt 0 ]]; do
  case $1 in
    --client)       CLIENT_NAME="$2";    shift 2 ;;
    --tailscale-key) TAILSCALE_KEY="$2"; shift 2 ;;
    --branch)       BRANCH="$2";         shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CLIENT_NAME"   ]] && { echo "[ERROR] --client is required" >&2; exit 1; }
[[ -z "$TAILSCALE_KEY" ]] && { echo "[ERROR] --tailscale-key is required" >&2; exit 1; }

SAFE_NAME=$(echo "$CLIENT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
LOG_FILE="/tmp/provision-${SAFE_NAME}.log"

echo "[provision] Starting provisioning for: $CLIENT_NAME"
echo "[provision] Log: $LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# ─── 1. Install Homebrew ──────────────────────────────────────────────────────

if ! command -v brew &>/dev/null; then
  echo "[provision] Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  echo "[provision] Homebrew already installed."
fi

# ─── 2. Install Docker Desktop (via Homebrew cask) ───────────────────────────

if ! command -v docker &>/dev/null; then
  echo "[provision] Installing Docker Desktop..."
  brew install --cask docker
  echo "[provision] Docker installed — please open Docker Desktop once to complete setup, then re-run this script."
  exit 0
else
  echo "[provision] Docker already installed."
fi

# ─── 3. Install Tailscale ─────────────────────────────────────────────────────

if ! command -v tailscale &>/dev/null; then
  echo "[provision] Installing Tailscale..."
  brew install --cask tailscale
fi

echo "[provision] Connecting to Tailscale..."
tailscale up --authkey="$TAILSCALE_KEY" --hostname="concierge-${SAFE_NAME}" --accept-routes

# ─── 4. Clone the AI Server repo ─────────────────────────────────────────────

REPO_DIR="$HOME/AI-Server"
if [[ -d "$REPO_DIR" ]]; then
  echo "[provision] Repo exists — pulling latest..."
  git -C "$REPO_DIR" fetch origin && git -C "$REPO_DIR" checkout "$BRANCH" && git -C "$REPO_DIR" pull
else
  echo "[provision] Cloning repo..."
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

# ─── 5. Launch Docker stack ──────────────────────────────────────────────────

cd "$REPO_DIR/client_ai"
echo "[provision] Starting Docker stack..."
docker compose up -d

# ─── 6. Wait for Ollama to be ready ──────────────────────────────────────────

echo "[provision] Waiting for Ollama to start..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:11434/ &>/dev/null; then
    echo "[provision] Ollama is up."
    break
  fi
  sleep 2
done

# ─── 7. Pull base model ───────────────────────────────────────────────────────

echo "[provision] Pulling Llama 3 base model (this may take several minutes)..."
docker exec symphony-concierge-ollama ollama pull llama3

# ─── 8. Done ──────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Symphony Concierge — Provisioning Complete                  ║"
echo "║                                                              ║"
echo "║  Client  : $CLIENT_NAME"
echo "║  Node    : concierge-${SAFE_NAME}.tail1234.ts.net"
echo "║  Stack   : docker compose ps (in ~/AI-Server/client_ai/)     ║"
echo "║                                                              ║"
echo "║  Next step: run client_knowledge_builder.py                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
