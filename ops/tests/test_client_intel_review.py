"""Tests for client thread review and approval system."""
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

from scripts.client_intel_backfill import init_schemas


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_test_db(tmp_path: Path) -> Path:
    """Create a populated thread index DB for testing."""
    import scripts.client_intel_backfill as mod
    orig_vars = {k: getattr(mod, k) for k in ("DATA_DIR", "THREAD_INDEX_DB", "PROFILES_DB", "PROPOSED_FACTS_DB", "BACKFILL_LOG")}
    mod.DATA_DIR = tmp_path
    mod.THREAD_INDEX_DB = tmp_path / "message_thread_index.sqlite"
    mod.PROFILES_DB = tmp_path / "client_profiles.sqlite"
    mod.PROPOSED_FACTS_DB = tmp_path / "proposed_facts.sqlite"
    mod.BACKFILL_LOG = tmp_path / "backfill_runs.ndjson"
    try:
        init_schemas()
    finally:
        for k, v in orig_vars.items():
            setattr(mod, k, v)

    db = tmp_path / "message_thread_index.sqlite"
    conn = sqlite3.connect(str(db))
    now = "2026-04-24T00:00:00+00:00"
    threads = [
        # thread_id, chat_guid, contact_handle, message_count, sample_count,
        # date_first, date_last, category, work_confidence, reason_codes,
        # is_reviewed, relationship_type, created_at
        ("aaa111", "chat_guid_1", "+18609171850", 100, 10, "2024-01-01", "2026-04-01",
         "work", 0.90, '["strong:control4"]', -1, "unknown", now),
        ("bbb222", "chat_guid_2", "+16077426880", 50, 8, "2023-06-01", "2026-03-15",
         "work", 0.75, '["strong:sonos"]', -1, "unknown", now),
        ("ccc333", "chat_guid_3", "+15551234567", 20, 5, "2022-01-01", "2025-12-31",
         "mixed", 0.35, '["weak:schedule"]', -1, "unknown", now),
        ("ddd444", "chat_guid_4", "+14445678901", 200, 20, "2020-01-01", "2026-04-20",
         "personal", 0.05, "[]", -1, "unknown", now),
        ("eee555", "chat_guid_5", "+13331234567", 80, 15, "2023-01-01", "2026-04-22",
         "work", 0.80, '["strong:lutron"]', 1, "unknown", now),    # already approved
        ("fff666", "chat_guid_6", "+12221234567", 30, 6, "2023-01-01", "2026-04-10",
         "work", 0.70, '["strong:keypad"]', 0, "unknown", now),    # already rejected
    ]
    conn.executemany(
        "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", threads
    )
    conn.commit()
    conn.close()
    return db


# ── Review DB helper ───────────────────────────────────────────────────────────

