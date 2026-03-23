"""Check platform connectivity and health."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)

# Platform client imports — guarded so a missing dependency doesn't crash the
# entire health checker.  We track import errors per-platform.
_PLATFORM_CLASSES: dict[str, type] = {}
_IMPORT_ERRORS: dict[str, str] = {}

try:
    from src.platforms.kalshi_client import KalshiClient
    _PLATFORM_CLASSES["kalshi"] = KalshiClient
except ImportError as exc:
    _IMPORT_ERRORS["kalshi"] = str(exc)

try:
    from src.platforms.crypto_client import CryptoClient
    _PLATFORM_CLASSES["crypto"] = CryptoClient
except ImportError as exc:
    _IMPORT_ERRORS["crypto"] = str(exc)

try:
    from src.platforms.polymarket_client import PolymarketPlatformClient
    _PLATFORM_CLASSES["polymarket"] = PolymarketPlatformClient
except ImportError as exc:
    _IMPORT_ERRORS["polymarket"] = str(exc)


def _build_kalshi_client():
    """Build a KalshiClient from environment variables."""
    api_key_id = os.environ.get("KALSHI_API_KEY_ID", "")
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    environment = os.environ.get("KALSHI_ENVIRONMENT", "demo")
    dry_run = os.environ.get("KALSHI_DRY_RUN", "true").lower() in ("true", "1", "yes")

    if not api_key_id or not private_key_path:
        return None, "KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH not set"

    return KalshiClient(
        api_key_id=api_key_id,
        private_key_path=private_key_path,
        environment=environment,
        dry_run=dry_run,
    ), None


def _build_crypto_client():
    """Build a CryptoClient from environment variables."""
    exchange_id = os.environ.get("CRYPTO_EXCHANGE", "kraken")
    api_key = os.environ.get("KRAKEN_API_KEY", "")
    api_secret = os.environ.get("KRAKEN_API_SECRET", "")
    dry_run = os.environ.get("KRAKEN_DRY_RUN", "true").lower() in ("true", "1", "yes")

    return CryptoClient(
        exchange_id=exchange_id,
        api_key=api_key,
        api_secret=api_secret,
        dry_run=dry_run,
    ), None


# Map platform name → builder function
_CLIENT_BUILDERS: dict[str, callable] = {
    "kalshi": _build_kalshi_client,
    "crypto": _build_crypto_client,
}


class HealthChecker:
    """Checks connectivity and balance for all enabled trading platforms."""

    async def check_all(self) -> dict:
        """Check all platform connections.

        Returns a dict with a 'platforms' key mapping platform names to status dicts.
        """
        results = {"platforms": {}}

        for platform_name in self._get_enabled_platforms():
            now = datetime.now(timezone.utc).isoformat()

            # 1. Check if the platform module could even be imported
            if platform_name in _IMPORT_ERRORS:
                results["platforms"][platform_name] = {
                    "status": "dependency_missing",
                    "last_check": now,
                    "error": _IMPORT_ERRORS[platform_name],
                    "notes": f"Missing dependency: {_IMPORT_ERRORS[platform_name]}",
                }
                continue

            # 2. Try to build the client from env vars
            builder = _CLIENT_BUILDERS.get(platform_name)
            if builder is None:
                results["platforms"][platform_name] = {
                    "status": "no_health_check",
                    "last_check": now,
                    "notes": f"No standalone health check for '{platform_name}'",
                }
                continue

            try:
                client, build_error = builder()
                if client is None:
                    results["platforms"][platform_name] = {
                        "status": "not_configured",
                        "last_check": now,
                        "notes": build_error or "Client could not be constructed",
                    }
                    continue

                connected = await client.connect()
                balance = await client.get_balance() if connected else {}
                results["platforms"][platform_name] = {
                    "status": "connected" if connected else "disconnected",
                    "last_check": now,
                    "balance": balance,
                    "dry_run": client.is_dry_run,
                    "notes": f"Balance: ${balance.get('balance', 0):.2f}" if balance else "",
                }

                # Clean up
                if hasattr(client, "close"):
                    try:
                        await client.close()
                    except Exception:
                        pass

            except Exception as e:
                logger.error("health_check_error", platform=platform_name, error=str(e))
                results["platforms"][platform_name] = {
                    "status": "error",
                    "last_check": now,
                    "error": str(e),
                    "notes": f"Error: {str(e)[:80]}",
                }

        return results

    def _get_enabled_platforms(self) -> list[str]:
        """Read PLATFORMS_ENABLED env var to determine which platforms to check."""
        platforms = os.environ.get("PLATFORMS_ENABLED", "kalshi,crypto")
        return [p.strip() for p in platforms.split(",") if p.strip()]
