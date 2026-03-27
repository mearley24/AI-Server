"""iMessage notifier — publishes to Redis for notification-hub dispatch."""

import json
import logging
import os

import redis

from .base import Notifier

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
NOTIFICATION_CHANNEL = "notifications:trading"


class IMessageNotifier(Notifier):
    def __init__(self):
        self._redis = redis.from_url(REDIS_URL, decode_responses=True)

    def _publish(self, title: str, body: str, priority: str = "normal") -> bool:
        try:
            payload = json.dumps({"title": title, "body": body, "priority": priority})
            self._redis.publish(NOTIFICATION_CHANNEL, payload)
            logger.info("Published to %s: %s", NOTIFICATION_CHANNEL, title)
            return True
        except Exception as exc:
            logger.error("Redis publish failed: %s", exc)
            return False

    async def send_message(self, to: str = None, text: str = "") -> bool:
        return self._publish("Message", text)

    async def send_message_with_detail(self, to: str = None, text: str = "") -> tuple[bool, str]:
        """Send message and return (success, detail) for test endpoint."""
        ok = self._publish("Message", text)
        return (ok, "published" if ok else "Redis publish failed")

    async def send_alert(self, to: str = None, title: str = "", body: str = "", urgency: str = "normal") -> bool:
        emoji = {"critical": "\U0001f6a8", "high": "\u26a0\ufe0f", "normal": "\U0001f4ca", "low": "\u2139\ufe0f"}
        prefix = emoji.get(urgency, "\U0001f4ca")
        return self._publish(f"{prefix} {title}", body, priority=urgency)

    async def send_trade_notification(self, to: str = None, trade: dict = None) -> bool:
        trade = trade or {}
        platform = trade.get("platform", "unknown")
        strategy = trade.get("strategy", "unknown")
        side = trade.get("side", "unknown")
        market = trade.get("market_id", "unknown")
        size = trade.get("size", 0)
        price = trade.get("price", 0)
        pnl = trade.get("pnl")
        category = trade.get("category", "")
        thesis = trade.get("thesis", "")

        text = f"Platform: {platform}\n"
        text += f"Strategy: {strategy}\n"
        text += f"Action: {side.upper()}\n"
        text += f"Market: {market}\n"
        text += f"Size: ${size:.2f} @ {price}\n"
        if pnl is not None:
            text += f"P&L: ${pnl:+.2f}\n"
        if category:
            text += f"Category: {category}\n"
        if thesis:
            text += f"Thesis: {thesis[:80]}\n"

        return self._publish("\U0001f4b0 Trade Executed", text)
