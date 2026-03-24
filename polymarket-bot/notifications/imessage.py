"""Linq API client for iMessage/RCS/SMS notifications."""

import os

import httpx

from .base import Notifier

LINQ_API_BASE = os.environ.get("LINQ_API_URL", "https://api.linqapp.com/v1")
LINQ_API_KEY = os.environ.get("LINQ_API_KEY", "")
LINQ_PHONE_NUMBER = os.environ.get("LINQ_PHONE_NUMBER", "")  # Bob's Linq number
OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "")  # Your iMessage number


class IMessageNotifier(Notifier):
    def __init__(self):
        self.api_key = LINQ_API_KEY
        self.from_number = LINQ_PHONE_NUMBER
        self.default_to = OWNER_PHONE

    async def send_message(self, to: str = None, text: str = "") -> bool:
        to = to or self.default_to
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{LINQ_API_BASE}/messages",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.from_number,
                    "to": to,
                    "body": text,
                },
                timeout=30,
            )
            return resp.status_code in (200, 201, 202)

    async def send_alert(self, to: str = None, title: str = "", body: str = "", urgency: str = "normal") -> bool:
        emoji = {"critical": "\U0001f6a8", "high": "\u26a0\ufe0f", "normal": "\U0001f4ca", "low": "\u2139\ufe0f"}
        prefix = emoji.get(urgency, "\U0001f4ca")
        text = f"{prefix} {title}\n\n{body}"
        return await self.send_message(to, text)

    async def send_trade_notification(self, to: str = None, trade: dict = None) -> bool:
        trade = trade or {}
        platform = trade.get("platform", "unknown")
        strategy = trade.get("strategy", "unknown")
        side = trade.get("side", "unknown")
        market = trade.get("market_id", "unknown")
        size = trade.get("size", 0)
        price = trade.get("price", 0)
        pnl = trade.get("pnl")

        text = "\U0001f4b0 Trade Executed\n"
        text += f"Platform: {platform}\n"
        text += f"Strategy: {strategy}\n"
        text += f"Action: {side.upper()}\n"
        text += f"Market: {market}\n"
        text += f"Size: ${size:.2f} @ {price}\n"
        if pnl is not None:
            text += f"P&L: ${pnl:+.2f}\n"

        return await self.send_message(to, text)
