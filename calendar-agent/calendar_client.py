"""Zoho Calendar API client using OAuth2 refresh token flow."""

import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ZOHO_BASE_URL = "https://calendar.zoho.com/api/v1"
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"


class ZohoCalendarClient:
    def __init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.calendar_uid = os.getenv("ZOHO_CALENDAR_UID", "")
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    @property
    def configured(self) -> bool:
        return all([self.client_id, self.client_secret, self.refresh_token, self.calendar_uid])

    async def _refresh_access_token(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(ZOHO_TOKEN_URL, params={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
            return self._access_token

    async def _get_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expiry:
            return await self._refresh_access_token()
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        token = await self._get_token()
        url = f"{ZOHO_BASE_URL}/calendars/{self.calendar_uid}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, headers={
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            }, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def list_events(self, start: str, end: str) -> list:
        """Fetch events in a date range.

        Zoho Calendar API v1 expects the range as a JSON object with dates in
        ``yyyyMMdd`` or ``yyyyMMddTHHmmssZ`` format — NOT ISO-8601 with colons
        and timezone offsets.  We convert the incoming ISO strings accordingly.
        """
        import json as _json

        zoho_start = self._to_zoho_date(start)
        zoho_end = self._to_zoho_date(end)
        range_param = _json.dumps({"start": zoho_start, "end": zoho_end})

        try:
            data = await self._request(
                "GET", "/events", params={"range": range_param},
            )
            return data.get("events", [])
        except httpx.HTTPStatusError as exc:
            logger.error(
                "zoho_events_error status=%d body=%s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            return []
        except Exception as exc:
            logger.error("zoho_events_unexpected_error: %s", exc)
            return []

    @staticmethod
    def _to_zoho_date(iso_str: str) -> str:
        """Convert an ISO-8601 datetime string to Zoho's ``yyyyMMddTHHmmssZ`` format.

        Accepts formats like ``2026-03-24T00:00:00+00:00``, ``2026-03-24T12:30:00``,
        or ``2026-03-24T12:30:00.123456`` (microseconds stripped).
        Returns ``20260324T000000Z`` style strings that Zoho expects.

        Zoho rejects decimal seconds (e.g. ``T073439.123456Z``) with
        "PATTERN_NOT_MATCHED" — always truncate before the dot.
        """
        # Strip timezone suffix (±HH:MM or Z) — Zoho always uses trailing 'Z'
        clean = iso_str.replace("+00:00", "").replace("Z", "")
        # Strip microseconds / sub-seconds (e.g. ".123456") — Zoho rejects them
        if "." in clean:
            clean = clean.split(".")[0]
        # Remove dashes and colons: 2026-03-24T00:00:00 → 20260324T000000
        clean = clean.replace("-", "").replace(":", "")
        if "T" not in clean:
            return clean  # Already yyyyMMdd
        return clean + "Z"

    async def create_event(self, event_data: dict) -> dict:
        return await self._request("POST", "/events", json={"eventdata": event_data})

    async def update_event(self, event_uid: str, event_data: dict) -> dict:
        return await self._request("PUT", f"/events/{event_uid}", json={"eventdata": event_data})

    async def delete_event(self, event_uid: str) -> dict:
        return await self._request("DELETE", f"/events/{event_uid}")
