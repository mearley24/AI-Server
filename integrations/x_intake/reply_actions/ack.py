"""
Outbound ACK helper — Phase 5.

Single entry point for all reply ACKs.  In dry-run mode (default):
  - Appends a JSON line to data/x_intake/reply_acks.ndjson.
  - Stores the last _RING_SIZE ACKs in an in-memory ring buffer.
  - Returns a stub success dict.

In live mode (CORTEX_REPLY_DRY_RUN=0, ALLOWED_TEST_RECIPIENTS set):
  1. Validates the thread_guid against ALLOWED_TEST_RECIPIENTS.
  2. Tries Cortex → /api/bluebubbles/send (BlueBubbles native path).
  3. If that fails, falls back to the iMessage bridge at IMESSAGE_BRIDGE_URL
     (:8199, AppleScript path — works on macOS 26 when BlueBubbles apple-script hangs).

Flipping to live is a [NEEDS_MATT] + [BOB_CLINE_ONLY] step.
"""
from __future__ import annotations

import json
import logging
import os
import re
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

# iMessage bridge fallback — AppleScript path that works when BlueBubbles hangs.
_IMESSAGE_BRIDGE_URL = os.environ.get(
    "IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199"
).rstrip("/")
_BRIDGE_TIMEOUT = 15  # seconds — bridge uses osascript with 10s per attempt


def _phone_from_thread_guid(thread_guid: str) -> str:
    """Extract E.164 phone from 'iMessage;-;+18609171850' → '+18609171850'.

    Returns empty string if the GUID doesn't contain a phone number.
    """
    m = re.search(r"(\+?1?\d{10,15})$", thread_guid)
    return m.group(1) if m else ""


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
            logger.debug("ack_log_write_failed error=%s", str(exc)[:100])
        logger.info("ack_dry_run thread=%s text=%s", thread_guid[:40], text[:80])
        return {"ok": True, "dry_run": True}

    # Live mode — validate recipient before sending.
    if _ALLOWED_RECIPIENTS and thread_guid not in _ALLOWED_RECIPIENTS:
        logger.warning("ack_blocked_not_allowlisted thread=%s", thread_guid[:40])
        return {"ok": False, "dry_run": False, "error": "recipient_not_allowlisted"}

    import httpx

    # ── Path 1: Cortex → BlueBubbles native API ───────────────────────────────
    cortex_url = os.environ.get("CORTEX_URL", "http://cortex:8102").rstrip("/")
    cortex_error: str = ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(
                f"{cortex_url}/api/bluebubbles/send",
                json={"chat_guid": thread_guid, "body": text},
            )
        result = resp.json()
        if result.get("ok"):
            logger.info("ack_sent path=bluebubbles thread=%s", thread_guid[:40])
            return {"ok": True, "dry_run": False, "path": "bluebubbles"}
        cortex_error = str(result.get("error", "unknown"))
        logger.warning("ack_bluebubbles_failed error=%s — trying bridge", cortex_error[:100])
    except Exception as exc:
        cortex_error = str(exc)[:100]
        logger.warning("ack_bluebubbles_exception error=%s — trying bridge", cortex_error)

    # ── Path 2: iMessage bridge fallback (AppleScript via host :8199) ─────────
    phone = _phone_from_thread_guid(thread_guid)
    if not phone:
        logger.warning("ack_no_phone_in_guid guid=%s", thread_guid[:60])
        return {
            "ok": False, "dry_run": False,
            "error": f"bluebubbles failed ({cortex_error}) and cannot extract phone from GUID",
        }

    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as c:
            resp = await c.post(
                _IMESSAGE_BRIDGE_URL,
                json={"phone": phone, "body": text},
            )
        if resp.status_code == 200:
            logger.info("ack_sent path=imessage_bridge phone=%s", phone[-4:])
            return {"ok": True, "dry_run": False, "path": "imessage_bridge"}
        bridge_err = resp.text[:200]
        logger.warning("ack_bridge_failed status=%s error=%s", resp.status_code, bridge_err[:80])
        return {"ok": False, "dry_run": False, "error": f"bridge HTTP {resp.status_code}: {bridge_err}"}
    except Exception as exc:
        logger.warning("ack_bridge_exception error=%s", str(exc)[:100])
        return {
            "ok": False, "dry_run": False,
            "error": f"both paths failed — bluebubbles: {cortex_error}; bridge: {exc!s:.80}",
        }
