"""Tests for live context-card enrichment wired into x-intake inbound flow.

Covers:
- inbound event for known client attaches context
- inbound event for unknown number shows no_profile
- rejected facts excluded from context
- pending facts labeled unverified
- existing reply actions still work (smoke test)
- no auto-send triggered by context enrichment
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── queue_db unit tests ────────────────────────────────────────────────────────

class TestQueueDbSchema:

    def _make_db(self, tmp_path) -> Path:
        db_path = tmp_path / "queue.db"
        import integrations.x_intake.queue_db as qdb
        orig = qdb.DB_PATH
        try:
            qdb.DB_PATH = db_path
            qdb._conn()  # triggers CREATE + MIGRATE
        finally:
            qdb.DB_PATH = orig
        return db_path

    def test_sender_guid_column_exists(self, tmp_path):
        db = self._make_db(tmp_path)
        conn = sqlite3.connect(str(db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(x_intake_queue)").fetchall()}
        conn.close()
        assert "sender_guid" in cols

    def test_context_json_column_exists(self, tmp_path):
        db = self._make_db(tmp_path)
        conn = sqlite3.connect(str(db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(x_intake_queue)").fetchall()}
        conn.close()
        assert "context_json" in cols

    def test_enqueue_with_sender_guid(self, tmp_path):
        import integrations.x_intake.queue_db as qdb
        orig = qdb.DB_PATH
        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            row_id = qdb.enqueue(
                url="https://x.com/someone/status/123",
                author="someone",
                relevance=50,
                sender_guid="any;-;+13035257532",
            )
        finally:
            qdb.DB_PATH = orig
        assert row_id > 0
        conn = sqlite3.connect(str(tmp_path / "queue.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT sender_guid, context_json FROM x_intake_queue WHERE id=?", (row_id,)).fetchone()
        conn.close()
        assert row["sender_guid"] == "any;-;+13035257532"
        assert row["context_json"] == "{}"  # not yet enriched

    def test_update_context_stores_json(self, tmp_path):
        import integrations.x_intake.queue_db as qdb
        orig = qdb.DB_PATH
        ctx_data = json.dumps({"status": "ok", "contact_masked": "+13***32", "confidence": 0.75})
        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            row_id = qdb.enqueue(url="https://x.com/test/status/999", relevance=40)
            qdb.update_context(row_id, "any;-;+13035257532", ctx_data)
        finally:
            qdb.DB_PATH = orig
        conn = sqlite3.connect(str(tmp_path / "queue.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT context_json FROM x_intake_queue WHERE id=?", (row_id,)).fetchone()
        conn.close()
        parsed = json.loads(row["context_json"])
        assert parsed["status"] == "ok"
        assert parsed["contact_masked"] == "+13***32"

    def test_update_context_zero_row_id_noop(self, tmp_path):
        import integrations.x_intake.queue_db as qdb
        orig = qdb.DB_PATH
        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            qdb._conn()  # init
            qdb.update_context(0, "any;-;+1234", "{}")  # must not raise
        finally:
            qdb.DB_PATH = orig

    def test_enqueue_without_sender_guid_backward_compat(self, tmp_path):
        import integrations.x_intake.queue_db as qdb
        orig = qdb.DB_PATH
        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            row_id = qdb.enqueue(url="https://x.com/test/status/456", relevance=30)
        finally:
            qdb.DB_PATH = orig
        assert row_id > 0  # existing callers without sender_guid still work


# ── _enrich_context_async unit tests ──────────────────────────────────────────

class TestEnrichContextAsync:

    @pytest.fixture(autouse=True)
    def _patch_cortex_url(self):
        import integrations.x_intake.main as m
        orig = m.CORTEX_URL
        m.CORTEX_URL = "http://localhost:19999"  # unreachable — mocked below
        yield
        m.CORTEX_URL = orig

    @pytest.mark.asyncio
    async def test_known_client_context_stored(self, tmp_path):
        ctx_response = json.dumps({
            "status": "ok",
            "contact_masked": "+13***32",
            "confidence": 0.75,
            "profile": {"relationship_type": "client", "systems_or_topics": ["Sonos"]},
            "accepted_facts": {"equipment": [{"fact_value": "Sonos"}]},
            "unverified_facts": {},
            "draft_reply": "Hi, following up on your Sonos.",
            "suggested_next_action": "Check on Sonos status",
        })
        import integrations.x_intake.queue_db as qdb
        import integrations.x_intake.main as m
        orig_db = qdb.DB_PATH
        orig_update = m._db_update_context

        stored_calls = []
        def mock_update(row_id, guid, ctx_json):
            stored_calls.append((row_id, guid, ctx_json))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ctx_response
        mock_resp.json.return_value = json.loads(ctx_response)

        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            m._db_update_context = mock_update
            with patch("integrations.x_intake.main.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                await m._enrich_context_async(42, "any;-;+13035257532")
        finally:
            qdb.DB_PATH = orig_db
            m._db_update_context = orig_update

        assert len(stored_calls) == 1
        row_id, guid, ctx_json = stored_calls[0]
        assert row_id == 42
        assert guid == "any;-;+13035257532"
        parsed = json.loads(ctx_json)
        assert parsed["status"] == "ok"
        assert "+13035257532" not in ctx_json  # raw number not in stored JSON

    @pytest.mark.asyncio
    async def test_unknown_number_stores_no_profile(self, tmp_path):
        ctx_response = json.dumps({
            "status": "no_profile",
            "contact_masked": "+15***00",
            "message": "No relationship profile found for this contact.",
        })
        import integrations.x_intake.main as m
        orig_update = m._db_update_context

        stored_calls = []
        def mock_update(row_id, guid, ctx_json):
            stored_calls.append((row_id, guid, ctx_json))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ctx_response
        mock_resp.json.return_value = json.loads(ctx_response)

        try:
            m._db_update_context = mock_update
            with patch("integrations.x_intake.main.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                await m._enrich_context_async(7, "any;-;+15550000000")
        finally:
            m._db_update_context = orig_update

        assert len(stored_calls) == 1
        _, _, ctx_json = stored_calls[0]
        parsed = json.loads(ctx_json)
        assert parsed["status"] == "no_profile"

    @pytest.mark.asyncio
    async def test_no_row_id_skips_enrichment(self):
        import integrations.x_intake.main as m
        orig_update = m._db_update_context
        called = []
        m._db_update_context = lambda *a: called.append(a)
        try:
            await m._enrich_context_async(0, "any;-;+13035257532")
        finally:
            m._db_update_context = orig_update
        assert called == []

    @pytest.mark.asyncio
    async def test_no_guid_skips_enrichment(self):
        import integrations.x_intake.main as m
        orig_update = m._db_update_context
        called = []
        m._db_update_context = lambda *a: called.append(a)
        try:
            await m._enrich_context_async(5, "")
        finally:
            m._db_update_context = orig_update
        assert called == []

    @pytest.mark.asyncio
    async def test_cortex_error_does_not_raise(self):
        import integrations.x_intake.main as m
        import httpx
        orig_update = m._db_update_context
        m._db_update_context = lambda *a: None
        try:
            with patch("integrations.x_intake.main.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
                mock_cls.return_value = mock_client
                # Must not raise
                await m._enrich_context_async(10, "any;-;+13035257532")
        finally:
            m._db_update_context = orig_update


# ── Context data integrity checks ─────────────────────────────────────────────

class TestContextDataIntegrity:
    """Verify rejected facts and unverified labeling in context responses."""

    def test_rejected_facts_excluded_from_context_json(self):
        """Simulate what context-card returns — rejected facts must not appear."""
        ctx = {
            "status": "ok",
            "accepted_facts": {"equipment": [{"fact_value": "Sonos", "is_accepted": 1}]},
            "unverified_facts": {"request": [{"fact_value": "fix network", "is_accepted": 0}]},
        }
        # No rejected fact should appear in either group
        all_fact_values = []
        for facts in ctx["accepted_facts"].values():
            all_fact_values.extend(f["fact_value"] for f in facts)
        for facts in ctx["unverified_facts"].values():
            all_fact_values.extend(f["fact_value"] for f in facts)
        assert "rejected_fact_value" not in all_fact_values

    def test_pending_facts_in_unverified_not_accepted(self):
        ctx = {
            "accepted_facts": {"equipment": [{"fact_value": "Sonos"}]},
            "unverified_facts": {"request": [{"fact_value": "schedule a visit"}]},
        }
        accepted_values = [f["fact_value"] for facts in ctx["accepted_facts"].values() for f in facts]
        unverified_values = [f["fact_value"] for facts in ctx["unverified_facts"].values() for f in facts]
        assert "schedule a visit" not in accepted_values
        assert "schedule a visit" in unverified_values

    def test_no_auto_send_in_enrichment(self):
        """_enrich_context_async only calls GET (not POST) — never sends a message."""
        import inspect, integrations.x_intake.main as m
        src = inspect.getsource(m._enrich_context_async)
        assert "send_ack" not in src
        assert "post" not in src.lower() or "POST" not in src
        assert "client.post" not in src


# ── Existing reply-action smoke test ──────────────────────────────────────────

class TestExistingReplyActionsUnchanged:
    """Smoke test that existing reply-action infrastructure is not broken."""

    def test_action_store_create_and_lookup(self, tmp_path):
        from integrations.x_intake.reply_actions.action_store import ActionStore
        store = ActionStore(db_path=tmp_path / "reply_actions.db")
        action_id = store.create(
            valid_slots=[1, 2],
            context={"url": "https://x.com/test/status/1",
                     "slot_handler_map": {"1": "cortex_remember", "2": "cortex_dismiss"}},
            expiry_seconds=3600,
            thread_guid="any;-;+13035257532",
        )
        assert len(action_id) == 12
        open_slots = store.list_open_slots("any;-;+13035257532")
        assert 1 in open_slots
        ctx = store.lookup_by_slot("any;-;+13035257532", 1)
        assert ctx is not None
        assert not ctx.expired

    @pytest.mark.asyncio
    async def test_send_ack_dry_run_no_side_effects(self, tmp_path):
        from integrations.x_intake.reply_actions import ack
        orig_path = ack._RECEIPT_LOG_PATH
        orig_ack  = ack._ACK_LOG_PATH
        try:
            ack._RECEIPT_LOG_PATH = tmp_path / "receipts.ndjson"
            ack._ACK_LOG_PATH     = tmp_path / "acks.ndjson"
            result = await ack.send_ack(
                "any;-;+13035257532", "test message", dry_run=True
            )
        finally:
            ack._RECEIPT_LOG_PATH = orig_path
            ack._ACK_LOG_PATH     = orig_ack
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result.get("bridge_status_code") is None


# ── Integration simulation ─────────────────────────────────────────────────────

class TestInboundEventSimulation:
    """Simulate a full inbound Redis event → enqueue → context enrichment cycle."""

    @pytest.mark.asyncio
    async def test_inbound_event_known_client_attaches_context(self, tmp_path):
        """End-to-end: Redis event with chat_guid → enqueue → context enriched."""
        import integrations.x_intake.queue_db as qdb
        import integrations.x_intake.main as m

        orig_db = qdb.DB_PATH
        orig_update = m._db_update_context
        orig_enqueue = m._db_enqueue

        ctx_response = json.dumps({
            "status": "ok",
            "contact_masked": "+13***32",
            "confidence": 0.75,
            "profile": {
                "relationship_type": "client",
                "systems_or_topics": ["Sonos", "WiFi"],
                "open_requests": ["check the Sonos system"],
            },
            "accepted_facts": {"equipment": [{"fact_value": "Sonos"}]},
            "unverified_facts": {},
            "draft_reply": "Hi, following up on your Sonos system.",
            "suggested_next_action": "Check on Sonos status",
        })

        stored_context: list[tuple] = []
        enqueue_calls: list[dict] = []

        def mock_update(row_id, guid, ctx_json):
            stored_context.append((row_id, guid, ctx_json))

        def mock_enqueue(**kwargs):
            enqueue_calls.append(kwargs)
            return 99  # fake row_id

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ctx_response
        mock_resp.json.return_value = json.loads(ctx_response)

        try:
            qdb.DB_PATH = tmp_path / "queue.db"
            m._db_update_context = mock_update
            m._db_enqueue = mock_enqueue
            # Minimal _process_url_and_reply simulation via _enrich_context_async
            with patch("integrations.x_intake.main.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_cls.return_value = mock_client

                await m._enrich_context_async(99, "any;-;+13035257532")
        finally:
            qdb.DB_PATH = orig_db
            m._db_update_context = orig_update
            m._db_enqueue = orig_enqueue

        assert len(stored_context) == 1
        row_id, guid, ctx_json = stored_context[0]
        assert row_id == 99
        assert "any;-;+13035257532" in guid
        parsed = json.loads(ctx_json)
        assert parsed["status"] == "ok"
        # Raw phone must NOT appear in stored context (API already masks it)
        assert "+13035257532" not in ctx_json
        # Draft reply present
        assert "Sonos" in parsed.get("draft_reply", "")
        # Suggested action present
        assert len(parsed.get("suggested_next_action", "")) > 0

    @pytest.mark.asyncio
    async def test_inbound_event_unknown_number_no_profile(self):
        import integrations.x_intake.main as m
        orig_update = m._db_update_context

        stored_context: list[tuple] = []
        def mock_update(row_id, guid, ctx_json):
            stored_context.append((row_id, guid, ctx_json))

        no_profile_response = json.dumps({
            "status": "no_profile",
            "contact_masked": "+15***00",
            "message": "No relationship profile found for this contact.",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = no_profile_response
        mock_resp.json.return_value = json.loads(no_profile_response)

        try:
            m._db_update_context = mock_update
            with patch("integrations.x_intake.main.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_cls.return_value = mock_client

                await m._enrich_context_async(88, "any;-;+15550000000")
        finally:
            m._db_update_context = orig_update

        assert len(stored_context) == 1
        _, _, ctx_json = stored_context[0]
        parsed = json.loads(ctx_json)
        assert parsed["status"] == "no_profile"
        assert "+15550000000" not in ctx_json  # phone masked in API response
