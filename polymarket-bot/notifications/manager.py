"""Notification manager — routes to configured channel."""

import os

import structlog

logger = structlog.get_logger(__name__)


class NotificationManager:
    """Routes notifications to the configured channel."""

    def __init__(self):
        self.notifier = self._get_notifier()

    def _get_notifier(self):
        channel = os.environ.get("NOTIFICATION_CHANNEL", "console")
        if channel == "imessage" and os.environ.get("LINQ_API_KEY"):
            from .imessage import IMessageNotifier
            return IMessageNotifier()
        else:
            from .console import ConsoleNotifier
            return ConsoleNotifier()

    async def on_trade_executed(self, trade: dict):
        await self.notifier.send_trade_notification(trade=trade)

    async def on_heartbeat_complete(self, report: dict):
        briefing = report.get("briefing", "No briefing")
        platforms = report.get("health", {}).get("platforms", {})
        connected = sum(1 for p in platforms.values() if p.get("status") == "connected")
        total = len(platforms)
        await self.notifier.send_alert(
            title=f"Daily Briefing ({connected}/{total} platforms)",
            body=briefing,
        )

    async def on_strategy_alert(self, strategy: str, message: str, urgency: str = "normal"):
        await self.notifier.send_alert(
            title=f"Strategy Alert: {strategy}",
            body=message,
            urgency=urgency,
        )

    async def on_proposal(self, proposals: list):
        if not proposals:
            return
        text = "Parameter adjustment proposals:\n\n"
        for p in proposals:
            text += f"- {p['strategy']}: {p['proposal']}\n"
        await self.notifier.send_alert(
            title=f"{len(proposals)} Tuning Proposals",
            body=text,
        )
