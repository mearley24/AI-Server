#!/bin/zsh
set -euo pipefail
printf 'M2 MacBook Pro — Always-On Worker Setup\n'
printf '=========================================\n\n'

printf 'This script sets up the M2 as an always-on Ollama worker with Tailscale.\n'
printf 'Run this ON the M2 MacBook Pro.\n\n'

printf '=== Part 1: Ollama ===\n\n'

printf 'Step 1: Installing Ollama...\n'
curl -fsSL https://ollama.com/install.sh | sh

printf '\nStep 2: Pulling llama3.2:3b...\n'
ollama pull llama3.2:3b

printf '\nStep 3: Configuring Ollama to listen on all interfaces...\n'
launchctl setenv OLLAMA_HOST "127.0.0.1:11434"

printf '\nStep 4: Restarting Ollama...\n'
pkill ollama 2>/dev/null || true
sleep 2
open -a Ollama 2>/dev/null || ollama serve &
sleep 3

printf '\nStep 5: Verifying Ollama...\n'
curl -s http://127.0.0.1:11434/api/tags && printf '\nOllama OK.\n'

printf '\n=== Part 2: Tailscale ===\n\n'

if command -v tailscale >/dev/null 2>&1; then
  printf 'Tailscale already installed.\n'
else
  printf 'Installing Tailscale...\n'
  printf 'Download from: https://tailscale.com/download/mac\n'
  printf 'Or install via brew: brew install tailscale\n'
  printf 'After installing, run this script again.\n'
  exit 1
fi

printf '\nTailscale status:\n'
tailscale status 2>/dev/null || printf 'Tailscale not connected. Run: tailscale up\n'

printf '\nTailscale IP:\n'
tailscale ip -4 2>/dev/null || printf 'Not available yet.\n'

printf '\n=== Part 3: Prevent Sleep ===\n\n'

printf 'Configuring M2 to stay awake with lid closed (clamshell mode)...\n'
printf 'IMPORTANT: The M2 must be connected to an external power source for clamshell mode.\n'
printf 'For always-on without external display, use:\n'
printf '  sudo pmset -a disablesleep 1\n'
printf '  sudo pmset -a sleep 0\n'
printf '  sudo pmset -a hibernatemode 0\n'
printf '  sudo pmset -a autopoweroff 0\n\n'

printf 'Current power settings:\n'
pmset -g | grep -E "sleep|hibernate|autopoweroff|displaysleep"

printf '\n=== Part 4: GL.iNet Travel Router Notes ===\n\n'

printf 'When traveling with the GL.iNet WiFi 7 travel router:\n'
printf '1. Enable Tailscale on the GL.iNet router (Applications > Tailscale)\n'
printf '2. Enable "Allow Remote Access LAN" in the Tailscale settings\n'
printf '3. Approve the subnet route in the Tailscale admin console\n'
printf '4. The M2 connects to the GL.iNet WiFi — all traffic to Bob tunnels through Tailscale\n'
printf '5. Bob reaches the M2 at its Tailscale IP (same IP whether home or traveling)\n\n'
printf 'Alternative: Run Tailscale directly on the M2 (simpler, works without the router):\n'
printf '  tailscale up --accept-routes\n'
printf '  Bob reaches M2 at its Tailscale IP regardless of physical network.\n\n'

printf '=== Setup Complete ===\n\n'
printf 'LAN IP: '
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk "{print \$2}" | head -1
printf 'Tailscale IP: '
tailscale ip -4 2>/dev/null || printf 'N/A'
printf '\n\nNext steps:\n'
printf '1. Update setup/nodes/nodes_registry.json on Bob with both IPs\n'
printf '2. Update setup/nodes/openclaw_workers.json endpoint to Tailscale IP\n'
printf '3. Test from Bob: curl http://<tailscale-ip>:11434/api/tags\n'
printf '4. Configure GL.iNet travel router Tailscale (for travel mode)\n'
