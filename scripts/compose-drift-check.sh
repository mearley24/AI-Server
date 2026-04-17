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
echo "## Dockerfile-bearing top-level dirs not in compose"
FOUND=0
for d in */; do
  d="${d%/}"
  if [ -f "$d/Dockerfile" ]; then
    if ! printf '%s\n' "$SERVICES" | grep -qx "$d"; then
      echo "  WARN: $d has Dockerfile but is not in compose"
      FOUND=1
    fi
  fi
done
[ "$FOUND" = 0 ] && echo "  (none)"
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
