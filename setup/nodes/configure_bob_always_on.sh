#!/usr/bin/env bash
# Configure Bob (Mac Mini) for 24/7 operation — run once with sudo.
set -euo pipefail

echo "Configuring Bob for 24/7 operation..."

# Never sleep when plugged in; display can sleep after 15 min
sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c displaysleep 15
# Wake on network access + auto-restart after power failure
sudo pmset -c womp 1
sudo pmset -c autorestart 1

echo ""
echo "Power settings applied:"
pmset -g custom | grep -E "sleep|wake|restart"

echo ""
echo "Manual checks needed:"
echo "  1. System Settings → Screen Time → OFF"
echo "  2. System Settings → General → Software Update → Automatic Updates OFF"
echo "  3. System Settings → Focus → No scheduled focus modes"
echo ""
echo "Done. Bob will stay awake when plugged in."
