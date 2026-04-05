#!/usr/bin/env bash
# setup-ollama-maestro.sh — Install and configure Ollama on Maestro (64GB iMac)
# Run from Bob or any machine with SSH access to Maestro.
#
# Prerequisites:
#   - SSH access to Maestro (ssh maestro.local or ssh <ip>)
#   - Maestro has 64GB RAM (sufficient for 70B parameter models)
#
# Usage:
#   bash scripts/setup-ollama-maestro.sh <maestro-ip>
#   Example: bash scripts/setup-ollama-maestro.sh 192.168.1.50

set -euo pipefail

MAESTRO="${1:-maestro.local}"

echo "=== Installing Ollama on $MAESTRO ==="
ssh "$MAESTRO" 'which ollama >/dev/null 2>&1 && echo "Ollama already installed: $(ollama --version)" || curl -fsSL https://ollama.com/install.sh | sh'

echo ""
echo "=== Starting Ollama server ==="
ssh "$MAESTRO" 'nohup ollama serve > /tmp/ollama.log 2>&1 &'
sleep 5

echo ""
echo "=== Pulling models (this will take a while) ==="
echo "  Pulling llama3.1:70b (~40GB)..."
ssh "$MAESTRO" 'ollama pull llama3.1:70b'
echo "  Pulling codellama:34b (~19GB)..."
ssh "$MAESTRO" 'ollama pull codellama:34b'

echo ""
echo "=== Verifying ==="
ssh "$MAESTRO" 'ollama list'

echo ""
echo "=== Configuration for AI-Server ==="
MAESTRO_IP=$(ssh "$MAESTRO" "ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1")
echo "Add to ~/AI-Server/.env:"
echo "  OLLAMA_HOST=http://${MAESTRO_IP}:11434"
echo ""
echo "Ollama API will be available at: http://${MAESTRO_IP}:11434"
echo "Test with: curl http://${MAESTRO_IP}:11434/api/tags"
