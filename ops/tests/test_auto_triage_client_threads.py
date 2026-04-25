"""
Scoring-focused tests for the revised auto-triage bucket logic.

These tests exercise the integrated scoring pipeline — real analyze_thread_assist
calls with snapshot-like texts — to verify that the bucket assignments match
the intent of the triage spec.

Run:
    python3 -m pytest ops/tests/test_auto_triage_client_threads.py -q
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.auto_triage_client_threads as mod
import scripts.review_client_threads as rct_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_assist(rel="unknown", domain="smart_home_work", conf=0.5, flags=None, evidence=None, scores=None):
    return {
        "suggested_relationship_type": rel,
        "inferred_domain": domain,
        "review_priority": "medium",
        "review_reason": "test reason",
        "confidence": conf,
        "risk_flags": flags or [],
        "evidence": evidence or [],
        "_scores": scores or {},
    }


def _bucket(texts: list[str], name: str, category: str = "work",
            work_confidence: float = 0.75, message_count: int = 10,
            date_last: str = "2026-04-01") -> tuple[str, str, float]:
    """Run real analyze_thread_assist → _determine_triage_bucket end-to-end."""
    assist = rct_mod.analyze_thread_assist(name, texts, [])
    return mod._determine_triage_bucket(
        category=category,
        work_confidence=work_confidence,
        message_count=message_count,
        date_last=date_last,
        name=name,
        assist=assist,
    )


# ── Named contact + smart-home terms → high_value ────────────────────────────

class TestNamedContactHighValue:

    def test_named_with_sonos_and_network_is_high_value(self):
        texts = ["sonos system installed", "network is running great"]
        bucket, reason, conf = _bucket(texts, "Dave Smith")
        assert bucket == "high_value", f"got {bucket}: {reason}"

    def test_named_with_control4_is_high_value(self):
        texts = ["control4 programming is done", "keypads are all working"]
        bucket, reason, conf = _bucket(texts, "Laura White")
        assert bucket == "high_value", f"got {bucket}: {reason}"

    def test_named_with_single_tech_term_is_high_value(self):
        """Even one tech term should surface a named contact as high_value."""
        texts = ["when can you come do the install?"]
        bucket, reason, conf = _bucket(texts, "Mike Jones")
        assert bucket == "high_value", f"got {bucket}: {reason}"

    def test_named_with_proposal_term_is_high_value(self):
        texts = ["the proposal looks great, when can we start?"]
        bucket, reason, conf = _bucket(texts, "Client Name")
        assert bucket == "high_value", f"got {bucket}: {reason}"

    def test_named_with_symphony_mention_is_high_value(self):
        texts = ["looking forward to working with symphony on this project"]
        bucket, reason, conf = _bucket(texts, "Sarah Cooper")
        assert bucket == "high_value", f"got {bucket}: {reason}"

    def test_named_active_thread_no_signals_but_high_wconf_is_high_value(self):
        """Named + high work_confidence + active thread → high_value even without tech terms."""
        texts = ["sounds good", "see you then", "works for me"]
        bucket, reason, conf = _bucket(
            texts, "Bob Client",
            work_confidence=0.80, message_count=20
        )
        assert bucket == "high_value", f"got {bucket}: {reason}"


# ── Unnamed + weak signal → low_priority ─────────────────────────────────────

class TestUnnamedWeakSignalLowPriority:

    def test_unnamed_no_signals_is_low_priority(self):
        texts = ["ok", "sounds good", "see you later"]
        bucket, _, _ = _bucket(texts, "", message_count=5)
        assert bucket == "low_priority", f"got {bucket}"

    def test_unnamed_single_weak_term_small_thread_is_low_priority(self):
        texts = ["the install looks good"]
        bucket, _, _ = _bucket(texts, "", message_count=1)
        assert bucket == "low_priority", f"got {bucket}"

    def test_unnamed_low_work_confidence_is_low_priority(self):
        texts = ["hey how are you", "good thanks"]
        bucket, _, _ = _bucket(texts, "", work_confidence=0.30, message_count=5)
        assert bucket == "low_priority", f"got {bucket}"

    def test_unnamed_very_few_messages_is_low_priority(self):
        texts = ["network is slow today"]
        bucket, _, _ = _bucket(texts, "", message_count=2)
        assert bucket == "low_priority", f"got {bucket}"


# ── GC suffix handling ────────────────────────────────────────────────────────

class TestGCSuffixHandling:

    def test_gc_with_restaurant_terms_is_ambiguous(self):
        """GC + restaurant signals → ambiguous (likely Game Creek venue)."""
        texts = ["dinner service was great", "game creek club reservation"]
        bucket, reason, _ = _bucket(texts, "Travis GC")
        assert bucket == "ambiguous", f"got {bucket}: {reason}"
        assert "restaurant" in reason.lower() or "game creek" in reason.lower() or "gc" in reason.lower()

    def test_gc_with_no_signals_is_ambiguous(self):
        """GC with no clear signals → ambiguous for manual review."""
        texts = ["sounds good", "let me know"]
        bucket, reason, _ = _bucket(texts, "Eagle GC")
        assert bucket == "ambiguous", f"got {bucket}: {reason}"
        assert "gc" in reason.lower()

    def test_gc_with_strong_tech_signals_is_high_value(self):
        """GC + 3+ distinct tech terms → high_value with gc risk flag noted."""
        texts = [
            "control4 programming done",
            "sonos configured in theater room",
            "keypad and lighting scenes working",
            "network rack fully installed",
        ]
        bucket, reason, conf = _bucket(texts, "Eagle GC", message_count=30)
        assert bucket == "high_value", f"got {bucket}: {reason}"
        # risk flag should still be in the assist
        assist = rct_mod.analyze_thread_assist("Eagle GC", texts, [])
        assert "gc_suffix_ambiguous" in assist["risk_flags"]

    def test_gc_with_single_tech_and_no_restaurant_is_ambiguous(self):
        """GC + 1 tech term (not enough for high_value) → ambiguous."""
        texts = ["network is running well", "let me know if you need anything"]
        bucket, reason, _ = _bucket(texts, "Aspen GC")
        assert bucket == "ambiguous", f"got {bucket}: {reason}"

    def test_gc_not_automatically_high_value_by_name_alone(self):
        """GC suffix alone (no signals) must not be high_value."""
        bucket, _, _ = _bucket([], "Mystery GC", work_confidence=0.90, message_count=50)
        assert bucket != "high_value", f"GC with no signals should not be high_value"


# ── Ambiguous requires actual conflicting signals ─────────────────────────────

class TestAmbiguousRequiresConflict:

    def test_builder_coordination_domain_is_ambiguous(self):
        """Builder + tech mix → ambiguous (contractor role unclear)."""
        assist = _make_assist(
            domain="builder_coordination", conf=0.55,
            scores={"tech": 1, "builder": 1, "restaurant": 0, "vendor": 0}
        )
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.75, 15, "2026-04-01", "", assist
        )
        assert bucket == "ambiguous", f"got {bucket}"

    def test_restaurant_domain_is_ambiguous(self):
        """Restaurant signals → ambiguous (AV client or venue?)."""
        texts = ["dinner at game creek was great", "kitchen renovation is going well"]
        bucket, _, _ = _bucket(texts, "")
        assert bucket == "ambiguous", f"got {bucket}"

    def test_mixed_category_with_substance_is_ambiguous(self):
        """Mixed work/personal with enough messages → ambiguous."""
        assist = _make_assist(conf=0.40, scores={"tech": 0, "restaurant": 0, "builder": 0, "vendor": 0})
        bucket, reason, _ = mod._determine_triage_bucket(
            "mixed", 0.65, 15, "2026-04-01", "", assist
        )
        assert bucket == "ambiguous", f"got {bucket}: {reason}"
        assert "mixed" in reason.lower()

    def test_mixed_category_tiny_weak_thread_is_low_priority(self):
        """Mixed + tiny thread + low work confidence → low_priority."""
        assist = _make_assist(conf=0.20, scores={"tech": 0, "restaurant": 0, "builder": 0, "vendor": 0})
        bucket, _, _ = mod._determine_triage_bucket(
            "mixed", 0.30, 2, "2026-04-01", "", assist
        )
        assert bucket == "low_priority", f"got {bucket}"

    def test_named_contact_with_no_signals_low_wconf_is_ambiguous_not_high_value(self):
        """Named + very low work_confidence → ambiguous (might be personal)."""
        assist = _make_assist(conf=0.20, scores={"tech": 0, "restaurant": 0, "builder": 0, "vendor": 0})
        bucket, reason, _ = mod._determine_triage_bucket(
            "work", 0.30, 5, "2026-04-01", "Friend Name", assist
        )
        assert bucket == "ambiguous", f"got {bucket}: {reason}"
        assert "weak" in reason.lower() or "personal" in reason.lower()

    def test_default_bucket_is_not_ambiguous(self):
        """Threads with no meaningful signals should default to low_priority, not ambiguous."""
        assist = _make_assist(conf=0.20, scores={"tech": 0, "restaurant": 0, "builder": 0, "vendor": 0})
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.60, 8, "2026-04-01", "", assist
        )
        assert bucket == "low_priority", f"default should be low_priority, got {bucket}"


# ── analyze_thread_assist scoring fixes ──────────────────────────────────────

class TestAnalyzeThreadAssistScoring:

    def test_tech_s_2_gives_meaningful_confidence(self):
        """tech_s==2 should give conf>=0.50, not fall to 0.25 (bug fix)."""
        texts = ["sonos configured", "network is running"]
        result = rct_mod.analyze_thread_assist("", texts, [])
        assert result["confidence"] >= 0.50, (
            f"tech_s=2 should give conf>=0.50, got {result['confidence']}"
        )

    def test_tech_s_1_gives_at_least_0_40(self):
        """Single tech signal should give conf>=0.40 (raised from 0.35)."""
        texts = ["sonos is working great"]
        result = rct_mod.analyze_thread_assist("", texts, [])
        assert result["confidence"] >= 0.40, (
            f"tech_s=1 should give conf>=0.40, got {result['confidence']}"
        )

    def test_tech_s_3_plus_gives_conf_above_0_65(self):
        """Three+ tech signals → conf≥0.70, classifying as 'client'."""
        texts = ["control4 programming complete", "sonos installed", "lighting scenes set"]
        result = rct_mod.analyze_thread_assist("", texts, [])
        assert result["confidence"] >= 0.65, (
            f"tech_s>=3 should give conf>=0.65, got {result['confidence']}"
        )
        assert result["suggested_relationship_type"] == "client"

    def test_low_voltage_term_counts_as_tech(self):
        """'low voltage' should count as a tech term."""
        texts = ["we do low voltage work", "structured wiring throughout"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["tech"] >= 1, f"low voltage not scored as tech: {scores}"

    def test_rough_in_term_counts_as_tech(self):
        texts = ["rough in for av is complete"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["tech"] >= 1, f"rough in not scored as tech: {scores}"

    def test_no_signals_gives_low_confidence(self):
        texts = ["hey how are you", "let me know"]
        result = rct_mod.analyze_thread_assist("", texts, [])
        assert result["confidence"] <= 0.25

    def test_scores_key_present_in_result(self):
        texts = ["control4 lighting installed"]
        result = rct_mod.analyze_thread_assist("", texts, [])
        assert "_scores" in result
        assert isinstance(result["_scores"], dict)


# ── Full pipeline: named contact + moderate terms → high_value ────────────────

class TestNamedModerateMsgsHighValue:

    def _run(self, tmp_path, texts, name, message_count=15, work_confidence=0.75):
        """Build a minimal thread DB and run triage, returning the result entry."""
        db = tmp_path / "threads.sqlite"
        chat_guid = "iMessage;-;+15550009999"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
            )
        """)
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", chat_guid, "+15550009999", message_count,
             "2026-01-01", "2026-04-01", "work", work_confidence, "[]", -1, "unknown", "2026-01-01"),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=texts):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        return result

    def test_named_network_sonos_multiple_msgs_is_high_value(self, tmp_path):
        result = self._run(
            tmp_path,
            texts=["sonos multi-room audio", "network is up", "rack wired"],
            name="Jane Client",
            message_count=20,
        )
        assert result["processed"] == 1
        entry = result["results"][0]
        assert entry["triage_bucket"] == "high_value", (
            f"expected high_value, got {entry['triage_bucket']}: {entry['triage_reason']}"
        )

    def test_named_moderate_work_conf_active_thread_is_high_value(self, tmp_path):
        result = self._run(
            tmp_path,
            texts=["sounds good", "let's meet tuesday"],
            name="Dave Builder",
            message_count=18,
            work_confidence=0.80,
        )
        assert result["processed"] == 1
        entry = result["results"][0]
        assert entry["triage_bucket"] == "high_value", (
            f"expected high_value, got {entry['triage_bucket']}: {entry['triage_reason']}"
        )

    def test_unnamed_no_signals_tiny_thread_is_low_priority(self, tmp_path):
        result = self._run(
            tmp_path,
            texts=["ok", "thanks"],
            name="",
            message_count=2,
            work_confidence=0.60,
        )
        assert result["processed"] == 1
        entry = result["results"][0]
        assert entry["triage_bucket"] == "low_priority", (
            f"expected low_priority, got {entry['triage_bucket']}: {entry['triage_reason']}"
        )

    def test_review_value_score_present_in_result(self, tmp_path):
        """review_value_score should be present in every triage result entry."""
        result = self._run(
            tmp_path,
            texts=["sonos installed", "network rack done"],
            name="Jane Client",
            message_count=20,
        )
        entry = result["results"][0]
        assert "review_value_score" in entry, "review_value_score missing from result"
        assert 0.0 <= entry["review_value_score"] <= 1.0

    def test_named_high_tech_has_higher_review_value_than_unnamed_no_tech(self, tmp_path):
        """Named contact with tech signals should score higher than unnamed with no signals."""
        result_named = self._run(
            tmp_path,
            texts=["control4 programming done", "sonos multi-room"],
            name="Rich Client",
            message_count=30,
        )
        tmp_path2 = tmp_path / "sub"
        tmp_path2.mkdir()
        result_unnamed = self._run(
            tmp_path2,
            texts=["ok", "sounds good"],
            name="",
            message_count=3,
            work_confidence=0.40,
        )
        val_named   = result_named["results"][0]["review_value_score"]
        val_unnamed = result_unnamed["results"][0]["review_value_score"]
        assert val_named > val_unnamed, (
            f"named+tech ({val_named}) should outscore unnamed+no-signals ({val_unnamed})"
        )


