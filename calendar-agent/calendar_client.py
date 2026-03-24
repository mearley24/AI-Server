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
        import json as _json
        range_param = _json.dumps({"start": start, "end": end})
        data = await self._request("GET", "/events", params={"range": range_param})
        return data.get("events", [])

    async def create_event(self, event_data: dict) -> dict:
        return await self._request("POST", "/events", json={"eventdata": event_data})

    async def update_event(self, event_uid: str, event_data: dict) -> dict:
        return await self._request("PUT", f"/events/{event_uid}", json={"eventdata": event_data})

    async def delete_event(self, event_uid: str) -> dict:
        return await self._request("DELETE", f"/events/{event_uid}")
