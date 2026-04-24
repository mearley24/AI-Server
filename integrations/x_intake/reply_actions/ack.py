"""
Outbound ACK helper — Phase 5, receipt-layer upgrade.

Every reply action now writes a durable receipt to:
  /data/x_intake/reply_receipts.ndjson

This covers all outcomes:
  - dry-run success
  - live send success (via Cortex/BlueBubbles or iMessage bridge)
  - live send failure
  - allowlist block
  - fallback path used

Old /data/x_intake/reply_acks.ndjson is still written for backward
compatibility (dry-run only) but reply_receipts.ndjson is the
authoritative source going forward.

Flipping to live (CORTEX_REPLY_DRY_RUN=0 + ALLOWED_TEST_RECIPIENTS set)
is a [NEEDS_MATT] + [BOB_CLINE_ONLY] step.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger(__name__)

_DRY_RUN_ENV = os.environ.get("CORTEX_REPLY_DRY_RUN", "1")
_DRY_RUN_DEFAULT = _DRY_RUN_ENV.strip() not in ("0", "false", "no")

_ALLOWED_RECIPIENTS_RAW = os.environ.get("ALLOWED_TEST_RECIPIENTS", "")
_ALLOWED_RECIPIENTS = frozenset(
    r.strip() for r in _ALLOWED_RECIPIENTS_RAW.split(",") if r.strip()
)

_DATA_DIR = Path(os.environ.get("X_INTAKE_DATA_DIR", "/data/x_intake"))
_ACK_LOG_PATH     = _DATA_DIR / "reply_acks.ndjson"      # legacy — dry-run only
_RECEIPT_LOG_PATH = _DATA_DIR / "reply_receipts.ndjson"  # authoritative

_RING_SIZE = 50
_ring: Deque[Dict[str, Any]] = deque(maxlen=_RING_SIZE)

_IMESSAGE_BRIDGE_URL = os.environ.get(
    "IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199"
).rstrip("/")
_BRIDGE_TIMEOUT = 15


def _phone_from_thread_guid(thread_guid: str) -> str:
    """Extract E.164 phone from 'iMessage;-;+18609171850' → '+18609171850'."""
    m = re.search(r"(\+?1?\d{10,15})$", thread_guid)
    return m.group(1) if m else ""


def _redact_phone(phone: str) -> str:
    """Return last-4 digits only: '+18609171850' → '...1850'."""
    return f"...{phone[-4:]}" if len(phone) >= 4 else "...????"


def _recipient_hash(thread_guid: str) -> str:
    """One-way hash of the thread_guid for analytics without exposing number."""
    return hashlib.sha256(thread_guid.encode()).hexdigest()[:12]


def _write_receipt(receipt: Dict[str, Any]) -> None:
    """Append receipt to reply_receipts.ndjson — never raises."""
    try:
        _RECEIPT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _RECEIPT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt) + "\n")
    except Exception as exc:
        logger.debug("receipt_write_failed error=%s", str(exc)[:100])


def get_ring() -> list:
    """Return a snapshot of the in-memory ACK ring buffer (for tests)."""
    return list(_ring)


def get_receipts(limit: int = 50) -> list:
    """Return last *limit* receipt entries from reply_receipts.ndjson."""
    if not _RECEIPT_LOG_PATH.is_file():
        return []
    try:
        lines = _RECEIPT_LOG_PATH.read_text(errors="replace").splitlines()
        results = []
        for line in reversed(lines[-limit * 2:]):
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except Exception:
                pass
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


async def send_ack(
    thread_guid: str,
    text: str,
    *,
    dry_run: bool = _DRY_RUN_DEFAULT,
    action_id: str = "",
    action_type: str = "",
) -> Dict[str, Any]:
    """Send or stub an outbound ACK and write a durable receipt.

    Always returns a dict with 'ok', 'dry_run', and optional 'error'.
    Never raises — caller should not crash on ACK failure.

    New optional kwargs (supplied by dispatcher):
      action_id   — ActionStore action_id for traceability
      action_type — handler name (cortex_remember, send_reply, …)
    """
    ts = datetime.now(timezone.utc).isoformat()
    phone = _phone_from_thread_guid(thread_guid)
    phone_last4 = _redact_phone(phone) if phone else ""
    rec_hash = _recipient_hash(thread_guid) if thread_guid else ""

    # ── base receipt skeleton ─────────────────────────────────────────────────
    receipt: Dict[str, Any] = {
        "ts": ts,
        "action_id": action_id,
        "action_type": action_type,
        "dry_run": dry_run,
        "success": False,
        "path": "dry_run" if dry_run else "pending",
        "phone_last4": phone_last4,
        "recipient_hash": rec_hash,
        "text": text,
        "error": "",
        "fallback_used": False,
        "bridge_status_code": None,
    }

    # ── dry-run path ──────────────────────────────────────────────────────────
    if dry_run:
        entry = {
            "ts": ts,
            "thread_guid": thread_guid,
            "text": text,
            "dry_run": True,
        }
        _ring.append(entry)
        # Legacy write — backward compat
        try:
            _ACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ACK_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("ack_log_write_failed error=%s", str(exc)[:100])
        logger.info("ack_dry_run thread=%s text=%s", thread_guid[:40], text[:80])
        receipt.update({"success": True, "path": "dry_run"})
        _write_receipt(receipt)
        return {"ok": True, "dry_run": True}

    # ── live path — validate recipient ────────────────────────────────────────
    if _ALLOWED_RECIPIENTS and thread_guid not in _ALLOWED_RECIPIENTS:
        logger.warning("ack_blocked_not_allowlisted thread=%s", thread_guid[:40])
        receipt.update({"path": "blocked", "error": "recipient_not_allowlisted"})
        _write_receipt(receipt)
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
            receipt.update({"success": True, "path": "bluebubbles"})
            _write_receipt(receipt)
            return {"ok": True, "dry_run": False, "path": "bluebubbles"}
        cortex_error = str(result.get("error", "unknown"))
        logger.warning("ack_bluebubbles_failed error=%s — trying bridge", cortex_error[:100])
    except Exception as exc:
        cortex_error = str(exc)[:100]
        logger.warning("ack_bluebubbles_exception error=%s — trying bridge", cortex_error)

    # ── Path 2: iMessage bridge fallback ─────────────────────────────────────
    if not phone:
        err = f"bluebubbles failed ({cortex_error}) and cannot extract phone from GUID"
        logger.warning("ack_no_phone_in_guid guid=%s", thread_guid[:60])
        receipt.update({"path": "failed", "error": err})
        _write_receipt(receipt)
        return {"ok": False, "dry_run": False, "error": err}

    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT) as c:
            resp = await c.post(_IMESSAGE_BRIDGE_URL, json={"phone": phone, "body": text})
        bridge_code = resp.status_code
        receipt["bridge_status_code"] = bridge_code
        receipt["fallback_used"] = True
        if bridge_code == 200:
            logger.info("ack_sent path=imessage_bridge phone=%s", phone[-4:])
            receipt.update({"success": True, "path": "imessage_bridge"})
            _write_receipt(receipt)
            return {"ok": True, "dry_run": False, "path": "imessage_bridge"}
        err = f"bridge HTTP {bridge_code}: {resp.text[:200]}"
        logger.warning("ack_bridge_failed status=%s error=%s", bridge_code, err[:80])
        receipt.update({"path": "bridge_failed", "error": err})
        _write_receipt(receipt)
        return {"ok": False, "dry_run": False, "error": err}
    except Exception as exc:
        err = f"both paths failed — bluebubbles: {cortex_error}; bridge: {exc!s:.80}"
        logger.warning("ack_bridge_exception error=%s", str(exc)[:100])
        receipt.update({"path": "both_failed", "error": err, "fallback_used": True})
        _write_receipt(receipt)
        return {"ok": False, "dry_run": False, "error": err}
