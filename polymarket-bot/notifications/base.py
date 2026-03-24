"""Abstract notifier interface."""

from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    async def send_message(self, to: str, text: str) -> bool:
        """Send a text message."""

    @abstractmethod
    async def send_alert(self, to: str, title: str, body: str, urgency: str = "normal") -> bool:
        """Send a structured alert (trade signal, heartbeat summary, etc.)."""

    @abstractmethod
    async def send_trade_notification(self, to: str, trade: dict) -> bool:
        """Send a formatted trade execution notification."""
