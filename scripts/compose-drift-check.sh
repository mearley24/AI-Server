#!/usr/bin/env bash
# scripts/compose-drift-check.sh — detect drift between repo directories and
# docker-compose.yml. Read-only. Exits 0 always; warnings on stdout.
# Flags:
#   - top-level dirs with a Dockerfile but no compose entry
#   - dirs whose basename matches a compose service name but have no files
#   - "stale" candidates: directories explicitly listed below but missing
#     a DECOMMISSIONED.md marker
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"

echo "=== compose-drift-check ($(date '+%Y-%m-%d %H:%M:%S %Z')) ==="
echo ""

# Pull the canonical service list from compose. One per line.
SERVICES="$(docker compose config --services 2>/dev/null | sort)"
if [ -z "$SERVICES" ]; then
  echo "docker compose config --services produced no output; is docker daemon running?"
  echo "(skipping — nothing to check)"
  exit 0
fi

echo "## compose services (live)"
echo "$SERVICES" | sed 's/^/  - /'
echo ""

# 1) Any top-level dir with a Dockerfile that is NOT a compose service?
#
# Honor an allowlist of dirs that hold Dockerfiles but are intentionally NOT
# compose services on Bob. These fall in three buckets:
#   a. Directory name differs from compose service name (voice_receptionist
#      on disk = voice-receptionist in compose).
#   b. Subsidiary/external compose stacks (telegram-*, operations).
#   c. Build artifact or dev-only containers not meant for production.
# Add new entries one per line; keep alphabetical.
KNOWN_NOT_STALE_NO_COMPOSE=(
  operations
  telegram-bob-remote
  telegram-interface
  voice_receptionist
)
echo "## Dockerfile-bearing top-level dirs not in compose"
FOUND=0
for d in */; do
  d="${d%/}"
  if [ -f "$d/Dockerfile" ]; then
    if ! printf '%s\n' "$SERVICES" | grep -qx "$d"; then
      # Skip allowlisted dirs — they are known-not-stale intentionally.
      is_allowed=0
      for allow in "${KNOWN_NOT_STALE_NO_COMPOSE[@]}"; do
        if [ "$d" = "$allow" ]; then
          is_allowed=1
          break
        fi
      done
      if [ "$is_allowed" = 1 ]; then
        echo "  OK  : $d has Dockerfile but is intentionally not in compose (allowlisted)"
      else
        echo "  WARN: $d has Dockerfile but is not in compose"
        FOUND=1
      fi
    fi
  fi
done
[ "$FOUND" = 0 ] && echo "  (no new drift)"
echo ""

# 2) Known stale directories — require DECOMMISSIONED.md marker.
echo "## stale-directory markers"
STALE_DIRS=(mission_control context-preprocessor knowledge-scanner remediator)
for d in "${STALE_DIRS[@]}"; do
  if [ -d "$d" ]; then
    if [ -f "$d/DECOMMISSIONED.md" ]; then
      echo "  OK  : $d has DECOMMISSIONED.md"
    else
      echo "  WARN: $d on disk but no DECOMMISSIONED.md marker"
    fi
  fi
done
echo ""

# 3) Count check vs CLAUDE.md and .clinerules.
COUNT="$(printf '%s\n' "$SERVICES" | wc -l | tr -d ' ')"
echo "## container count check"
echo "  compose services: $COUNT"
for f in CLAUDE.md .clinerules; do
  if [ -f "$f" ]; then
    if grep -q "18 containers" "$f" 2>/dev/null; then
      echo "  WARN: $f still says '18 containers'"
    fi
  fi
done
echo ""

echo "compose-drift-check done."