# ── Restaurant signal hardening ────────────────────────────────────────────────

class TestRestaurantSignalHardening:

    def test_table_alone_gives_zero_restaurant_score(self):
        """'table' alone (a weak term) must NOT trigger restaurant_work."""
        texts = ["let me know about the table", "see you at the table"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["restaurant"] == 0, (
            f"'table' alone should give restaurant=0, got {scores['restaurant']}"
        )

    def test_table_with_strong_term_counts(self):
        """'table' + 'chef' (strong) should count as restaurant=2."""
        texts = ["the chef set up the table for the event"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["restaurant"] >= 2, (
            f"table+chef should give restaurant>=2, got {scores['restaurant']}"
        )

    def test_strong_term_alone_scores_as_restaurant(self):
        """A strong term like 'reservation' alone should score restaurant>=1."""
        texts = ["reservation confirmed for 8pm"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["restaurant"] >= 1, (
            f"'reservation' should score restaurant>=1, got {scores['restaurant']}"
        )

    def test_game_creek_is_strong_restaurant_term(self):
        """'game creek' is a known Eagle County venue — strong restaurant signal."""
        texts = ["dinner at game creek was great"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert scores["restaurant"] >= 1, (
            f"'game creek' should score restaurant>=1, got {scores['restaurant']}"
        )
        assert scores.get("restaurant_strong", 0) >= 1

    def test_unnamed_table_only_thread_is_low_priority(self):
        """Unnamed thread with only 'table' (weak term) → low_priority, not ambiguous."""
        texts = ["ok the table looks good", "see you then"]
        bucket, reason, _ = _bucket(texts, "", message_count=5)
        assert bucket == "low_priority", (
            f"'table'-only unnamed should be low_priority, got {bucket}: {reason}"
        )

    def test_unnamed_table_only_large_thread_is_low_priority(self):
        """Even a larger unnamed thread with only weak restaurant terms → low_priority."""
        texts = ["dinner plans set", "lunch at noon", "breakfast meeting"]
        bucket, reason, _ = _bucket(texts, "", message_count=15, work_confidence=0.65)
        assert bucket == "low_priority", (
            f"weak-only restaurant unnamed should be low_priority, got {bucket}: {reason}"
        )

    def test_gc_with_strong_restaurant_term_is_ambiguous(self):
        """GC contact with a strong restaurant term (chef) → ambiguous."""
        texts = ["the chef came by", "kitchen is ready"]
        bucket, reason, _ = _bucket(texts, "Eagle GC")
        assert bucket == "ambiguous", f"GC+strong-restaurant should be ambiguous, got {bucket}"

    def test_restaurant_strong_key_in_scores(self):
        """_score_domain_signals should return 'restaurant_strong' key."""
        texts = ["restaurant reservation confirmed"]
        scores = rct_mod._score_domain_signals(texts, [])
        assert "restaurant_strong" in scores, f"'restaurant_strong' key missing: {scores}"


class TestReviewIntelligence:
    """Tests for review_reason_summary, review_next_action, evidence_categories."""

    def _run(self, tmp_path, texts, name, message_count=15, work_confidence=0.75):
        db = tmp_path / "threads.sqlite"
        chat_guid = "iMessage;-;+15550009999"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
            )
        """)
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", chat_guid, "+15550009999", message_count,
             "2026-01-01", "2026-04-01", "work", work_confidence, "[]", -1, "unknown", "2026-01-01"),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=texts):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        return result["results"][0]

    def test_saved_contact_with_smart_home_terms_has_reason_summary(self, tmp_path):
        entry = self._run(
            tmp_path,
            texts=["sonos multi-room audio installed", "network rack done"],
            name="Jane Client",
            message_count=14,
        )
        assert entry["triage_bucket"] == "high_value"
        summary = entry.get("review_reason_summary", "")
        assert summary, "review_reason_summary should not be empty"
        assert "jane client" in summary.lower() or "saved contact" in summary.lower()

    def test_proposal_install_terms_generates_high_value(self, tmp_path):
        entry = self._run(
            tmp_path,
            texts=["the proposal looks great", "when can you start the install?"],
            name="Client Name",
            message_count=10,
        )
        assert entry["triage_bucket"] == "high_value", (
            f"proposal+install should be high_value, got {entry['triage_bucket']}: {entry.get('triage_reason')}"
        )

    def test_gc_restaurant_has_ambiguous_next_action(self, tmp_path):
        entry = self._run(
            tmp_path,
            texts=["dinner service was great", "game creek reservation"],
            name="Travis GC",
            message_count=15,
        )
        assert entry["triage_bucket"] == "ambiguous"
        action = entry.get("review_next_action", "")
        assert action, "review_next_action should not be empty"
        assert "gc" in action.lower() or "game creek" in action.lower() or "ambiguous" in action.lower()

    def test_unnamed_restaurant_only_gets_defer_action(self, tmp_path):
        entry = self._run(
            tmp_path,
            texts=["dinner reservation confirmed", "kitchen team is ready"],
            name="",
            message_count=8,
        )
        assert entry["triage_bucket"] in ("low_priority", "ambiguous")
        action = entry.get("review_next_action", "")
        assert action, "review_next_action should not be empty"
        assert "defer" in action.lower() or "restaurant" in action.lower() or "profile" in action.lower()

    def test_stale_unnamed_weak_thread_is_low_priority(self, tmp_path):
        db = tmp_path / "threads.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2020-01-01', date_last TEXT DEFAULT '2020-06-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.65,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2020-01-01'
            )
        """)
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "iMessage;-;+15550001234", "+15550001234", 3,
             "2020-01-01", "2020-06-01", "work", 0.65, "[]", -1, "unknown", "2020-01-01"),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["ok", "sounds good"]):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        entry = result["results"][0]
        assert entry["triage_bucket"] == "low_priority", (
            f"stale+weak should be low_priority, got {entry['triage_bucket']}: {entry.get('triage_reason')}"
        )

    def test_reason_summary_not_empty_for_all_buckets(self, tmp_path):
        """Every result should have a non-empty review_reason_summary."""
        db = tmp_path / "threads.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
            )
        """)
        rows = [
            ("t1", "iMessage;-;+15550001111", "+15550001111", 20, "2026-01-01", "2026-04-01", "work", 0.85, "[]", -1, "unknown", "2026-01-01"),
            ("t2", "iMessage;-;+15550002222", "+15550002222", 3,  "2026-01-01", "2026-04-01", "work", 0.50, "[]", -1, "unknown", "2026-01-01"),
        ]
        conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.row_factory = sqlite3.Row
        def fake_name(handle):
            return "Rich Client" if "1111" in handle else ""
        def fake_texts(guid):
            if "1111" in guid:
                return ["control4 programming done", "sonos installed"]
            return ["ok", "thanks"]
        with patch.object(rct_mod, "_lookup_contact_name", side_effect=fake_name), \
             patch.object(rct_mod, "_fetch_sample_texts", side_effect=fake_texts):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        for entry in result["results"]:
            assert entry.get("review_reason_summary"), (
                f"review_reason_summary empty for {entry['triage_bucket']}: {entry}"
            )

    def test_is_reviewed_never_changed(self, tmp_path):
        """is_reviewed must remain -1 after triage."""
        db = tmp_path / "threads.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
            )
        """)
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "iMessage;-;+15550009999", "+15550009999", 20,
             "2026-01-01", "2026-04-01", "work", 0.85, "[]", -1, "unknown", "2026-01-01"),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value="Test Client"), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["sonos installed"]):
            mod.run_triage(conn, dry_run=False)
        is_reviewed = conn.execute("SELECT is_reviewed FROM threads WHERE thread_id='t1'").fetchone()[0]
        conn.close()
        assert is_reviewed == -1, f"is_reviewed was modified! got {is_reviewed}"

    def test_evidence_categories_present_in_result(self, tmp_path):
        """evidence_categories should be a non-None list in every result."""
        db = tmp_path / "threads.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
                contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
                date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
                category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
                reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
                relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
            )
        """)
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "iMessage;-;+15550009999", "+15550009999", 15,
             "2026-01-01", "2026-04-01", "work", 0.80, "[]", -1, "unknown", "2026-01-01"),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value="Test Client"), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["control4 install done"]):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        entry = result["results"][0]
        assert "evidence_categories" in entry
        cats = json.loads(entry["evidence_categories"])
        assert isinstance(cats, list)
        assert "saved_contact" in cats
        assert "smart_home_terms" in cats or "service_terms" in cats


# ── Project context linking ───────────────────────────────────────────────────

def _make_thread_conn(tmp_path, handle="+15550001234", message_count=10,
                      is_reviewed=-1, relationship_type="unknown"):
    """Create a minimal in-memory threads table for project context tests."""
    db = tmp_path / "threads.sqlite"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY, chat_guid TEXT NOT NULL DEFAULT '',
            contact_handle TEXT NOT NULL, message_count INTEGER DEFAULT 10,
            date_first TEXT DEFAULT '2026-01-01', date_last TEXT DEFAULT '2026-04-01',
            category TEXT DEFAULT 'work', work_confidence REAL DEFAULT 0.8,
            reason_codes TEXT DEFAULT '[]', is_reviewed INTEGER DEFAULT -1,
            relationship_type TEXT DEFAULT 'unknown', created_at TEXT DEFAULT '2026-01-01'
        )
    """)
    conn.execute(
        "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("t1", f"iMessage;-;{handle}", handle, message_count,
         "2026-01-01", "2026-04-01", "work", 0.8, "[]", is_reviewed,
         relationship_type, "2026-01-01"),
    )
    conn.commit()
    return conn


