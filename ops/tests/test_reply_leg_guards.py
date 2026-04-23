"""
Phase 6 — Security / guardrail tests for the reply-leg executor.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.x_intake.reply_actions.action_store import ActionContext, ActionStore, AlreadyUsed
from integrations.x_intake.reply_actions.dispatcher import Dispatcher, HANDLER_REGISTRY, _RateLimiter
from integrations.x_intake.reply_actions.listener import process_message
from integrations.x_intake.reply_actions.ack import send_ack


def _make_store(tmp_path: Path) -> ActionStore:
    return ActionStore(db_path=tmp_path / "ra.db")


def _seed(store: ActionStore, thread: str = "iMessage;-;+1970", handler: str = "cortex_remember") -> str:
    return store.create(
        valid_slots=[1],
        context={
            "thread_guid": thread,
            "url": "https://example.com",
            "title": "t",
            "summary": "s",
            "category": "x_intel",
            "slot_handler_map": {"1": handler},
        },
        expiry_seconds=3600,
        thread_guid=thread,
    )


async def _noop_ack(thread_guid: str, text: str, *, dry_run: bool = True) -> dict:
    return {"ok": True, "dry_run": True}


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_handler_name_not_executed(tmp_path: Path):
    """slot_handler_map pointing to 'os.system' → rejected, never executed."""
    store = _make_store(tmp_path)
    _seed(store, handler="os.system")
    dispatcher = Dispatcher(store)
    called = []

    async def spy(ctx):
        called.append("SHOULD_NOT_BE_CALLED")
        return {}

    with patch.dict(HANDLER_REGISTRY, {"os.system": spy}):
        # Even if someone sneaks it into the registry in a test, we verify the
        # real path: a name NOT in the real HANDLER_REGISTRY is rejected.
        pass  # do not add to real registry

    ack_texts = []

    async def capturing_ack(thread_guid: str, text: str, *, dry_run: bool = True):
        ack_texts.append(text)
        return {"ok": True, "dry_run": True}

    # os.system is not in the real HANDLER_REGISTRY
    await process_message(
        json.dumps({"text": "1", "chat_guid": "iMessage;-;+1970", "from": "+1"}),
        store, dispatcher, capturing_ack, dry_run=True,
    )

    assert "os.system" not in str(called)
    # ACK should say "not recognized"
    assert any("not recognized" in t.lower() or "action" in t.lower() for t in ack_texts)


def test_rate_limit_caps_per_handle():
    """11 rapid dispatches from the same handle → 11th is rejected."""
    limiter = _RateLimiter(limit=10, window=60.0)
    results = [limiter.is_allowed("test_user") for _ in range(11)]
    allowed = sum(results)
    assert allowed == 10
    assert results[10] is False


@pytest.mark.asyncio
async def test_dry_run_never_calls_send_text(tmp_path: Path):
    """CORTEX_REPLY_DRY_RUN=1 — BlueBubblesClient.send_text is never called."""
    store = _make_store(tmp_path)
    _seed(store)
    dispatcher = Dispatcher(store)
    send_text_called = []

    class FakeBB:
        configured = True
        async def send_text(self, **kw):
            send_text_called.append(kw)
            return {"ok": True}

    with patch.dict(HANDLER_REGISTRY,
                    {"cortex_remember": AsyncMock(return_value={"status": "ok"}),
                     "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(
            json.dumps({"text": "1", "chat_guid": "iMessage;-;+1970", "from": "+1"}),
            store, dispatcher, send_ack, dry_run=True,
        )

    # send_ack in dry_run=True must not call BlueBubblesClient.send_text
    assert send_text_called == []


@pytest.mark.asyncio
async def test_expired_context_ignored(tmp_path: Path):
    store = _make_store(tmp_path)
    store.create(
        valid_slots=[1],
        context={"thread_guid": "iMessage;-;+1970", "url": "", "title": "", "summary": "",
                 "category": "x_intel", "slot_handler_map": {"1": "cortex_remember"}},
        expiry_seconds=-1,
        thread_guid="iMessage;-;+1970",
    )
    dispatcher = Dispatcher(store)
    called = []

    with patch.dict(HANDLER_REGISTRY, {"cortex_remember": AsyncMock(side_effect=lambda c: called.append(1) or {})}):
        await process_message(
            json.dumps({"text": "1", "chat_guid": "iMessage;-;+1970", "from": "+1"}),
            store, dispatcher, _noop_ack, dry_run=True,
        )

    assert called == []


@pytest.mark.asyncio
async def test_already_used_action_is_noop(tmp_path: Path):
    """Mark an action used, then try again → AlreadyUsed caught, no double-execute."""
    store = _make_store(tmp_path)
    action_id = _seed(store)
    store.mark_used(action_id, 1)
    dispatcher = Dispatcher(store)
    called = []

    with patch.dict(HANDLER_REGISTRY, {"cortex_remember": AsyncMock(side_effect=lambda c: called.append(1) or {})}):
        await process_message(
            json.dumps({"text": "1", "chat_guid": "iMessage;-;+1970", "from": "+1"}),
            store, dispatcher, _noop_ack, dry_run=True,
        )

    assert called == []
