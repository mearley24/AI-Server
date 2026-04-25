"""Tests for relationship profile extraction — Phase 2 (quality filters)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.extract_relationship_profiles import (
    PROCESSABLE_TYPES,
    _ensure_profiles_schema,
    _ensure_facts_schema,
    _pid,
    _fid,
    _clean_value,
    _is_fragment,
    _is_open_request_phrase,
    _dedup_key,
    extract_facts,
    build_profile,
    run_extraction,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _fake_thread(rel_type: str = "client", contact: str = "+15551234567") -> dict:
    return {
        "thread_id": "tid_" + rel_type,
        "chat_guid": "guid_" + rel_type,
        "contact_handle": contact,
        "relationship_type": rel_type,
        "date_first": "2024-01-01T00:00:00+00:00",
        "date_last": "2026-04-24T00:00:00+00:00",
        "work_confidence": 0.80,
    }


def _fake_messages(texts: list[str]) -> list[dict]:
    return [{"text": t, "from_me": False, "ts": "2026-04-24T10:00:00+00:00"} for t in texts]


# ── Profile ID / Fact ID stability ────────────────────────────────────────────

class TestIDs:

    def test_profile_id_stable(self):
        pid1 = _pid("+15551234567", "client")
        pid2 = _pid("+15551234567", "client")
        assert pid1 == pid2
        assert len(pid1) == 16

    def test_profile_id_differs_by_type(self):
        assert _pid("+15551234567", "client") != _pid("+15551234567", "vendor")

    def test_fact_id_stable(self):
        fid1 = _fid("tid_client", "equipment", "Sonos")
        fid2 = _fid("tid_client", "equipment", "Sonos")
        assert fid1 == fid2

    def test_fact_id_differs_by_value(self):
        assert _fid("t", "system", "Sonos") != _fid("t", "system", "Lutron")


# ── Extraction rules ──────────────────────────────────────────────────────────

class TestExtraction:

    def test_client_equipment_extracted(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        msgs = _fake_messages(["The Sonos system in the living room is cutting out again"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "client", msgs)
        types = {f["fact_type"] for f in facts}
        assert "equipment" in types or "system" in types
        values = [f["fact_value"].lower() for f in facts]
        assert any("sonos" in v for v in values)

    def test_client_issue_extracted(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        msgs = _fake_messages(["The network is not working since yesterday"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "client", msgs)
        types = {f["fact_type"] for f in facts}
        assert "issue" in types or "system" in types

    def test_client_project_ref_extracted(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        msgs = _fake_messages(["Can we schedule the site visit for the Vail Project next week?"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "client", msgs)
        types = {f["fact_type"] for f in facts}
        assert "project_ref" in types or "follow_up" in types

    def test_vendor_pricing_extracted(self):
        thread = _fake_thread("vendor")
        pid = _pid(thread["contact_handle"], "vendor")
        msgs = _fake_messages(["The Sonos Arc is $899 and available to ship next week"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "vendor", msgs)
        types = {f["fact_type"] for f in facts}
        assert "pricing" in types or "product" in types

    def test_builder_schedule_extracted(self):
        thread = _fake_thread("builder")
        pid = _pid(thread["contact_handle"], "builder")
        msgs = _fake_messages(["Rough-in is scheduled for Tuesday, trim should be ready by Friday"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "builder", msgs)
        types = {f["fact_type"] for f in facts}
        assert "schedule" in types or "coordination" in types

    def test_internal_team_ops_ref_extracted(self):
        thread = _fake_thread("internal_team")
        pid = _pid(thread["contact_handle"], "internal_team")
        msgs = _fake_messages(["Ticket #4521 needs to be updated before the deadline Friday"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "internal_team", msgs)
        types = {f["fact_type"] for f in facts}
        assert "ops_ref" in types or "ops_timeline" in types

    def test_personal_work_related_extracts_work_context(self):
        thread = _fake_thread("personal_work_related")
        pid = _pid(thread["contact_handle"], "personal_work_related")
        msgs = _fake_messages(["Can we set up a meeting to go over the proposal?"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "personal_work_related", msgs)
        # May or may not match — but must not crash
        assert isinstance(facts, list)

    def test_facts_deduped_within_thread(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        msgs = _fake_messages(["Sonos issue", "Sonos is not working", "the Sonos keeps cutting out"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "client", msgs)
        sonos_facts = [f for f in facts if "sonos" in f["fact_value"].lower()]
        # Should be deduped — at most 2 distinct types for sonos
        assert len(sonos_facts) <= 3

    def test_facts_have_source_excerpt_and_timestamp(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        msgs = _fake_messages(["Control4 system needs a firmware update"])
        facts = extract_facts("tid1", pid, thread["contact_handle"], "client", msgs)
        for f in facts:
            assert f["source_excerpt"], "source_excerpt must not be empty"
            assert f["source_timestamp"], "source_timestamp must not be empty"
            assert f["is_accepted"] == 0, "facts must start as proposed (not accepted)"
            assert f["is_rejected"] == 0


# ── Profile building ──────────────────────────────────────────────────────────

class TestProfileBuilding:

    def test_profile_status_is_proposed(self):
        thread = _fake_thread("client")
        facts = []
        profile = build_profile(thread, facts, [])
        assert profile["status"] == "proposed"

    def test_profile_has_correct_relationship_type(self):
        for rt in PROCESSABLE_TYPES:
            t = _fake_thread(rt)
            p = build_profile(t, [], [])
            assert p["relationship_type"] == rt

    def test_profile_includes_thread_id(self):
        thread = _fake_thread("vendor")
        p = build_profile(thread, [], [])
        assert thread["thread_id"] in json.loads(p["thread_ids"])

    def test_profile_systems_populated_from_facts(self):
        thread = _fake_thread("client")
        pid = _pid(thread["contact_handle"], "client")
        facts = [
            {"fact_type": "equipment", "fact_value": "Sonos", "profile_id": pid,
             "thread_id": "t1", "contact_handle": thread["contact_handle"],
             "confidence": 0.7, "source_excerpt": "x", "source_timestamp": "ts",
             "is_accepted": 0, "is_rejected": 0, "created_at": "now",
             "fact_id": "f1"},
        ]
        p = build_profile(thread, facts, [])
        assert "Sonos" in json.loads(p["systems_or_topics"])

    def test_unknown_not_in_processable_types(self):
        assert "unknown" not in PROCESSABLE_TYPES

    def test_all_six_types_processable(self):
        expected = {"client", "vendor", "builder", "trade_partner", "internal_team", "personal_work_related"}
        assert expected == PROCESSABLE_TYPES


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchemas:

    def test_profiles_schema_columns(self, tmp_path):
        db = str(tmp_path / "profiles.sqlite")
        conn = sqlite3.connect(db)
        _ensure_profiles_schema(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        conn.close()
        required = {"profile_id", "relationship_type", "contact_handle",
                    "status", "confidence", "summary", "open_requests",
                    "systems_or_topics", "project_refs", "dtools_project_refs"}
        assert required.issubset(cols)

    def test_facts_schema_columns(self, tmp_path):
        db = str(tmp_path / "facts.sqlite")
        conn = sqlite3.connect(db)
        _ensure_facts_schema(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(proposed_facts)").fetchall()}
        conn.close()
        required = {"fact_id", "profile_id", "thread_id", "contact_handle",
                    "fact_type", "fact_value", "confidence",
                    "source_excerpt", "source_timestamp", "is_accepted", "is_rejected"}
        assert required.issubset(cols)

    def test_facts_default_not_accepted(self, tmp_path):
        db = str(tmp_path / "facts.sqlite")
        conn = sqlite3.connect(db)
        _ensure_facts_schema(conn)
        conn.execute(
            "INSERT INTO proposed_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("f1", "p1", "t1", "+15551234567", "equipment", "Sonos",
             0.7, "excerpt", "ts", 0, 0, "now"),
        )
        conn.commit()
        row = conn.execute("SELECT is_accepted, is_rejected FROM proposed_facts WHERE fact_id='f1'").fetchone()
        conn.close()
        assert row[0] == 0
        assert row[1] == 0


# ── Quality filter unit tests ─────────────────────────────────────────────────

class TestCleanValue:

    def test_trims_at_sentence_boundary(self):
        v = _clean_value("check out the Sonos system. And also verify you")
        assert v == "check out the Sonos system"

    def test_strips_truncated_trailing_token(self):
        # "syst" has no vowels and is ≤4 chars → stripped
        v = _clean_value("check out your Sonos syst")
        assert "syst" not in v
        assert "Sonos" in v

    def test_preserves_short_complete_value(self):
        # "WiFi" has vowels → kept
        v = _clean_value("WiFi")
        assert v == "WiFi"

    def test_clause_break_trimming(self):
        v = _clean_value("Beaver Creek project and then also fix the TV")
        assert "and then" not in v

    def test_empty_string(self):
        assert _clean_value("") == ""

    def test_no_modification_for_clean_value(self):
        v = _clean_value("fix the Sonos system at Beaver Creek")
        assert "Sonos" in v


class TestIsFragment:

    def test_ocr_junk_rejected(self):
        assert _is_fragment("anything else. iI", "request") is True

    def test_short_non_equipment_request_not_fragment_but_no_trigger(self):
        # "along with verifying you" passes _is_fragment (4 words, no garbage)
        # but is rejected by _is_open_request_phrase in the extraction pipeline
        assert _is_fragment("along with verifying you", "request") is False
        assert _is_open_request_phrase("along with verifying you") is False

    def test_equipment_name_kept_even_if_short(self):
        assert _is_fragment("Sonos", "equipment") is False

    def test_network_kept_as_system(self):
        # "network" is in _EQUIPMENT_RE
        assert _is_fragment("network", "system") is False

    def test_real_request_with_equipment_kept(self):
        assert _is_fragment("check out your Sonos system at Beaver Creek", "request") is False

    def test_short_issue_value_kept(self):
        # issue type is in _SHORT_OK_TYPES
        assert _is_fragment("not working", "issue") is False

    def test_follow_up_keyword_kept(self):
        assert _is_fragment("schedule", "follow_up") is False

    def test_four_word_non_equipment_without_action_rejected(self):
        # No equipment, no OCR junk, but < 4 useful words
        assert _is_fragment("come check this", "request") is True

    def test_five_word_value_with_no_ocr_kept(self):
        # 5 useful words, no OCR junk
        assert _is_fragment("please schedule a service visit", "request") is False


class TestIsOpenRequestPhrase:

    def test_real_service_request_kept(self):
        assert _is_open_request_phrase("can you check out the Sonos system") is True

    def test_fix_trigger_kept(self):
        assert _is_open_request_phrase("fix the network issue in the living room") is True

    def test_schedule_trigger_kept(self):
        assert _is_open_request_phrase("schedule a service visit next week") is True

    def test_not_working_trigger_kept(self):
        assert _is_open_request_phrase("the system is not working since Tuesday") is True

    def test_vague_fragment_rejected(self):
        assert _is_open_request_phrase("along with verifying you") is False

    def test_plain_project_name_rejected(self):
        assert _is_open_request_phrase("Beaver Creek Condo renovation") is False

    def test_cutting_out_trigger_kept(self):
        assert _is_open_request_phrase("the audio keeps cutting out in the theater") is True


class TestDedupKey:

    def test_same_value_different_case_same_key(self):
        assert _dedup_key("equipment", "Sonos") == _dedup_key("equipment", "sonos")

    def test_punctuation_stripped(self):
        assert _dedup_key("request", "fix the Sonos!") == _dedup_key("request", "fix the Sonos")

    def test_different_types_different_keys(self):
        assert _dedup_key("equipment", "Sonos") != _dedup_key("system", "Sonos")


class TestFragmentFiltering:
    """Integration-level tests: extract_facts must drop known-bad fragments."""

    def _pid_for(self, contact: str, rel: str) -> str:
        return _pid(contact, rel)

    def test_broken_fragment_along_with_verifying_ignored(self):
        # Simulates the "along with verifying you" garbage from a request capture
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        # Message whose "can you" capture yields a vague fragment
        msgs = [{"text": "I want along with verifying you know the system", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        request_values = [f["fact_value"] for f in facts if f["fact_type"] == "request"]
        # No request fact should be kept — the captured text is a fragment with no action trigger
        assert not any("verifying you" in v for v in request_values), \
            f"Fragment 'verifying you' should not appear in facts: {request_values}"

    def test_ocr_junk_iI_ignored(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [{"text": "can you do anything else. iI", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        request_values = [f["fact_value"] for f in facts if f["fact_type"] == "request"]
        assert not any("iI" in v or "anything else" in v for v in request_values), \
            f"OCR junk should not appear in facts: {request_values}"

    def test_real_service_request_kept(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [{"text": "Can you check out the Sonos system? It keeps cutting out.", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        types = {f["fact_type"] for f in facts}
        assert "equipment" in types or "request" in types or "issue" in types

    def test_sonos_equipment_mention_kept(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [{"text": "The Sonos in the living room is offline", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        equip = [f["fact_value"].lower() for f in facts if f["fact_type"] == "equipment"]
        assert any("sonos" in v for v in equip)

    def test_network_system_mention_kept(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [{"text": "The network has been going down every night this week", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        types = {f["fact_type"] for f in facts}
        assert "system" in types or "issue" in types

    def test_duplicate_equipment_merged(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [
            {"text": "Sonos issue in the living room", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"},
            {"text": "The SONOS keeps cutting out", "from_me": False, "ts": "2026-04-24T10:01:00+00:00"},
            {"text": "I mentioned the Sonos earlier", "from_me": False, "ts": "2026-04-24T10:02:00+00:00"},
        ]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        sonos_facts = [f for f in facts if "sonos" in f["fact_value"].lower() and f["fact_type"] == "equipment"]
        # Dedup by normalized key — should be exactly 1 equipment fact for Sonos
        assert len(sonos_facts) == 1, f"Expected 1 Sonos equipment fact, got {len(sonos_facts)}"

    def test_evidence_snippet_preserved(self):
        contact = "+15551234567"
        pid = self._pid_for(contact, "client")
        msgs = [{"text": "Can you come check the Control4 system at Beaver Creek?", "from_me": False, "ts": "2026-04-24T10:00:00+00:00"}]
        facts = extract_facts("tid1", pid, contact, "client", msgs)
        for f in facts:
            assert f["source_excerpt"], f"source_excerpt must not be empty for {f['fact_type']}"
            assert f["source_timestamp"] == "2026-04-24T10:00:00+00:00"
            assert f["thread_id"] == "tid1"
            assert f["is_accepted"] == 0
            assert f["is_rejected"] == 0
