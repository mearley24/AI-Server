#!/bin/bash
# Rsync pending audio recordings from Bert to Bob's data/audio_intake/incoming.
# Runs on Bert via ssh_and_run. Host key for Bob must be pinned first via
# the bert-hostkey-pin task.
set -euo pipefail

BOB="bob@bobs-mac-mini.tailbcf3fe.ts.net"

# Make sure the landing zone exists on Bob (BatchMode fails loud on new hosts).
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BOB" \
  "mkdir -p /Users/bob/AI-Server/data/audio_intake/incoming"

# RECORD and MEETING both land in the same incoming/ directory so the audio
# worker picks them up uniformly. --partial keeps resumable state on flaky links.
rsync -avh --partial --stats \
  "$HOME/Documents/Audio Recordings/RECORD/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"

rsync -avh --partial --stats \
  "$HOME/Documents/Audio Recordings/MEETING/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"

LANDED=$(ssh -o BatchMode=yes "$BOB" \
  "ls -1 /Users/bob/AI-Server/data/audio_intake/incoming/ 2>/dev/null | wc -l | tr -d ' '")
echo "files-on-bob: $LANDED"
