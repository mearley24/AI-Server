"""
Outbound ACK helper — Phase 5.

Single entry point for all reply ACKs.  In dry-run mode (default):
  - Appends a JSON line to data/x_intake/reply_acks.ndjson.
  - Stores the last _RING_SIZE ACKs in an in-memory ring buffer.
  - Returns a stub success dict.

In live mode (CORTEX_REPLY_DRY_RUN=0, ALLOWED_TEST_RECIPIENTS set):
  - Validates the thread_guid against ALLOWED_TEST_RECIPIENTS.
  - Calls cortex.bluebubbles.BlueBubblesClient().send_text().

Flipping to live is a [NEEDS_MATT] + [BOB_CLINE_ONLY] step.
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict

logger = logging.getLogger(__name__)

_DRY_RUN_ENV = os.environ.get("CORTEX_REPLY_DRY_RUN", "1")
_DRY_RUN_DEFAULT = _DRY_RUN_ENV.strip() not in ("0", "false", "no")

_ALLOWED_RECIPIENTS_RAW = os.environ.get("ALLOWED_TEST_RECIPIENTS", "")
_ALLOWED_RECIPIENTS = frozenset(
    r.strip() for r in _ALLOWED_RECIPIENTS_RAW.split(",") if r.strip()
)

_ACK_LOG_PATH = Path(os.environ.get("X_INTAKE_DATA_DIR", "/data/x_intake")) / "reply_acks.ndjson"

_RING_SIZE = 50
_ring: Deque[Dict[str, Any]] = deque(maxlen=_RING_SIZE)


def get_ring() -> list:
    """Return a snapshot of the in-memory ACK ring buffer (for tests)."""
    return list(_ring)


async def send_ack(
    thread_guid: str,
    text: str,
    *,
    dry_run: bool = _DRY_RUN_DEFAULT,
) -> Dict[str, Any]:
    """Send or stub an outbound ACK.

    Always returns a dict with 'ok', 'dry_run', and optional 'error'.
    Never raises — caller should not crash on ACK failure.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_guid": thread_guid,
        "text": text,
        "dry_run": dry_run,
    }

    if dry_run:
        _ring.append(entry)
        try:
            _ACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ACK_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("ack_log_write_failed", error=str(exc)[:100])
        logger.info("ack_dry_run", thread=thread_guid[:40], text=text[:80])
        return {"ok": True, "dry_run": True}

    # Live mode — validate recipient before sending.
    if _ALLOWED_RECIPIENTS and thread_guid not in _ALLOWED_RECIPIENTS:
        logger.warning("ack_blocked_not_allowlisted", thread=thread_guid[:40])
        return {"ok": False, "dry_run": False, "error": "recipient_not_allowlisted"}

    try:
        from cortex.bluebubbles import BlueBubblesClient
        client = BlueBubblesClient()
        if not client.configured:
            logger.warning("ack_bluebubbles_not_configured")
            return {"ok": False, "dry_run": False, "error": "not_configured"}
        result = await client.send_text(chat_guid=thread_guid, body=text)
        if not result.get("ok"):
            logger.warning("ack_send_failed", error=str(result)[:100])
            return {"ok": False, "dry_run": False, "error": str(result.get("error", "unknown"))}
        logger.info("ack_sent", thread=thread_guid[:40])
        return {"ok": True, "dry_run": False}
    except Exception as exc:
        logger.warning("ack_exception", error=str(exc)[:100])
        return {"ok": False, "dry_run": False, "error": str(exc)[:100]}
