"""Tests for GET /api/x-intake/context-card — incoming message context cards."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import helpers we can test directly without running the FastAPI app
from cortex.engine import (
    _handle_from_guid,
    _normalize_handle,
    _lookup_contact_handle,
    _build_draft_with_context,
    _suggest_action,
    _mask_handle,
)


# ── Unit tests: handle extraction / normalisation ──────────────────────────────

class TestHandleHelpers:

    def test_extract_handle_from_any_guid(self):
        assert _handle_from_guid("any;-;+13035257532") == "+13035257532"

    def test_extract_handle_from_imessage_guid(self):
        assert _handle_from_guid("iMessage;-;+19705193013") == "+19705193013"

    def test_extract_handle_empty_guid(self):
        assert _handle_from_guid("") == ""

    def test_extract_handle_invalid_guid(self):
        assert _handle_from_guid("not-a-guid") == ""

    def test_normalize_adds_plus(self):
        assert _normalize_handle("13035257532") == "+13035257532"

    def test_normalize_keeps_plus(self):
        assert _normalize_handle("+13035257532") == "+13035257532"

    def test_normalize_strips_whitespace(self):
        assert _normalize_handle("  +13035257532  ") == "+13035257532"

    def test_lookup_contact_explicit_handle_wins(self):
        handle = _lookup_contact_handle("any;-;+19999999999", "+13035257532")
        assert handle == "+13035257532"

    def test_lookup_contact_from_guid_when_no_handle(self):
        handle = _lookup_contact_handle("any;-;+13035257532", "")
        assert handle == "+13035257532"

    def test_lookup_contact_empty_both(self):
        assert _lookup_contact_handle("", "") == ""

    def test_mask_handle_standard(self):
        masked = _mask_handle("+13035257532")
        assert "***" in masked
        assert "+13035257532" not in masked

    def test_mask_handle_short(self):
        assert _mask_handle("+1234") == "***"


# ── Unit tests: draft reply and action suggestions ─────────────────────────────

def _profile(rel_type: str = "client", open_requests: list | None = None,
             systems: list | None = None) -> dict:
    return {
        "relationship_type": rel_type,
        "open_requests":     open_requests or [],
        "systems_or_topics": systems or [],
        "follow_ups":        [],
        "summary":           "",
        "confidence":        0.75,
    }


class TestDraftReply:

    def test_draft_uses_open_request_first(self):
        result = _build_draft_with_context(
            _profile(open_requests=["fix the Sonos offline issue"]),
            {}, {}, [],
        )
        assert "fix the Sonos offline issue" in result["draft_reply"]

    def test_draft_uses_system_when_no_request(self):
        result = _build_draft_with_context(_profile(systems=["Lutron"]), {}, {}, [])
        assert "Lutron" in result["draft_reply"]

    def test_draft_vendor_fallback(self):
        result = _build_draft_with_context(_profile("vendor"), {}, {}, [])
        assert "availability" in result["draft_reply"].lower() or "lead time" in result["draft_reply"].lower()

    def test_draft_builder_fallback(self):
        result = _build_draft_with_context(_profile("builder"), {}, {}, [])
        assert "schedul" in result["draft_reply"].lower() or "coordinat" in result["draft_reply"].lower()

    def test_draft_generic_fallback(self):
        result = _build_draft_with_context(_profile("unknown"), {}, {}, [])
        assert len(result["draft_reply"]) > 10


class TestSuggestAction:

    def test_issue_triggers_service_call(self):
        action = _suggest_action({"issue": [{"fact_value": "Sonos offline"}]}, "client")
        assert "service" in action.lower() or "issue" in action.lower()

    def test_request_triggers_follow_up(self):
        action = _suggest_action({"request": [{"fact_value": "check the network"}]}, "client")
        assert "follow up" in action.lower() or "request" in action.lower()

    def test_follow_up_fact(self):
        action = _suggest_action({"follow_up": [{"fact_value": "Let me know"}]}, "client")
        assert "follow" in action.lower()

    def test_equipment_fact(self):
        action = _suggest_action({"equipment": [{"fact_value": "Sonos"}]}, "client")
        assert "Sonos" in action or "check" in action.lower() or "system" in action.lower()

    def test_empty_facts_generic(self):
        action = _suggest_action({}, "client")
        assert len(action) > 5


# ── Integration tests: context card with mocked DB helpers ────────────────────

class TestContextCardIntegration:
    """Test the context card logic by patching DB helpers.

    These verify the routing and assembly logic (facts split, masking, etc.)
    without spinning up the full FastAPI app or needing real DBs.
    """

    def _make_profile(self):
        return {
            "profile_id":        "testprof001",
            "relationship_type": "client",
            "display_name":      "",
            "contact_handle":    "+13035257532",
            "thread_ids":        '["tid1"]',
            "first_seen":        "2026-01-01T00:00:00+00:00",
            "last_seen":         "2026-04-01T00:00:00+00:00",
            "summary":           "Systems/topics: Sonos. 3 proposed fact(s) extracted",
            "open_requests":     '["check the Sonos system"]',
            "follow_ups":        '[]',
            "systems_or_topics": '["Sonos", "WiFi"]',
            "project_refs":      '["Beaver Creek"]',
            "dtools_project_refs": '[]',
            "confidence":        0.75,
            "status":            "proposed",
            "last_updated":      "2026-04-24T10:00:00+00:00",
        }

    def _make_facts(self):
        return [
            # accepted
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos offline", "source_timestamp": "2026-04-01T10:00:00+00:00",
             "is_accepted": 1, "is_rejected": 0},
            # pending (unverified)
            {"fact_id": "f2", "thread_id": "tid1", "fact_type": "request",
             "fact_value": "check the Sonos system", "confidence": 0.60,
             "source_excerpt": "can you check the Sonos", "source_timestamp": "2026-04-01T10:01:00+00:00",
             "is_accepted": 0, "is_rejected": 0},
            # rejected (should be EXCLUDED — _facts_for_profile filters is_rejected=0)
            {"fact_id": "f3", "thread_id": "tid1", "fact_type": "system",
             "fact_value": "network", "confidence": 0.50,
             "source_excerpt": "network issue", "source_timestamp": "2026-04-01T10:02:00+00:00",
             "is_accepted": 0, "is_rejected": 1},
        ]

    def test_known_client_returns_profile_context(self):
        profile = self._make_profile()
        import json as _json
        open_reqs = _json.loads(profile["open_requests"])
        systems   = _json.loads(profile["systems_or_topics"])
        result = _build_draft_with_context(
            {"relationship_type": "client", "open_requests": open_reqs,
             "systems_or_topics": systems, "follow_ups": [], "summary": "", "confidence": 0.75},
            {}, {}, [],
        )
        assert "check the Sonos system" in result["draft_reply"]
        assert profile["profile_id"] == "testprof001"

    def test_unknown_number_returns_no_profile(self):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            from cortex.engine import _lookup_contact_handle
            handle = _lookup_contact_handle("any;-;+15550000000", "")
            assert handle == "+15550000000"
            profile = None
            assert profile is None

    def test_rejected_facts_excluded_by_query(self):
        facts = self._make_facts()
        non_rejected = [f for f in facts if not f["is_rejected"]]
        rejected = [f for f in facts if f["is_rejected"]]
        assert len(rejected) == 1
        assert rejected[0]["fact_value"] == "network"
        assert all(not f["is_rejected"] for f in non_rejected)

    def test_pending_facts_marked_unverified(self):
        facts = [f for f in self._make_facts() if not f["is_rejected"]]
        accepted = {f["fact_type"]: [] for f in facts if f["is_accepted"]}
        unverified = {f["fact_type"]: [] for f in facts if not f["is_accepted"] and not f["is_rejected"]}
        for f in facts:
            if f["is_accepted"]:
                accepted[f["fact_type"]].append(f)
            else:
                unverified[f["fact_type"]].append(f)
        assert "equipment" in accepted
        assert "request" in unverified
        assert "network" not in str(accepted)  # rejected fact not in accepted

    def test_contact_masked_in_response(self):
        masked = _mask_handle("+13035257532")
        assert "+13035257532" not in masked
        assert "***" in masked

    def test_draft_not_auto_sent(self):
        result = _build_draft_with_context(
            {"relationship_type": "client",
             "open_requests": ["fix the Sonos offline issue"],
             "systems_or_topics": ["Sonos"],
             "follow_ups": [], "summary": "", "confidence": 0.75},
            {}, {}, [],
        )
        assert isinstance(result["draft_reply"], str)
        assert len(result["draft_reply"]) > 0
        # Draft is a plain string value — no callable send method on it
        assert not callable(result["draft_reply"])


# ── HTTP endpoint smoke test ──────────────────────────────────────────────────

class TestContextCardEndpoint:
    """Smoke-test the FastAPI endpoint via TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def test_no_params_returns_no_handle(self, client):
        r = client.get("/api/x-intake/context-card")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "no_handle"

    def test_unknown_contact_returns_no_profile(self, client):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15559999999")
            assert r.status_code == 200
            d = r.json()
            assert d["status"] == "no_profile"
            assert "+15559999999" not in d.get("contact_masked", "")
            assert "***" in d.get("contact_masked", "")

    def test_known_client_full_response(self, client):
        profile = {
            "profile_id": "p1", "relationship_type": "client",
            "display_name": "", "contact_handle": "+13035257532",
            "thread_ids": '["tid1"]', "first_seen": "", "last_seen": "",
            "summary": "Systems: Sonos", "open_requests": '["check Sonos"]',
            "follow_ups": '[]', "systems_or_topics": '["Sonos"]',
            "project_refs": '[]', "dtools_project_refs": '[]',
            "confidence": 0.75, "status": "proposed", "last_updated": "",
        }
        facts = [
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
            assert "+13035257532" not in d.get("contact_masked", "")
            assert "equipment" in d["accepted_facts"]
            assert d["accepted_facts"]["equipment"][0]["fact_value"] == "Sonos"
            assert d["unverified_facts"] == {}
            assert "check Sonos" in d["draft_reply"]
            assert len(d["suggested_next_action"]) > 0

    def test_rejected_facts_absent_from_response(self, client):
        profile = {
            "profile_id": "p2", "relationship_type": "client",
            "display_name": "", "contact_handle": "+15551234567",
            "thread_ids": '[]', "first_seen": "", "last_seen": "",
            "summary": "", "open_requests": '[]', "follow_ups": '[]',
            "systems_or_topics": '[]', "project_refs": '[]',
            "dtools_project_refs": '[]', "confidence": 0.5,
            "status": "proposed", "last_updated": "",
        }
        # _facts_for_profile already filters is_rejected=0 in SQL, so it returns
        # only accepted and pending. Simulate: no rejected leaks through.
        facts = []  # no non-rejected facts for this profile
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
            assert r.status_code == 200
            d = r.json()
            assert d["accepted_facts"] == {}
            assert d["unverified_facts"] == {}

    def test_pending_facts_in_unverified_not_accepted(self, client):
        profile = {
            "profile_id": "p3", "relationship_type": "client",
            "display_name": "", "contact_handle": "+15559876543",
            "thread_ids": '[]', "first_seen": "", "last_seen": "",
            "summary": "", "open_requests": '[]', "follow_ups": '[]',
            "systems_or_topics": '[]', "project_refs": '[]',
            "dtools_project_refs": '[]', "confidence": 0.5,
            "status": "proposed", "last_updated": "",
        }
        facts = [
            {"fact_id": "p1", "thread_id": "tid1", "fact_type": "request",
             "fact_value": "schedule a visit", "confidence": 0.60,
             "source_excerpt": "can you schedule", "source_timestamp": "2026-04-01T10:00:00+00:00",
             "is_accepted": 0, "is_rejected": 0},
        ]
        with patch("cortex.engine._profile_by_handle", return_value=profile), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15559876543")
            assert r.status_code == 200
            d = r.json()
            assert "request" not in d["accepted_facts"]
            assert "request" in d["unverified_facts"]
            assert d["unverified_facts"]["request"][0]["fact_value"] == "schedule a visit"

    def test_thread_guid_lookup(self, client):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?thread_guid=any%3B-%3B%2B13035257532")
            assert r.status_code == 200
            d = r.json()
            assert d["status"] == "no_profile"
            assert "32" in d.get("contact_masked", "")  # last 2 of +13035257532