class _ReviewDB:
    """Thin wrapper exposing the same approve/reject logic as the API."""

    def __init__(self, db_path: Path) -> None:
        self.db = db_path

    def get(self, thread_id: str) -> dict | None:
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_reviewed(self, thread_id: str, status: int) -> bool:
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE threads SET is_reviewed=? WHERE thread_id=?", (status, thread_id))
        conn.commit()
        conn.close()
        return True

    def count_by_review(self, is_reviewed: int) -> int:
        conn = sqlite3.connect(str(self.db))
        n = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=?", (is_reviewed,)
        ).fetchone()[0]
        conn.close()
        return n

    def pending_work(self) -> list[dict]:
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM threads WHERE category='work' AND is_reviewed=-1 "
            "ORDER BY work_confidence DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestApproval:

    def test_approve_sets_is_reviewed_1(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        assert rdb.get("aaa111")["is_reviewed"] == -1
        rdb.set_reviewed("aaa111", 1)
        assert rdb.get("aaa111")["is_reviewed"] == 1

    def test_reject_sets_is_reviewed_0(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        assert rdb.get("bbb222")["is_reviewed"] == -1
        rdb.set_reviewed("bbb222", 0)
        assert rdb.get("bbb222")["is_reviewed"] == 0

    def test_approve_does_not_affect_other_threads(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        rdb.set_reviewed("aaa111", 1)
        # Other threads unchanged
        assert rdb.get("bbb222")["is_reviewed"] == -1
        assert rdb.get("ccc333")["is_reviewed"] == -1

    def test_can_change_approval_back(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        rdb.set_reviewed("aaa111", 1)
        assert rdb.get("aaa111")["is_reviewed"] == 1
        rdb.set_reviewed("aaa111", 0)
        assert rdb.get("aaa111")["is_reviewed"] == 0

    def test_already_approved_thread_stays(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        # eee555 was pre-approved
        assert rdb.get("eee555")["is_reviewed"] == 1

    def test_already_rejected_thread_stays(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        # fff666 was pre-rejected
        assert rdb.get("fff666")["is_reviewed"] == 0


class TestFiltering:

    def test_pending_work_returns_only_unreviewed_work(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        pending = rdb.pending_work()
        assert len(pending) == 2  # aaa111 + bbb222 (eee555 approved, fff666 rejected)
        for t in pending:
            assert t["category"] == "work"
            assert t["is_reviewed"] == -1

    def test_pending_count_decreases_after_approval(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        before = len(rdb.pending_work())
        rdb.set_reviewed("aaa111", 1)
        after = len(rdb.pending_work())
        assert after == before - 1

    def test_filter_reviewed_false(self, tmp_path):
        """reviewed=false (is_reviewed=-1) should return only pending threads."""
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM threads WHERE is_reviewed=-1"
        ).fetchall()
        conn.close()
        assert all(r["is_reviewed"] == -1 for r in rows)
        thread_ids = {r["thread_id"] for r in rows}
        assert "aaa111" in thread_ids
        assert "bbb222" in thread_ids
        assert "eee555" not in thread_ids  # approved
        assert "fff666" not in thread_ids  # rejected

    def test_filter_reviewed_true(self, tmp_path):
        """is_reviewed=1 should return only approved threads."""
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        rdb.set_reviewed("aaa111", 1)
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT thread_id FROM threads WHERE is_reviewed=1").fetchall()
        conn.close()
        ids = {r[0] for r in rows}
        assert "aaa111" in ids
        assert "eee555" in ids  # pre-approved
        assert "bbb222" not in ids

    def test_filter_rejected(self, tmp_path):
        """is_reviewed=0 should return only rejected threads."""
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        rdb.set_reviewed("bbb222", 0)
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT thread_id FROM threads WHERE is_reviewed=0").fetchall()
        conn.close()
        ids = {r[0] for r in rows}
        assert "bbb222" in ids
        assert "fff666" in ids  # pre-rejected
        assert "aaa111" not in ids

    def test_approved_count_increases(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        before = rdb.count_by_review(1)  # eee555 is pre-approved
        rdb.set_reviewed("aaa111", 1)
        after = rdb.count_by_review(1)
        assert after == before + 1

    def test_personal_threads_not_in_work_pending(self, tmp_path):
        db = _make_test_db(tmp_path)
        rdb = _ReviewDB(db)
        pending = rdb.pending_work()
        handles = {r["contact_handle"] for r in pending}
        # ddd444 is personal — must not appear
        assert "+14445678901" not in handles


class TestSummary:

    def test_summary_counts_correct(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        pending_work = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE category='work' AND is_reviewed=-1"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=1"
        ).fetchone()[0]
        conn.close()
        assert pending_work == 2   # aaa111 + bbb222
        assert approved == 1       # eee555

    def test_masked_contact_format(self, tmp_path):
        from scripts.review_client_threads import _mask
        assert _mask("+18609171850") == "+18***50"
        assert _mask("short") == "***"
        assert _mask("ab") == "***"
        assert _mask("+16077426880") == "+16***80"


# ══════════════════════════════════════════════════════════════════════════════
#  Relationship type tests
# ══════════════════════════════════════════════════════════════════════════════

from scripts.review_client_threads import (
    set_relationship,
    RELATIONSHIP_CHOICES,
    VALID_RELATIONSHIP_TYPES,
)
# VALID_RELATIONSHIP_TYPES may live in backfill or review script; define locally if needed
_VALID = {"client","vendor","builder","trade_partner","internal_team","personal_work_related","unknown"}


class TestRelationshipType:

    def test_relationship_type_defaults_to_unknown(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        rt = conn.execute("SELECT relationship_type FROM threads WHERE thread_id='aaa111'").fetchone()
        conn.close()
        # Either the column exists and defaults to unknown, or it doesn't exist yet (pre-migration)
        if rt is not None:
            assert rt[0] in ("unknown", None)

    def test_set_relationship_persists(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        # eee555 is pre-approved
        set_relationship(conn, "eee555", "client")
        rt = conn.execute("SELECT relationship_type FROM threads WHERE thread_id='eee555'").fetchone()
        conn.close()
        assert rt["relationship_type"] == "client"

    def test_all_relationship_types_storable(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        types = ["client","vendor","builder","trade_partner","internal_team","personal_work_related","unknown"]
        for rt in types:
            set_relationship(conn, "eee555", rt)
            val = conn.execute("SELECT relationship_type FROM threads WHERE thread_id='eee555'").fetchone()
            assert val["relationship_type"] == rt, f"Expected {rt}, got {val['relationship_type']}"
        conn.close()

    def test_relationship_does_not_change_approval(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        set_relationship(conn, "eee555", "vendor")
        row = conn.execute("SELECT is_reviewed, relationship_type FROM threads WHERE thread_id='eee555'").fetchone()
        conn.close()
        assert row["is_reviewed"] == 1       # still approved
        assert row["relationship_type"] == "vendor"

    def test_relationship_choices_map_correctly(self):
        assert RELATIONSHIP_CHOICES["c"] == "client"
        assert RELATIONSHIP_CHOICES["v"] == "vendor"
        assert RELATIONSHIP_CHOICES["b"] == "builder"
        assert RELATIONSHIP_CHOICES["t"] == "trade_partner"
        assert RELATIONSHIP_CHOICES["i"] == "internal_team"
        assert RELATIONSHIP_CHOICES["p"] == "personal_work_related"
        assert RELATIONSHIP_CHOICES["u"] == "unknown"

    def test_all_choices_are_valid_types(self):
        for key, val in RELATIONSHIP_CHOICES.items():
            assert val in _VALID, f"{val!r} not in valid types"

    def test_set_relationship_different_threads_independent(self, tmp_path):
        db = _make_test_db(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        # Need two approved threads — approve bbb222
        conn.execute("UPDATE threads SET is_reviewed=1 WHERE thread_id='bbb222'")
        conn.commit()
        set_relationship(conn, "eee555", "client")
        set_relationship(conn, "bbb222", "vendor")
        rows = {r["thread_id"]: r["relationship_type"]
                for r in conn.execute("SELECT thread_id, relationship_type FROM threads WHERE thread_id IN ('eee555','bbb222')").fetchall()}
        conn.close()
        assert rows["eee555"] == "client"
        assert rows["bbb222"] == "vendor"
