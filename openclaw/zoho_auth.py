"""Zoho OAuth access token with refresh + in-memory cache."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger("openclaw.zoho_auth")

_TOKEN_LOCK = threading.Lock()
_cached_access: str = ""
_cached_expires_at: float = 0.0
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"


def get_access_token(*, force_refresh: bool = False, proactive_refresh_seconds: int = 300) -> Optional[str]:
    global _cached_access, _cached_expires_at
    refresh = (os.getenv("ZOHO_REFRESH_TOKEN") or "").strip()
    client_id = (os.getenv("ZOHO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("ZOHO_CLIENT_SECRET") or "").strip()
    if not refresh or not client_id or not client_secret:
        logger.debug("Zoho OAuth env incomplete")
        return None
    now = time.time()
    with _TOKEN_LOCK:
        if (
            not force_refresh
            and _cached_access
            and _cached_expires_at - now > proactive_refresh_seconds
        ):
            return _cached_access
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    ZOHO_TOKEN_URL,
                    data={
                        "refresh_token": refresh,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                    },
                )
            if resp.status_code != 200:
                logger.warning("Zoho token refresh failed: %s", resp.status_code)
                return None
            data = resp.json()
            access = (data.get("access_token") or "").strip()
            expires_in = float(data.get("expires_in") or 3600)
            if not access:
                return None
            _cached_access = access
            _cached_expires_at = now + max(60.0, expires_in - 30.0)
            logger.info("Zoho access token refreshed")
            return _cached_access
        except Exception as e:
            logger.warning("Zoho token error: %s", e)
            return None


def auth_header() -> dict[str, str]:
    tok = get_access_token()
    if not tok:
        return {}
    return {"Authorization": f"Zoho-oauthtoken {tok}"}
