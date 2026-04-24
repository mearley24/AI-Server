"""
Phase 6 — End-to-end reply-leg integration test (offline, no Redis, no network).

Uses an asyncio.Queue-based fake Redis stub to simulate pubsub messages.
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
from integrations.x_intake.reply_actions.dispatcher import Dispatcher, HANDLER_REGISTRY
from integrations.x_intake.reply_actions.listener import process_message
from integrations.x_intake.reply_actions.ack import get_ring, send_ack


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path) -> ActionStore:
    return ActionStore(db_path=tmp_path / "ra.db")


def _seed_action(store: ActionStore, thread: str = "iMessage;-;+1970") -> str:
    """Create a test action with slots 1→cortex_remember, 2→cortex_dismiss."""
    return store.create(
        valid_slots=[1, 2],
        context={
            "thread_guid": thread,
            "url": "https://twitter.com/user/status/1",
            "title": "Test post",
            "summary": "Test summary",
            "category": "x_intel",
            "slot_handler_map": {"1": "cortex_remember", "2": "cortex_dismiss"},
        },
        expiry_seconds=3600,
        thread_guid=thread,
    )


async def _noop_ack(thread_guid: str, text: str, *, dry_run: bool = True) -> dict:
    return {"ok": True, "dry_run": dry_run}


def _make_event(text: str, thread: str = "iMessage;-;+1970") -> str:
    return json.dumps({
        "text": text,
        "chat_guid": thread,
        "from": "+19705193013",
        "message_id": "test-evt-001",
    })


# ── e2e tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_reply1_calls_cortex_remember(tmp_path: Path):
    """Reply '1' → cortex_remember handler → Cortex POST captured."""
    store = _make_store(tmp_path)
    action_id = _seed_action(store)
    dispatcher = Dispatcher(store)

    posted = []

    async def fake_remember(ctx: ActionContext):
        posted.append(ctx.action_id)
        return {"handler": "cortex_remember", "status": "ok", "mem_id": "x1"}

    ack_calls = []

    async def capturing_ack(thread_guid: str, text: str, *, dry_run: bool = True):
        ack_calls.append({"thread": thread_guid, "text": text})
        return {"ok": True, "dry_run": True}

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": fake_remember, "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(_make_event("reply 1"), store, dispatcher, capturing_ack, dry_run=True)

    assert action_id in posted
    assert len(ack_calls) == 1
    assert "Saved" in ack_calls[0]["text"] or "Done" in ack_calls[0]["text"]


@pytest.mark.asyncio
async def test_e2e_mark_used_called(tmp_path: Path):
    store = _make_store(tmp_path)
    action_id = _seed_action(store)
    dispatcher = Dispatcher(store)

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": AsyncMock(return_value={"status": "ok"}),
                     "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(_make_event("1"), store, dispatcher, _noop_ack, dry_run=True)

    ctx = store.lookup(action_id)
    assert ctx is not None
    assert ctx.used_at is not None
    assert ctx.used_slot == 1


@pytest.mark.asyncio
async def test_e2e_idempotency_second_reply_is_noop(tmp_path: Path):
    """Second identical reply → AlreadyUsed caught → no double execution."""
    store = _make_store(tmp_path)
    _seed_action(store)
    dispatcher = Dispatcher(store)
    call_count = 0

    async def counting_handler(ctx):
        nonlocal call_count
        call_count += 1
        return {"status": "ok"}

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": counting_handler,
                     "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(_make_event("1"), store, dispatcher, _noop_ack, dry_run=True)
        await process_message(_make_event("1"), store, dispatcher, _noop_ack, dry_run=True)

    assert call_count == 1  # only executed once


@pytest.mark.asyncio
async def test_e2e_invalid_slot_ignored(tmp_path: Path):
    """Reply '9' (not in valid slots) → no handler invoked."""
    store = _make_store(tmp_path)
    _seed_action(store)
    dispatcher = Dispatcher(store)
    called = []

    async def recording_handler(ctx):
        called.append(ctx.action_id)
        return {"status": "ok"}

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": recording_handler,
                     "cortex_dismiss": recording_handler,
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(_make_event("9"), store, dispatcher, _noop_ack, dry_run=True)

    assert called == []


@pytest.mark.asyncio
async def test_e2e_expired_context_ignored(tmp_path: Path):
    """Expired action → dispatcher not called."""
    store = _make_store(tmp_path)
    store.create(
        valid_slots=[1],
        context={
            "thread_guid": "iMessage;-;+1970",
            "url": "https://example.com",
            "title": "old",
            "summary": "old",
            "category": "x_intel",
            "slot_handler_map": {"1": "cortex_remember"},
        },
        expiry_seconds=-1,   # already expired
        thread_guid="iMessage;-;+1970",
    )
    dispatcher = Dispatcher(store)
    called = []

    async def recording_handler(ctx):
        called.append(ctx.action_id)
        return {"status": "ok"}

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": recording_handler,
                     "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        await process_message(_make_event("1"), store, dispatcher, _noop_ack, dry_run=True)

    assert called == []


@pytest.mark.asyncio
async def test_e2e_dry_run_ack_goes_to_ring(tmp_path: Path):
    """In dry_run=True, send_ack writes to in-memory ring buffer."""
    store = _make_store(tmp_path)
    _seed_action(store)
    dispatcher = Dispatcher(store)

    before = len(get_ring())

    with patch.dict("integrations.x_intake.reply_actions.dispatcher.HANDLER_REGISTRY",
                    {"cortex_remember": AsyncMock(return_value={"status": "ok"}),
                     "cortex_dismiss": AsyncMock(return_value={}),
                     "escalate_to_matt": AsyncMock(return_value={})}):
        # Use the real send_ack (dry_run=True)
        await process_message(_make_event("1"), store, dispatcher, send_ack, dry_run=True)

    after = len(get_ring())
    assert after > before


@pytest.mark.asyncio
async def test_e2e_send_reply_passes_explicit_body(tmp_path: Path):
    """send_reply handler must deliver the exact body string set in context["body"],
    not a hardcoded confirmation like 'Saved to Bob's memory ✓'."""
    store = _make_store(tmp_path)
    THREAD = "iMessage;-;+18609171850"
    EXPECTED = "Bob live reply-leg explicit-body test."

    store.create(
        valid_slots=[1],
        context={
            "slot_handler_map": {"1": "send_reply"},
            "thread_guid": THREAD,
            "body": EXPECTED,
        },
        expiry_seconds=300,
        thread_guid=THREAD,
    )

    dispatcher = Dispatcher(store)
    captured: list[str] = []

    async def capture_ack(thread_guid: str, text: str, *, dry_run: bool = True) -> dict:
        captured.append(text)
        return {"ok": True, "dry_run": dry_run}

    await process_message(
        json.dumps({
            "text": "reply 1",
            "chat_guid": THREAD,
            "from": "18609171850",
            "message_id": "expl-test-001",
        }),
        store, dispatcher, capture_ack, dry_run=True,
    )

    assert len(captured) == 1, f"Expected 1 ACK, got {len(captured)}"
    assert captured[0] == EXPECTED, (
        f"ACK text mismatch.\n  got:      {captured[0]!r}\n  expected: {EXPECTED!r}"
    )


@pytest.mark.asyncio
async def test_e2e_send_reply_skip_when_no_body(tmp_path: Path):
    """send_reply with no body in context must produce 'Done ✓' fallback, not crash."""
    store = _make_store(tmp_path)
    THREAD = "iMessage;-;+18609171850"

    store.create(
        valid_slots=[1],
        context={
            "slot_handler_map": {"1": "send_reply"},
            "thread_guid": THREAD,
            # deliberately no 'body' key
        },
        expiry_seconds=300,
        thread_guid=THREAD,
    )

    dispatcher = Dispatcher(store)
    captured: list[str] = []

    async def capture_ack(thread_guid: str, text: str, *, dry_run: bool = True) -> dict:
        captured.append(text)
        return {"ok": True, "dry_run": dry_run}

    await process_message(
        json.dumps({
            "text": "reply 1",
            "chat_guid": THREAD,
            "from": "18609171850",
            "message_id": "expl-test-002",
        }),
        store, dispatcher, capture_ack, dry_run=True,
    )

    # send_reply with no body returns skip — dispatcher falls back to "Done ✓"
    assert len(captured) == 1
    assert captured[0] == "Done ✓"
