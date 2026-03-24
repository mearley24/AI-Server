"""Fallback notifier that logs to stdout."""

import logging

from .base import Notifier

log = logging.getLogger(__name__)


class ConsoleNotifier(Notifier):
    async def send_message(self, to: str = None, text: str = "") -> bool:
        log.info("[NOTIFY] to=%s: %s", to or "default", text)
        return True

    async def send_alert(self, to: str = None, title: str = "", body: str = "", urgency: str = "normal") -> bool:
        log.info("[ALERT:%s] %s — %s", urgency.upper(), title, body)
        return True

    async def send_trade_notification(self, to: str = None, trade: dict = None) -> bool:
        trade = trade or {}
        log.info(
            "[TRADE] %s %s on %s via %s — $%.2f @ %s",
            trade.get("side", "?"),
            trade.get("market_id", "?"),
            trade.get("platform", "?"),
            trade.get("strategy", "?"),
            trade.get("size", 0),
            trade.get("price", "?"),
        )
        return True
