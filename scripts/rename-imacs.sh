#!/usr/bin/env bash
# rename-imacs.sh — Rename the two iMacs on the Symphony network
# Run from any machine with SSH access to both iMacs.
#
# Betty (64GB iMac) → Maestro
# Stagehand iMac   → Stagehand (verify current name)
#
# Usage:
#   bash scripts/rename-imacs.sh <betty-ip> <stagehand-ip>
#   Example: bash scripts/rename-imacs.sh 192.168.1.50 192.168.1.51

set -euo pipefail

BETTY_IP="${1:-}"
STAGEHAND_IP="${2:-}"

if [[ -z "$BETTY_IP" || -z "$STAGEHAND_IP" ]]; then
    echo "Usage: bash scripts/rename-imacs.sh <betty-ip> <stagehand-ip>"
    echo "  betty-ip:      IP of the 64GB iMac (currently 'Betty')"
    echo "  stagehand-ip:  IP of the other iMac (currently 'Stagehand')"
    exit 1
fi

echo "=== Renaming Betty → Maestro ==="
ssh "$BETTY_IP" 'sudo scutil --set ComputerName "Maestro" && sudo scutil --set HostName "Maestro" && sudo scutil --set LocalHostName "Maestro" && echo "Done: $(scutil --get ComputerName)"'

echo ""
echo "=== Verifying Stagehand ==="
ssh "$STAGEHAND_IP" 'current=$(scutil --get ComputerName); if [[ "$current" == "Stagehand" ]]; then echo "Already named Stagehand — no change needed"; else sudo scutil --set ComputerName "Stagehand" && sudo scutil --set HostName "Stagehand" && sudo scutil --set LocalHostName "Stagehand" && echo "Renamed to Stagehand"; fi'

echo ""
echo "Both machines renamed. You may need to restart them for Bonjour/mDNS to update."
