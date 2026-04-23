"""
Unit + integration tests for Cortex embeddings (NullProvider, no network).
All tests use tmp_path DBs.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.embeddings import NullProvider, OllamaProvider, pack_vector, unpack_vector, embed_worker
from cortex.memory import _content_digest, _cosine


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_store(db_path: Path):
    import cortex.config as _cfg
    _cfg.DATA_DIR = db_path.parent
    _cfg.DB_PATH = db_path
    from cortex.memory import MemoryStore
    store = MemoryStore.__new__(MemoryStore)
    store.conn = sqlite3.connect(str(db_path), check_same_thread=False)
    store.conn.row_factory = sqlite3.Row
    store._init_schema()
    return store


# ── pack/unpack ───────────────────────────────────────────────────────────────

def test_pack_unpack_roundtrip_preserves_floats():
    vec = [0.1, 0.5, -0.3, 1.0, 0.0]
    blob = pack_vector(vec)
    back = unpack_vector(blob)
    assert len(back) == len(vec)
    for a, b in zip(vec, back):
        assert abs(a - b) < 1e-5


def test_null_provider_is_deterministic():
    provider = NullProvider()

    async def run():
        v1 = await provider.embed("hello world")
        v2 = await provider.embed("hello world")
        v3 = await provider.embed("different text")
        return v1, v2, v3

    v1, v2, v3 = asyncio.run(run())
    assert v1 == v2
    assert v1 != v3
    # Unit vector
    norm = sum(f * f for f in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-4


# ── writer task ───────────────────────────────────────────────────────────────

def test_writer_is_noop_when_disabled(tmp_path: Path, monkeypatch):
    import cortex.config as cfg
    monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", False)
    store = _make_store(tmp_path / "brain.db")
    mem_id = store.remember(
        category="x_intel", title="T", content="hello disabled",
        source="test", importance=5,
    )
    # No row in memory_embeddings
    count = store.conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
    assert count == 0


def test_writer_writes_row_when_enabled_with_null_provider(tmp_path: Path, monkeypatch):
    import cortex.config as cfg
    monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", True)

    store = _make_store(tmp_path / "brain.db")

    async def run():
        import asyncio as _asyncio
        from cortex.memory import set_embed_queue
        q: _asyncio.Queue = _asyncio.Queue(maxsize=100)
        set_embed_queue(q)
        provider = NullProvider()

        mem_id = store.remember(
            category="x_intel", title="T", content="embed me",
            source="test", importance=5,
        )
        # Run worker just long enough to drain the one item
        task = _asyncio.create_task(embed_worker(q, store, provider))
        await q.join()
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass
        set_embed_queue(None)
        return mem_id

    mem_id = asyncio.run(run())
    row = store.conn.execute(
        "SELECT memory_id, model, dim FROM memory_embeddings WHERE memory_id=?", (mem_id,)
    ).fetchone()
    assert row is not None
    assert row[1] == "null-v1"
    assert row[2] == 64


def test_writer_skips_on_provider_timeout(tmp_path: Path, monkeypatch):
    import cortex.config as cfg
    monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", True)
    store = _make_store(tmp_path / "brain.db")

    class SlowProvider:
        model_name = "slow-v1"
        async def embed(self, text: str):
            await asyncio.sleep(100)
            return []

    async def run():
        import asyncio as _asyncio
        from cortex.memory import set_embed_queue
        q: _asyncio.Queue = _asyncio.Queue(maxsize=100)
        set_embed_queue(q)
        provider = SlowProvider()

        mem_id = store.remember(
            category="x_intel", title="T", content="slow embed",
            source="test", importance=5,
        )
        task = _asyncio.create_task(embed_worker(q, store, provider))
        # Give it a moment — the worker will timeout the provider
        await _asyncio.sleep(0.1)
        await q.join()
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass
        set_embed_queue(None)
        return mem_id

    mem_id = asyncio.run(run())
    # Should have no embedding row (timed out + logged, no raise)
    count = store.conn.execute(
        "SELECT COUNT(*) FROM memory_embeddings WHERE memory_id=?", (mem_id,)
    ).fetchone()[0]
    assert count == 0


# ── search_semantic ───────────────────────────────────────────────────────────

def test_search_semantic_returns_top_k_by_cosine(tmp_path: Path, monkeypatch):
    import cortex.config as cfg
    monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", False)

    store = _make_store(tmp_path / "brain.db")
    provider = NullProvider()

    async def run():
        import asyncio as _asyncio
        from cortex.memory import set_embed_queue
        q: _asyncio.Queue = _asyncio.Queue(100)
        set_embed_queue(q)
        monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", True)

        ids = []
        for i in range(5):
            mid = store.remember(
                category="x_intel", title=f"M{i}", content=f"memory content {i}",
                source="test", importance=5,
            )
            ids.append(mid)

        task = _asyncio.create_task(embed_worker(q, store, provider))
        await q.join()
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass
        set_embed_queue(None)
        monkeypatch.setattr(cfg, "CORTEX_EMBEDDINGS_ENABLED", False)

        # Monkey-patch get_provider to return NullProvider
        import cortex.embeddings as emb
        original = emb.get_provider
        emb.get_provider = lambda: provider
        results = await store.search_semantic("memory content 2", k=3)
        emb.get_provider = original
        return results

    results = asyncio.run(run())
    assert len(results) <= 3
    assert all("memory_id" in r and "score" in r for r in results)
    # Top result should be reasonably relevant (score > 0)
    assert results[0]["score"] > 0.0


# ── backfill script ───────────────────────────────────────────────────────────

def _seed_db(db_path: Path, n: int = 10) -> None:
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
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT PRIMARY KEY, embedding BLOB NOT NULL,
            dim INTEGER NOT NULL, model TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_memory_emb_model ON memory_embeddings(model);
    """)
    for i in range(n):
        conn.execute(
            "INSERT INTO memories (id,created_at,updated_at,category,title,content,importance)"
            " VALUES (?,datetime('now'),datetime('now'),'x_intel',?,?,5)",
            (f"m{i:02d}", f"Title {i}", f"Content for memory {i}"),
        )
    conn.commit()
    conn.close()


def test_backfill_dry_run_writes_no_rows(tmp_path: Path):
    db = tmp_path / "brain.db"
    _seed_db(db, n=10)

    from scripts.cortex_embed_backfill import _run
    result = asyncio.run(_run(db, dry_run=True, provider=NullProvider(), batch_size=100))

    assert result["dry_run"] is True
    assert result["written"] == 0
    assert result["missing"] == 10

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
    conn.close()
    assert count == 0


def test_backfill_apply_populates_missing_rows_only(tmp_path: Path):
    db = tmp_path / "brain.db"
    _seed_db(db, n=10)

    from scripts.cortex_embed_backfill import _run
    # First apply — writes all 10
    result1 = asyncio.run(_run(db, dry_run=False, provider=NullProvider(), batch_size=100))
    assert result1["written"] == 10
    assert result1["failed"] == 0

    # Second apply — nothing left to write
    result2 = asyncio.run(_run(db, dry_run=False, provider=NullProvider(), batch_size=100))
    assert result2["written"] == 0
    assert result2["already_done"] == 10
