"""Check platform connectivity and health — focused on Polymarket copy-trader."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger(__name__)


class HealthChecker:
    """Checks connectivity for Polymarket and other enabled platforms."""

    async def check_all(self) -> dict:
        """Check all platform connections."""
        results = {"platforms": {}}
        now = datetime.now(timezone.utc).isoformat()

        # Always check Polymarket (primary platform)
        results["platforms"]["polymarket"] = await self._check_polymarket(now)

        # Check notification-hub
        results["platforms"]["notification-hub"] = await self._check_notification_hub(now)

        # Check optional platforms from PLATFORMS_ENABLED
        enabled = self._get_enabled_platforms()

        if "kalshi" in enabled:
            results["platforms"]["kalshi"] = await self._check_kalshi(now)

        if "crypto" in enabled:
            results["platforms"]["crypto"] = await self._check_crypto(now)

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
                # notification-hub is accessible via host.docker.internal:8095 from polymarket-bot
                # or via redis:6379 from services on the normal Docker network
                hub_url = os.environ.get("NOTIFICATION_HUB_URL", "http://host.docker.internal:8095")
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

    async def _check_kalshi(self, now: str) -> dict:
        """Check Kalshi connectivity."""
        try:
            from src.platforms.kalshi_client import KalshiClient
            api_key = os.environ.get("KALSHI_API_KEY_ID", "")
            if not api_key:
                return {"status": "not_configured", "last_check": now, "notes": "No API key"}

            client = KalshiClient(
                api_key_id=api_key,
                private_key_path=os.environ.get("KALSHI_PRIVATE_KEY_PATH", ""),
                environment=os.environ.get("KALSHI_ENVIRONMENT", "demo"),
                dry_run=True,
            )
            connected = await client.connect()
            result = {
                "status": "connected" if connected else "disconnected",
                "last_check": now,
                "notes": "Connected" if connected else "Connection failed",
            }
            try:
                await client.close()
            except Exception:
                pass
            return result
        except ImportError:
            return {"status": "dependency_missing", "last_check": now, "notes": "KalshiClient not available"}
        except Exception as exc:
            return {"status": "error", "last_check": now, "notes": str(exc)[:80]}

    async def _check_crypto(self, now: str) -> dict:
        """Check crypto exchange connectivity."""
        try:
            from src.platforms.crypto_client import CryptoClient
            client = CryptoClient(
                exchange_id=os.environ.get("CRYPTO_EXCHANGE", "kraken"),
                api_key=os.environ.get("KRAKEN_API_KEY", ""),
                api_secret=os.environ.get("KRAKEN_API_SECRET", ""),
                dry_run=True,
            )
            connected = await client.connect()
            result = {
                "status": "connected" if connected else "disconnected",
                "last_check": now,
                "notes": "Connected" if connected else "Connection failed",
            }
            try:
                await client.close()
            except Exception:
                pass
            return result
        except ImportError:
            return {"status": "dependency_missing", "last_check": now, "notes": "CryptoClient not available"}
        except Exception as exc:
            return {"status": "error", "last_check": now, "notes": str(exc)[:80]}

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

    def _get_enabled_platforms(self) -> list[str]:
        """Read PLATFORMS_ENABLED env var."""
        platforms = os.environ.get("PLATFORMS_ENABLED", "polymarket")
        return [p.strip() for p in platforms.split(",") if p.strip()]
