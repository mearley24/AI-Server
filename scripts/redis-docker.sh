#!/usr/bin/env bash
# Run redis-cli against the Docker redis service (no local redis-cli install needed).
# Usage: ./scripts/redis-docker.sh PING
#        ./scripts/redis-docker.sh LRANGE events:log 0 5
set -euo pipefail
if docker exec redis redis-cli "$@" 2>/dev/null; then
  exit 0
fi
if command -v redis-cli >/dev/null 2>&1; then
  exec redis-cli "$@"
fi
echo "Neither 'docker exec redis redis-cli' nor host redis-cli worked." >&2
echo "Start Redis: docker compose up -d redis" >&2
echo "Or install CLI: brew install redis" >&2
exit 1
