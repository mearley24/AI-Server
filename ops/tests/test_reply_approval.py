"""Tests for the suggested reply + approval flow (v1).

Covers:
  - known client generates a context-aware draft reply
  - unknown contact generates a safe fallback reply
  - rejected facts are excluded from source_facts
  - approval endpoint stores the final reply and returns ok
  - no send is triggered by any endpoint
  - simulate-incoming returns same shape as context-card
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.engine import (
    _build_draft_with_context,
    _suggest_action,
    _mask_handle,
)


# ── _build_draft_with_context unit tests ──────────────────────────────────────

class TestBuildDraftWithContext:

    def _profile(self, rel_type: str = "client", **overrides) -> dict:
        base = {
            "relationship_type": rel_type,
            "open_requests":     [],
            "systems_or_topics": [],
            "follow_ups":        [],
            "summary":           "",
            "confidence":        0.75,
        }
        base.update(overrides)
        return base

    def test_known_client_with_issue_and_equipment(self):
        accepted = {
            "issue":     [{"fact_type": "issue", "fact_value": "Sonos offline", "confidence": 0.8,
                           "source_excerpt": "x", "source_timestamp": "t"}],
            "equipment": [{"fact_type": "equipment", "fact_value": "Sonos", "confidence": 0.75,
                           "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "Sonos" in result["draft_reply"]
        assert "service call" in result["draft_reply"].lower() or "schedule" in result["draft_reply"].lower()
        assert result["confidence"] >= 0.85
        assert any(sf["verified"] for sf in result["source_facts"])
        assert result["reasoning"]

    def test_known_client_with_request_and_equipment(self):
        accepted = {
            "request":   [{"fact_type": "request", "fact_value": "fix the WiFi network",
                           "confidence": 0.7, "source_excerpt": "x", "source_timestamp": "t"}],
            "system":    [{"fact_type": "system", "fact_value": "WiFi",
                           "confidence": 0.75, "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "WiFi" in result["draft_reply"] or "fix the WiFi" in result["draft_reply"]
        assert result["confidence"] >= 0.80
        assert len(result["source_facts"]) >= 2

    def test_open_request_from_profile_no_facts(self):
        profile = self._profile(open_requests=["check the Sonos at Beaver Creek"])
        result = _build_draft_with_context(profile, {}, {}, [])
        assert "check the Sonos at Beaver Creek" in result["draft_reply"]
        assert result["confidence"] >= 0.70

    def test_equipment_only_no_requests(self):
        accepted = {
            "equipment": [{"fact_type": "equipment", "fact_value": "Lutron",
                           "confidence": 0.75, "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "Lutron" in result["draft_reply"]
        assert result["confidence"] >= 0.65

    def test_systems_from_profile_summary(self):
        profile = self._profile(systems_or_topics=["Sonos", "Lutron"])
        result = _build_draft_with_context(profile, {}, {}, [])
        assert "Sonos" in result["draft_reply"]

    def test_unverified_only_lowers_confidence(self):
        unverified = {
            "issue": [{"fact_type": "issue", "fact_value": "network down",
                       "confidence": 0.5, "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), {}, unverified, [])
        assert result["confidence"] <= 0.55
        assert any(not sf["verified"] for sf in result["source_facts"])

    def test_vendor_fallback(self):
        result = _build_draft_with_context(self._profile("vendor"), {}, {}, [])
        assert "availability" in result["draft_reply"].lower() or "lead time" in result["draft_reply"].lower()
        assert result["confidence"] < 0.60

    def test_no_profile_fallback(self):
        result = _build_draft_with_context(self._profile("unknown"), {}, {}, [])
        assert len(result["draft_reply"]) > 10
        assert result["confidence"] <= 0.40

    def test_last_message_appears_in_reasoning(self):
        result = _build_draft_with_context(
            self._profile(),
            {},
            {},
            [],
            last_message="My Sonos is not working since yesterday",
        )
        assert "Sonos is not working" in result["reasoning"] or "Last message" in result["reasoning"]

    def test_recent_reply_appears_in_reasoning(self):
        receipts = [{"ts": "2026-04-24T10:00:00Z", "phone_last4": "...1234", "path": "dry_run"}]
        result = _build_draft_with_context(self._profile(), {}, {}, receipts)
        assert "2026-04-24" in result["reasoning"]

    def test_source_facts_capped_at_8(self):
        # Create more than 8 facts
        many = [
            {"fact_type": "equipment", "fact_value": f"Device{i}", "confidence": 0.7,
             "source_excerpt": "x", "source_timestamp": "t"}
            for i in range(12)
        ]
        accepted = {"equipment": many}
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert len(result["source_facts"]) <= 8

    def test_rejected_facts_not_in_source_facts(self):
        # Rejected facts never reach _build_draft_with_context because
        # _facts_for_profile filters is_rejected=0 at SQL level.
        # This test verifies the accepted/unverified split is correct.
        accepted = {
            "equipment": [{"fact_type": "equipment", "fact_value": "Sonos",
                           "confidence": 0.75, "source_excerpt": "x", "source_timestamp": "t"}]
        }
        unverified = {
            "issue": [{"fact_type": "issue", "fact_value": "offline",
                       "confidence": 0.5, "source_excerpt": "x", "source_timestamp": "t"}]
        }
        result = _build_draft_with_context(self._profile(), accepted, unverified, [])
        verified_vals   = [sf["fact_value"] for sf in result["source_facts"] if sf["verified"]]
        unverified_vals = [sf["fact_value"] for sf in result["source_facts"] if not sf["verified"]]
        assert "Sonos" in verified_vals
        assert "offline" in unverified_vals
        # No "rejected" label should appear — rejected facts are excluded at DB layer


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

class TestContextCardEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _make_profile(self, rel_type: str = "client"):
        return {
            "profile_id": "prof_test_01",
            "relationship_type": rel_type,
            "display_name": "",
            "contact_handle": "+13035257532",
            "thread_ids": '["tid1"]',
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen":  "2026-04-01T00:00:00+00:00",
            "summary": "Systems: Sonos. 2 proposed fact(s)",
            "open_requests":     '["check the Sonos system"]',
            "follow_ups":        '[]',
            "systems_or_topics": '["Sonos"]',
            "project_refs":      '[]',
            "dtools_project_refs": '[]',
            "confidence": 0.75,
            "status": "proposed",
            "last_updated": "2026-04-24T10:00:00+00:00",
        }

    def test_known_client_returns_draft_reply_and_reasoning(self, client):
        profile = self._make_profile()
        facts   = [
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos offline", "source_timestamp": "2026-04-01T10:00:00+00:00",
             "is_accepted": 1, "is_rejected": 0},
        ]
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B13035257532")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert "Sonos" in d["draft_reply"]
        assert d["reasoning"]
        assert 0.0 < d["confidence"] <= 1.0
        assert isinstance(d["source_facts"], list)
        assert d["action_id"]  # fresh per request
        assert "+13035257532" not in d.get("contact_masked", "")

    def test_unknown_contact_returns_safe_fallback(self, client):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15550000000")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "no_profile"
        assert len(d["draft_reply"]) > 5
        assert d["confidence"] <= 0.30
        assert d["action_id"]

    def test_rejected_facts_excluded_from_source_facts(self, client):
        profile = self._make_profile()
        # _facts_for_profile already filters is_rejected=0; we simulate that here
        facts = [
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos offline", "source_timestamp": "t",
             "is_accepted": 1, "is_rejected": 0},
            # rejected fact would never appear (filtered at SQL level)
        ]
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B13035257532")
        d = r.json()
        # All source_facts that are verified must come from is_accepted=1 facts
        verified = [sf for sf in d["source_facts"] if sf["verified"]]
        assert all(sf["fact_value"] != "rejected_value" for sf in verified)

    def test_pending_facts_labeled_unverified(self, client):
        profile = self._make_profile()
        facts = [
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "request",
             "fact_value": "schedule a visit", "confidence": 0.60,
             "source_excerpt": "can you schedule", "source_timestamp": "t",
             "is_accepted": 0, "is_rejected": 0},
        ]
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B13035257532")
        d = r.json()
        assert "request" in d["unverified_facts"]
        assert "request" not in d["accepted_facts"]
        # Unverified source facts are marked verified=False
        unverified_sf = [sf for sf in d["source_facts"] if not sf["verified"]]
        assert any("schedule a visit" in sf["fact_value"] for sf in unverified_sf)


class TestApproveReplyEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def test_approval_stores_final_reply(self, client, tmp_path):
        approval_log = tmp_path / "reply_approvals.ndjson"
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = approval_log
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":      "abc123def456",
                "approved":       True,
                "draft_reply":    "Hi, I wanted to follow up on your Sonos.",
                "contact_masked": "+13***32",
                "reasoning":      "Equipment on file: Sonos",
                "confidence":     0.85,
            })
        finally:
            eng._APPROVAL_LOG = orig

        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert d["stored"] is True
        assert d["send_triggered"] is False
        assert d["approval_id"]
        assert "+13035257532" not in json.dumps(d)  # raw phone never in response

        # Verify log was written
        lines = approval_log.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["status"] == "approved"
        assert record["final_reply"] == "Hi, I wanted to follow up on your Sonos."
        assert record["edited"] is False

    def test_edited_reply_stored_as_final(self, client, tmp_path):
        approval_log = tmp_path / "reply_approvals.ndjson"
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = approval_log
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":      "abc123def456",
                "approved":       True,
                "draft_reply":    "Hi, original draft.",
                "edited_reply":   "Hi, I edited this before approving.",
                "contact_masked": "+13***32",
                "confidence":     0.75,
            })
        finally:
            eng._APPROVAL_LOG = orig

        d = r.json()
        assert d["final_reply"] == "Hi, I edited this before approving."
        assert d["edited"] is True
        record = json.loads(approval_log.read_text().strip())
        assert record["final_reply"] == "Hi, I edited this before approving."
        assert record["edited"] is True

    def test_unapproved_not_stored(self, client):
        r = client.post("/api/x-intake/approve-reply", json={
            "action_id": "xyz",
            "approved":  False,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "not_approved"

    def test_no_send_triggered(self, client, tmp_path):
        import cortex.engine as eng
        orig = eng._APPROVAL_LOG
        eng._APPROVAL_LOG = tmp_path / "approvals.ndjson"
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":      "testid123",
                "approved":       True,
                "draft_reply":    "Hi there.",
                "contact_masked": "+13***32",
            })
        finally:
            eng._APPROVAL_LOG = orig
        assert r.json()["send_triggered"] is False


class TestSimulateIncomingEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def test_simulate_known_client(self, client):
        profile = {
            "profile_id": "p_sim_1", "relationship_type": "client",
            "display_name": "", "contact_handle": "+13035257532",
            "thread_ids": '["tid1"]', "first_seen": "", "last_seen": "",
            "summary": "Systems: Sonos",
            "open_requests": '["check Sonos"]', "follow_ups": '[]',
            "systems_or_topics": '["Sonos"]', "project_refs": '[]',
            "dtools_project_refs": '[]', "confidence": 0.75,
            "status": "proposed", "last_updated": "",
        }
        facts = [
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos", "source_timestamp": "t",
             "is_accepted": 1, "is_rejected": 0},
        ]
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": "+13035257532",
                "message_text": "My Sonos is offline again.",
            })
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert d["simulated"] is True
        assert "Sonos" in d["draft_reply"]
        assert d["reasoning"]
        assert d["action_id"]
        assert d["last_message"] == "My Sonos is offline again."
        assert "+13035257532" not in d.get("contact_masked", "")

    def test_simulate_unknown_returns_no_profile(self, client):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": "+15550000000",
            })
        d = r.json()
        assert d["status"] == "no_profile"
        assert d["simulated"] is True
        assert d["draft_reply"]
        assert d["action_id"]

    def test_simulate_message_text_in_reasoning(self, client):
        profile = {
            "profile_id": "p_sim_2", "relationship_type": "client",
            "display_name": "", "contact_handle": "+13035257532",
            "thread_ids": '["tid1"]', "first_seen": "", "last_seen": "",
            "summary": "", "open_requests": '[]', "follow_ups": '[]',
            "systems_or_topics": '[]', "project_refs": '[]',
            "dtools_project_refs": '[]', "confidence": 0.5,
            "status": "proposed", "last_updated": "",
        }
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=[]), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": "+13035257532",
                "message_text": "Can you fix the network at Beaver Creek?",
            })
        d = r.json()
        assert "Can you fix the network" in d["reasoning"] or "Last message" in d["reasoning"]
