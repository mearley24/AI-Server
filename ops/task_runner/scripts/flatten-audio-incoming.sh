#!/bin/bash
# Flatten date-organized audio recordings into the incoming/ root.
# Bert's Audio Recordings are organized as RECORD/YYYYMMDD/file.wav; the
# audio_intake worker's glob only matches files directly under incoming/.
# This script moves every audio file from any nested YYYYMMDD/ directory
# up to incoming/, prefixing the filename with the date folder name so we
# don't lose the session grouping. Idempotent: already-flat files are left
# alone; collisions use the date prefix.
set -euo pipefail

INCOMING="/Users/bob/AI-Server/data/audio_intake/incoming"
cd "$INCOMING"

moved=0
collisions=0
for dir in */ ; do
  [ -d "$dir" ] || continue
  prefix="${dir%/}"
  # Only flatten dirs that look like YYYYMMDD (8 digits).
  [[ "$prefix" =~ ^[0-9]{8}$ ]] || continue
  while IFS= read -r -d '' f; do
    base="$(basename "$f")"
    dest="${prefix}__${base}"
    if [ -e "$INCOMING/$dest" ]; then
      collisions=$((collisions+1))
      echo "skip-collision: $dest already exists"
      continue
    fi
    mv "$f" "$INCOMING/$dest"
    moved=$((moved+1))
  done < <(find "$dir" -type f \( -iname '*.wav' -o -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.flac' \) -print0)
  # Prune now-empty date dir.
  if [ -z "$(ls -A "$dir" 2>/dev/null)" ]; then
    rmdir "$dir" 2>/dev/null || true
  fi
done

echo "moved: $moved"
echo "collisions: $collisions"
echo "incoming contents after flatten:"
ls -la "$INCOMING" | head -40
echo "audio file count at root of incoming:"
find "$INCOMING" -maxdepth 1 -type f \( -iname '*.wav' -o -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.flac' \) | wc -l | tr -d ' '
