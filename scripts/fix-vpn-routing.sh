#!/bin/bash
set -e

WG_CONF="polymarket-bot/vpn/wg0.conf"

if [ ! -f "$WG_CONF" ]; then
    echo "ERROR: $WG_CONF not found. Run from AI-Server root."
    exit 1
fi

ROUTE_CMD="PostUp = ip route add 172.16.0.0/12 via \$(ip route show default dev eth0 | awk '{print \$3}') dev eth0; ip route add 192.168.65.0/24 via \$(ip route show default dev eth0 | awk '{print \$3}') dev eth0"

if grep -q "172.16.0.0/12" "$WG_CONF"; then
    echo "VPN routing fix already applied."
    exit 0
fi

if grep -q "PostUp" "$WG_CONF"; then
    sed -i.bak "/PostUp/a\\
$ROUTE_CMD" "$WG_CONF"
    echo "Added Docker route exclusion after existing PostUp."
else
    sed -i.bak "/\[Interface\]/a\\
$ROUTE_CMD" "$WG_CONF"
    echo "Added Docker route exclusion to [Interface] section."
fi

echo ""
echo "Done. Now restart the VPN:"
echo "  /usr/local/bin/docker compose up -d --force-recreate vpn polymarket-bot"
echo ""
echo "Verify with:"
echo "  /usr/local/bin/docker exec polymarket-bot python3 -c \"import redis; r=redis.from_url('redis://host.docker.internal:6379', socket_timeout=2); r.ping(); print('Redis OK')\""
