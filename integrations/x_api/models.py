"""SQLite schema and helpers for X API intake.

Tables:
  x_items     — fetched posts / bookmarks / likes / extracted URLs
  x_api_usage — per-call usage log for cost tracking and daily limit enforcement
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "x_api" / "x_items.sqlite"


def get_db_path() -> Path:
    import os
    env_path = os.environ.get("X_API_DB_PATH")
    if env_path:
        return Path(env_path)
    # Container path
    container = Path("/data/x_api/x_items.sqlite")
    if container.parent.is_dir():
        return container
    return DB_PATH_DEFAULT


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Create tables if they don't exist and return a connection."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS x_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            x_item_id        TEXT    UNIQUE NOT NULL,
            item_type        TEXT    NOT NULL,
            x_post_id        TEXT,
            author_handle    TEXT,
            author_name      TEXT,
            text             TEXT,
            url              TEXT,
            created_at       TEXT,
            fetched_at       TEXT    NOT NULL,
            category         TEXT,
            tags             TEXT    DEFAULT '[]',
            processed_status TEXT    NOT NULL DEFAULT 'pending',
            source           TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_x_items_type        ON x_items(item_type);
        CREATE INDEX IF NOT EXISTS idx_x_items_fetched_at  ON x_items(fetched_at);
        CREATE INDEX IF NOT EXISTS idx_x_items_status      ON x_items(processed_status);

        CREATE TABLE IF NOT EXISTS x_api_usage (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                  TEXT    NOT NULL,
            endpoint            TEXT    NOT NULL,
            request_count       INTEGER NOT NULL DEFAULT 1,
            item_count          INTEGER NOT NULL DEFAULT 0,
            estimated_cost_units INTEGER NOT NULL DEFAULT 0,
            status              TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_usage_ts ON x_api_usage(ts);
    """)
    conn.commit()
    return conn


@dataclass
class XItem:
    x_item_id: str
    item_type: str           # bookmark | like | post | url
    x_post_id: Optional[str] = None
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    processed_status: str = "pending"
    source: Optional[str] = None

    def to_row(self) -> dict:
        return {
            "x_item_id":        self.x_item_id,
            "item_type":        self.item_type,
            "x_post_id":        self.x_post_id,
            "author_handle":    self.author_handle,
            "author_name":      self.author_name,
            "text":             self.text,
            "url":              self.url,
            "created_at":       self.created_at,
            "fetched_at":       self.fetched_at,
            "category":         self.category,
            "tags":             json.dumps(self.tags),
            "processed_status": self.processed_status,
            "source":           self.source,
        }


def insert_item(conn: sqlite3.Connection, item: XItem) -> bool:
    """Insert item; return True if inserted, False if duplicate."""
    try:
        conn.execute(
            """INSERT INTO x_items
               (x_item_id, item_type, x_post_id, author_handle, author_name,
                text, url, created_at, fetched_at, category, tags, processed_status, source)
               VALUES
               (:x_item_id, :item_type, :x_post_id, :author_handle, :author_name,
                :text, :url, :created_at, :fetched_at, :category, :tags, :processed_status, :source)""",
            item.to_row(),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate x_item_id
