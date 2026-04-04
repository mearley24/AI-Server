"""Callback from outcome_listener / HTTP into orchestrator.resolve_approval."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("openclaw.approval_bridge")

_resolve: Optional[Callable[[int, bool, str], Awaitable[None]]] = None


def set_resolve_handler(fn: Callable[[int, bool, str], Awaitable[None]]) -> None:
    global _resolve
    _resolve = fn


async def resolve_async(decision_id: int, granted: bool, edit_note: str = "") -> None:
    if _resolve is None:
        logger.warning("approval_bridge: no handler registered for decision_id=%s", decision_id)
        return
    try:
        await _resolve(decision_id, granted, edit_note)
    except Exception as e:
        logger.error("approval_bridge resolve failed: %s", e, exc_info=True)
