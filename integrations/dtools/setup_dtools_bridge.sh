#!/bin/bash
# =============================================================================
# D-Tools Cloud Bridge — Setup Script
# Run on Bob (Mac Mini M4) to deploy the D-Tools bridge service
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║  D-Tools Cloud Bridge — Setup            ║"
echo "║  Symphony Smart Homes                    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check for .env
if [ ! -f .env ]; then
    echo "⚠  No .env found. Creating from template..."
    cp .env.example .env
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ACTION REQUIRED: Add your D-Tools API key"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1. Log into D-Tools Cloud"
    echo "  2. Go to Settings → Integration → Developer → API Keys"
    echo "  3. Click 'Create API Key'"
    echo "  4. Copy the key and paste it here:"
    echo ""
    read -p "  D-Tools API Key: " API_KEY
    if [ -n "$API_KEY" ]; then
        sed -i.bak "s/your-api-key-here/$API_KEY/" .env
        rm -f .env.bak
        echo "  ✓ API key saved to .env"
    else
        echo "  ✗ No key entered. Edit .env manually: nano .env"
        exit 1
    fi
fi

echo ""
echo "→ Creating Docker network (if needed)..."
docker network create symphony 2>/dev/null || true

echo "→ Building D-Tools bridge container..."
docker-compose -f docker-compose.dtools.yml build

echo "→ Starting D-Tools bridge..."
docker-compose -f docker-compose.dtools.yml up -d

echo ""
echo "→ Waiting for service to start..."
sleep 3

echo "→ Health check..."
if curl -sf http://localhost:5050/health > /dev/null 2>&1; then
    echo "  ✓ D-Tools bridge is ONLINE at http://localhost:5050"
    echo ""
    echo "  Quick test commands:"
    echo "    curl http://localhost:5050/snapshot"
    echo "    curl http://localhost:5050/opportunities"
    echo "    curl http://localhost:5050/projects"
    echo "    curl http://localhost:5050/clients"
    echo "    curl 'http://localhost:5050/catalog?q=sonos'"
    echo ""
    echo "  ✓ Bob can now access D-Tools data!"
else
    echo "  ⚠ Service may still be starting. Check with:"
    echo "    docker logs dtools_bridge"
fi

echo ""
echo "Done."
