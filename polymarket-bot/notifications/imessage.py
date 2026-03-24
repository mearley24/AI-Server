"""Linq API client for iMessage/RCS/SMS notifications."""

import logging
import os

import httpx

from .base import Notifier

logger = logging.getLogger(__name__)

LINQ_API_URL = "https://api.linqapp.com/api/partner/v2/chats"
LINQ_API_KEY = os.environ.get("LINQ_API_KEY", "")  # Integration token
OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "")  # Recipient iMessage number


class IMessageNotifier(Notifier):
    def __init__(self):
        self.api_key = LINQ_API_KEY
        self.default_to = OWNER_PHONE

    async def send_message(self, to: str = None, text: str = "") -> bool:
        to = to or self.default_to
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    LINQ_API_URL,
                    headers={"X-LINQ-INTEGRATION-TOKEN": self.api_key},
                    json={
                        "phone_number": to,
                        "text": text,
                    },
                    timeout=30,
                )
                if resp.status_code in (200, 201, 202):
                    logger.info("Linq message sent to %s (status %d)", to, resp.status_code)
                    return True

                # Log failure details for debugging
                logger.error(
                    "Linq API error: status=%d body=%s",
                    resp.status_code,
                    resp.text,
                )
                if resp.status_code == 401:
                    logger.error("Linq auth failed — check LINQ_API_KEY (integration token)")
                elif resp.status_code == 403:
                    logger.error("Linq forbidden — token may lack permissions")
                elif resp.status_code == 429:
                    logger.error("Linq rate limited — back off and retry later")
                return False
        except httpx.TimeoutException:
            logger.error("Linq API request timed out")
            return False
        except Exception as exc:
            logger.error("Linq API request failed: %s", exc)
            return False

    @property
    def last_error(self) -> str | None:
        """Return last error message for diagnostics."""
        return getattr(self, "_last_error", None)

    async def send_message_with_detail(self, to: str = None, text: str = "") -> tuple[bool, str]:
        """Send message and return (success, detail) for test endpoint."""
        to = to or self.default_to
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    LINQ_API_URL,
                    headers={"X-LINQ-INTEGRATION-TOKEN": self.api_key},
                    json={
                        "phone_number": to,
                        "text": text,
                    },
                    timeout=30,
                )
                if resp.status_code in (200, 201, 202):
                    return True, "sent"
                return False, f"Linq API returned {resp.status_code}: {resp.text}"
        except httpx.TimeoutException:
            return False, "Linq API request timed out"
        except Exception as exc:
            return False, f"Linq API request failed: {exc}"

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
