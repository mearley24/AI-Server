"""Append-only audit log for vault access events.

Written to data/vault/audit.ndjson — never contains secret values.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_AUDIT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "vault" / "audit.ndjson"
_CONTAINER_AUDIT_PATH = Path("/data/vault/audit.ndjson")


def _audit_path() -> Path:
    env = os.environ.get("VAULT_AUDIT_PATH")
    if env:
        return Path(env)
    if _CONTAINER_AUDIT_PATH.parent.is_dir():
        return _CONTAINER_AUDIT_PATH
    return _DEFAULT_AUDIT_PATH


def log(
    event_type: str,
    secret_name: str,
    requester: str,
    purpose: Optional[str] = None,
    approved: Optional[bool] = None,
    fingerprint: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Append one audit record. Never writes the secret value itself."""
    record = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "event":       event_type,
        "secret_name": secret_name,
        "requester":   requester,
        "purpose":     purpose,
        "approved":    approved,
        "fingerprint": fingerprint,
    }
    if extra:
        record.update({k: v for k, v in extra.items() if k != "value"})

    p = _audit_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # audit failure must never break the main flow
