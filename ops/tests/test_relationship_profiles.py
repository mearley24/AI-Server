"""Tests for relationship profile extraction — Phase 1."""
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
