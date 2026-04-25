"""Tests for the Follow-Up Priority Engine v1.

Covers:
  - relationship-aware thresholds (client 2h, vendor 6h, etc.)
  - priority labels (urgent, high, medium, low, review)
  - internal_team ignored by default, included with include_internal=true
  - threshold_hours override works (for testing / manual override)
  - sorting: priority rank first, then oldest-overdue first
  - approved reply clears follow-up
  - response includes priority, relationship_type, threshold_hours_used, overdue_by_hours
  - no sends or writes triggered
  - helper functions (_queue_rows_with_context, _approvals_index) behave correctly
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.engine import (
    _approvals_index,
    _queue_rows_with_context,
    _rel_priority,
    _FOLLOW_UP_PRIORITY,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_queue_db(tmp_path: Path, rows: list[dict]) -> Path:
    """Create a minimal x_intake_queue SQLite file."""
    db = tmp_path / "queue.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE x_intake_queue (
            id INTEGER PRIMARY KEY,
            sender_guid TEXT DEFAULT '',
            context_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO x_intake_queue (id, sender_guid, context_json, created_at) VALUES (?,?,?,?)",
            (r["id"], r.get("sender_guid", ""), r.get("context_json", "{}"), r["created_at"]),
        )
    conn.commit()
    conn.close()
    return db


def _make_approval_log(tmp_path: Path, approvals: list[dict]) -> Path:
    """Write approval entries to a ndjson file."""
    log = tmp_path / "reply_approvals.ndjson"
    lines = [json.dumps(a) for a in approvals]
    log.write_text("\n".join(lines) + ("\n" if lines else ""))
    return log


def _ctx(contact_masked: str, draft: str = "Got it — try unplugging your Sonos.",
         status: str = "ok", confidence: float = 0.75,
         rel_type: str = "client") -> str:
    return json.dumps({
        "status":                status,
        "contact_masked":        contact_masked,
        "draft_reply":           draft,
        "confidence":            confidence,
        "draft_quality_status":  "pass",
        "suggested_next_action": "Check on Sonos status",
        "profile": {
            "relationship_type": rel_type,
            "systems_or_topics": ["Sonos"],
            "open_requests":     [],
        },
    })


NOW             = time.time()
THREE_HOURS_AGO = NOW - 3 * 3600
THIRTY_MINS_AGO = NOW - 30 * 60
SIX_HOURS_AGO   = NOW - 6 * 3600
SEVEN_HOURS_AGO = NOW - 7 * 3600
THIRTEEN_H_AGO  = NOW - 13 * 3600


# ── _queue_rows_with_context ──────────────────────────────────────────────────

class TestQueueRowsWithContext:

    def test_returns_rows_with_sender_and_context(self, tmp_path):
        db = _make_queue_db(tmp_path, [
            {"id": 1, "sender_guid": "any;-;+13001001001",
             "context_json": _ctx("+13***01"), "created_at": THREE_HOURS_AGO},
        ])
        import cortex.engine as eng
        orig = eng._X_INTAKE_QUEUE_DB
        eng._X_INTAKE_QUEUE_DB = db
        try:
            rows = _queue_rows_with_context(limit=10)
        finally:
            eng._X_INTAKE_QUEUE_DB = orig
        assert len(rows) == 1
        assert rows[0]["id"] == 1

    def test_skips_rows_without_sender_guid(self, tmp_path):
        db = _make_queue_db(tmp_path, [
            {"id": 1, "sender_guid": "",
             "context_json": _ctx("+13***01"), "created_at": THREE_HOURS_AGO},
            {"id": 2, "sender_guid": "any;-;+13002002002",
             "context_json": _ctx("+13***02"), "created_at": THREE_HOURS_AGO},
        ])
        import cortex.engine as eng
        orig = eng._X_INTAKE_QUEUE_DB
        eng._X_INTAKE_QUEUE_DB = db
        try:
            rows = _queue_rows_with_context(limit=10)
        finally:
            eng._X_INTAKE_QUEUE_DB = orig
        assert len(rows) == 1
        assert rows[0]["id"] == 2

    def test_skips_empty_context_json(self, tmp_path):
        db = _make_queue_db(tmp_path, [
            {"id": 1, "sender_guid": "any;-;+13001001001",
             "context_json": "{}", "created_at": THREE_HOURS_AGO},
            {"id": 2, "sender_guid": "any;-;+13002002002",
             "context_json": _ctx("+13***02"), "created_at": THREE_HOURS_AGO},
        ])
        import cortex.engine as eng
        orig = eng._X_INTAKE_QUEUE_DB
        eng._X_INTAKE_QUEUE_DB = db
        try:
            rows = _queue_rows_with_context(limit=10)
        finally:
            eng._X_INTAKE_QUEUE_DB = orig
        assert len(rows) == 1

    def test_missing_db_returns_empty(self):
        import cortex.engine as eng
        orig = eng._X_INTAKE_QUEUE_DB
        eng._X_INTAKE_QUEUE_DB = Path("/nonexistent/queue.db")
        try:
            rows = _queue_rows_with_context()
        finally:
            eng._X_INTAKE_QUEUE_DB = orig
        assert rows == []


# ── _approvals_index ─────────────────────────────────────────────────────────

class TestApprovalsIndex:

    def test_returns_latest_per_contact(self, tmp_path):
        log = _make_approval_log(tmp_path, [
            {"contact_masked": "+13***01", "approved_at": "2026-04-20T10:00:00+00:00"},
            {"contact_masked": "+13***01", "approved_at": "2026-04-21T10:00:00+00:00"},  # newer
            {"contact_masked": "+13***02", "approved_at": "2026-04-22T10:00:00+00:00"},
        ])
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = log
        try:
            idx = _approvals_index()
        finally:
            eng._APPROVAL_LOG = orig
        assert "+13***01" in idx
        assert idx["+13***01"] > idx.get("+13***01_old", 0)  # newer timestamp stored
        assert "+13***02" in idx

    def test_empty_log_returns_empty_dict(self, tmp_path):
        log = _make_approval_log(tmp_path, [])
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = log
        try:
            idx = _approvals_index()
        finally:
            eng._APPROVAL_LOG = orig
        assert idx == {}

    def test_missing_log_returns_empty_dict(self):
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = Path("/nonexistent/approvals.ndjson")
        try:
            idx = _approvals_index()
        finally:
            eng._APPROVAL_LOG = orig
        assert idx == {}


# ── Priority table unit tests ─────────────────────────────────────────────────

class TestRelPriority:

    def test_client_is_urgent_2h(self):
        threshold, label, rank = _rel_priority("client")
        assert label == "urgent"
        assert threshold == 2.0
        assert rank == 0

    def test_vendor_is_medium_6h(self):
        threshold, label, rank = _rel_priority("vendor")
        assert label == "medium"
        assert threshold == 6.0

    def test_internal_team_is_ignored(self):
        threshold, label, rank = _rel_priority("internal_team")
        assert label == "ignore"
        assert threshold is None

    def test_builder_is_high_3h(self):
        threshold, label, _ = _rel_priority("builder")
        assert label == "high"
        assert threshold == 3.0

    def test_unknown_type_gets_default(self):
        threshold, label, _ = _rel_priority("mystery_type")
        assert label == "review"
        assert threshold == 8.0

    def test_all_known_types_in_table(self):
        expected = {
            "client", "builder", "trade_partner", "vendor",
            "personal_work_related", "unknown", "internal_team",
        }
        assert expected == set(_FOLLOW_UP_PRIORITY.keys())


# ── /api/x-intake/follow-ups endpoint ────────────────────────────────────────

class TestFollowUpsEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _patch(self, queue_rows, approvals_map):
        """Patch both data sources."""
        return (
            patch("cortex.engine._queue_rows_with_context", return_value=queue_rows),
            patch("cortex.engine._approvals_index",         return_value=approvals_map),
        )

    def _row(self, item_id: int, contact: str, created_at: float,
             draft: str = "Got it — try unplugging your Sonos.",
             rel_type: str = "client") -> dict:
        return {
            "id":           item_id,
            "sender_guid":  f"any;-;{contact}",
            "context_json": _ctx(contact, draft, rel_type=rel_type),
            "created_at":   created_at,
        }

    # ── Relationship-aware threshold tests ───────────────────────────────────

    def test_client_triggers_at_2h(self, client):
        """Client threshold is 2h — 3-hour-old client message surfaces."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="client")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            # no threshold_hours override → use per-type defaults
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["count"] == 1
        fu = d["follow_ups"][0]
        assert fu["priority"] == "urgent"
        assert fu["relationship_type"] == "client"
        assert fu["threshold_hours_used"] == 2.0
        assert fu["overdue_by_hours"] >= 0.9   # at least 0.9h overdue

    def test_vendor_does_not_trigger_until_6h(self, client):
        """Vendor threshold is 6h — 3h-old vendor message must not surface."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="vendor")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        assert r.json()["count"] == 0, "3h-old vendor must not surface (threshold=6h)"

    def test_vendor_triggers_after_6h(self, client):
        """7-hour-old vendor message surfaces with medium priority."""
        row = self._row(1, "+13***01", SEVEN_HOURS_AGO, rel_type="vendor")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["count"] == 1
        fu = d["follow_ups"][0]
        assert fu["priority"] == "medium"
        assert fu["threshold_hours_used"] == 6.0

    def test_internal_team_ignored_by_default(self, client):
        """internal_team messages must not surface unless include_internal=true."""
        row = self._row(1, "+13***01", THIRTEEN_H_AGO, rel_type="internal_team")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        assert r.json()["count"] == 0, "internal_team ignored by default"

    def test_include_internal_surfaces_internal_team(self, client):
        """include_internal=true includes internal_team (uses 24h threshold).
        We use threshold_hours=0.1 override so the 13h-old message passes."""
        row = self._row(1, "+13***01", THIRTEEN_H_AGO, rel_type="internal_team")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?include_internal=true&threshold_hours=0.1")
        d = r.json()
        assert d["count"] == 1
        assert d["follow_ups"][0]["relationship_type"] == "internal_team"

    # ── threshold_hours override ─────────────────────────────────────────────

    def test_threshold_hours_override_ignores_per_type_defaults(self, client):
        """threshold_hours >= 0 overrides per-type thresholds for all contacts."""
        row = self._row(1, "+13***01", THIRTY_MINS_AGO, rel_type="client")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            # 0.01h override (36s) → 30-minute-old message surfaces
            r = client.get("/api/x-intake/follow-ups?threshold_hours=0.01")
        d = r.json()
        assert d["count"] == 1
        assert d["follow_ups"][0]["threshold_hours_used"] == pytest.approx(0.01, rel=0.01)

    def test_no_override_uses_relationship_defaults(self, client):
        """Without threshold_hours, each contact uses its rel-type default."""
        rows = [
            self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="client"),   # 3h, threshold 2h → surfaces
            self._row(2, "+13***02", THREE_HOURS_AGO, rel_type="vendor"),   # 3h, threshold 6h → not yet
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["count"] == 1
        assert d["follow_ups"][0]["contact_masked"] == "+13***01"

    # ── Priority sorting ─────────────────────────────────────────────────────

    def test_sorted_by_priority_then_oldest_overdue(self, client):
        """urgent client must appear before medium vendor even if vendor is older."""
        rows = [
            # vendor, 7h old → medium priority, 1h overdue
            self._row(1, "+13***01", SEVEN_HOURS_AGO,   rel_type="vendor"),
            # client, 3h old → urgent priority, 1h overdue
            self._row(2, "+13***02", THREE_HOURS_AGO,   rel_type="client"),
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["count"] == 2
        priorities = [f["priority"] for f in d["follow_ups"]]
        assert priorities[0] == "urgent", f"urgent must come first: {priorities}"
        assert priorities[1] == "medium"

    def test_same_priority_sorted_oldest_overdue_first(self, client):
        """Within same priority, most-overdue item appears first."""
        rows = [
            # Both clients, so both urgent; one is more overdue
            self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="client"),   # 1h overdue
            self._row(2, "+13***02", SIX_HOURS_AGO,   rel_type="client"),   # 4h overdue
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["count"] == 2
        assert d["follow_ups"][0]["contact_masked"] == "+13***02", (
            "More-overdue contact must come first within same priority"
        )

    # ── Response fields ─────────────────────────────────────────────────────

    def test_response_includes_priority_fields(self, client):
        """All new priority fields must be present in the response."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="client")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        fu = r.json()["follow_ups"][0]
        assert "priority"             in fu, "priority field required"
        assert "relationship_type"    in fu, "relationship_type field required"
        assert "threshold_hours_used" in fu, "threshold_hours_used field required"
        assert "overdue_by_hours"     in fu, "overdue_by_hours field required"
        assert fu["priority"] == "urgent"
        assert fu["relationship_type"] == "client"
        assert fu["threshold_hours_used"] == 2.0
        assert fu["overdue_by_hours"] >= 0.9

    # ── Core follow-up logic (preserved from v1) ─────────────────────────────

    def test_message_without_approval_triggers_follow_up(self, client):
        """3-hour-old client message with no approval → follow-up returned."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO, rel_type="client")
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["status"] == "ok"
        assert d["count"] == 1
        fu = d["follow_ups"][0]
        assert fu["contact_masked"] == "+13***01"
        assert fu["has_approved_reply"] is False
        assert fu["has_draft_reply"] is True
        assert fu["elapsed_hours"] >= 2.9

    def test_approved_reply_after_message_clears_follow_up(self, client):
        """Approval timestamp > message timestamp → follow-up cleared."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO)
        approvals = {"+13***01": NOW - 1800}  # approved 30 min ago (after 3h message)
        p1, p2 = self._patch([row], approvals)
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 0, "Approved reply should clear the follow-up"

    def test_approval_before_message_does_not_clear(self, client):
        """Approval timestamp < message timestamp → still needs follow-up."""
        msg_ts      = NOW - 3 * 3600
        approval_ts = NOW - 4 * 3600  # approval came BEFORE this message
        row = self._row(1, "+13***01", msg_ts)
        approvals = {"+13***01": approval_ts}
        p1, p2 = self._patch([row], approvals)
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 1, "Old approval should not clear a newer message"

    def test_threshold_respected_recent_message_excluded(self, client):
        """30-minute-old message with 2h threshold → NOT a follow-up yet."""
        row = self._row(1, "+13***01", THIRTY_MINS_AGO)
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 0, "Message within threshold must not surface"

    def test_threshold_custom_value(self, client):
        """threshold_hours=0.1 (6 min) → 30-min-old message is overdue."""
        row = self._row(1, "+13***01", THIRTY_MINS_AGO)
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=0.1")
        d = r.json()
        assert d["count"] == 1

    # ── Deduplication ─────────────────────────────────────────────────────────

    def test_no_duplicate_entries_same_contact(self, client):
        """Same contact with multiple messages → only one follow-up entry."""
        rows = [
            self._row(1, "+13***01", SIX_HOURS_AGO,   "older draft"),
            self._row(2, "+13***01", THREE_HOURS_AGO,  "newer draft"),
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 1, "Same contact should only appear once"
        assert d["follow_ups"][0]["queue_item_id"] == 2, "Most recent message wins"
        assert "newer draft" in d["follow_ups"][0]["draft_reply"]

    def test_different_contacts_each_appear(self, client):
        """Two different contacts each overdue → two follow-up entries."""
        rows = [
            self._row(1, "+13***01", THREE_HOURS_AGO),
            self._row(2, "+13***02", SIX_HOURS_AGO),
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 2
        contacts = {f["contact_masked"] for f in d["follow_ups"]}
        assert "+13***01" in contacts
        assert "+13***02" in contacts

    def test_sorted_oldest_first(self, client):
        """Results must be sorted oldest-first (most overdue at top)."""
        rows = [
            self._row(1, "+13***01", THREE_HOURS_AGO),   # 3h ago
            self._row(2, "+13***02", SIX_HOURS_AGO),     # 6h ago (older)
        ]
        p1, p2 = self._patch(rows, {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        assert d["count"] == 2
        assert d["follow_ups"][0]["contact_masked"] == "+13***02", "Oldest must be first"
        assert d["follow_ups"][1]["contact_masked"] == "+13***01"

    # ── Response shape ────────────────────────────────────────────────────────

    def test_response_fields_present(self, client):
        """Each follow-up must include all required fields."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO)
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        d = r.json()
        fu = d["follow_ups"][0]
        required = {
            "queue_item_id", "contact_masked", "created_at",
            "has_context_card", "has_draft_reply", "has_approved_reply",
            "draft_reply", "confidence", "profile",
            "suggested_next_action", "elapsed_seconds", "elapsed_hours",
        }
        missing = required - set(fu.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_sender_guid_not_in_response(self, client):
        """sender_guid must never appear in the API response."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO)
        p1, p2 = self._patch([row], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups?threshold_hours=2")
        import re as _re
        raw = json.dumps(r.json())
        # sender_guid key must not appear
        assert "sender_guid" not in raw
        # raw E.164 phone must not appear
        assert not _re.search(r"\+1\d{10}", raw), "Raw phone must not appear in response"

    def test_empty_queue_returns_ok(self, client):
        p1, p2 = self._patch([], {})
        with p1, p2:
            r = client.get("/api/x-intake/follow-ups")
        d = r.json()
        assert d["status"] == "ok"
        assert d["count"] == 0
        assert d["follow_ups"] == []

    def test_no_send_triggered(self, client):
        """Endpoint is read-only — no writes or sends must occur."""
        row = self._row(1, "+13***01", THREE_HOURS_AGO)
        writes = []
        orig_write = __import__("cortex.engine", fromlist=["_write_approval_record"])._write_approval_record
        with patch("cortex.engine._write_approval_record", side_effect=lambda r: writes.append(r)), \
             patch("cortex.engine._queue_rows_with_context", return_value=[row]), \
             patch("cortex.engine._approvals_index", return_value={}):
            client.get("/api/x-intake/follow-ups?threshold_hours=2")
        assert writes == [], "GET follow-ups must not write any approval records"
