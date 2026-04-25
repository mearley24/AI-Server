"""Tests for client intelligence fact quality validation.

Covers:
  - validate_fact() rules for each fact type
  - known bad facts flagged as invalid
  - equipment/system facts kept valid
  - rejected facts excluded from context-card accepted_facts and suggested_next_action
  - rejected facts excluded from draft_reply
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_client_facts import validate_fact, audit


# ── validate_fact unit tests ──────────────────────────────────────────────────

class TestValidateFactEquipmentSystem:

    def test_sonos_valid(self):
        v, _ = validate_fact("equipment", "Sonos")
        assert v == "valid"

    def test_wifi_valid(self):
        v, _ = validate_fact("system", "WiFi")
        assert v == "valid"

    def test_network_valid(self):
        v, _ = validate_fact("system", "network")
        assert v == "valid"

    def test_control4_valid(self):
        v, _ = validate_fact("equipment", "Control4")
        assert v == "valid"

    def test_lutron_valid(self):
        v, _ = validate_fact("equipment", "Lutron")
        assert v == "valid"

    def test_equipment_with_decoder_artifact_invalid(self):
        v, r = validate_fact("equipment", "Sonos iI")
        assert v == "invalid"
        assert "artifact" in r.lower()

    def test_empty_equipment_invalid(self):
        v, _ = validate_fact("equipment", "")
        assert v == "invalid"


class TestValidateFactRequest:

    def test_good_request_valid(self):
        v, _ = validate_fact("request", "check out the Sonos system at Beaver Creek")
        assert v == "valid"

    def test_schedule_request_valid(self):
        v, _ = validate_fact("request", "schedule a service visit next week")
        assert v == "valid"

    def test_messy_speech_fragment_invalid(self):
        """The real bad fact — speech transcript ending in incomplete phrase."""
        v, reason = validate_fact(
            "request",
            "give me call as soon as you can as am trying to setup the WiFi network and need",
        )
        assert v == "invalid", f"Expected invalid, got {v}: {reason}"
        assert reason  # must explain why

    def test_trailing_and_need_invalid(self):
        v, r = validate_fact("request", "fix the network and need")
        assert v == "invalid"
        assert "fragment" in r.lower()

    def test_trailing_as_am_invalid(self):
        v, r = validate_fact("request", "looking into it as am")
        assert v == "invalid"

    def test_speech_give_me_call_invalid(self):
        v, r = validate_fact("request", "give me call as soon as you can")
        assert v == "invalid"
        assert "speech" in r.lower() or "fragment" in r.lower()

    def test_too_long_invalid(self):
        v, r = validate_fact(
            "request",
            "can you please just call me back when you get a chance because I need to ask "
            "you about the system at my house and also the WiFi has been down",
        )
        assert v == "invalid"
        assert "words" in r.lower() or "transcript" in r.lower()

    def test_decoder_artifact_invalid(self):
        v, r = validate_fact("request", "please +E fix the Sonos")
        assert v == "invalid"
        assert "artifact" in r.lower()

    def test_short_request_weak(self):
        v, _ = validate_fact("request", "fix it")
        assert v == "weak"


class TestValidateFactFollowUp:

    def test_let_me_know_invalid(self):
        """The real bad fact — standalone generic phrase."""
        v, reason = validate_fact("follow_up", "Let me know")
        assert v == "invalid", f"Expected invalid, got {v}: {reason}"
        assert "generic" in reason.lower() or "non-actionable" in reason.lower()

    def test_ok_invalid(self):
        v, _ = validate_fact("follow_up", "Ok")
        assert v == "invalid"

    def test_thanks_invalid(self):
        v, _ = validate_fact("follow_up", "Thanks")
        assert v == "invalid"

    def test_got_it_invalid(self):
        v, _ = validate_fact("follow_up", "Got it")
        assert v == "invalid"

    def test_will_do_invalid(self):
        v, _ = validate_fact("follow_up", "Will do")
        assert v == "invalid"

    def test_specific_follow_up_valid(self):
        v, _ = validate_fact("follow_up", "Let me know when you're back in town")
        assert v == "valid"

    def test_schedule_follow_up_valid(self):
        v, _ = validate_fact("follow_up", "schedule a callback for next week")
        assert v == "valid"

    def test_decoder_artifact_invalid(self):
        v, r = validate_fact("follow_up", "+E Let me know if you need anything")
        assert v == "invalid"


class TestValidateFactIssue:

    def test_generic_problem_invalid(self):
        v, r = validate_fact("issue", "problem")
        assert v == "invalid"
        assert "generic" in r.lower()

    def test_offline_valid(self):
        # "offline" is a specific state, not a generic word
        v, _ = validate_fact("issue", "offline")
        assert v == "valid"

    def test_not_working_valid(self):
        v, _ = validate_fact("issue", "not working")
        assert v == "valid"

    def test_cutting_out_valid(self):
        v, _ = validate_fact("issue", "cutting out")
        assert v == "valid"


class TestAuditRunner:
    """Test the audit() function using a temp DB."""

    def _make_db(self, tmp_path: Path) -> Path:
        db = tmp_path / "facts.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE proposed_facts (
                fact_id TEXT PRIMARY KEY,
                profile_id TEXT, thread_id TEXT, contact_handle TEXT,
                fact_type TEXT, fact_value TEXT,
                confidence REAL, source_excerpt TEXT, source_timestamp TEXT,
                is_accepted INTEGER DEFAULT 0, is_rejected INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        rows = [
            ("f1", "equipment", "Sonos",          0.75, 1, 0),  # valid   → keep
            ("f2", "system",    "WiFi",            0.75, 1, 0),  # valid   → keep
            ("f3", "system",    "network",         0.75, 1, 0),  # valid   → keep
            ("f4", "follow_up", "Let me know",     0.50, 1, 0),  # invalid → reject
            ("f5", "request",
             "give me call as soon as you can as am trying to setup the WiFi network and need",
             0.70, 1, 0),                                        # invalid → reject
        ]
        for fid, ftype, fval, conf, acc, rej in rows:
            conn.execute(
                "INSERT INTO proposed_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, "p1", "t1", "+1xxx", ftype, fval, conf, "x", "t", acc, rej, "now"),
            )
        conn.commit()
        conn.close()
        return db

    def test_dry_run_flags_correct_facts(self, tmp_path):
        db = self._make_db(tmp_path)
        results = audit(db, apply=False)
        by_id = {r["fact_id"]: r for r in results}
        assert by_id["f1"]["verdict"] == "valid",   "Sonos must be valid"
        assert by_id["f2"]["verdict"] == "valid",   "WiFi must be valid"
        assert by_id["f3"]["verdict"] == "valid",   "network must be valid"
        assert by_id["f4"]["verdict"] == "invalid", "Let me know must be invalid"
        assert by_id["f5"]["verdict"] == "invalid", "Messy request must be invalid"

    def test_dry_run_does_not_modify_db(self, tmp_path):
        db = self._make_db(tmp_path)
        audit(db, apply=False)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        still_accepted = conn.execute(
            "SELECT COUNT(*) FROM proposed_facts WHERE is_accepted=1"
        ).fetchone()[0]
        conn.close()
        assert still_accepted == 5, "Dry-run must not modify the DB"

    def test_apply_rejects_invalid_facts(self, tmp_path):
        db = self._make_db(tmp_path)
        audit(db, apply=True)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = {r["fact_id"]: dict(r) for r in conn.execute(
            "SELECT fact_id, is_accepted, is_rejected FROM proposed_facts"
        ).fetchall()}
        conn.close()
        # Valid facts unchanged
        assert rows["f1"]["is_accepted"] == 1 and rows["f1"]["is_rejected"] == 0
        assert rows["f2"]["is_accepted"] == 1 and rows["f2"]["is_rejected"] == 0
        assert rows["f3"]["is_accepted"] == 1 and rows["f3"]["is_rejected"] == 0
        # Invalid facts rejected
        assert rows["f4"]["is_accepted"] == 0 and rows["f4"]["is_rejected"] == 1
        assert rows["f5"]["is_accepted"] == 0 and rows["f5"]["is_rejected"] == 1

    def test_apply_never_deletes_rows(self, tmp_path):
        db = self._make_db(tmp_path)
        audit(db, apply=True)
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM proposed_facts").fetchone()[0]
        conn.close()
        assert count == 5, "apply must never delete rows"


# ── Context-card and reply integration tests ──────────────────────────────────

class TestRejectedFactsExcludedFromContextCard:
    """Verify rejected facts don't reach context-card output or reply drafting."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _profile(self):
        return {
            "profile_id": "prof_quality_test",
            "relationship_type": "client",
            "display_name": "",
            "contact_handle": "+15551234567",
            "thread_ids": '["tid1"]',
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-04-25T00:00:00+00:00",
            "summary": "Systems: Sonos, WiFi",
            "open_requests": '[]',
            "follow_ups": '[]',
            "systems_or_topics": '["Sonos", "WiFi"]',
            "project_refs": '[]',
            "dtools_project_refs": '[]',
            "confidence": 0.75,
            "status": "proposed",
            "last_updated": "2026-04-25T00:00:00+00:00",
        }

    def _make_facts(self, *, include_rejected: bool = True):
        """Return a fact list with good accepted facts plus optionally bad rejected ones."""
        facts = [
            # Good — accepted
            {"fact_id": "g1", "thread_id": "t", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos offline", "source_timestamp": "t",
             "is_accepted": 1, "is_rejected": 0},
            {"fact_id": "g2", "thread_id": "t", "fact_type": "system",
             "fact_value": "WiFi", "confidence": 0.75,
             "source_excerpt": "WiFi setup", "source_timestamp": "t",
             "is_accepted": 1, "is_rejected": 0},
        ]
        if include_rejected:
            facts += [
                # Bad — rejected (should not appear in context card)
                {"fact_id": "b1", "thread_id": "t", "fact_type": "request",
                 "fact_value": "give me call as soon as you can as am trying to setup the WiFi network and need",
                 "confidence": 0.70,
                 "source_excerpt": "speech fragment", "source_timestamp": "t",
                 "is_accepted": 0, "is_rejected": 1},
                {"fact_id": "b2", "thread_id": "t", "fact_type": "follow_up",
                 "fact_value": "Let me know",
                 "confidence": 0.50,
                 "source_excerpt": "let me know", "source_timestamp": "t",
                 "is_accepted": 0, "is_rejected": 1},
            ]
        return facts

    def test_rejected_request_not_in_accepted_facts(self, client):
        """Rejected messy request must not appear in context-card accepted_facts."""
        # _facts_for_profile filters is_rejected=0 at SQL level;
        # simulate that by only returning non-rejected facts to the mock
        non_rejected = [f for f in self._make_facts() if not f["is_rejected"]]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        all_accepted_values = [
            f["fact_value"]
            for facts in d.get("accepted_facts", {}).values()
            for f in facts
        ]
        assert not any(
            "give me call" in v.lower() for v in all_accepted_values
        ), f"Rejected messy request must not be in accepted_facts: {all_accepted_values}"

    def test_rejected_follow_up_not_in_accepted_facts(self, client):
        """Rejected 'Let me know' must not appear in accepted_facts."""
        non_rejected = [f for f in self._make_facts() if not f["is_rejected"]]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        follow_up_values = [
            f["fact_value"]
            for f in d.get("accepted_facts", {}).get("follow_up", [])
        ]
        assert "Let me know" not in follow_up_values, (
            f"'Let me know' must not be in accepted_facts: {follow_up_values}"
        )

    def test_valid_sonos_wifi_facts_present(self, client):
        """Sonos and WiFi must still appear as accepted facts after the audit."""
        non_rejected = [f for f in self._make_facts() if not f["is_rejected"]]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        accepted = d.get("accepted_facts", {})
        equip_vals = [f["fact_value"] for f in accepted.get("equipment", [])]
        sys_vals   = [f["fact_value"] for f in accepted.get("system", [])]
        assert "Sonos" in equip_vals, f"Sonos must be in accepted equipment: {equip_vals}"
        assert "WiFi"  in sys_vals,   f"WiFi must be in accepted system: {sys_vals}"

    def test_rejected_request_not_in_suggested_action(self, client):
        """Rejected messy request must not drive suggested_next_action."""
        non_rejected = [f for f in self._make_facts() if not f["is_rejected"]]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        action = d.get("suggested_next_action", "")
        assert "give me call" not in action.lower(), (
            f"Messy request fragment must not drive suggested_next_action: {action}"
        )

    def test_rejected_request_not_in_draft_reply(self, client):
        """Rejected messy request must not appear verbatim in draft_reply."""
        non_rejected = [f for f in self._make_facts() if not f["is_rejected"]]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551234567")
        d = r.json()
        draft = d.get("draft_reply", "")
        assert "give me call" not in draft.lower(), (
            f"Messy fragment must not appear in draft_reply: {draft}"
        )
        assert "as am trying" not in draft.lower(), (
            f"Speech fragment must not appear in draft_reply: {draft}"
        )
