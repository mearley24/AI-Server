"""Check platform connectivity and health."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


class HealthChecker:
    """Checks connectivity and balance for all enabled trading platforms."""

    async def check_all(self) -> dict:
        """Check all platform connections.

        Returns a dict with a 'platforms' key mapping platform names to status dicts.
        """
        results = {"platforms": {}}

        for platform_name in self._get_enabled_platforms():
            try:
                client = self._get_platform_client(platform_name)
                if client is None:
                    results["platforms"][platform_name] = {
                        "status": "not_installed",
                        "last_check": datetime.now(timezone.utc).isoformat(),
                        "notes": f"Platform client for '{platform_name}' not available",
                    }
                    continue

                connected = await client.connect()
                balance = await client.get_balance() if connected else {}
                results["platforms"][platform_name] = {
                    "status": "connected" if connected else "disconnected",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "balance": balance,
                    "dry_run": client.is_dry_run,
                    "notes": f"Balance: ${balance.get('total', 0):.2f}" if balance else "",
                }
            except Exception as e:
                logger.error("health_check_error", platform=platform_name, error=str(e))
                results["platforms"][platform_name] = {
                    "status": "error",
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                    "notes": f"Error: {str(e)[:50]}",
                }

        return results

    def _get_enabled_platforms(self) -> list[str]:
        """Read PLATFORMS_ENABLED env var to determine which platforms to check."""
        platforms = os.environ.get("PLATFORMS_ENABLED", "kalshi,crypto")
        return [p.strip() for p in platforms.split(",") if p.strip()]

    def _get_platform_client(self, name: str):
        """Import and return the appropriate platform client instance.

        Returns None if the platform client cannot be imported.
        """
        platform_map = {
            "kalshi": ("src.platforms.kalshi_client", "KalshiClient"),
            "crypto": ("src.platforms.crypto_client", "CryptoClient"),
            "polymarket": ("src.platforms.polymarket_client", "PolymarketPlatformClient"),
        }

        if name not in platform_map:
            logger.warning("unknown_platform", platform=name)
            return None

        module_path, class_name = platform_map[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            return cls()
        except (ImportError, AttributeError, Exception) as e:
            logger.warning("platform_import_error", platform=name, error=str(e))
            return None
