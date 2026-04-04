"""Redis pub/sub plus durable events:log list for Mission Control and silent-service checks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("openclaw.event_bus")

LOG_KEY = "events:log"
MAX_LOG_ENTRIES = 1000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def publish_and_log(redis_url: str, channel: str, payload: dict[str, Any]) -> None:
    """PUBLISH to channel and LPUSH JSON audit line to events:log (+ LTRIM)."""
    import redis as redis_sync

    r = redis_sync.from_url(redis_url, decode_responses=True)
    try:
        body = json.dumps(payload, default=str)
        r.publish(channel, body)
        entry = json.dumps(
            {"ts": _utc_now_iso(), "channel": channel, "payload": payload},
            default=str,
        )
        r.lpush(LOG_KEY, entry)
        r.ltrim(LOG_KEY, 0, MAX_LOG_ENTRIES - 1)
    except Exception as e:
        logger.debug("event_bus publish_and_log: %s", e)
    finally:
        r.close()


def log_only(redis_url: str, entry: dict[str, Any]) -> None:
    """Append-only audit (heartbeat, no pub/sub)."""
    import redis as redis_sync

    r = redis_sync.from_url(redis_url, decode_responses=True)
    try:
        payload = dict(entry)
        payload.setdefault("ts", _utc_now_iso())
        line = json.dumps(payload, default=str)
        r.lpush(LOG_KEY, line)
        r.ltrim(LOG_KEY, 0, MAX_LOG_ENTRIES - 1)
    except Exception as e:
        logger.debug("event_bus log_only: %s", e)
    finally:
        r.close()
