"""Hermes multi-platform routing (API-6) — channel resolution + Zoho drafts."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_ACCOUNTS_URL = "https://mail.zoho.com/api/accounts"

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


class NotificationRequest(BaseModel):
    recipient: str = Field(..., description="Phone, email, or client: alias")
    message: str
    channel: str = Field("auto", pattern="^(auto|imessage|email|telegram|both)$")
    priority: str = Field("normal", pattern="^(normal|high|urgent)$")
    message_type: str = Field(
        "general",
        description="alert|trade|client_comm|system_log|general",
    )
    subject: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] | None = None


def resolve_channel(req: NotificationRequest) -> list[str]:
    """Return ordered channel list: imessage, email, telegram, or combinations."""
    ch = (req.channel or "auto").lower()
    if ch == "imessage":
        return ["imessage"]
    if ch == "email":
        return ["email"]
    if ch == "telegram":
        return ["telegram"]
    if ch == "both":
        return ["imessage", "email"]

    mt = (req.message_type or "general").lower()
    pr = (req.priority or "normal").lower()
    rc = (req.recipient or "").strip()

    if mt == "system_log":
        return ["telegram"]

    if pr == "urgent":
        return ["imessage", "email"]

    if rc.lower().startswith("client:"):
        return ["email"]

    if mt in {"alert", "trade"} and pr in {"high", "urgent"}:
        return ["imessage"]

    if "matt" in rc.lower():
        return ["imessage"]

    return ["imessage"]


async def get_zoho_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < float(_token_cache["expires_at"]) - 60:
        return str(_token_cache["token"])

    refresh = os.environ.get("ZOHO_REFRESH_TOKEN", "")
    client_id = os.environ.get("ZOHO_CLIENT_ID", "")
    client_secret = os.environ.get("ZOHO_CLIENT_SECRET", "")
    if not all([refresh, client_id, client_secret]):
        raise RuntimeError("ZOHO_REFRESH_TOKEN, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET required for email")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            ZOHO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    token = data["access_token"]
    expires_in = float(data.get("expires_in", 3600))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


async def get_zoho_account_id(token: str) -> str:
    aid = os.environ.get("ZOHO_MAIL_ACCOUNT_ID", "") or os.environ.get("ZOHO_ACCOUNT_ID", "")
    if aid:
        return aid
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            ZOHO_ACCOUNTS_URL,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["data"][0]["accountId"])


async def send_zoho_draft(to_addr: str, subject: str, body_text: str) -> str:
    """Create Zoho Mail draft (does not send)."""
    token = await get_zoho_access_token()
    account_id = await get_zoho_account_id(token)
    from_address = os.environ.get("SYMPHONY_EMAIL", "info@symphonysh.com")
    draft_url = f"https://mail.zoho.com/api/accounts/{account_id}/messages"
    html = body_text.replace("\n", "<br/>")
    payload = {
        "fromAddress": from_address,
        "toAddress": to_addr,
        "ccAddress": "",
        "subject": subject,
        "content": html,
        "mode": "draft",
        "mailFormat": "html",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            draft_url,
            headers={
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
    logger.info("hermes zoho draft created to=%s subject=%s", to_addr[:40], subject[:60])
    return "email_draft"


async def send_telegram_text(text: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not token or not chat:
        logger.warning("telegram not configured — stub only")
        return "telegram_skipped"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(url, json={"chat_id": chat, "text": text[:4000]})
        if r.status_code != 200:
            logger.warning("telegram send failed: %s %s", r.status_code, r.text[:200])
            return "telegram_failed"
    return "telegram"


def normalize_email_recipient(recipient: str) -> str:
    r = recipient.strip()
    if r.lower().startswith("client:"):
        return r.split(":", 1)[1].strip()
    return r
