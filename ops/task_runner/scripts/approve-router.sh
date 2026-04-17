#!/bin/bash
# Touch the audio router approval flag on Bob.
# Used to flip the router from dry-run/suspended to live once a human (or a
# signed task from a trusted agent) has reviewed the most recent plan.
set -euo pipefail

FLAG_DIR="/Users/bob/AI-Server/data/audio_intake/router"
FLAG="$FLAG_DIR/approved"

mkdir -p "$FLAG_DIR"
date '+%Y-%m-%d %H:%M:%S %z approved via task-runner' > "$FLAG"
chmod 644 "$FLAG"

echo "approved flag set:"
ls -l "$FLAG"
cat "$FLAG"
