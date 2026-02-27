#!/usr/bin/env env bash
# ClawWork Installation Script for Mac Mini M4
# Installs ClawWork integration for Bob the Conductor's side hustle

set -euo pipefail

SYMPHONY_DIR="$HOME/.symphony"
CLAWWORK_DIR="$SYMPHONY_DIR/clawwork"
LOG_FILE="$SYMPHONY_DIR/logs/install_clawwork.log"

mkdir -p "$SYMPHONY_DIR/logs"

echo "Installing ClawWork integration..."
echo "Log: $LOG_FILE"

# Clone ClawWork repo
if [ ! -d "$CLAWWORK_DIR/ClawWork" ]; then
  git clone https://github.com/mearley24/ClawWork "$CLAWWORK_DIR/ClawWork"
else
  echo "ClawWork already cloned, pulling latest..."
  cd "$CLAWWORK_DIR/ClawWork" && git pull
fi

# Install Python deps
pip install -r "$CLAWWORK_DIR/ClawWork/requirements.txt"

# Copy config files
cp clawwork_config.json "$CLAWWORK_DIR/"
cp bob_side_hustle.py "$CLAWWORK_DIR/"
cp earnings_tracker.py "$CLAWWORK_DIR/"
cp task_selector.py "$CLAWWORK_DIR/"
cp -r sector_strategies "$CLAWWORK_DIR/"

echo "ClawWork installation complete!"
echo "Run: python $CLAWWORK_DIR/bob_side_hustle.py --test"
