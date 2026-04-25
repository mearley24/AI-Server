"""
Tests for client intelligence backfill v2.

Covers: batch limit, checkpoint/resume, personal-thread isolation,
work/mixed fact extraction, and backfill status helper.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.client_intel_backfill as mod


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_threads(n: int) -> list[dict]:
    return [
        {
            "chat_guid": f"iMessage;-;+1555{i:07d}",
            "contact_handle": f"+1555{i:07d}",
            "message_count": 10 + i,
            "date_first": "2026-01-01T00:00:00+00:00",
            "date_last": "2026-04-01T00:00:00+00:00",
        }
        for i in range(n)
    ]


_WORK_TEXTS = ["Control4 proposal for the Beaver Creek project", "Invoice for Sonos audio system"]
_PERSONAL_TEXTS = ["Hey are you coming to dinner tonight?", "Happy birthday, hope you have a great day!"]


class _BackfillPatcher:
    """Patches chat.db I/O and redirects DB paths to tmp_path for isolation."""

    def __init__(self, tmp_path: Path, threads: list[dict], texts_fn=None):
        self.tmp_path = tmp_path
        self.threads = threads
        self.texts_fn = texts_fn or (lambda guid: _WORK_TEXTS)
        self._originals: dict[str, Any] = {}

    def __enter__(self):
        p = self.tmp_path
        fake_conn = MagicMock()

        self._originals = {
            "DATA_DIR": mod.DATA_DIR,
            "THREAD_INDEX_DB": mod.THREAD_INDEX_DB,
            "PROFILES_DB": mod.PROFILES_DB,
            "PROPOSED_FACTS_DB": mod.PROPOSED_FACTS_DB,
            "BACKFILL_LOG": mod.BACKFILL_LOG,
            "fetch_threads": mod.fetch_threads,
            "fetch_sample_texts": mod.fetch_sample_texts,
            "_open_chat_db": mod._open_chat_db,
            "_close_chat_db": mod._close_chat_db,
        }

        mod.DATA_DIR = p
        mod.THREAD_INDEX_DB = p / "message_thread_index.sqlite"
        mod.PROFILES_DB = p / "client_profiles.sqlite"
        mod.PROPOSED_FACTS_DB = p / "proposed_facts.sqlite"
        mod.BACKFILL_LOG = p / "backfill_runs.ndjson"

        captured_threads = self.threads
        captured_texts = self.texts_fn

        mod.fetch_threads = lambda conn, limit: captured_threads[:limit]
        mod.fetch_sample_texts = lambda conn, guid, sample_size=30: captured_texts(guid)
        mod._open_chat_db = lambda: (fake_conn, "")
        mod._close_chat_db = lambda conn, tmp: None
        return self

    def __exit__(self, *args):
        for k, v in self._originals.items():
            setattr(mod, k, v)


# ── Batch limit tests ─────────────────────────────────────────────────────────

class TestBatchLimit:

    def test_limit_respected_dry_run(self, tmp_path):
        threads = _fake_threads(20)
        with _BackfillPatcher(tmp_path, threads):
            result = mod.run_backfill(limit=5, dry_run=True, output_summary=False)
        assert len(result["threads"]) == 5

    def test_limit_respected_apply(self, tmp_path):
        threads = _fake_threads(20)
        with _BackfillPatcher(tmp_path, threads):
            result = mod.run_backfill(limit=8, dry_run=False, output_summary=False)
        assert len(result["threads"]) == 8

    def test_limit_zero_processes_nothing(self, tmp_path):
        threads = _fake_threads(10)
        with _BackfillPatcher(tmp_path, threads):
            result = mod.run_backfill(limit=0, dry_run=True, output_summary=False)
        assert len(result["threads"]) == 0

    def test_limit_larger_than_available(self, tmp_path):
        threads = _fake_threads(3)
        with _BackfillPatcher(tmp_path, threads):
            result = mod.run_backfill(limit=100, dry_run=False, output_summary=False)
        assert len(result["threads"]) == 3


# ── Checkpoint / resume tests ─────────────────────────────────────────────────

class TestCheckpoint:

    def test_apply_resume_skips_applied_threads(self, tmp_path):
        threads = _fake_threads(5)
        with _BackfillPatcher(tmp_path, threads):
            r1 = mod.run_backfill(limit=5, dry_run=False, output_summary=False)
            r2 = mod.run_backfill(limit=5, dry_run=False, output_summary=False)
        assert r1["run"]["processed"] == 5
        assert r2["run"]["processed"] == 0
        assert r2["run"]["skipped"] == 5

    def test_dry_run_resume_skips_indexed_threads(self, tmp_path):
        threads = _fake_threads(5)
        with _BackfillPatcher(tmp_path, threads):
            r1 = mod.run_backfill(limit=5, dry_run=True, output_summary=False)
            r2 = mod.run_backfill(limit=5, dry_run=True, output_summary=False)
        assert r1["run"]["processed"] == 5
        assert r2["run"]["processed"] == 0
        assert r2["run"]["skipped"] == 5

    def test_partial_resume_processes_new_threads(self, tmp_path):
        threads = _fake_threads(5)
        with _BackfillPatcher(tmp_path, threads):
            r1 = mod.run_backfill(limit=3, dry_run=False, output_summary=False)
            r2 = mod.run_backfill(limit=5, dry_run=False, output_summary=False)
        assert r1["run"]["processed"] == 3
        assert r2["run"]["processed"] == 2
        assert r2["run"]["skipped"] == 3

    def test_dry_run_then_apply_reprocesses_proposals(self, tmp_path):
        """Apply mode should upgrade dry-run proposals (is_reviewed=-1 → 0)."""
        threads = _fake_threads(5)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _WORK_TEXTS):
            r1 = mod.run_backfill(limit=5, dry_run=True, output_summary=False)
            # Apply should NOT skip the dry-run-only entries
            r2 = mod.run_backfill(limit=5, dry_run=False, output_summary=False)
        assert r1["run"]["processed"] == 5
        assert r2["run"]["processed"] == 5
        assert r2["run"]["skipped"] == 0


# ── Personal thread isolation tests ──────────────────────────────────────────

class TestPersonalThreads:

    def test_personal_threads_indexed(self, tmp_path):
        threads = _fake_threads(3)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _PERSONAL_TEXTS):
            mod.run_backfill(limit=3, dry_run=False, output_summary=False)
        conn = sqlite3.connect(str(tmp_path / "message_thread_index.sqlite"))
        count = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE category='personal'"
        ).fetchone()[0]
        conn.close()
        assert count == 3

    def test_personal_threads_no_proposed_facts(self, tmp_path):
        threads = _fake_threads(3)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _PERSONAL_TEXTS):
            result = mod.run_backfill(limit=3, dry_run=False, output_summary=False)
        assert result["run"]["facts_proposed"] == 0
        assert result["run"]["review_candidates"] == 0
        facts_db = tmp_path / "proposed_facts.sqlite"
        if facts_db.is_file():
            conn = sqlite3.connect(str(facts_db))
            count = conn.execute("SELECT COUNT(*) FROM proposed_facts").fetchone()[0]
            conn.close()
            assert count == 0


# ── Work/mixed review candidate tests ────────────────────────────────────────

class TestWorkMixedCandidates:

    def test_work_threads_create_review_candidates(self, tmp_path):
        threads = _fake_threads(3)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _WORK_TEXTS):
            result = mod.run_backfill(limit=3, dry_run=False, output_summary=False)
        assert result["run"]["review_candidates"] == 3
        assert result["run"]["facts_proposed"] > 0
        conn = sqlite3.connect(str(tmp_path / "proposed_facts.sqlite"))
        count = conn.execute("SELECT COUNT(*) FROM proposed_facts").fetchone()[0]
        conn.close()
        assert count > 0

    def test_dry_run_no_facts_written(self, tmp_path):
        """Dry-run must not write to proposed_facts even for work threads."""
        threads = _fake_threads(3)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _WORK_TEXTS):
            result = mod.run_backfill(limit=3, dry_run=True, output_summary=False)
        assert result["run"]["facts_proposed"] == 0
        facts_db = tmp_path / "proposed_facts.sqlite"
        if facts_db.is_file():
            conn = sqlite3.connect(str(facts_db))
            count = conn.execute("SELECT COUNT(*) FROM proposed_facts").fetchone()[0]
            conn.close()
            assert count == 0

    def test_work_facts_include_relationship_type(self, tmp_path):
        threads = _fake_threads(2)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _WORK_TEXTS):
            mod.run_backfill(limit=2, dry_run=False, output_summary=False)
        conn = sqlite3.connect(str(tmp_path / "proposed_facts.sqlite"))
        types = {r[0] for r in conn.execute("SELECT DISTINCT fact_type FROM proposed_facts").fetchall()}
        conn.close()
        assert "relationship_type" in types

    def test_work_facts_are_pending_not_accepted(self, tmp_path):
        """All extracted facts must start as pending (is_accepted=0, is_rejected=0)."""
        threads = _fake_threads(2)
        with _BackfillPatcher(tmp_path, threads, texts_fn=lambda g: _WORK_TEXTS):
            mod.run_backfill(limit=2, dry_run=False, output_summary=False)
        conn = sqlite3.connect(str(tmp_path / "proposed_facts.sqlite"))
        auto_accepted = conn.execute(
            "SELECT COUNT(*) FROM proposed_facts WHERE is_accepted=1"
        ).fetchone()[0]
        conn.close()
        assert auto_accepted == 0


# ── Status helper tests ───────────────────────────────────────────────────────

class TestBackfillStatus:

    def test_status_required_keys(self, tmp_path):
        with _BackfillPatcher(tmp_path, _fake_threads(3)):
            mod.init_schemas()
            status = mod.get_backfill_status()
        required = {
            "total_indexed", "work", "mixed", "personal", "unknown",
            "reviewed", "approved_profiles", "proposed_facts", "last_run",
        }
        assert required.issubset(set(status.keys()))

    def test_status_counts_threads_correctly(self, tmp_path):
        threads = _fake_threads(5)

        def texts_fn(guid: str) -> list[str]:
            i = int(guid.split("+1555")[1])
            return _WORK_TEXTS if i < 3 else _PERSONAL_TEXTS

        with _BackfillPatcher(tmp_path, threads, texts_fn=texts_fn):
            mod.run_backfill(limit=5, dry_run=False, output_summary=False)
            status = mod.get_backfill_status()

        assert status["total_indexed"] == 5
        assert status["work"] == 3
        assert status["personal"] == 2

    def test_status_last_run_populated(self, tmp_path):
        threads = _fake_threads(2)
        with _BackfillPatcher(tmp_path, threads):
            mod.run_backfill(limit=2, dry_run=True, output_summary=False)
            status = mod.get_backfill_status()
        assert status["last_run"] is not None

    def test_status_empty_db_returns_zeros(self, tmp_path):
        with _BackfillPatcher(tmp_path, []):
            mod.init_schemas()
            status = mod.get_backfill_status()
        assert status["total_indexed"] == 0
        assert status["proposed_facts"] == 0
        assert status["last_run"] is None
