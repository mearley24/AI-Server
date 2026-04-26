"""Tests for the Reply Suggestion Inbox endpoints.

Covers:
  - GET /api/reply/suggestions/pending returns empty list when queue is empty
  - pending endpoint returns correct shape fields
  - no raw phone numbers exposed in pending response
  - no live send occurs on approve-reply
  - approve-reply writes dry-run receipt only
  - POST /api/reply/regenerate with missing queue_item_id returns error
  - POST /api/reply/regenerate with unknown queue_item_id returns error
  - approve-reply stores approval but send_triggered=False
  - approve-reply blocked on empty draft
  - pending suggestions count field matches suggestions list length
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────────

# Keys that hold hex tokens / IDs — never phone numbers, skip them.
_SKIP_KEYS = {"action_id", "approval_id", "queue_item_id", "recipient_hash"}


def _no_raw_phone(obj: Any, path: str = "") -> list[str]:
    """Recursively find strings containing 7+ consecutive digits (raw phone indicators).

    Skips ID fields (action_id, approval_id, etc.) which are hex tokens.
    """
    hits: list[str] = []
    if isinstance(obj, str):
        if re.search(r"\d{7,}", obj):
            hits.append(f"{path}={obj!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS:
                continue
            hits.extend(_no_raw_phone(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_no_raw_phone(v, f"{path}[{i}]"))
    return hits


# ── TestPendingSuggestionsEndpoint ─────────────────────────────────────────────

class TestPendingSuggestionsEndpoint:
    """Integration-style tests that call the endpoint functions directly."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_empty_when_no_follow_ups(self):
        """When _compute_follow_ups returns [], endpoint returns count=0."""
        import cortex.engine as eng
        with patch.object(eng, "_compute_follow_ups", return_value=[]):
            result = self._run(eng.reply_suggestions_pending())
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["suggestions"] == []

    def test_returns_correct_shape(self):
        """Each suggestion has the required fields."""
        import cortex.engine as eng
        fake_item = {
            "queue_item_id":         42,
            "contact_masked":        "+13***32",
            "created_at":            1714000000,
            "relationship_type":     "client",
            "has_context_card":      True,
            "has_draft_reply":       True,
            "draft_reply":           "Got it — I'll check on that.",
            "confidence":            0.75,
            "draft_quality_status":  "pass",
            "profile":               {"display_name": "Test Client", "systems_or_topics": ["Sonos"], "relationship_type": "client"},
            "suggested_next_action": "Follow up on shades",
            "priority":              "urgent",
            "priority_rank":         0,
            "overdue_by_hours":      3.5,
            "elapsed_hours":         5.5,
        }
        with patch.object(eng, "_compute_follow_ups", return_value=[fake_item]):
            with patch.object(eng, "_active_rules_summary", return_value=[]):
                result = self._run(eng.reply_suggestions_pending())
        assert result["status"] == "ok"
        assert result["count"] == 1
        s = result["suggestions"][0]
        required = [
            "action_id", "queue_item_id", "contact_masked", "relationship_type",
            "display_name", "systems_or_topics", "suggested_reply", "confidence",
            "draft_quality_status", "draft_quality_reasons", "active_rules_applied",
            "suggested_next_action", "created_at", "follow_up_priority",
            "overdue_by_hours", "elapsed_hours",
        ]
        for field in required:
            assert field in s, f"Missing field: {field}"

    def test_priority_rank_stripped(self):
        """priority_rank (internal) must not appear in suggestions."""
        import cortex.engine as eng
        fake_item = {
            "queue_item_id":        1,
            "contact_masked":       "+13***32",
            "created_at":           1714000000,
            "relationship_type":    "client",
            "has_context_card":     True,
            "has_draft_reply":      True,
            "draft_reply":          "Ok.",
            "confidence":           0.5,
            "draft_quality_status": "pass",
            "profile":              {},
            "suggested_next_action":"",
            "priority":             "high",
            "priority_rank":        1,
            "overdue_by_hours":     1.0,
            "elapsed_hours":        4.0,
        }
        with patch.object(eng, "_compute_follow_ups", return_value=[fake_item]):
            with patch.object(eng, "_active_rules_summary", return_value=[]):
                result = self._run(eng.reply_suggestions_pending())
        s = result["suggestions"][0]
        assert "priority_rank" not in s

    def test_no_raw_phone_in_response(self):
        """Full phone numbers must never appear in pending suggestions output."""
        import cortex.engine as eng
        fake_item = {
            "queue_item_id":         1,
            "contact_masked":        "+13***32",    # already masked
            "created_at":            1714000000,
            "relationship_type":     "client",
            "has_context_card":      True,
            "has_draft_reply":       True,
            "draft_reply":           "Got it.",
            "confidence":            0.7,
            "draft_quality_status":  "pass",
            "profile":               {"display_name": "Alice", "systems_or_topics": []},
            "suggested_next_action": "",
            "priority":              "urgent",
            "priority_rank":         0,
            "overdue_by_hours":      2.0,
            "elapsed_hours":         4.0,
        }
        with patch.object(eng, "_compute_follow_ups", return_value=[fake_item]):
            with patch.object(eng, "_active_rules_summary", return_value=[]):
                result = self._run(eng.reply_suggestions_pending())
        hits = _no_raw_phone(result)
        assert hits == [], f"Raw phone found: {hits}"

    def test_count_matches_suggestions_length(self):
        """count field must equal len(suggestions)."""
        import cortex.engine as eng
        def _make_item(n):
            return {
                "queue_item_id":         n,
                "contact_masked":        f"+13***{n:02d}",
                "created_at":            1714000000 + n,
                "relationship_type":     "client",
                "has_context_card":      True,
                "has_draft_reply":       True,
                "draft_reply":           "Ok.",
                "confidence":            0.6,
                "draft_quality_status":  "pass",
                "profile":               {},
                "suggested_next_action": "",
                "priority":              "medium",
                "priority_rank":         2,
                "overdue_by_hours":      1.0,
                "elapsed_hours":         5.0,
            }
        items = [_make_item(i) for i in range(3)]
        with patch.object(eng, "_compute_follow_ups", return_value=items):
            with patch.object(eng, "_active_rules_summary", return_value=[]):
                result = self._run(eng.reply_suggestions_pending())
        assert result["count"] == len(result["suggestions"])
        assert result["count"] == 3

    def test_limit_param_respected(self):
        """limit parameter caps the number of suggestions returned."""
        import cortex.engine as eng
        items = [
            {
                "queue_item_id": i, "contact_masked": f"+1***{i:02d}",
                "created_at": 1714000000 + i, "relationship_type": "client",
                "has_context_card": True, "has_draft_reply": True,
                "draft_reply": "Ok.", "confidence": 0.5,
                "draft_quality_status": "pass", "profile": {},
                "suggested_next_action": "", "priority": "low",
                "priority_rank": 3, "overdue_by_hours": 0.5, "elapsed_hours": 13.0,
            }
            for i in range(8)
        ]
        with patch.object(eng, "_compute_follow_ups", return_value=items):
            with patch.object(eng, "_active_rules_summary", return_value=[]):
                result = self._run(eng.reply_suggestions_pending(limit=3))
        assert result["count"] <= 3


