"""Unified daily briefing v2 — Auto-17 / Wave 5-6.

Scheduled at 13:00 UTC (6:00 AM MT) via heartbeat; publishes Redis briefing:daily.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
BRIEFING_CHANNEL = "briefing:daily"


def build_briefing_payload() -> dict[str, Any]:
    """Assemble a concise briefing (<20 bullets) — placeholders for live integrations."""
    return {
        "ts": time.time(),
        "trading": {"summary": "P/L by strategy — connect portfolio:snapshot"},
        "business": {"emails": "unread count — connect Zoho", "calendar": "today"},
        "system": {"status": "green", "vpn": "unknown"},
        "intel": {"signals": "top overnight — connect intel-feeds"},
        "mission_control": os.environ.get("MISSION_CONTROL_URL", "http://127.0.0.1:8098"),
    }


def publish_daily_briefing() -> dict[str, Any]:
    payload = build_briefing_payload()
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        r.set("briefing:last", json.dumps(payload))
        r.publish(BRIEFING_CHANNEL, json.dumps(payload))
        logger.info("daily_briefing_v2 published")
    except Exception as exc:
        logger.warning("daily_briefing_v2 redis failed: %s", exc)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    publish_daily_briefing()
