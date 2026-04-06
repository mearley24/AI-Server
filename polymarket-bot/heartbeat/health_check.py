"""Check platform connectivity and health — focused on Polymarket copy-trader."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

def _local_now():
    import time as _time
    if _time.daylight and _time.localtime().tm_isdst:
        utc_offset = -_time.altzone
    else:
        utc_offset = -_time.timezone
    tz = timezone(timedelta(seconds=utc_offset))
    return datetime.now(tz)

import httpx
import structlog

logger = structlog.get_logger(__name__)


class HealthChecker:
    """Checks connectivity for Polymarket and other enabled platforms."""

    async def check_all(self) -> dict:
        """Check all platform connections."""
        results = {"platforms": {}}
        now = _local_now().isoformat()

        # Always check Polymarket (primary platform)
        results["platforms"]["polymarket"] = await self._check_polymarket(now)

        # Check notification-hub
        results["platforms"]["notification-hub"] = await self._check_notification_hub(now)

        return results

    async def _check_polymarket(self, now: str) -> dict:
        """Check Polymarket API connectivity and wallet balance."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Check CLOB API
                resp = await client.get("https://clob.polymarket.com/time")
                if resp.status_code == 200:
                    # Check wallet balance if private key is set
                    wallet = self._get_wallet_address()
                    balance_note = ""
                    if wallet:
                        try:
                            pos_resp = await client.get(
                                "https://data-api.polymarket.com/positions",
                                params={"user": wallet.lower()},
                            )
                            if pos_resp.status_code == 200:
                                positions = pos_resp.json()
                                open_pos = [p for p in positions if float(p.get("curPrice", 0)) > 0 and float(p.get("curPrice", 0)) < 1 and float(p.get("currentValue", 0)) > 0]
                                total_value = sum(float(p.get("currentValue", 0)) for p in open_pos)
                                balance_note = f"{len(open_pos)} positions, ${total_value:.2f} value"
                        except Exception:
                            balance_note = "positions check failed"

                    return {
                        "status": "connected",
                        "last_check": now,
                        "notes": balance_note or "CLOB API reachable",
                    }
                return {
                    "status": "error",
                    "last_check": now,
                    "notes": f"CLOB API returned {resp.status_code}",
                }
        except Exception as exc:
            return {
                "status": "error",
                "last_check": now,
                "error": str(exc),
                "notes": f"Error: {str(exc)[:80]}",
            }

    async def _check_notification_hub(self, now: str) -> dict:
        """Check notification-hub connectivity."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                # Default: Docker service name (same compose network as vpn when using network_mode: service:vpn)
                hub_url = os.environ.get("NOTIFICATION_HUB_URL", "http://notification-hub:8095")
                resp = await client.get(f"{hub_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    channel = data.get("channel", "unknown")
                    return {
                        "status": "connected",
                        "last_check": now,
                        "notes": f"Channel: {channel}",
                    }
                return {
                    "status": "error",
                    "last_check": now,
                    "notes": f"Hub returned {resp.status_code}",
                }
        except Exception as exc:
            return {
                "status": "unreachable",
                "last_check": now,
                "notes": f"Cannot reach notification-hub: {str(exc)[:60]}",
            }

    def _get_wallet_address(self) -> str:
        """Derive wallet address from private key."""
        pk = os.environ.get("POLY_PRIVATE_KEY", "")
        if not pk:
            return ""
        try:
            from eth_account import Account
            if not pk.startswith("0x"):
                pk = f"0x{pk}"
            return Account.from_key(pk).address
        except Exception:
            return ""

