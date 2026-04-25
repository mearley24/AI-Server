"""
Tests for scripts/auto_triage_client_threads.py

Covers: bucket determination (pure logic), triage runner (dry-run / apply),
approved/rejected thread isolation, schema migration, get_triage_summary,
get_review_queue, and Cortex endpoint shapes.
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

def _make_assist(
    rel: str = "unknown",
    domain: str = "smart_home_work",
    conf: float = 0.5,
    flags: "list[str] | None" = None,
    evidence: "list[str] | None" = None,
) -> dict:
    return {
        "suggested_relationship_type": rel,
        "inferred_domain": domain,
        "review_priority": "medium",
        "review_reason": "test reason",
        "confidence": conf,
        "risk_flags": flags or [],
        "evidence": evidence or [],
    }


def _create_thread_db(path: Path, threads: list[dict]) -> Path:
    db = path / "threads.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY,
            chat_guid TEXT NOT NULL DEFAULT '',
            contact_handle TEXT NOT NULL,
            message_count INTEGER DEFAULT 10,
            date_first TEXT DEFAULT '2026-01-01T00:00:00',
            date_last  TEXT DEFAULT '2026-04-01T00:00:00',
            category TEXT DEFAULT 'work',
            work_confidence REAL DEFAULT 0.8,
            reason_codes TEXT DEFAULT '[]',
            is_reviewed INTEGER DEFAULT -1,
            relationship_type TEXT DEFAULT 'unknown',
            created_at TEXT DEFAULT '2026-01-01T00:00:00'
        )
    """)
    for t in threads:
        tid = t.get("thread_id", "t1")
        conn.execute("""
            INSERT INTO threads
              (thread_id, chat_guid, contact_handle, message_count,
               date_first, date_last, category, work_confidence, reason_codes, is_reviewed)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            tid,
            t.get("chat_guid", f"guid-{tid}"),
            t.get("contact_handle", "+15550000000"),
            t.get("message_count", 10),
            t.get("date_first", "2026-01-01"),
            t.get("date_last", "2026-04-01"),
            t.get("category", "work"),
            t.get("work_confidence", 0.8),
            t.get("reason_codes", "[]"),
            t.get("is_reviewed", -1),
        ))
    conn.commit()
    conn.close()
    return db


def _open_rw(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


# ── mock helpers ─────────────────────────────────────────────────────────────

def _null_lookup(handle: str) -> str:
    return ""


def _null_texts(guid: str, n: int = 20) -> list[str]:
    return []


# ── TestDetermineTriageBucket ─────────────────────────────────────────────────

class TestDetermineTriageBucket:
    """Pure function — no DB or external calls."""

    def test_personal_always_hidden_personal(self):
        bucket, _, _ = mod._determine_triage_bucket(
            "personal", 0.9, 50, "2026-01-01", "John Smith", _make_assist(conf=0.9)
        )
        assert bucket == "hidden_personal"

    def test_personal_overrides_high_signals(self):
        """personal category wins even with high confidence and named contact."""
        bucket, _, _ = mod._determine_triage_bucket(
            "personal", 0.95, 100, "2026-01-01", "Top Client", _make_assist(conf=0.95)
        )
        assert bucket == "hidden_personal"

    def test_gc_suffix_always_ambiguous(self):
        assist = _make_assist(flags=["gc_suffix_ambiguous"])
        bucket, reason, conf = mod._determine_triage_bucket(
            "work", 0.9, 30, "2026-01-01", "Travis GC", assist
        )
        assert bucket == "ambiguous"
        assert "GC" in reason

    def test_named_high_assist_conf_is_high_value(self):
        assist = _make_assist(conf=0.75)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.8, 20, "2026-01-01", "John Smith", assist
        )
        assert bucket == "high_value"

    def test_named_high_work_confidence_is_high_value(self):
        assist = _make_assist(conf=0.40)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.85, 5, "2026-01-01", "Jane Doe", assist
        )
        assert bucket == "high_value"

    def test_named_many_messages_moderate_signals_is_high_value(self):
        assist = _make_assist(conf=0.50)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 25, "2026-01-01", "Bob Client", assist
        )
        assert bucket == "high_value"

    def test_very_strong_unnamed_signals_is_high_value(self):
        """assist_conf >= 0.80 surfaces even unnamed contacts."""
        assist = _make_assist(conf=0.85)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 20, "2026-01-01", "", assist
        )
        assert bucket == "high_value"

    def test_restaurant_domain_is_ambiguous(self):
        assist = _make_assist(domain="restaurant_work", rel="restaurant_work", conf=0.6)
        bucket, reason, _ = mod._determine_triage_bucket(
            "work", 0.7, 15, "2026-01-01", "", assist
        )
        assert bucket == "ambiguous"
        assert "restaurant" in reason.lower()

    def test_builder_coordination_is_ambiguous(self):
        assist = _make_assist(domain="builder_coordination", rel="builder", conf=0.6)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.75, 15, "2026-01-01", "", assist
        )
        assert bucket == "ambiguous"

    def test_mixed_category_is_ambiguous(self):
        assist = _make_assist(conf=0.5)
        bucket, _, _ = mod._determine_triage_bucket(
            "mixed", 0.7, 12, "2026-01-01", "", assist
        )
        assert bucket == "ambiguous"

    def test_old_thread_with_signals_is_ambiguous(self):
        assist = _make_assist(conf=0.4)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 10, "2021-06-01", "", assist
        )
        assert bucket == "ambiguous"

    def test_large_thread_low_conf_is_ambiguous(self):
        assist = _make_assist(conf=0.35)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 60, "2026-01-01", "", assist
        )
        assert bucket == "ambiguous"

    def test_unnamed_low_conf_is_low_priority(self):
        assist = _make_assist(conf=0.25)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.6, 10, "2026-01-01", "", assist
        )
        assert bucket == "low_priority"

    def test_unnamed_few_messages_is_low_priority(self):
        assist = _make_assist(conf=0.55)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 3, "2026-01-01", "", assist
        )
        assert bucket == "low_priority"

    def test_unnamed_below_work_threshold_is_low_priority(self):
        assist = _make_assist(conf=0.5)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.50, 10, "2026-01-01", "", assist
        )
        assert bucket == "low_priority"

    def test_unknown_category_is_low_priority(self):
        assist = _make_assist(conf=0.45)
        bucket, _, _ = mod._determine_triage_bucket(
            "unknown", 0.65, 8, "2026-01-01", "", assist
        )
        assert bucket == "low_priority"

    def test_result_always_valid_bucket(self):
        cases = [
            ("personal", 0.9, 50, "2026-01-01", "Alice"),
            ("work", 0.8, 20, "2026-01-01", "Bob"),
            ("work", 0.5, 3, "2026-01-01", ""),
            ("mixed", 0.7, 15, "2021-01-01", ""),
        ]
        for cat, wconf, msgs, dl, name in cases:
            bucket, reason, conf = mod._determine_triage_bucket(
                cat, wconf, msgs, dl, name, _make_assist()
            )
            assert bucket in mod.TRIAGE_BUCKETS, f"invalid bucket '{bucket}'"
            assert isinstance(reason, str) and reason
            assert 0.0 <= conf <= 1.0

    def test_gc_suffix_before_high_value(self):
        """GC suffix with a named contact still lands in ambiguous, not high_value."""
        assist = _make_assist(conf=0.90, flags=["gc_suffix_ambiguous"])
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.9, 50, "2026-01-01", "Eagle GC", assist
        )
        assert bucket == "ambiguous"


# ── TestSchemaMigration ───────────────────────────────────────────────────────

class TestSchemaMigration:

    def test_ensure_triage_columns_idempotent(self, tmp_path):
        db = _create_thread_db(tmp_path, [])
        conn = _open_rw(db)
        mod._ensure_triage_columns(conn)
        mod._ensure_triage_columns(conn)  # second call must not raise
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        conn.close()
        for col, _ in mod._TRIAGE_COLS:
            assert col in cols, f"missing column: {col}"

    def test_triage_cols_added_to_existing_table(self, tmp_path):
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        mod._ensure_triage_columns(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        conn.close()
        assert "triage_bucket" in cols
        assert "triaged_at" in cols


# ── TestTriageDryRun ──────────────────────────────────────────────────────────

class TestTriageDryRun:

    def _run(self, tmp_path, threads, assist_conf=0.3, name=""):
        db = _create_thread_db(tmp_path, threads)
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=assist_conf)):
            result = mod.run_triage(conn, dry_run=True)
        conn.close()
        return db, result

    def test_dry_run_flag_in_result(self, tmp_path):
        _, result = self._run(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        assert result["dry_run"] is True

    def test_dry_run_no_db_writes(self, tmp_path):
        db, _ = self._run(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        check = sqlite3.connect(str(db))
        has_col = any(r[1] == "triage_bucket" for r in check.execute("PRAGMA table_info(threads)").fetchall())
        if has_col:
            val = check.execute("SELECT triage_bucket FROM threads WHERE thread_id='t1'").fetchone()[0]
            assert val is None
        check.close()

    def test_dry_run_processed_count(self, tmp_path):
        _, result = self._run(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001"},
            {"thread_id": "t2", "contact_handle": "+15550000002"},
        ])
        assert result["processed"] == 2

    def test_dry_run_results_have_required_keys(self, tmp_path):
        _, result = self._run(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        assert result["results"]
        entry = result["results"][0]
        for key in ("triage_bucket", "triage_reason", "triage_confidence",
                    "triage_suggested_relationship", "triage_inferred_domain",
                    "triage_risk_flags", "contact_masked"):
            assert key in entry, f"missing key: {key}"

    def test_dry_run_bucket_in_valid_set(self, tmp_path):
        _, result = self._run(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        assert result["results"][0]["triage_bucket"] in mod.TRIAGE_BUCKETS

    def test_dry_run_contact_is_masked(self, tmp_path):
        _, result = self._run(tmp_path, [{"thread_id": "t1", "contact_handle": "+15551234567"}])
        masked = result["results"][0]["contact_masked"]
        assert "+15551234567" not in masked
        assert "***" in masked


# ── TestTriageApply ───────────────────────────────────────────────────────────

class TestTriageApply:

    def _apply(self, tmp_path, threads, assist=None, name=""):
        db = _create_thread_db(tmp_path, threads)
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist",
                          return_value=assist or _make_assist(conf=0.25)):
            result = mod.run_triage(conn, dry_run=False)
        conn.close()
        return db, result

    def test_apply_writes_triage_bucket(self, tmp_path):
        db, _ = self._apply(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        check = sqlite3.connect(str(db))
        row = check.execute("SELECT triage_bucket FROM threads WHERE thread_id='t1'").fetchone()
        check.close()
        assert row[0] in mod.TRIAGE_BUCKETS

    def test_apply_writes_triaged_at(self, tmp_path):
        db, _ = self._apply(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        check = sqlite3.connect(str(db))
        ts = check.execute("SELECT triaged_at FROM threads WHERE thread_id='t1'").fetchone()[0]
        check.close()
        assert ts is not None and len(ts) > 10

    def test_apply_does_not_change_is_reviewed(self, tmp_path):
        db, _ = self._apply(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001", "is_reviewed": -1}])
        check = sqlite3.connect(str(db))
        is_rev = check.execute("SELECT is_reviewed FROM threads WHERE thread_id='t1'").fetchone()[0]
        check.close()
        assert is_rev == -1

    def test_approved_threads_skipped(self, tmp_path):
        db, result = self._apply(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "is_reviewed": 1},
            {"thread_id": "t2", "contact_handle": "+15550000002", "is_reviewed": -1},
        ])
        assert result["processed"] == 1
        check = sqlite3.connect(str(db))
        t1_bucket = check.execute("SELECT triage_bucket FROM threads WHERE thread_id='t1'").fetchone()[0]
        check.close()
        assert t1_bucket is None

    def test_rejected_threads_skipped(self, tmp_path):
        db, result = self._apply(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "is_reviewed": 0},
        ])
        assert result["processed"] == 0

    def test_personal_threads_bucket_hidden_personal(self, tmp_path):
        db, result = self._apply(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "category": "personal"},
        ])
        assert result["counts"]["hidden_personal"] == 1
        check = sqlite3.connect(str(db))
        bucket = check.execute("SELECT triage_bucket FROM threads WHERE thread_id='t1'").fetchone()[0]
        check.close()
        assert bucket == "hidden_personal"

    def test_named_high_conf_bucket_high_value(self, tmp_path):
        db, result = self._apply(
            tmp_path,
            [{"thread_id": "t1", "contact_handle": "+15550000001", "work_confidence": 0.85}],
            assist=_make_assist(conf=0.75),
            name="John Smith",
        )
        assert result["counts"]["high_value"] == 1

    def test_limit_respected(self, tmp_path):
        threads = [{"thread_id": f"t{i}", "contact_handle": f"+1555{i:07d}"} for i in range(10)]
        db = _create_thread_db(tmp_path, threads)
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            result = mod.run_triage(conn, dry_run=True, limit=4)
        conn.close()
        assert result["processed"] == 4


# ── TestBucketFilter ──────────────────────────────────────────────────────────

class TestBucketFilter:

    def test_bucket_filter_only_returns_matching(self, tmp_path):
        threads = [
            {"thread_id": "t1", "contact_handle": "+15550000001", "category": "personal"},
            {"thread_id": "t2", "contact_handle": "+15550000002", "category": "work"},
        ]
        db = _create_thread_db(tmp_path, threads)
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            result = mod.run_triage(conn, dry_run=True, bucket_filter="hidden_personal")
        conn.close()
        for entry in result["results"]:
            assert entry["triage_bucket"] == "hidden_personal"


# ── TestGetTriageSummary ──────────────────────────────────────────────────────

class TestGetTriageSummary:

    def test_summary_required_keys(self, tmp_path):
        db = _create_thread_db(tmp_path, [])
        conn = _open_rw(db)
        s = mod.get_triage_summary(conn)
        conn.close()
        required = {"high_value", "ambiguous", "low_priority", "hidden_personal", "untriaged", "last_triaged"}
        assert required.issubset(set(s.keys()))

    def test_summary_untriaged_on_fresh_db(self, tmp_path):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001"},
            {"thread_id": "t2", "contact_handle": "+15550000002"},
        ])
        conn = _open_rw(db)
        s = mod.get_triage_summary(conn)
        conn.close()
        assert s["untriaged"] == 2

    def test_summary_counts_after_apply(self, tmp_path):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "category": "personal"},
            {"thread_id": "t2", "contact_handle": "+15550000002", "category": "work"},
        ])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            mod.run_triage(conn, dry_run=False)
        s = mod.get_triage_summary(conn)
        conn.close()
        assert s["hidden_personal"] == 1
        assert s["untriaged"] == 0
        assert s["last_triaged"] is not None

    def test_summary_zeros_on_empty_db(self, tmp_path):
        db = _create_thread_db(tmp_path, [])
        conn = _open_rw(db)
        s = mod.get_triage_summary(conn)
        conn.close()
        for b in ("high_value", "ambiguous", "low_priority", "hidden_personal"):
            assert s[b] == 0


# ── TestGetReviewQueue ────────────────────────────────────────────────────────

class TestGetReviewQueue:

    def _setup(self, tmp_path, threads, assist_conf=0.25, name=""):
        db = _create_thread_db(tmp_path, threads)
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=assist_conf)):
            mod.run_triage(conn, dry_run=False)
        return db, conn

    def test_queue_returns_list(self, tmp_path):
        db, conn = self._setup(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        q = mod.get_review_queue(conn)
        conn.close()
        assert isinstance(q, list)

    def test_queue_all_buckets_returned(self, tmp_path):
        db, conn = self._setup(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001"},
        ])
        q = mod.get_review_queue(conn)
        conn.close()
        assert len(q) == 1

    def test_queue_phone_numbers_masked(self, tmp_path):
        db, conn = self._setup(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15551234567"},
        ])
        q = mod.get_review_queue(conn)
        conn.close()
        assert q
        assert "+15551234567" not in q[0]["contact_masked"]
        assert "***" in q[0]["contact_masked"]

    def test_queue_bucket_filter(self, tmp_path):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "category": "personal"},
            {"thread_id": "t2", "contact_handle": "+15550000002", "category": "work"},
        ])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            mod.run_triage(conn, dry_run=False)
        q = mod.get_review_queue(conn, bucket="hidden_personal")
        conn.close()
        assert all(r["triage_bucket"] == "hidden_personal" for r in q)

    def test_queue_approved_not_returned(self, tmp_path):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "is_reviewed": 1},
            {"thread_id": "t2", "contact_handle": "+15550000002", "is_reviewed": -1},
        ])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            mod.run_triage(conn, dry_run=False)
        q = mod.get_review_queue(conn)
        conn.close()
        thread_ids = [r["thread_id"] for r in q]
        assert "t1" not in thread_ids  # approved not in queue


# ── TestChatDbSnapshot ───────────────────────────────────────────────────────

def _create_snapshot_chat_db(path: Path, guid: str, messages: list[str]) -> Path:
    """Build a minimal chat.db replica at path (same schema as Messages.app)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY, guid TEXT NOT NULL, chat_identifier TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, attributedBody BLOB,
            is_from_me INTEGER DEFAULT 0, date INTEGER DEFAULT 0
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
    """)
    conn.execute("INSERT INTO chat VALUES (1, ?, '+15550000001')", (guid,))
    for i, msg in enumerate(messages, 1):
        conn.execute(
            "INSERT INTO message VALUES (?, ?, NULL, 0, ?)",
            (i, msg, i * 1_000_000_000),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (i,))
    conn.commit()
    conn.close()
    return path


class TestChatDbSnapshot:
    """Verify that --chat-db / chat_db_path redirects _fetch_sample_texts."""

    def test_snapshot_texts_are_read(self, tmp_path):
        """Messages in the snapshot must reach analyze_thread_assist."""
        chat_guid = "iMessage;-;+15550000001"
        snap = _create_snapshot_chat_db(
            tmp_path / "snap" / "chat.db",
            chat_guid,
            [
                "Control4 proposal ready for Beaver Creek project",
                "Sonos system installed, keypad programming done",
                "Lighting scenes updated on the theater system",
            ],
        )

        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1",
            "chat_guid": chat_guid,
            "contact_handle": "+15550000001",
            "work_confidence": 0.80,
            "message_count": 20,
        }])
        conn = _open_rw(db)

        captured_texts: list[list[str]] = []

        def _spy_assist(name, texts, codes):
            captured_texts.append(texts)
            return _make_assist(conf=0.75)

        with patch.object(rct_mod, "_lookup_contact_name", return_value="John Smith"), \
             patch.object(rct_mod, "analyze_thread_assist", side_effect=_spy_assist):
            result = mod.run_triage(conn, dry_run=True, chat_db_path=snap)
        conn.close()

        assert captured_texts, "analyze_thread_assist was never called"
        texts_seen = captured_texts[0]
        assert any("Control4" in t for t in texts_seen), \
            f"snapshot messages not read; got: {texts_seen}"

    def test_snapshot_chat_db_restored_after_run(self, tmp_path):
        """_rct.CHAT_DB must be restored to its original value after run_triage."""
        original_path = rct_mod.CHAT_DB
        chat_guid = "iMessage;-;+15550000002"
        snap = _create_snapshot_chat_db(
            tmp_path / "snap2" / "chat.db", chat_guid, ["hello world"]
        )
        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1", "chat_guid": chat_guid, "contact_handle": "+15550000002",
        }])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True, chat_db_path=snap)
        conn.close()
        assert rct_mod.CHAT_DB == original_path, \
            f"CHAT_DB not restored: got {rct_mod.CHAT_DB}"

    def test_snapshot_restored_even_on_error(self, tmp_path):
        """CHAT_DB must be restored even if the loop raises."""
        original_path = rct_mod.CHAT_DB
        chat_guid = "iMessage;-;+15550000003"
        snap = _create_snapshot_chat_db(
            tmp_path / "snap3" / "chat.db", chat_guid, ["test"]
        )
        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1", "chat_guid": chat_guid, "contact_handle": "+15550000003",
        }])
        conn = _open_rw(db)

        def _boom(name, texts, codes):
            raise RuntimeError("simulated failure")

        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "analyze_thread_assist", side_effect=_boom):
            with pytest.raises(RuntimeError):
                mod.run_triage(conn, dry_run=True, chat_db_path=snap)
        conn.close()
        assert rct_mod.CHAT_DB == original_path, "CHAT_DB not restored after exception"

    def test_no_chat_db_arg_does_not_change_chat_db(self, tmp_path):
        """When chat_db_path is None, _rct.CHAT_DB must not be touched."""
        original_path = rct_mod.CHAT_DB
        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1", "contact_handle": "+15550000004",
        }])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True, chat_db_path=None)
        conn.close()
        assert rct_mod.CHAT_DB == original_path

    def test_snapshot_high_value_from_tech_signals(self, tmp_path):
        """With strong tech messages in snapshot + named contact → high_value bucket."""
        chat_guid = "iMessage;-;+15550000005"
        snap = _create_snapshot_chat_db(
            tmp_path / "snap5" / "chat.db",
            chat_guid,
            [
                "Control4 keypad programming complete",
                "Sonos multi-room audio configured for theater zone",
                "Lighting scenes set via composer, all dimmers tested",
                "Network rack installed with Araknis switch and WattBox",
            ],
        )
        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1",
            "chat_guid": chat_guid,
            "contact_handle": "+15550000005",
            "work_confidence": 0.85,
            "message_count": 30,
        }])
        conn = _open_rw(db)

        # Let analyze_thread_assist run for real (no mock) to test full pipeline.
        with patch.object(rct_mod, "_lookup_contact_name", return_value="Jane Smith"):
            result = mod.run_triage(conn, dry_run=True, chat_db_path=snap)
        conn.close()

        assert result["processed"] == 1
        entry = result["results"][0]
        # Named contact with strong tech signals must land in high_value
        assert entry["triage_bucket"] == "high_value", (
            f"expected high_value, got {entry['triage_bucket']}: {entry['triage_reason']}"
        )


# ── TestCortexEndpoints ───────────────────────────────────────────────────────

class TestCortexEndpoints:
    """Shape tests using FastAPI TestClient with mocked DB."""

    @pytest.fixture
    def client(self):
        try:
            from fastapi.testclient import TestClient
            from cortex.engine import app
            return TestClient(app, raise_server_exceptions=False)
        except ImportError:
            pytest.skip("fastapi.testclient not available")

    def test_triage_summary_shape(self, client, tmp_path):
        db = _create_thread_db(tmp_path, [])
        import cortex.engine as eng
        orig = eng._CLIENT_INTEL_DB
        eng._CLIENT_INTEL_DB = db
        try:
            r = client.get("/api/client-intel/triage-summary")
        finally:
            eng._CLIENT_INTEL_DB = orig
        assert r.status_code == 200
        data = r.json()
        for key in ("high_value", "ambiguous", "low_priority", "hidden_personal", "untriaged"):
            assert key in data, f"missing key: {key}"

    def test_review_queue_shape(self, client, tmp_path):
        db = _create_thread_db(tmp_path, [])
        import cortex.engine as eng
        orig = eng._CLIENT_INTEL_DB
        eng._CLIENT_INTEL_DB = db
        try:
            r = client.get("/api/client-intel/review-queue")
        finally:
            eng._CLIENT_INTEL_DB = orig
        assert r.status_code == 200
        data = r.json()
        assert "threads" in data
        assert "count" in data

    def test_review_queue_invalid_bucket(self, client, tmp_path):
        db = _create_thread_db(tmp_path, [])
        import cortex.engine as eng
        orig = eng._CLIENT_INTEL_DB
        eng._CLIENT_INTEL_DB = db
        try:
            r = client.get("/api/client-intel/review-queue?bucket=nonexistent_bucket")
        finally:
            eng._CLIENT_INTEL_DB = orig
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "error"

    def test_review_queue_bucket_filter(self, client, tmp_path):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15550000001", "category": "personal"},
        ])
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist(conf=0.25)):
            mod.run_triage(conn, dry_run=False)
        conn.close()

        import cortex.engine as eng
        orig = eng._CLIENT_INTEL_DB
        eng._CLIENT_INTEL_DB = db
        try:
            r = client.get("/api/client-intel/review-queue?bucket=hidden_personal")
        finally:
            eng._CLIENT_INTEL_DB = orig
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["threads"][0]["triage_bucket"] == "hidden_personal"


# ── TestAutoSnapshot ──────────────────────────────────────────────────────────

class TestAutoSnapshot:

    def test_auto_snapshot_returns_path_on_success(self, tmp_path):
        fake_src = tmp_path / "chat.db"
        fake_src.write_bytes(b"fakedb")
        snap_dir = tmp_path / "snap"
        with patch.object(mod, "_LIVE_CHAT_DB", fake_src), \
             patch.object(mod, "_SNAPSHOT_DIR", snap_dir):
            result = mod._auto_snapshot()
        assert result is not None
        assert result.name == "chat.db"
        assert result.is_file()

    def test_auto_snapshot_copies_wal_file(self, tmp_path):
        fake_src = tmp_path / "chat.db"
        fake_src.write_bytes(b"fakedb")
        wal = tmp_path / "chat.db-wal"
        wal.write_bytes(b"fakewal")
        snap_dir = tmp_path / "snap"
        with patch.object(mod, "_LIVE_CHAT_DB", fake_src), \
             patch.object(mod, "_SNAPSHOT_DIR", snap_dir):
            mod._auto_snapshot()
        assert (snap_dir / "chat.db-wal").is_file()

    def test_auto_snapshot_returns_none_on_failure(self, tmp_path):
        missing = tmp_path / "nonexistent" / "chat.db"
        snap_dir = tmp_path / "snap"
        with patch.object(mod, "_LIVE_CHAT_DB", missing), \
             patch.object(mod, "_SNAPSHOT_DIR", snap_dir):
            result = mod._auto_snapshot()
        assert result is None

    def test_auto_snapshot_creates_snapshot_dir(self, tmp_path):
        fake_src = tmp_path / "chat.db"
        fake_src.write_bytes(b"fakedb")
        snap_dir = tmp_path / "deep" / "nested" / "snap"
        with patch.object(mod, "_LIVE_CHAT_DB", fake_src), \
             patch.object(mod, "_SNAPSHOT_DIR", snap_dir):
            mod._auto_snapshot()
        assert snap_dir.is_dir()


# ── TestSnapshotDiagnostics ───────────────────────────────────────────────────

class TestSnapshotDiagnostics:

    def test_diagnostics_required_keys(self, tmp_path):
        snap = _create_snapshot_chat_db(
            tmp_path / "chat.db", "iMessage;-;+15550001111", ["hello world"]
        )
        diag = mod._snapshot_diagnostics(snap)
        for key in ("total_messages", "text_messages", "attributed_body_messages",
                    "readable_sample", "readable_sample_of", "coverage_ok"):
            assert key in diag, f"missing key: {key}"

    def test_diagnostics_counts_messages(self, tmp_path):
        snap = _create_snapshot_chat_db(
            tmp_path / "chat.db",
            "iMessage;-;+15550001112",
            ["msg1", "msg2", "msg3"],
        )
        diag = mod._snapshot_diagnostics(snap)
        assert diag["total_messages"] == 3
        assert diag["text_messages"] == 3

    def test_diagnostics_empty_db(self, tmp_path):
        snap = _create_snapshot_chat_db(tmp_path / "chat.db", "iMessage;-;+1", [])
        diag = mod._snapshot_diagnostics(snap)
        assert diag["total_messages"] == 0
        assert diag["coverage_ok"] is True

    def test_diagnostics_error_on_bad_path(self, tmp_path):
        diag = mod._snapshot_diagnostics(tmp_path / "nonexistent.db")
        assert "error" in diag


# ── TestTriageBucketReadableCount ─────────────────────────────────────────────

class TestTriageBucketReadableCount:

    def test_readable_count_param_does_not_break_existing(self):
        """readable_message_count=0 default must not change bucket logic."""
        assist = _make_assist(conf=0.25)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.6, 10, "2026-01-01", "", assist, readable_message_count=0
        )
        assert bucket == "low_priority"

    def test_readable_count_stored_in_triage_debug(self, tmp_path):
        """readable_message_count must appear in triage_debug JSON after apply."""
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        fake_texts = ["Control4 proposal ready", "sonos installed"]
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=fake_texts), \
             patch.object(rct_mod, "analyze_thread_assist",
                          return_value=_make_assist(conf=0.25)):
            mod.run_triage(conn, dry_run=False)
        row = conn.execute("SELECT triage_debug FROM threads WHERE thread_id='t1'").fetchone()
        conn.close()
        assert row and row[0], "triage_debug not stored"
        dbg = json.loads(row[0])
        assert dbg["readable_message_count"] == len(fake_texts)

    def test_named_contact_high_message_count_moderate_conf_is_high_value(self):
        """Named contact + >10 msgs + assist_conf>=0.50 → high_value."""
        assist = _make_assist(conf=0.55)
        bucket, reason, _ = mod._determine_triage_bucket(
            "work", 0.7, 15, "2026-04-01", "Bob Builder", assist
        )
        assert bucket == "high_value"
        assert "15 messages" in reason


# ── TestImprovedHighValueScoring ──────────────────────────────────────────────

class TestImprovedHighValueScoring:

    def test_named_11_messages_conf_50_is_high_value(self):
        assist = _make_assist(conf=0.50)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.7, 11, "2026-04-01", "Alice Client", assist
        )
        assert bucket == "high_value"

    def test_named_10_messages_conf_50_not_high_value(self):
        """Boundary: exactly 10 messages does NOT trigger the >10 rule."""
        assist = _make_assist(conf=0.50)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.5, 10, "2026-04-01", "Alice Client", assist
        )
        assert bucket != "high_value"

    def test_unnamed_11_messages_conf_50_not_high_value(self):
        """The >10 rule only applies when name is present."""
        assist = _make_assist(conf=0.50)
        bucket, _, _ = mod._determine_triage_bucket(
            "work", 0.6, 15, "2026-04-01", "", assist
        )
        assert bucket != "high_value"

    def test_symphony_signal_boost_increases_tech_score(self):
        """'symphony' in message texts should boost tech score via intro-phrase logic."""
        import scripts.review_client_threads as rct
        scores = rct._score_domain_signals(
            ["symphony smart homes proposal ready for the Beaver Creek project"], []
        )
        assert scores["tech"] >= 3, f"expected tech>=3, got {scores}"

    def test_proposal_term_in_tech_terms(self):
        """'proposal' in _TECH_TERMS contributes to tech score."""
        import scripts.review_client_threads as rct
        scores = rct._score_domain_signals(["the proposal looks great"], [])
        assert scores["tech"] >= 1

    def test_walkthrough_term_in_tech_terms(self):
        """'walkthrough' in _TECH_TERMS contributes to tech score."""
        import scripts.review_client_threads as rct
        scores = rct._score_domain_signals(["let's schedule a walkthrough next week"], [])
        assert scores["tech"] >= 1


# ── TestTriageDebugStored ─────────────────────────────────────────────────────

class TestTriageDebugStored:

    def test_triage_debug_column_exists_after_apply(self, tmp_path):
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=False)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        conn.close()
        assert "triage_debug" in cols

    def test_triage_debug_is_valid_json(self, tmp_path):
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=False)
        row = conn.execute("SELECT triage_debug FROM threads WHERE thread_id='t1'").fetchone()
        conn.close()
        assert row and row[0]
        dbg = json.loads(row[0])
        assert "contact_name_found" in dbg
        assert "readable_message_count" in dbg
        assert "inferred_domain" in dbg

    def test_triage_debug_dry_run_not_written_to_db(self, tmp_path):
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True)
        # triage_debug column may not exist in dry-run; if it does exist value is NULL
        has_col = any(r[1] == "triage_debug" for r in conn.execute("PRAGMA table_info(threads)").fetchall())
        conn.close()
        if has_col:
            check = sqlite3.connect(str(db))
            val = check.execute("SELECT triage_debug FROM threads WHERE thread_id='t1'").fetchone()[0]
            check.close()
            assert val is None


# ── TestGetThreadExplain ──────────────────────────────────────────────────────

class TestGetThreadExplain:

    def _prepare(self, tmp_path, name="John Smith"):
        db = _create_thread_db(tmp_path, [{
            "thread_id": "t1", "contact_handle": "+15550000001",
            "message_count": 20, "work_confidence": 0.85,
        }])
        conn = _open_rw(db)
        with patch.object(rct_mod, "_lookup_contact_name", return_value=name), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=["control4 installed"]), \
             patch.object(rct_mod, "analyze_thread_assist",
                          return_value=_make_assist(conf=0.75, evidence=["tech signals: control4"])):
            mod.run_triage(conn, dry_run=False)
        return db, conn

    def test_explain_returns_required_keys(self, tmp_path):
        _, conn = self._prepare(tmp_path)
        info = mod.get_thread_explain(conn, "t1")
        conn.close()
        for key in ("thread_id", "triage_bucket", "triage_reason", "triage_confidence",
                    "suggested_relationship", "inferred_domain", "risk_flags", "debug"):
            assert key in info, f"missing key: {key}"

    def test_explain_unknown_thread_returns_error(self, tmp_path):
        db = _create_thread_db(tmp_path, [])
        conn = _open_rw(db)
        mod._ensure_triage_columns(conn)
        info = mod.get_thread_explain(conn, "nonexistent_id")
        conn.close()
        assert "error" in info

    def test_explain_debug_contains_scores(self, tmp_path):
        _, conn = self._prepare(tmp_path)
        info = mod.get_thread_explain(conn, "t1")
        conn.close()
        assert "debug" in info
        dbg = info["debug"]
        assert "readable_message_count" in dbg
        assert "contact_name_found" in dbg

    def test_explain_phone_masked(self, tmp_path):
        _, conn = self._prepare(tmp_path, name="")
        info = mod.get_thread_explain(conn, "t1")
        conn.close()
        assert "+15550000001" not in info.get("contact_display", "")
        assert "***" in info.get("contact_masked", "")


# ── TestTriageStatsJson ───────────────────────────────────────────────────────

class TestTriageStatsJson:

    def test_stats_json_written_after_run(self, tmp_path):
        stats_path = tmp_path / "triage_stats.json"
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        with patch.object(mod, "_TRIAGE_STATS_PATH", stats_path), \
             patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True)
        conn.close()
        assert stats_path.is_file(), "triage_stats.json not written"
        data = json.loads(stats_path.read_text())
        assert "last_run" in data
        assert "processed" in data
        assert "counts" in data

    def test_stats_json_includes_snapshot_info(self, tmp_path):
        stats_path = tmp_path / "triage_stats.json"
        snap = _create_snapshot_chat_db(
            tmp_path / "snap" / "chat.db", "iMessage;-;+1", ["hello"]
        )
        diag = mod._snapshot_diagnostics(snap)
        db = _create_thread_db(tmp_path, [{"thread_id": "t1", "contact_handle": "+15550000001"}])
        conn = _open_rw(db)
        with patch.object(mod, "_TRIAGE_STATS_PATH", stats_path), \
             patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True, chat_db_path=snap, snapshot_diagnostics=diag)
        conn.close()
        data = json.loads(stats_path.read_text())
        assert data.get("snapshot_used") is not None
        assert "snapshot_message_count" in data

    def test_stats_json_dry_run_flag_recorded(self, tmp_path):
        stats_path = tmp_path / "triage_stats.json"
        db = _create_thread_db(tmp_path, [])
        conn = _open_rw(db)
        with patch.object(mod, "_TRIAGE_STATS_PATH", stats_path), \
             patch.object(rct_mod, "_lookup_contact_name", return_value=""), \
             patch.object(rct_mod, "_fetch_sample_texts", return_value=[]), \
             patch.object(rct_mod, "analyze_thread_assist", return_value=_make_assist()):
            mod.run_triage(conn, dry_run=True)
        conn.close()
        data = json.loads(stats_path.read_text())
        assert data["dry_run"] is True
