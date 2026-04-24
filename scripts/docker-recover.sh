#!/bin/bash
set -e

echo "=== Docker status ==="
docker ps >/dev/null 2>&1 && {
  echo "Docker engine OK"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  exit 0
}

echo "Docker engine not responding. Restarting Docker Desktop cleanly..."

osascript -e 'quit app "Docker"' 2>/dev/null || true
sleep 10

pkill -f "Docker Desktop" 2>/dev/null || true
pkill -f "com.docker.backend" 2>/dev/null || true
pkill -f "vpnkit" 2>/dev/null || true

sleep 5
open -a Docker

echo "Waiting for Docker engine..."
for i in {1..60}; do
  if docker ps >/dev/null 2>&1; then
    echo "Docker recovered."
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    exit 0
  fi
  sleep 5
done

echo "Docker did not recover after 5 minutes."
exit 1
