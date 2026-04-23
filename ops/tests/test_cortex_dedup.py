"""
Unit + integration tests for Cortex cross-source dedup (dedupe_key + store_or_update).
All tests use tmp_path or tempfile DBs — never cortex.config.DB_PATH.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Patch DB_PATH before importing MemoryStore so it doesn't try to open /data/cortex/brain.db
import cortex.config as _cfg  # noqa: E402


def _make_store(db_path: Path) -> "MemoryStore":
    """Create a MemoryStore backed by a temp DB."""
    import os
    old = os.environ.get("CORTEX_DATA_DIR")
    os.environ["CORTEX_DATA_DIR"] = str(db_path.parent)
    _cfg.DATA_DIR = db_path.parent
    _cfg.DB_PATH = db_path

    from cortex.memory import MemoryStore
    store = MemoryStore.__new__(MemoryStore)
    store.conn = sqlite3.connect(str(db_path), check_same_thread=False)
    store.conn.row_factory = sqlite3.Row
    store._init_schema()

    if old is not None:
        os.environ["CORTEX_DATA_DIR"] = old
    return store


# ── _canonical_key ────────────────────────────────────────────────────────────

def test_canonical_key_uses_hint_first():
    from cortex.memory import MemoryStore
    key = MemoryStore._canonical_key("x_intel", "https://example.com", "", "my-hint")
    expected = hashlib.sha256(b"hint:my-hint").hexdigest()
    assert key == expected


def test_canonical_key_canonicalizes_url_host_and_strips_utm():
    from cortex.memory import MemoryStore
    url_with_utm = "https://Twitter.com/user/status/123?utm_source=share&utm_medium=web"
    key = MemoryStore._canonical_key("x_intel", url_with_utm, "", "")
    canonical_url = "https://twitter.com/user/status/123"
    expected = hashlib.sha256(f"url:{canonical_url}".encode()).hexdigest()
    assert key == expected


def test_canonical_key_strips_trailing_slash():
    from cortex.memory import MemoryStore
    k1 = MemoryStore._canonical_key("x_intel", "https://example.com/page/", "", "")
    k2 = MemoryStore._canonical_key("x_intel", "https://example.com/page", "", "")
    assert k1 == k2


def test_canonical_key_msg_prefix():
    from cortex.memory import MemoryStore
    key = MemoryStore._canonical_key("email", "imessage:+19705193013:thread42", "inbox", "")
    expected = hashlib.sha256(b"email:imessage:+19705193013:thread42:inbox").hexdigest()
    assert key == expected


def test_canonical_key_returns_none_when_source_unrecognized():
    from cortex.memory import MemoryStore
    key = MemoryStore._canonical_key("meta_learning", "AGENT_LEARNINGS.md", "", "")
    assert key is None


def test_canonical_key_hint_wins_over_url():
    from cortex.memory import MemoryStore
    url = "https://example.com/page"
    key_url = MemoryStore._canonical_key("x_intel", url, "", "")
    key_hint = MemoryStore._canonical_key("x_intel", url, "", "explicit-hint")
    assert key_url != key_hint
    assert key_hint == hashlib.sha256(b"hint:explicit-hint").hexdigest()


# ── store_or_update ───────────────────────────────────────────────────────────

def test_store_or_update_inserts_on_new_key(tmp_path: Path):
    store = _make_store(tmp_path / "brain.db")
    mem_id = store.store_or_update(
        category="x_intel", title="Test", content="body",
        source="https://example.com/post/1",
    )
    rows = store.conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] is not None


def test_store_or_update_merges_on_collision(tmp_path: Path):
    store = _make_store(tmp_path / "brain.db")
    url = "https://example.com/post/42"
    id1 = store.store_or_update(
        category="x_intel", title="First", content="short",
        source=url, importance=5,
        tags=["a"], metadata={"k1": "v1"},
    )
    id2 = store.store_or_update(
        category="x_intel", title="Second", content="also short",
        source=url, importance=8,
        tags=["b"], metadata={"k2": "v2"},
    )
    assert id1 == id2  # same row
    row = store.conn.execute("SELECT * FROM memories WHERE id = ?", (id1,)).fetchone()
    assert row["access_count"] == 1       # bumped on second store
    assert row["importance"] == 8         # max(5, 8)
    tags = json.loads(row["tags"])
    assert "a" in tags and "b" in tags    # union
    meta = json.loads(row["metadata"])
    assert meta["k1"] == "v1" and meta["k2"] == "v2"  # shallow merge


def test_store_or_update_preserves_content_unless_overwrite(tmp_path: Path):
    store = _make_store(tmp_path / "brain.db")
    url = "https://example.com/post/99"
    id1 = store.store_or_update(
        category="x_intel", title="T", content="original longer content here",
        source=url,
    )
    # Without overwrite_content — short new content should NOT replace longer original
    store.store_or_update(
        category="x_intel", title="T", content="short",
        source=url, overwrite_content=False,
    )
    row = store.conn.execute("SELECT content FROM memories WHERE id = ?", (id1,)).fetchone()
    assert row["content"] == "original longer content here"

    # With overwrite_content=True and longer content — should replace
    store.store_or_update(
        category="x_intel", title="T",
        content="much longer replacement content that beats the original",
        source=url, overwrite_content=True,
    )
    row = store.conn.execute("SELECT content FROM memories WHERE id = ?", (id1,)).fetchone()
    assert "much longer" in row["content"]


def test_partial_unique_index_allows_multiple_null_keys(tmp_path: Path):
    store = _make_store(tmp_path / "brain.db")
    # Two rows from unrecognized sources → both have dedupe_key=NULL → no UNIQUE collision
    id1 = store.store_or_update(
        category="meta_learning", title="A", content="x", source="file1.txt",
    )
    id2 = store.store_or_update(
        category="meta_learning", title="B", content="y", source="file2.txt",
    )
    assert id1 != id2  # separate rows, both with NULL key
    count = store.conn.execute(
        "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NULL"
    ).fetchone()[0]
    assert count >= 2


# ── backfill script ───────────────────────────────────────────────────────────

def _seed_duplicate_db(db_path: Path) -> None:
    """Seed 5 rows: 2 pairs share a derived URL key, 1 row has unrecognized source."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
            category TEXT, subcategory TEXT DEFAULT '', title TEXT, content TEXT,
            source TEXT DEFAULT '', confidence REAL DEFAULT 0.5,
            importance INTEGER DEFAULT 5, ttl_days INTEGER,
            access_count INTEGER DEFAULT 0, last_accessed TEXT,
            tags TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}',
            dedupe_key TEXT DEFAULT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_dedupe_key
            ON memories(dedupe_key) WHERE dedupe_key IS NOT NULL;
    """)
    rows = [
        ("a1", "2026-01-01T00:00:00+00:00", "x_intel", "https://example.com/post/1", "First", 5),
        ("a2", "2026-01-02T00:00:00+00:00", "x_intel", "https://example.com/post/1", "Dup", 7),
        ("b1", "2026-01-01T00:00:00+00:00", "x_intel", "https://example.com/post/2", "Other", 5),
        ("b2", "2026-01-02T00:00:00+00:00", "x_intel", "https://example.com/post/2", "Dup2", 6),
        ("c1", "2026-01-01T00:00:00+00:00", "meta_learning", "notes.txt", "Solo", 4),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO memories (id, created_at, updated_at, category, source, title, importance)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r[0], r[1], r[1], r[2], r[3], r[4], r[5]),
        )
    conn.commit()
    conn.close()


def test_backfill_dry_run_writes_no_rows(tmp_path: Path):
    db = tmp_path / "brain.db"
    _seed_duplicate_db(db)

    from scripts.cortex_dedup_backfill import run
    result = run(db, dry_run=True)

    assert result["dry_run"] is True
    assert result["rows_deleted"] == 0
    assert result["groups"] == 2  # 2 duplicate pairs

    # DB unchanged
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 5


def test_backfill_apply_collapses_duplicates_and_keeps_oldest(tmp_path: Path):
    db = tmp_path / "brain.db"
    _seed_duplicate_db(db)

    from scripts.cortex_dedup_backfill import run
    result = run(db, dry_run=False)

    assert result["rows_deleted"] == 2     # one from each pair
    assert result["groups"] == 2

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM memories ORDER BY created_at").fetchall()
    conn.close()

    # 5 - 2 deleted = 3 rows remaining
    assert len(rows) == 3

    # Oldest id from each pair should survive
    ids = {r["id"] for r in rows}
    assert "a1" in ids
    assert "b1" in ids
    assert "c1" in ids  # solo row untouched

    # Merged importance on pair 1: max(5,7)=7
    a1 = next(r for r in rows if r["id"] == "a1")
    assert a1["importance"] == 7

    # dedupe_key set on surviving rows
    assert a1["dedupe_key"] is not None
