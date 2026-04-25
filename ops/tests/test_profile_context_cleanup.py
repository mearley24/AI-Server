"""Regression tests for profile context cleanup after fact quality audit.

Covers:
  - profile.open_requests emptied when underlying request fact is rejected
  - profile.follow_ups emptied when underlying follow_up fact is rejected
  - accepted equipment (Sonos) with no accepted issues/requests → Sonos self-fix draft
  - rejected facts absent from context card JSON at every level
  - simulate-incoming respects same cleanup
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.engine import _build_draft_with_context


# ── Helpers ────────────────────────────────────────────────────────────────────

def _profile(**kw):
    base = {
        "relationship_type": "client",
        "open_requests":     [],
        "follow_ups":        [],
        "systems_or_topics": [],
        "summary":           "",
        "confidence":        0.80,
    }
    base.update(kw)
    return base


def _fact(ftype, val, accepted=True, rejected=False):
    return {
        "fact_id":          f"fid_{ftype[:3]}",
        "fact_type":        ftype,
        "fact_value":       val,
        "confidence":       0.75,
        "source_excerpt":   "x",
        "source_timestamp": "2026-01-01T00:00:00+00:00",
        "is_accepted":      1 if accepted else 0,
        "is_rejected":      1 if rejected  else 0,
    }


def _profile_row(**kw):
    """Simulate a row from the profiles table (may contain stale columns)."""
    import json
    base = {
        "profile_id":        "prof_test",
        "relationship_type": "client",
        "display_name":      "",
        "contact_handle":    "+15551234567",
        "thread_ids":        '["tid1"]',
        "first_seen":        "2026-01-01T00:00:00+00:00",
        "last_seen":         "2026-04-25T00:00:00+00:00",
        "summary":           "Systems: Sonos, WiFi",
        # Stale columns that may still contain rejected fact values
        "open_requests":     json.dumps(["give me call as soon as you can as am trying to setup the WiFi network and need"]),
        "follow_ups":        json.dumps(["Let me know"]),
        "systems_or_topics": json.dumps(["Sonos", "WiFi", "network"]),
        "project_refs":      json.dumps([]),
        "dtools_project_refs": json.dumps([]),
        "confidence":        0.85,
        "status":            "proposed",
        "last_updated":      "2026-04-25T00:00:00+00:00",
    }
    base.update({k: v if isinstance(v, str) else __import__("json").dumps(v)
                 for k, v in kw.items()})
    return base


# ── Draft builder: accepted_equip-only with Sonos ─────────────────────────────

class TestAcceptedEquipOnlyDraft:
    """When only equipment/system facts are accepted (no issues, no requests),
    the draft builder must still use capability-aware self-fix wording."""

    def test_sonos_equipment_only_produces_self_fix_draft(self):
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
        }
        # Profile cleaned: no open_requests, no follow_ups
        r = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = r["draft_reply"]
        assert "unplug" in draft.lower() or "10 seconds" in draft.lower(), (
            f"Sonos equipment-only should suggest power cycle: {draft}"
        )
        assert "swing by" in draft.lower() or "take a look" in draft.lower(), (
            f"Sonos equipment-only should offer on-site: {draft}"
        )
        assert "remotely" not in draft.lower(), (
            f"Sonos must not mention remote access: {draft}"
        )
        assert r["draft_quality_status"] == "pass"

    def test_sonos_equipment_only_exact_wording(self):
        """Exact regression check against the expected output."""
        accepted = {"equipment": [_fact("equipment", "Sonos")]}
        r = _build_draft_with_context(_profile(), accepted, {}, [])
        expected_fragments = [
            "try unplugging your Sonos",
            "10 seconds",
            "swing by",
        ]
        draft = r["draft_reply"]
        for frag in expected_fragments:
            assert frag in draft, f"Expected '{frag}' in draft: {draft}"

    def test_wifi_equipment_only_suggests_reboot_or_remote(self):
        accepted = {"system": [_fact("system", "WiFi")]}
        r = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = r["draft_reply"]
        helpful = ["router", "remotely", "reboot", "check"]
        assert any(p in draft.lower() for p in helpful), (
            f"WiFi equipment-only should mention router/remote: {draft}"
        )
        assert r["draft_quality_status"] == "pass"

    def test_control4_equipment_only_offers_remote(self):
        accepted = {"equipment": [_fact("equipment", "Control4")]}
        r = _build_draft_with_context(_profile(), accepted, {}, [])
        assert "remotely" in r["draft_reply"].lower(), (
            f"Control4 should offer remote check: {r['draft_reply']}"
        )

    def test_unknown_equipment_only_neutral(self):
        accepted = {"equipment": [_fact("equipment", "SomeUnknownBox")]}
        r = _build_draft_with_context(_profile(), accepted, {}, [])
        assert r["draft_quality_status"] == "pass"
        # Unknown → passive check-in, no specific fix
        assert "unplug" not in r["draft_reply"].lower()
        assert "router" not in r["draft_reply"].lower()


# ── Profile context cleanup (context-card endpoint) ───────────────────────────

class TestProfileContextCleanup:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _nonrejected_facts(self):
        """The post-audit accepted facts: only Sonos, WiFi, network."""
        return [
            _fact("equipment", "Sonos",   accepted=True,  rejected=False),
            _fact("system",    "WiFi",    accepted=True,  rejected=False),
            _fact("system",    "network", accepted=True,  rejected=False),
        ]

    def test_open_requests_not_populated_from_rejected_request(self, client):
        """profile.open_requests must be empty when all request facts are rejected."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        assert d["status"] == "ok"
        open_reqs = d["profile"]["open_requests"]
        assert open_reqs == [], (
            f"open_requests must be empty when all request facts are rejected: {open_reqs}"
        )
        messy = "give me call as soon as you can"
        assert not any(messy in v for v in open_reqs), (
            f"Rejected messy request must not appear in open_requests: {open_reqs}"
        )

    def test_follow_ups_not_populated_from_rejected_follow_up(self, client):
        """profile.follow_ups must be empty when all follow_up facts are rejected."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        follow_ups = d["profile"]["follow_ups"]
        assert follow_ups == [], (
            f"follow_ups must be empty when all follow_up facts are rejected: {follow_ups}"
        )
        assert "Let me know" not in follow_ups, "Rejected generic follow_up must not appear"

    def test_valid_equipment_facts_still_accepted(self, client):
        """After audit: Sonos, WiFi, network remain in accepted_facts."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        accepted = d["accepted_facts"]
        equip = [f["fact_value"] for f in accepted.get("equipment", [])]
        sys_  = [f["fact_value"] for f in accepted.get("system", [])]
        assert "Sonos"   in equip, f"Sonos must be in accepted equipment: {equip}"
        assert "WiFi"    in sys_,  f"WiFi must be in accepted system: {sys_}"
        assert "network" in sys_,  f"network must be in accepted system: {sys_}"

    def test_draft_uses_sonos_self_fix_when_only_equipment_accepted(self, client):
        """The core regression: Sonos equipment → power-cycle draft, not generic fallback."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        draft = d["draft_reply"]
        # Must not be the generic "thanks for the heads up" fallback
        generic_fallback = "Thanks for the heads up"
        assert generic_fallback not in draft, (
            f"Draft must not use generic fallback when Sonos is accepted: {draft}"
        )
        # Must suggest Sonos self-fix
        assert "unplug" in draft.lower() or "10 seconds" in draft.lower(), (
            f"Sonos draft must suggest power cycle: {draft}"
        )
        assert d["draft_quality_status"] == "pass"

    def test_no_stale_request_fragment_anywhere_in_response(self, client):
        """The messy request fragment must not appear anywhere in the context card."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        import json
        raw = json.dumps(r.json())
        fragment = "give me call"
        assert fragment not in raw.lower(), (
            f"Rejected fragment '{fragment}' must not appear anywhere in response"
        )

    def test_simulate_incoming_also_cleans_profile(self, client):
        """simulate-incoming must apply the same profile cleanup."""
        with patch("cortex.engine._profile_by_handle", return_value=_profile_row()), \
             patch("cortex.engine._facts_for_profile",
                   return_value=self._nonrejected_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": "+15551234567",
                "message_text":   "Sonos is acting up again",
            })
        d = r.json()
        assert d["status"] == "ok"
        assert d["profile"]["open_requests"] == [], (
            f"simulate open_requests must be clean: {d['profile']['open_requests']}"
        )
        assert d["profile"]["follow_ups"] == [], (
            f"simulate follow_ups must be clean: {d['profile']['follow_ups']}"
        )
        draft = d["draft_reply"]
        assert "give me call" not in draft.lower()
        assert "Thanks for the heads up" not in draft