class TestProjectContextLinking:

    def test_eagle_county_location_in_texts_gives_project_hint(self, tmp_path):
        conn = _make_thread_conn(tmp_path)
        ctx = mod._build_project_context(
            conn, "+15550001234", "Jane Client", 10, "2026-04-01",
            ["let's meet at the beaver creek property Tuesday"],
        )
        conn.close()
        assert ctx["project_hint"].lower() == "beaver creek"
        assert ctx["project_confidence"] == pytest.approx(0.80)

    def test_vail_location_in_texts_gives_project_hint(self, tmp_path):
        conn = _make_thread_conn(tmp_path)
        ctx = mod._build_project_context(
            conn, "+15550001234", "", 5, "2026-04-01",
            ["the vail house needs a network upgrade"],
        )
        conn.close()
        assert ctx["project_hint"].lower() == "vail"
        assert ctx["project_confidence"] == pytest.approx(0.80)

    def test_generic_phrase_gives_low_confidence_project_hint(self, tmp_path):
        conn = _make_thread_conn(tmp_path)
        ctx = mod._build_project_context(
            conn, "+15550001234", "", 5, "2026-04-01",
            ["sounds good, I'll come by the house"],
        )
        conn.close()
        assert ctx["project_hint"] != ""
        assert ctx["project_confidence"] == pytest.approx(0.35)

    def test_no_location_signals_gives_empty_project_hint(self, tmp_path):
        conn = _make_thread_conn(tmp_path)
        ctx = mod._build_project_context(
            conn, "+15550001234", "", 5, "2026-04-01",
            ["ok thanks", "see you then"],
        )
        conn.close()
        assert ctx["project_hint"] == ""
        assert ctx["project_confidence"] == pytest.approx(0.0)

    def test_named_contact_with_20_msgs_is_repeat_contact(self, tmp_path):
        conn = _make_thread_conn(tmp_path, message_count=20)
        ctx = mod._build_project_context(
            conn, "+15550001234", "Dave Builder", 20, "2026-04-01", [],
        )
        conn.close()
        assert ctx["repeat_contact"] == 1

    def test_named_contact_with_fewer_than_20_msgs_not_repeat(self, tmp_path):
        conn = _make_thread_conn(tmp_path, message_count=15)
        ctx = mod._build_project_context(
            conn, "+15550001234", "Dave Builder", 15, "2026-04-01", [],
        )
        conn.close()
        assert ctx["repeat_contact"] == 0

    def test_unnamed_contact_not_repeat_regardless_of_msgs(self, tmp_path):
        conn = _make_thread_conn(tmp_path, message_count=50)
        ctx = mod._build_project_context(
            conn, "+15550001234", "", 50, "2026-04-01", [],
        )
        conn.close()
        assert ctx["repeat_contact"] == 0

    def test_approved_profile_match_sets_known_relationship(self, tmp_path):
        """If the same normalized phone exists in an approved (is_reviewed=1) row, known_relationship is populated."""
        conn = _make_thread_conn(tmp_path, handle="+15550001234", message_count=5)
        # Insert an approved row with the same number
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("approved1", "iMessage;-;+15550001234", "+15550001234", 30,
             "2025-06-01", "2025-12-01", "work", 0.9, "[]", 1, "client", "2025-06-01"),
        )
        conn.commit()
        ctx = mod._build_project_context(
            conn, "+15550001234", "", 5, "2026-04-01", [],
        )
        conn.close()
        assert ctx["known_relationship"] == "client"
        assert ctx["repeat_contact"] == 1
        assert ctx["previous_thread_count"] >= 1

    def test_review_value_score_boosted_for_repeat_contact(self, tmp_path):
        """repeat_contact should increase review_value_score vs identical thread without it."""
        (tmp_path / "base").mkdir()
        (tmp_path / "repeat").mkdir()
        conn_base = _make_thread_conn(tmp_path / "base", handle="+15550001111", message_count=5)
        conn_repeat = _make_thread_conn(tmp_path / "repeat", handle="+15550002222", message_count=20)

        with patch.object(rct_mod, "_lookup_contact_name", side_effect=lambda h, *a, **kw: "Test Client"), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["sonos install network rack"]):
            result_base   = mod.run_triage(conn_base,   dry_run=True)
            result_repeat = mod.run_triage(conn_repeat, dry_run=True)
        conn_base.close()
        conn_repeat.close()

        rvs_base   = result_base["results"][0]["review_value_score"]
        rvs_repeat = result_repeat["results"][0]["review_value_score"]
        assert rvs_repeat >= rvs_base, (
            f"repeat contact (val={rvs_repeat:.3f}) should score >= base (val={rvs_base:.3f})"
        )

    def test_project_hint_fields_present_in_all_results(self, tmp_path):
        """Every triage result must include the 6 project context fields."""
        conn = _make_thread_conn(tmp_path, message_count=8)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["ok", "thanks"]):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        entry = result["results"][0]
        for field in ("project_hint", "project_confidence", "repeat_contact",
                      "previous_thread_count", "last_interaction_date", "known_relationship"):
            assert field in entry, f"Missing field: {field}"

    def test_extract_project_hints_direct_eagle_county(self):
        """Unit test _extract_project_hints directly for Eagle County location."""
        hint, conf = rct_mod._extract_project_hints(["I'm at the edwards house this week"])
        assert hint.lower() == "edwards"
        assert conf == pytest.approx(0.80)

    def test_extract_project_hints_direct_no_signal(self):
        """Unit test _extract_project_hints when no signals present."""
        hint, conf = rct_mod._extract_project_hints(["sounds good", "see you at noon"])
        assert hint == ""
        assert conf == pytest.approx(0.0)
