#!/bin/zsh
set -euo pipefail
# M2 MacBook Pro Ollama Worker Setup
# Run this script directly on the M2. After completion, update the IP in
# setup/nodes/nodes_registry.json on Bob.

printf 'M2 MacBook Pro Ollama Worker Setup\n'
printf '===================================\n\n'

printf 'Step 1: Installing Ollama...\n'
curl -fsSL https://ollama.com/install.sh | sh

printf '\nStep 2: Pulling llama3.2:3b...\n'
ollama pull llama3.2:3b

printf '\nStep 3: Configuring Ollama to listen on all interfaces...\n'
launchctl setenv OLLAMA_HOST "127.0.0.1:11434"

printf '\nStep 4: Restarting Ollama...\n'
pkill ollama 2>/dev/null || true
sleep 2
ollama serve &
sleep 3

printf '\nStep 5: Verifying...\n'
curl -s http://127.0.0.1:11434/api/tags && printf '\n\nOllama is running.\n'

printf '\nDone. Update the IP address in setup/nodes/nodes_registry.json on Bob.\n'
printf 'Bob can reach this machine at: '
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1
printf '\n'
