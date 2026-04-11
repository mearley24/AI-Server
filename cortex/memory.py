"""MemoryStore — Bob's persistent long-term memory backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import structlog

from cortex.config import DB_PATH, PRUNE_CONFIDENCE_THRESHOLD, PRUNE_STALE_DAYS

logger = structlog.get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    importance INTEGER DEFAULT 5,
    ttl_days INTEGER DEFAULT NULL,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT DEFAULT NULL,
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    decision_type TEXT NOT NULL,
    context TEXT NOT NULL,
    options_considered TEXT DEFAULT '[]',
    chosen_option TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    outcome TEXT DEFAULT 'pending',
    outcome_details TEXT DEFAULT '',
    outcome_recorded_at TEXT DEFAULT NULL,
    memories_consulted TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    goal_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'active',
    target_metric TEXT DEFAULT '',
    current_value TEXT DEFAULT '',
    target_value TEXT DEFAULT '',
    deadline TEXT DEFAULT NULL,
    progress_log TEXT DEFAULT '[]',
    parent_goal_id TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS improvement_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    loop_type TEXT NOT NULL,
    findings TEXT NOT NULL,
    actions_taken TEXT DEFAULT '[]',
    impact_estimate TEXT DEFAULT '',
    status TEXT DEFAULT 'proposed'
);
"""

# Valid memory categories
CATEGORIES = {
    "trading_rule",
    "strategy_idea",
    "strategy_performance",
    "market_pattern",
    "whale_intel",
    "x_intel",
    "infrastructure",
    "edge",
    "meta_learning",
    "external_research",
}


