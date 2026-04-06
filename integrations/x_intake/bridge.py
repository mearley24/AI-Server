"""
Thin Redis bridge for X intake — same publish path as `pipeline.py`.

Use this module when tests or callers need `from integrations.x_intake.bridge import XIntakeBridge`.
Publishing after each analyzed post uses `REDIS_CHANNEL_OUT` (default `notification-hub`).
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from integrations.x_intake.pipeline import (
        REDIS_CHANNEL_OUT,
        publish_to_redis,
        _get_redis,
    )
except ImportError:
    from pipeline import (
        REDIS_CHANNEL_OUT,
        publish_to_redis,
        _get_redis,
    )

get_redis_client = _get_redis


class XIntakeBridge:
    """Publishes X intake payloads to Redis on the notification-hub channel."""

    def __init__(self, channel_out: Optional[str] = None) -> None:
        self._channel = channel_out or REDIS_CHANNEL_OUT
        self._client: Any = None

    def connect(self) -> bool:
        """Initialize Redis client (same host/port as the pipeline daemon)."""
        try:
            self._client = get_redis_client()
            return True
        except Exception:
            self._client = None
            return False

    def publish(self, payload: dict[str, Any]) -> bool:
        """Publish a JSON-serializable dict to the configured channel."""
        if self._client is None and not self.connect():
            return False
        publish_to_redis(self._client, self._channel, payload)
        return True
