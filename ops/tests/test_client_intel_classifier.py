"""Tests for client intelligence classifier and schema (Phase 1)."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.client_intel_backfill import (
    classify_text_sample,
    init_schemas,
    _thread_id,
)

# Re-export for convenience
from scripts.client_intel_backfill import (
    THREAD_INDEX_DB,
    PROFILES_DB,
    PROPOSED_FACTS_DB,
    BACKFILL_LOG,
)


# ── Classifier tests ──────────────────────────────────────────────────────────

class TestClassifier:

    def test_strong_signal_gives_work(self):
        r = classify_text_sample(["We need a Control4 proposal for the Beaver Creek project"])
        assert r["category"] == "work"
        assert r["work_confidence"] >= 0.70

    def test_symphony_brand_strong(self):
        r = classify_text_sample(["Matt Earley with Symphony Smart Homes here"])
        assert r["category"] == "work"
        assert r["work_confidence"] >= 0.70

    def test_lutron_dimmer_strong(self):
        r = classify_text_sample(["The Lutron keypad in the master bedroom is dimming incorrectly"])
        assert r["category"] == "work"
        assert r["work_confidence"] >= 0.70

    def test_multiple_strong_increases_confidence(self):
        r_single = classify_text_sample(["Control4 system"])
        r_multi = classify_text_sample(["Control4 proposal for theater with Sonos audio and Lutron shading"])
        assert r_multi["work_confidence"] > r_single["work_confidence"]

    def test_single_weak_gives_mixed(self):
        r = classify_text_sample(["Can you give me a quote on that?"])
        assert r["category"] == "mixed"
        assert r["work_confidence"] < 0.50

    def test_two_weak_gives_work(self):
        r = classify_text_sample(["Can you schedule an install appointment?"])
        assert r["category"] == "work"
        assert r["work_confidence"] >= 0.55

    def test_personal_gives_personal(self):
        r = classify_text_sample([
            "Hey are you coming to dinner tonight?",
            "Happy birthday! Hope you have a great day",
            "Just checking in. How are the kids?",
        ])
        assert r["category"] == "personal"
        assert r["work_confidence"] < 0.20

    def test_empty_is_personal(self):
        r = classify_text_sample([])
        assert r["category"] == "personal"
        assert r["work_confidence"] < 0.20

    def test_reason_codes_populated_for_work(self):
        r = classify_text_sample(["Sonos audio system installation proposal"])
        assert r["category"] == "work"
        assert len(r["reason_codes"]) > 0
        assert any("strong:" in code for code in r["reason_codes"])

    def test_reason_codes_empty_for_personal(self):
        r = classify_text_sample(["See you tonight"])
        assert r["category"] == "personal"
        # No strong or weak matches in reason_codes
        assert r["strong_count"] == 0

    def test_case_insensitive_matching(self):
        r = classify_text_sample(["CONTROL4 PROPOSAL FOR THEATER"])
        assert r["category"] == "work"

    def test_mixed_work_personal_messages(self):
        texts = [
            "Hey want to grab lunch?",
            "Also the Control4 system at the Vail project needs attention",
            "No rush on the dinner thing",
        ]
        r = classify_text_sample(texts)
        assert r["category"] == "work"  # one strong signal dominates

    def test_prewire_and_builder_signals(self):
        r = classify_text_sample(["Builder wants to prewire for home theater in the rough-in stage"])
        assert r["category"] == "work"

    def test_wattbox_araknis_strong(self):
        r = classify_text_sample(["WattBox reboot resolved the Araknis network issue"])
        assert r["category"] == "work"


# ── Schema tests ──────────────────────────────────────────────────────────────

class TestSchemas:

    def test_init_schemas_creates_files(self, tmp_path):
        import scripts.client_intel_backfill as mod
        orig_dir = mod.DATA_DIR
        orig_thread = mod.THREAD_INDEX_DB
        orig_profiles = mod.PROFILES_DB
        orig_facts = mod.PROPOSED_FACTS_DB
        orig_log = mod.BACKFILL_LOG
        try:
            mod.DATA_DIR = tmp_path
            mod.THREAD_INDEX_DB = tmp_path / "message_thread_index.sqlite"
            mod.PROFILES_DB = tmp_path / "client_profiles.sqlite"
            mod.PROPOSED_FACTS_DB = tmp_path / "proposed_facts.sqlite"
            mod.BACKFILL_LOG = tmp_path / "backfill_runs.ndjson"
            init_schemas()
            assert (tmp_path / "message_thread_index.sqlite").is_file()
            assert (tmp_path / "client_profiles.sqlite").is_file()
            assert (tmp_path / "proposed_facts.sqlite").is_file()
        finally:
            mod.DATA_DIR = orig_dir
            mod.THREAD_INDEX_DB = orig_thread
            mod.PROFILES_DB = orig_profiles
            mod.PROPOSED_FACTS_DB = orig_facts
            mod.BACKFILL_LOG = orig_log

    def test_thread_index_schema(self, tmp_path):
        db = tmp_path / "threads.sqlite"
        import scripts.client_intel_backfill as mod
        orig_t = mod.THREAD_INDEX_DB
        orig_p = mod.PROFILES_DB
        orig_f = mod.PROPOSED_FACTS_DB
        orig_d = mod.DATA_DIR
        try:
            mod.THREAD_INDEX_DB = db
            mod.PROFILES_DB = tmp_path / "p.sqlite"
            mod.PROPOSED_FACTS_DB = tmp_path / "f.sqlite"
            mod.DATA_DIR = tmp_path
            init_schemas()
        finally:
            mod.THREAD_INDEX_DB = orig_t
            mod.PROFILES_DB = orig_p
            mod.PROPOSED_FACTS_DB = orig_f
            mod.DATA_DIR = orig_d
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        conn.close()
        required = {"thread_id", "chat_guid", "contact_handle", "category",
                    "work_confidence", "reason_codes", "is_reviewed"}
        assert required.issubset(cols)

    def test_profiles_schema(self, tmp_path):
        db = tmp_path / "profiles.sqlite"
        import scripts.client_intel_backfill as mod
        orig = mod.PROFILES_DB
        orig_dir = mod.DATA_DIR
        try:
            mod.PROFILES_DB = db
            mod.DATA_DIR = tmp_path
            mod.THREAD_INDEX_DB = tmp_path / "t.sqlite"
            mod.PROPOSED_FACTS_DB = tmp_path / "f.sqlite"
            init_schemas()
        finally:
            mod.PROFILES_DB = orig
            mod.DATA_DIR = orig_dir
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        conn.close()
        assert {"profile_id", "contact_handle", "category", "work_confidence"}.issubset(cols)

    def test_proposed_facts_schema(self, tmp_path):
        db = tmp_path / "facts.sqlite"
        import scripts.client_intel_backfill as mod
        orig = mod.PROPOSED_FACTS_DB
        orig_dir = mod.DATA_DIR
        try:
            mod.PROPOSED_FACTS_DB = db
            mod.DATA_DIR = tmp_path
            mod.THREAD_INDEX_DB = tmp_path / "t.sqlite"
            mod.PROFILES_DB = tmp_path / "p.sqlite"
            init_schemas()
        finally:
            mod.PROPOSED_FACTS_DB = orig
            mod.DATA_DIR = orig_dir
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(proposed_facts)").fetchall()}
        conn.close()
        assert {"fact_id", "thread_id", "contact_handle", "fact_type",
                "fact_value", "confidence", "is_accepted", "is_rejected"}.issubset(cols)
