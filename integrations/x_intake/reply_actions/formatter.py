"""
Outbound card formatter — Phase 1 foundation.

Appends the reply-action options block to an x-intake outbound message.
Pure function: format_card() is stateless; schema is loaded once at import.

Output template (from config/reply_actions.schema.json):
    {summary}

    ──────────
    Reply 1 — card  |  2 — research  |  3 — prototype
    ID:a3f9c1 · exp 24h

Caller is responsible for generating the action_id via ActionStore.create().
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "config" / "reply_actions.schema.json"
)

# Load catalog once; tests may patch _CATALOG directly if needed.
try:
    with open(_SCHEMA_PATH) as _f:
        _RAW_SCHEMA = json.load(_f)
    _CATALOG: List[Dict] = _RAW_SCHEMA["actions"]
    _SETTINGS: Dict = _RAW_SCHEMA["global_settings"]
    _FMT: Dict = _RAW_SCHEMA["outbound_format"]
except (FileNotFoundError, KeyError):
    _CATALOG = []
    _SETTINGS = {
        "default_expiry_seconds": 86400,
        "id_length_bytes": 6,
        "id_encoding": "hex",
    }
    _FMT = {"separator": "  |  "}

_DEFAULT_EXPIRY = _SETTINGS.get("default_expiry_seconds", 86400)
_SEP = _FMT.get("separator", "  |  ")
_DIVIDER = "──────────"


def _expiry_label(expiry_seconds: int) -> str:
    """Convert seconds to a compact human label: 3600 → '1h', 86400 → '24h'."""
    hours = math.ceil(expiry_seconds / 3600)
    return f"{hours}h"


def _build_options_line(slots: Sequence[int]) -> str:
    """
    Produce the compact options line, e.g.:
        Reply 1 — card  |  2 — research  |  3 — prototype
    """
    catalog_by_slot: Dict[int, Dict] = {a["slot"]: a for a in _CATALOG}
    parts: List[str] = []
    for i, slot in enumerate(slots):
        action = catalog_by_slot.get(slot)
        label = action["short_label"] if action else str(slot)
        if i == 0:
            parts.append(f"Reply {slot} — {label}")
        else:
            parts.append(f"{slot} — {label}")
    return _SEP.join(parts)


def format_card(
    summary: str,
    action_id: str,
    expiry_seconds: int = _DEFAULT_EXPIRY,
    slots: Sequence[int] = (1, 2, 3),
) -> str:
    """
    Append the reply-action options block to *summary* and return the full
    outbound message string.

    *summary*        — the pre-built iMessage card text (emoji + author + body).
    *action_id*      — 12-char hex from ActionStore.create().
    *expiry_seconds* — used to compute the displayed expiry label.
    *slots*          — which action slots to show (default: 1, 2, 3).
    """
    options_line = _build_options_line(slots)
    expiry_label = _expiry_label(expiry_seconds)
    footer = f"ID:{action_id} · exp {expiry_label}"
    return f"{summary}\n\n{_DIVIDER}\n{options_line}\n{footer}"


def strip_options_block(message: str) -> str:
    """
    Remove the options block from an existing formatted card.
    Useful when re-formatting with updated action IDs.
    """
    idx = message.find(f"\n\n{_DIVIDER}\n")
    if idx == -1:
        return message
    return message[:idx]