class MemoryStore:
    """Bob's persistent long-term memory."""

    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info("memory_store_initialized", db=str(DB_PATH))

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────────

    def remember(
        self,
        category: str,
        title: str,
        content: str,
        source: str = "",
        confidence: float = 0.5,
        importance: int = 5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_days: int | None = None,
        subcategory: str = "",
    ) -> str:
        """Store a new memory. Returns the memory ID."""
        mem_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO memories
               (id, created_at, updated_at, category, subcategory, title, content,
                source, confidence, importance, tags, metadata, ttl_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mem_id, now, now, category, subcategory, title, content,
                source, confidence, importance,
                json.dumps(tags or []),
                json.dumps(metadata or {}),
                ttl_days,
            ),
        )
        self.conn.commit()
        logger.debug("memory_stored", id=mem_id, category=category, title=title[:50])
        return mem_id

    # ── Read ───────────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        category: str | None = None,
        min_importance: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search memories by keyword. Returns list of dicts. Updates access_count."""
        if query:
            sql = """
                SELECT * FROM memories
                WHERE importance >= ?
                  AND (title LIKE ? OR content LIKE ?)
                  {cat_filter}
                ORDER BY importance DESC, access_count DESC
                LIMIT ?
            """
            like = f"%{query}%"
            if category:
                sql = sql.format(cat_filter="AND category = ?")
                rows = self.conn.execute(
                    sql, (min_importance, like, like, category, limit)
                ).fetchall()
            else:
                sql = sql.format(cat_filter="")
                rows = self.conn.execute(
                    sql, (min_importance, like, like, limit)
                ).fetchall()
        else:
            sql = """
                SELECT * FROM memories
                WHERE importance >= ?
                  {cat_filter}
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """
            if category:
                sql = sql.format(cat_filter="AND category = ?")
                rows = self.conn.execute(sql, (min_importance, category, limit)).fetchall()
            else:
                sql = sql.format(cat_filter="")
                rows = self.conn.execute(sql, (min_importance, limit)).fetchall()

        results = [dict(r) for r in rows]

        # Update access stats
        if results:
            now = datetime.now(timezone.utc).isoformat()
            ids = [r["id"] for r in results]
            placeholders = ",".join("?" * len(ids))
            self.conn.execute(
                f"""UPDATE memories
                    SET access_count = access_count + 1, last_accessed = ?
                    WHERE id IN ({placeholders})""",
                [now] + ids,
            )
            self.conn.commit()

        return results

    def get_rules(
        self,
        category: str = "trading_rule",
        min_confidence: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Get all active rules above confidence threshold."""
        rows = self.conn.execute(
            """SELECT * FROM memories
               WHERE category = ? AND confidence >= ? AND importance > 0
               ORDER BY confidence DESC, importance DESC""",
            (category, min_confidence),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_category(self, category: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return all memories in a category, ordered by importance."""
        rows = self.conn.execute(
            """SELECT * FROM memories
               WHERE category = ? AND importance > 0
               ORDER BY importance DESC, updated_at DESC
               LIMIT ?""",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, hours: int = 24, limit: int = 50) -> list[dict[str, Any]]:
        """Return memories created in the last N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM memories
               WHERE created_at >= ? AND importance > 0
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Update ─────────────────────────────────────────────────────────────────

    def update_confidence(
        self,
        memory_id: str,
        new_confidence: float,
        reason: str = "",
    ) -> None:
        """Adjust confidence of a memory based on new evidence."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE memories SET confidence = ?, updated_at = ? WHERE id = ?",
            (max(0.0, min(1.0, new_confidence)), now, memory_id),
        )
        self.conn.commit()
        logger.info(
            "memory_confidence_updated",
            id=memory_id,
            confidence=new_confidence,
            reason=reason[:80],
        )

    def deprecate(self, memory_id: str, reason: str = "") -> None:
        """Mark a memory as deprecated (importance=0) instead of deleting."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE memories SET importance = 0, updated_at = ? WHERE id = ?",
            (now, memory_id),
        )
        self.conn.commit()
        logger.info("memory_deprecated", id=memory_id, reason=reason[:80])

    # ── Decisions ──────────────────────────────────────────────────────────────

    def record_decision(
        self,
        decision_type: str,
        context: str,
        options: list[str],
        chosen: str,
        reasoning: str,
        memories_consulted: list[str] | None = None,
    ) -> str:
        """Log a decision for future outcome tracking."""
        dec_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO decisions
               (id, created_at, decision_type, context, options_considered,
                chosen_option, reasoning, memories_consulted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dec_id, now, decision_type, context,
                json.dumps(options), chosen, reasoning,
                json.dumps(memories_consulted or []),
            ),
        )
        self.conn.commit()
        return dec_id

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        details: str = "",
    ) -> None:
        """Record the outcome of a past decision."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE decisions
               SET outcome = ?, outcome_details = ?, outcome_recorded_at = ?
               WHERE id = ?""",
            (outcome, details, now, decision_id),
        )
        self.conn.commit()

    def get_pending_decisions(self) -> list[dict[str, Any]]:
        """Get decisions awaiting outcome recording."""
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE outcome = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Goals ──────────────────────────────────────────────────────────────────

    def upsert_goal(self, goal: dict[str, Any]) -> str:
        """Insert or update a goal. Returns the goal ID."""
        now = datetime.now(timezone.utc).isoformat()
        goal_id = goal.get("id") or str(uuid.uuid4())[:8]
        existing = self.conn.execute(
            "SELECT id FROM goals WHERE title = ?", (goal["title"],)
        ).fetchone()
        if existing:
            goal_id = existing["id"]
            self.conn.execute(
                """UPDATE goals
                   SET updated_at = ?, description = ?, priority = ?,
                       current_value = ?, target_value = ?, status = ?
                   WHERE id = ?""",
                (
                    now, goal.get("description", ""),
                    goal.get("priority", 5),
                    goal.get("current_value", ""),
                    goal.get("target_value", ""),
                    goal.get("status", "active"),
                    goal_id,
                ),
            )
        else:
            self.conn.execute(
                """INSERT INTO goals
                   (id, created_at, updated_at, title, description, goal_type,
                    priority, status, target_metric, current_value, target_value,
                    deadline, parent_goal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    goal_id, now, now,
                    goal["title"],
                    goal.get("description", ""),
                    goal.get("goal_type", "general"),
                    goal.get("priority", 5),
                    goal.get("status", "active"),
                    goal.get("target_metric", ""),
                    goal.get("current_value", ""),
                    goal.get("target_value", ""),
                    goal.get("deadline"),
                    goal.get("parent_goal_id"),
                ),
            )
        self.conn.commit()
        return goal_id

    def get_goals(self, status: str = "active") -> list[dict[str, Any]]:
        """Return goals filtered by status."""
        rows = self.conn.execute(
            "SELECT * FROM goals WHERE status = ? ORDER BY priority DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_goal_value(
        self,
        goal_id: str,
        new_value: str,
        note: str = "",
    ) -> None:
        """Update goal current_value and append to progress_log."""
        now = datetime.now(timezone.utc).isoformat()
        row = self.conn.execute(
            "SELECT progress_log FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not row:
            return
        log = json.loads(row["progress_log"] or "[]")
        log.append({"at": now, "value": new_value, "note": note})
        self.conn.execute(
            "UPDATE goals SET current_value = ?, progress_log = ?, updated_at = ? WHERE id = ?",
            (new_value, json.dumps(log), now, goal_id),
        )
        self.conn.commit()

    # ── Improvement Log ────────────────────────────────────────────────────────

    def log_improvement(
        self,
        loop_type: str,
        findings: str,
        actions: list[str] | None = None,
        impact: str = "",
        status: str = "proposed",
    ) -> str:
        """Record an improvement cycle."""
        log_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO improvement_log
               (id, created_at, loop_type, findings, actions_taken, impact_estimate, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (log_id, now, loop_type, findings, json.dumps(actions or []), impact, status),
        )
        self.conn.commit()
        return log_id

    # ── Maintenance ────────────────────────────────────────────────────────────

    def prune_expired(self) -> list[str]:
        """Remove memories past their TTL. Called by improvement loop."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            """SELECT id, created_at, ttl_days FROM memories
               WHERE ttl_days IS NOT NULL AND importance > 0"""
        ).fetchall()
        pruned = []
        for row in rows:
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                expires = created + timedelta(days=row["ttl_days"])
                if datetime.now(timezone.utc) > expires:
                    self.deprecate(row["id"], reason="TTL expired")
                    pruned.append(row["id"])
            except Exception:
                pass
        if pruned:
            logger.info("memories_ttl_pruned", count=len(pruned))
        return pruned

    def prune_low_confidence(self) -> list[str]:
        """Deprecate memories with low confidence that haven't been accessed recently."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=PRUNE_STALE_DAYS)
        ).isoformat()
        rows = self.conn.execute(
            """SELECT id FROM memories
               WHERE confidence < ?
                 AND importance > 0
                 AND (last_accessed IS NULL OR last_accessed < ?)""",
            (PRUNE_CONFIDENCE_THRESHOLD, cutoff),
        ).fetchall()
        pruned = [r["id"] for r in rows]
        for mem_id in pruned:
            self.deprecate(mem_id, reason="low confidence + stale")
        if pruned:
            logger.info("memories_low_confidence_pruned", count=len(pruned))
        return pruned

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return memory stats: total, by category, avg confidence, etc."""
        total = self.conn.execute(
            "SELECT COUNT(*) as n FROM memories WHERE importance > 0"
        ).fetchone()["n"]

        by_cat_rows = self.conn.execute(
            """SELECT category, COUNT(*) as n, AVG(confidence) as avg_conf
               FROM memories WHERE importance > 0
               GROUP BY category ORDER BY n DESC"""
        ).fetchall()

        pending_decisions = self.conn.execute(
            "SELECT COUNT(*) as n FROM decisions WHERE outcome = 'pending'"
        ).fetchone()["n"]

        active_goals = self.conn.execute(
            "SELECT COUNT(*) as n FROM goals WHERE status = 'active'"
        ).fetchone()["n"]

        return {
            "total": total,
            "by_category": {
                r["category"]: {"count": r["n"], "avg_confidence": round(r["avg_conf"] or 0, 2)}
                for r in by_cat_rows
            },
            "pending_decisions": pending_decisions,
            "active_goals": active_goals,
        }