# ── TestRegenerateEndpoint ──────────────────────────────────────────────────────

class TestRegenerateEndpoint:

    def _run(self, coro):
        return asyncio.run(coro)

    def test_missing_queue_item_id_returns_error(self):
        import cortex.engine as eng
        result = self._run(eng.reply_regenerate({}))
        assert result["status"] == "error"
        assert "queue_item_id" in result["error"]

    def test_unknown_queue_item_id_returns_error(self):
        """Non-existent queue_item_id returns error without raising."""
        import cortex.engine as eng
        # Patch DB lookup to return None
        with patch.object(eng, "_X_INTAKE_QUEUE_DB", Path("/nonexistent/queue.db")):
            result = self._run(eng.reply_regenerate({"queue_item_id": 999999}))
        assert result["status"] == "error"
        assert result["draft"] == ""
        assert result["confidence"] == 0.0

    def test_no_raw_phone_in_error_response(self):
        """Error paths must not leak raw phone numbers."""
        import cortex.engine as eng
        with patch.object(eng, "_X_INTAKE_QUEUE_DB", Path("/nonexistent/queue.db")):
            result = self._run(eng.reply_regenerate({"queue_item_id": 1}))
        hits = _no_raw_phone(result)
        assert hits == [], f"Raw phone in error response: {hits}"


# ── TestApproveReplyNeverSends ─────────────────────────────────────────────────

class TestApproveReplyNeverSends:
    """Verify approve-reply stores approval but never triggers a live send."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _call_approve(self, draft="Got it — checking now.", edited="", **kwargs):
        import cortex.engine as eng
        body = {
            "action_id":            "abc123",
            "approved":             True,
            "draft_reply":          draft,
            "edited_reply":         edited,
            "contact_masked":       "+13***32",
            "reasoning":            "test",
            "confidence":           0.75,
            "draft_quality_status": "pass",
        }
        body.update(kwargs)

        written = []
        receipts = []

        def _fake_write_approval(record):
            written.append(record)

        def _fake_write_receipt(approval_id, contact_masked, final_reply, action_type="approve_reply"):
            receipts.append({"approval_id": approval_id, "contact_masked": contact_masked,
                             "final_reply": final_reply, "action_type": action_type})

        with patch.object(eng, "_write_approval_record", side_effect=_fake_write_approval):
            with patch.object(eng, "_write_dry_run_receipt", side_effect=_fake_write_receipt):
                result = self._run(eng.x_intake_approve_reply(body))

        return result, written, receipts

    def test_approve_stores_approval(self):
        result, written, _ = self._call_approve()
        assert result["status"] == "ok"
        assert len(written) == 1
        assert written[0]["status"] == "approved"

    def test_send_triggered_is_false(self):
        result, _, _ = self._call_approve()
        assert result["send_triggered"] is False

    def test_send_dry_run_is_true(self):
        result, _, _ = self._call_approve()
        assert result["send_dry_run"] is True

    def test_writes_dry_run_receipt(self):
        result, _, receipts = self._call_approve()
        assert len(receipts) == 1
        assert receipts[0]["contact_masked"] == "+13***32"

    def test_no_raw_phone_in_approval_record(self):
        _, written, _ = self._call_approve()
        assert written
        hits = _no_raw_phone(written[0])
        assert hits == [], f"Raw phone in approval record: {hits}"

    def test_empty_draft_returns_error(self):
        result, written, _ = self._call_approve(draft="", edited="")
        assert result["status"] in ("error", "not_approved", "blocked")
        assert len(written) == 0

    def test_not_approved_is_noop(self):
        import cortex.engine as eng
        written = []
        with patch.object(eng, "_write_approval_record", side_effect=written.append):
            result = self._run(eng.x_intake_approve_reply({"approved": False}))
        assert result["status"] == "not_approved"
        assert len(written) == 0

    def test_edited_reply_used_as_final(self):
        result, written, receipts = self._call_approve(
            draft="Original.", edited="Edited version."
        )
        assert result["final_reply"] == "Edited version."
        assert written[0]["edited"] is True

    def test_no_raw_phone_in_response(self):
        result, _, _ = self._call_approve()
        hits = _no_raw_phone(result)
        assert hits == [], f"Raw phone in response: {hits}"
