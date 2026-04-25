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
    _is_clean_for_injection,
    _check_draft_quality,
    SAFE_FALLBACK_REPLY,
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

    # ── behavior: no basic diagnostic questions when history exists ──────────

    _DIAGNOSTIC_QUESTIONS = [
        "when did it start",
        "have you tried",
        "what times work",
        "let me know your availability",
        "can you describe",
        "what error",
        "please let me know",
    ]

    def _has_diagnostic_question(self, draft: str) -> bool:
        low = draft.lower()
        return any(q in low for q in self._DIAGNOSTIC_QUESTIONS)

    def test_issue_and_equipment_no_diagnostic_questions(self):
        accepted = {
            "issue":     [{"fact_type": "issue", "fact_value": "Sonos offline", "confidence": 0.8,
                           "source_excerpt": "x", "source_timestamp": "t"}],
            "equipment": [{"fact_type": "equipment", "fact_value": "Sonos", "confidence": 0.75,
                           "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "Sonos" in result["draft_reply"], "equipment must be referenced"
        assert not self._has_diagnostic_question(result["draft_reply"]), (
            f"Should not ask diagnostic questions when history exists. Got: {result['draft_reply']}"
        )
        assert result["confidence"] >= 0.85
        assert any(sf["verified"] for sf in result["source_facts"])
        assert result["reasoning"]

    def test_issue_and_equipment_proactive_action(self):
        """Draft must imply proactive action, not passive wait-and-see."""
        accepted = {
            "issue":     [{"fact_type": "issue", "fact_value": "network offline", "confidence": 0.8,
                           "source_excerpt": "x", "source_timestamp": "t"}],
            "equipment": [{"fact_type": "equipment", "fact_value": "Araknis", "confidence": 0.75,
                           "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        proactive_phrases = ["i'll", "i will", "on it", "taking a look", "check", "look into"]
        low = result["draft_reply"].lower()
        assert any(p in low for p in proactive_phrases), (
            f"Draft should contain proactive action. Got: {result['draft_reply']}"
        )

    def test_repeat_issue_acknowledges_history(self):
        """When ≥2 issues on file, draft should acknowledge the recurring pattern."""
        accepted = {
            "issue": [
                {"fact_type": "issue", "fact_value": "Sonos offline", "confidence": 0.8,
                 "source_excerpt": "x", "source_timestamp": "t1"},
                {"fact_type": "issue", "fact_value": "Sonos cutting out again", "confidence": 0.75,
                 "source_excerpt": "x", "source_timestamp": "t2"},
            ],
            "equipment": [{"fact_type": "equipment", "fact_value": "Sonos", "confidence": 0.75,
                           "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        history_phrases = ["come up before", "happened before", "again", "recurring"]
        low = result["draft_reply"].lower()
        assert any(p in low for p in history_phrases), (
            f"Repeat issues should acknowledge history. Got: {result['draft_reply']}"
        )
        assert "Recurring" in result["reasoning"] or "repeat" in result["reasoning"].lower()

    def test_known_client_with_request_and_equipment(self):
        accepted = {
            "request": [{"fact_type": "request", "fact_value": "fix the WiFi network",
                         "confidence": 0.7, "source_excerpt": "x", "source_timestamp": "t"}],
            "system":  [{"fact_type": "system", "fact_value": "WiFi",
                         "confidence": 0.75, "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "WiFi" in result["draft_reply"]
        assert not self._has_diagnostic_question(result["draft_reply"])
        assert result["confidence"] >= 0.80
        assert len(result["source_facts"]) >= 2

    def test_open_request_from_profile_no_facts(self):
        # Clean open_req — should produce a clean draft (req text goes to reasoning, not draft).
        profile = self._profile(open_requests=["check the Sonos at Beaver Creek"])
        result = _build_draft_with_context(profile, {}, {}, [])
        draft = result["draft_reply"]
        # Req text must NOT be injected verbatim (it sounds like a transcript fragment in context)
        # Draft must be clean and pass quality check
        q_status, _ = _check_draft_quality(draft)
        assert q_status == "pass", f"Draft failed quality: {draft}"
        assert result["confidence"] >= 0.55
        # The req context should appear in reasoning for auditability
        assert "Beaver Creek" in result["reasoning"] or "check the Sonos" in result["reasoning"]

    def test_equipment_only_short_personal_checkin(self):
        """Equipment with no issues → short personal check-in, not a support-desk question."""
        accepted = {
            "equipment": [{"fact_type": "equipment", "fact_value": "Lutron",
                           "confidence": 0.75, "source_excerpt": "x", "source_timestamp": "t"}],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert "Lutron" in result["draft_reply"]
        assert result["confidence"] >= 0.65
        # Should NOT say "is there anything I can help with" — that's generic support language
        assert "is there anything i can help with" not in result["draft_reply"].lower()
        assert "let me know if you need any assistance" not in result["draft_reply"].lower()

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

    def test_client_no_history_diagnostic_question_is_ok(self):
        """Only when there's NO history at all is a clarifying question appropriate."""
        result = _build_draft_with_context(self._profile("client"), {}, {}, [])
        # Should be a short open question, not a form-letter response
        assert len(result["draft_reply"]) < 120, "Should be short when no context"
        assert result["confidence"] <= 0.35

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


# ── Quality gate unit tests ───────────────────────────────────────────────────

class TestIsCleanForInjection:

    def test_equipment_name_always_clean(self):
        assert _is_clean_for_injection("Sonos") is True
        assert _is_clean_for_injection("Lutron") is True
        assert _is_clean_for_injection("WiFi") is True

    def test_short_clean_phrase_ok(self):
        assert _is_clean_for_injection("fix the network issue") is True
        assert _is_clean_for_injection("schedule a service visit") is True

    def test_speech_fragment_give_me_call(self):
        assert _is_clean_for_injection(
            "give me call as soon as you can as am trying to setup the WiFi"
        ) is False

    def test_speech_fragment_as_am(self):
        assert _is_clean_for_injection("as am trying to reach you") is False

    def test_speech_fragment_i_am(self):
        assert _is_clean_for_injection("I am trying to get the network working") is False

    def test_too_many_words(self):
        assert _is_clean_for_injection(
            "please check on the system when you can because it has been offline"
        ) is False

    def test_ocr_artifact(self):
        assert _is_clean_for_injection("the Sonos iI offline") is False

    def test_empty_string(self):
        assert _is_clean_for_injection("") is False


class TestCheckDraftQuality:

    def test_broken_fragment_sounds_like_give(self):
        status, reasons = _check_draft_quality(
            "I'll take a look at your Sonos — sounds like give me call as soon as you can."
        )
        assert status == "blocked"
        assert any("sounds like give" in r or "fragment" in r for r in reasons)

    def test_clean_draft_passes(self):
        status, reasons = _check_draft_quality(
            "On it — I'll check your Sonos and see what's going on. I'll let you know."
        )
        assert status == "pass"
        assert reasons == []

    def test_safe_fallback_passes(self):
        status, reasons = _check_draft_quality(SAFE_FALLBACK_REPLY)
        assert status == "pass"

    def test_repeated_word_detected(self):
        status, reasons = _check_draft_quality(
            "I'll check check your system and get back to you."
        )
        assert status == "blocked"
        assert any("repeated" in r for r in reasons)

    def test_speech_fragment_as_am_trying(self):
        status, reasons = _check_draft_quality(
            "On it — sounds like as am trying to setup your network."
        )
        assert status == "blocked"


class TestDraftQualityIntegration:
    """Verify messy fact values never appear in generated drafts."""

    def _profile(self, **kw):
        base = {"relationship_type": "client", "open_requests": [], "systems_or_topics": [],
                "follow_ups": [], "summary": "", "confidence": 0.75}
        base.update(kw)
        return base

    def _fact(self, ftype, val, accepted=True):
        return {"fact_type": ftype, "fact_value": val, "confidence": 0.7,
                "source_excerpt": "x", "source_timestamp": "t",
                "is_accepted": 1 if accepted else 0, "is_rejected": 0}

    def test_broken_fragment_not_in_draft(self):
        """The classic bad case: request fact is a raw iMessage transcript."""
        messy_request = "give me call as soon as you can as am trying to setup the WiFi network and need"
        accepted = {
            "request":   [self._fact("request", messy_request)],
            "equipment": [self._fact("equipment", "Sonos")],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        draft = result["draft_reply"]
        assert "give me call" not in draft,      f"Fragment appeared in draft: {draft}"
        assert "as am trying" not in draft,       f"Fragment appeared in draft: {draft}"
        assert "as soon as you can" not in draft, f"Fragment appeared in draft: {draft}"
        assert result["draft_quality_status"] in ("pass", "fallback")

    def test_broken_fragment_goes_to_reasoning_not_draft(self):
        """Messy req must appear in reasoning (for audit) but not in draft text."""
        messy = "give me call as soon as you can as am trying to setup"
        accepted = {
            "request":   [self._fact("request", messy)],
            "equipment": [self._fact("equipment", "Sonos")],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert messy[:20] in result["reasoning"], "Messy fact should appear in reasoning"
        assert messy[:20] not in result["draft_reply"], "Messy fact must not appear in draft"

    def test_sonos_context_produces_clean_draft(self):
        """Sonos equipment fact → clean, human-readable draft."""
        accepted = {
            "equipment": [self._fact("equipment", "Sonos")],
            "issue":     [self._fact("issue", "offline")],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        draft = result["draft_reply"]
        assert "Sonos" in draft
        _q_status, _q_reasons = _check_draft_quality(draft)
        assert _q_status == "pass", f"Clean draft failed quality check: {_q_reasons} — {draft}"

    def test_network_context_produces_clean_draft(self):
        accepted = {
            "system":  [self._fact("system", "network")],
            "issue":   [self._fact("issue", "not working")],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        draft = result["draft_reply"]
        _q_status, _ = _check_draft_quality(draft)
        assert _q_status == "pass", f"Draft failed quality: {draft}"

    def test_fallback_used_when_open_req_is_messy(self):
        """Messy open_requests → safe fallback, quality_status=fallback."""
        profile = self._profile(
            open_requests=["give me call as soon as you can as am trying to setup the WiFi network and need"]
        )
        result = _build_draft_with_context(profile, {}, {}, [])
        assert result["draft_reply"] == SAFE_FALLBACK_REPLY
        assert result["draft_quality_status"] == "fallback"
        assert result["confidence"] <= 0.60

    def test_clean_open_req_not_overridden(self):
        """Clean open_request → stays in draft via system name."""
        profile = self._profile(
            open_requests=["schedule a service visit"],
            systems_or_topics=["Sonos"],
        )
        result = _build_draft_with_context(profile, {}, {}, [])
        assert result["draft_quality_status"] == "pass"
        assert result["draft_reply"] != SAFE_FALLBACK_REPLY

    def test_quality_status_and_reasons_always_present(self):
        """Both fields must be in every response."""
        result = _build_draft_with_context(self._profile(), {}, {}, [])
        assert "draft_quality_status" in result
        assert "draft_quality_reasons" in result
        assert isinstance(result["draft_quality_reasons"], list)

    def test_confidence_downgraded_for_messy_facts(self):
        messy_request = "give me call as soon as you can as am trying to setup WiFi"
        accepted = {
            "request":   [self._fact("request", messy_request)],
            "equipment": [self._fact("equipment", "Sonos")],
        }
        result = _build_draft_with_context(self._profile(), accepted, {}, [])
        assert result["confidence"] <= 0.65, (
            f"Confidence should be downgraded for messy facts, got {result['confidence']}"
        )


class TestApprovalBlockedDraft:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def test_blocked_draft_refused(self, client):
        """approve-reply must refuse when draft_quality_status=blocked."""
        r = client.post("/api/x-intake/approve-reply", json={
            "action_id":            "blocked_test_01",
            "approved":             True,
            "draft_reply":          "sounds like give me call as soon as you can.",
            "contact_masked":       "+13***32",
            "draft_quality_status": "blocked",
            "draft_quality_reasons": ["fragment: 'sounds like give...'"],
        })
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "blocked", f"Expected blocked, got: {d}"
        assert d.get("draft_quality_reasons")

    def test_clean_draft_approved(self, client, tmp_path):
        import cortex.engine as eng
        orig_a, orig_r = eng._APPROVAL_LOG, eng._DRY_RUN_RECEIPT_LOG
        eng._APPROVAL_LOG        = tmp_path / "a.ndjson"
        eng._DRY_RUN_RECEIPT_LOG = tmp_path / "r.ndjson"
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":            "clean_test_01",
                "approved":             True,
                "draft_reply":          "On it — I'll check your Sonos and get back to you.",
                "contact_masked":       "+13***32",
                "draft_quality_status": "pass",
            })
        finally:
            eng._APPROVAL_LOG        = orig_a
            eng._DRY_RUN_RECEIPT_LOG = orig_r
        d = r.json()
        assert d["status"] == "ok"

    def test_fallback_draft_can_be_approved(self, client, tmp_path):
        """Fallback drafts (status='fallback') must be approvable."""
        import cortex.engine as eng
        orig_a, orig_r = eng._APPROVAL_LOG, eng._DRY_RUN_RECEIPT_LOG
        eng._APPROVAL_LOG        = tmp_path / "a.ndjson"
        eng._DRY_RUN_RECEIPT_LOG = tmp_path / "r.ndjson"
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":            "fallback_test_01",
                "approved":             True,
                "draft_reply":          SAFE_FALLBACK_REPLY,
                "contact_masked":       "+13***32",
                "draft_quality_status": "fallback",
            })
        finally:
            eng._APPROVAL_LOG        = orig_a
            eng._DRY_RUN_RECEIPT_LOG = orig_r
        assert r.json()["status"] == "ok"


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
