"""SQLite schema and helpers for X API insight extraction.

Table: x_insights — structured insights extracted from eligible x_items
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DB_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "x_api" / "x_insights.sqlite"


def get_db_path() -> Path:
    import os
    env = os.environ.get("X_INSIGHTS_DB_PATH")
    if env:
        return Path(env)
    container = Path("/data/x_api/x_insights.sqlite")
    if container.parent.is_dir():
        return container
    return _DB_DEFAULT


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS x_insights (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            x_item_id        TEXT    UNIQUE NOT NULL,
            topic            TEXT    NOT NULL,
            insight_type     TEXT    NOT NULL,
            summary          TEXT    NOT NULL,
            key_points       TEXT    NOT NULL DEFAULT '[]',
            relevance_score  REAL    NOT NULL,
            source_url       TEXT,
            author_handle    TEXT,
            created_at       TEXT,
            extracted_at     TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_insights_topic     ON x_insights(topic);
        CREATE INDEX IF NOT EXISTS idx_insights_type      ON x_insights(insight_type);
        CREATE INDEX IF NOT EXISTS idx_insights_score     ON x_insights(relevance_score);
        CREATE INDEX IF NOT EXISTS idx_insights_extracted ON x_insights(extracted_at);
    """)
    conn.commit()
    return conn


@dataclass
class XInsight:
    x_item_id: str
    topic: str
    insight_type: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    source_url: Optional[str] = None
    author_handle: Optional[str] = None
    created_at: Optional[str] = None
    extracted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_row(self) -> dict:
        return {
            "x_item_id":       self.x_item_id,
            "topic":           self.topic,
            "insight_type":    self.insight_type,
            "summary":         self.summary,
            "key_points":      json.dumps(self.key_points),
            "relevance_score": self.relevance_score,
            "source_url":      self.source_url,
            "author_handle":   self.author_handle,
            "created_at":      self.created_at,
            "extracted_at":    self.extracted_at,
        }


def insert_insight(conn: sqlite3.Connection, insight: XInsight) -> bool:
    """Insert insight; return True if inserted, False if duplicate."""
    try:
        conn.execute(
            """INSERT INTO x_insights
               (x_item_id, topic, insight_type, summary, key_points,
                relevance_score, source_url, author_handle, created_at, extracted_at)
               VALUES
               (:x_item_id, :topic, :insight_type, :summary, :key_points,
                :relevance_score, :source_url, :author_handle, :created_at, :extracted_at)""",
            insight.to_row(),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_insights(
    conn: sqlite3.Connection,
    limit: int = 50,
    topic: str = "",
    insight_type: str = "",
) -> list[dict]:
    conditions: list[str] = []
    params: list = []
    if topic:
        conditions.append("topic=?")
        params.append(topic)
    if insight_type:
        conditions.append("insight_type=?")
        params.append(insight_type)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(min(limit, 200))
    rows = conn.execute(
        f"SELECT * FROM x_insights {where} "
        f"ORDER BY relevance_score DESC, extracted_at DESC LIMIT ?",
        params,
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["key_points"] = json.loads(d.get("key_points") or "[]")
        results.append(d)
    return results
