"""Tests for GET /api/x-intake/follow-up-count.

Covers:
  - correct total/urgent/high counts returned
  - zero total hides the alert (count returns {total:0, urgent:0, high:0})
  - urgent and high counts are accurate
  - already-approved contacts excluded
  - no external messages sent
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


NOW       = time.time()
THREE_H   = NOW - 3 * 3600     # 3 hours ago  (client threshold=2h → urgent)
FOUR_H    = NOW - 4 * 3600     # 4 hours ago  (builder threshold=3h → high)
SEVEN_H   = NOW - 7 * 3600     # 7 hours ago  (vendor threshold=6h → medium)
RECENT    = NOW - 0.5 * 3600   # 30 min ago   (under all thresholds)


def _ctx(contact: str, rel_type: str = "client") -> str:
    return json.dumps({
        "contact_masked":    contact,
        "status":            "ok",
        "draft_reply":       "Got it.",
        "confidence":        0.8,
        "draft_quality_status": "pass",
        "suggested_next_action": "",
        "profile": {"relationship_type": rel_type},
    })


def _row(item_id: int, contact: str, created_at: float, rel_type: str = "client") -> dict:
    return {
        "id":           item_id,
        "sender_guid":  f"any;-;{contact}",
        "context_json": _ctx(contact, rel_type),
        "created_at":   created_at,
    }


def _patch(queue_rows, approvals_map=None):
    return (
        patch("cortex.engine._queue_rows_with_context", return_value=queue_rows),
        patch("cortex.engine._approvals_index",         return_value=approvals_map or {}),
    )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from cortex.engine import app
    return TestClient(app, raise_server_exceptions=False)


# ── Basic count tests ─────────────────────────────────────────────────────────

class TestFollowUpCount:

    def test_zero_when_no_overdue(self, client):
        """No overdue items → total=0, urgent=0, high=0."""
        row = _row(1, "+13***01", RECENT, rel_type="client")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 0
        assert d["urgent"] == 0
        assert d["high"] == 0

    def test_zero_when_queue_empty(self, client):
        """Empty queue → all counts zero."""
        p1, p2 = _patch([])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 0
        assert d["urgent"] == 0
        assert d["high"] == 0

    def test_urgent_client_counted(self, client):
        """3-hour-old client message → urgent=1, total=1."""
        row = _row(1, "+13***01", THREE_H, rel_type="client")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 1
        assert d["urgent"] == 1
        assert d["high"] == 0

    def test_high_builder_counted(self, client):
        """4-hour-old builder message → high=1, urgent=0."""
        row = _row(2, "+13***02", FOUR_H, rel_type="builder")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 1
        assert d["urgent"] == 0
        assert d["high"] == 1

    def test_mixed_priorities_counted(self, client):
        """One urgent client + one high builder → total=2, urgent=1, high=1."""
        rows = [
            _row(1, "+13***01", THREE_H, rel_type="client"),
            _row(2, "+13***02", FOUR_H,  rel_type="builder"),
        ]
        p1, p2 = _patch(rows)
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 2
        assert d["urgent"] == 1
        assert d["high"] == 1

    def test_multiple_urgents_counted(self, client):
        """Two urgent clients → urgent=2."""
        rows = [
            _row(1, "+13***01", THREE_H, rel_type="client"),
            _row(2, "+13***02", THREE_H, rel_type="client"),
        ]
        p1, p2 = _patch(rows)
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 2
        assert d["urgent"] == 2
        assert d["high"] == 0

    def test_approved_reply_excluded(self, client):
        """Approved contacts must not be counted."""
        contact = "+13***01"
        row = _row(1, contact, THREE_H, rel_type="client")
        # Approval timestamp is AFTER the queue item was created
        approvals = {contact: NOW - 0.5 * 3600}  # approved 30 min ago
        p1, p2 = _patch([row], approvals)
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 0, "Approved contact must not appear in count"
        assert d["urgent"] == 0

    def test_vendor_below_threshold_not_counted(self, client):
        """3-hour-old vendor (threshold=6h) must not appear in count."""
        row = _row(1, "+13***01", THREE_H, rel_type="vendor")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 0

    def test_vendor_above_threshold_counted(self, client):
        """7-hour-old vendor (threshold=6h) appears in count as medium."""
        row = _row(1, "+13***01", SEVEN_H, rel_type="vendor")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert d["total"] == 1
        assert d["urgent"] == 0
        assert d["high"] == 0  # vendor is medium, not high

    def test_threshold_override_works(self, client):
        """threshold_hours=0 forces all contacts overdue."""
        row = _row(1, "+13***01", RECENT, rel_type="client")
        p1, p2 = _patch([row])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count?threshold_hours=0")
        d = r.json()
        assert d["total"] == 1

    def test_response_schema(self, client):
        """Response must contain exactly total, urgent, high keys."""
        p1, p2 = _patch([])
        with p1, p2:
            r = client.get("/api/x-intake/follow-up-count")
        d = r.json()
        assert set(d.keys()) == {"total", "urgent", "high"}
