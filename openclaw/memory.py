"""
OpenClaw Persistent Memory Plugin
SQLite-backed key-value memory with categories, fuzzy search, and agent context.

Replaces the in-memory cache that dies on restart. Memories survive across
container restarts and feed back into AGENT_LEARNINGS_LIVE.md.
"""

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.memory")

VALID_CATEGORIES = {
    "user_preference",
    "project_context",
    "trading_insight",
    "business_context",
    "agent_learning",
}

DEFAULT_DB_PATH = "/app/data/openclaw_memory.db"


class MemoryPlugin:
    """Persistent memory backed by SQLite."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("memory_plugin_init db=%s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'project_context',
                source_agent TEXT NOT NULL DEFAULT 'openclaw',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at)
        """)
        conn.commit()
        logger.info("memory_db_ready")

    def remember(self, key: str, value: str, category: str = "project_context", source_agent: str = "openclaw"):
        """Upsert a memory. Updates value and timestamp if key exists."""
        if category not in VALID_CATEGORIES:
            logger.warning("invalid_category category=%s using=project_context", category)
            category = "project_context"

        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO memories (key, value, category, source_agent, created_at, updated_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    source_agent = excluded.source_agent,
                    updated_at = excluded.updated_at
                """,
                (key, value, category, source_agent, now, now),
            )
            conn.commit()
            logger.info("memory_stored key=%s category=%s agent=%s", key, category, source_agent)
        except Exception as e:
            logger.error("memory_store_failed key=%s error=%s", key, e)

    def recall(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]:
        """Fuzzy search memories by key or value using LIKE matching."""
        conn = self._get_conn()
        pattern = f"%{query}%"
        try:
            if category:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE (key LIKE ? OR value LIKE ?) AND category = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE key LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()

            results = [dict(r) for r in rows]

            # Bump access count for returned rows
            ids = [r["id"] for r in results]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE memories SET access_count = access_count + 1 WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()

            return results
        except Exception as e:
            logger.error("memory_recall_failed query=%s error=%s", query, e)
            return []

    def recall_recent(self, hours: int = 24, category: Optional[str] = None) -> list[dict]:
        """Get memories from the last N hours."""
        conn = self._get_conn()
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        try:
            if category:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE updated_at > ? AND category = ?
                    ORDER BY updated_at DESC
                    """,
                    (cutoff, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE updated_at > ?
                    ORDER BY updated_at DESC
                    """,
                    (cutoff,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("memory_recall_recent_failed error=%s", e)
            return []

    def forget(self, key: str) -> bool:
        """Delete a memory by key. Returns True if deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("memory_forgotten key=%s", key)
            return deleted
        except Exception as e:
            logger.error("memory_forget_failed key=%s error=%s", key, e)
            return False

    def get_context_for_agent(self, agent_id: str) -> list[dict]:
        """Return memories relevant to an agent — by category + recency.

        Strategy: return recent memories from all categories, plus any
        memories sourced from this agent, sorted by recency.
        """
        conn = self._get_conn()
        cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        cutoff_7d = (datetime.utcnow() - timedelta(days=7)).isoformat()
        try:
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE updated_at > ?
                   OR (source_agent = ? AND updated_at > ?)
                ORDER BY updated_at DESC
                LIMIT 50
                """,
                (cutoff_24h, agent_id, cutoff_7d),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("memory_context_failed agent=%s error=%s", agent_id, e)
            return []

    def export_to_markdown(self) -> str:
        """Dump all memories as markdown for AGENT_LEARNINGS integration."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY category, updated_at DESC"
            ).fetchall()
        except Exception as e:
            logger.error("memory_export_failed error=%s", e)
            return "# OpenClaw Memory Export\n\n*Export failed.*\n"

        lines = [
            "# OpenClaw Memory Export",
            f"*Generated {datetime.utcnow().isoformat()}Z — {len(rows)} memories*\n",
        ]

        current_cat = None
        for r in rows:
            row = dict(r)
            if row["category"] != current_cat:
                current_cat = row["category"]
                lines.append(f"\n## {current_cat.replace('_', ' ').title()}\n")
            lines.append(f"- **{row['key']}**: {row['value']}")
            lines.append(f"  *(agent: {row['source_agent']}, updated: {row['updated_at']}, accessed: {row['access_count']}x)*")

        return "\n".join(lines) + "\n"

    def stats(self) -> dict:
        """Return memory statistics."""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_category = {}
            for row in conn.execute("SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"):
                by_category[row["category"]] = row["cnt"]
            oldest = conn.execute("SELECT MIN(created_at) FROM memories").fetchone()[0]
            newest = conn.execute("SELECT MAX(updated_at) FROM memories").fetchone()[0]
            return {
                "total": total,
                "by_category": by_category,
                "oldest": oldest,
                "newest": newest,
            }
        except Exception as e:
            logger.error("memory_stats_failed error=%s", e)
            return {"total": 0, "by_category": {}, "oldest": None, "newest": None}

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
