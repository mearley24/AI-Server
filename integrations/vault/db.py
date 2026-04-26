"""SQLite operations for the vault.

Tables: secrets, secret_access_log
Never returns encrypted_value in list/get_meta calls.
Decryption is the caller's responsibility using crypto.decrypt().
"""
from __future__ import annotations

import json
import secrets as _secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "vault" / "vault.sqlite"
DB_PATH_CONTAINER = Path("/data/vault/vault.sqlite")


def get_db_path() -> Path:
    import os
    env = os.environ.get("VAULT_DB_PATH")
    if env:
        return Path(env)
    if DB_PATH_CONTAINER.parent.is_dir():
        return DB_PATH_CONTAINER
    return DB_PATH_DEFAULT


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS secrets (
            secret_id        TEXT PRIMARY KEY,
            name             TEXT UNIQUE NOT NULL,
            category         TEXT NOT NULL DEFAULT 'general',
            encrypted_value  TEXT NOT NULL,
            sha256_fingerprint TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            last_accessed_at TEXT,
            access_policy    TEXT NOT NULL DEFAULT 'medium_risk',
            notes            TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_secrets_name ON secrets(name);
        CREATE INDEX IF NOT EXISTS idx_secrets_category ON secrets(category);

        CREATE TABLE IF NOT EXISTS secret_access_log (
            log_id       TEXT PRIMARY KEY,
            ts           TEXT NOT NULL,
            secret_id    TEXT,
            secret_name  TEXT NOT NULL,
            requester    TEXT NOT NULL,
            purpose      TEXT,
            approved     INTEGER,
            action       TEXT NOT NULL,
            fingerprint  TEXT,
            FOREIGN KEY (secret_id) REFERENCES secrets(secret_id)
        );
        CREATE INDEX IF NOT EXISTS idx_log_ts         ON secret_access_log(ts);
        CREATE INDEX IF NOT EXISTS idx_log_secret_id  ON secret_access_log(secret_id);
        CREATE INDEX IF NOT EXISTS idx_log_approved   ON secret_access_log(approved);
    """)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return _secrets.token_hex(8)


# --------------------------------------------------------------------------- #
# Secret CRUD
# --------------------------------------------------------------------------- #

def set_secret(
    conn: sqlite3.Connection,
    name: str,
    encrypted_value: str,
    sha256_fingerprint: str,
    category: str = "general",
    access_policy: str = "medium_risk",
    notes: Optional[str] = None,
) -> str:
    """Insert or update a secret. Returns the secret_id."""
    now = _now()
    existing = conn.execute("SELECT secret_id FROM secrets WHERE name=?", (name,)).fetchone()
    if existing:
        secret_id = existing["secret_id"]
        conn.execute(
            """UPDATE secrets SET encrypted_value=?, sha256_fingerprint=?, category=?,
               access_policy=?, notes=?, updated_at=? WHERE secret_id=?""",
            (encrypted_value, sha256_fingerprint, category, access_policy, notes, now, secret_id),
        )
    else:
        secret_id = _new_id()
        conn.execute(
            """INSERT INTO secrets
               (secret_id, name, category, encrypted_value, sha256_fingerprint,
                created_at, updated_at, access_policy, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (secret_id, name, category, encrypted_value, sha256_fingerprint,
             now, now, access_policy, notes),
        )
    conn.commit()
    return secret_id


def get_secret_meta(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    """Return secret metadata without the encrypted_value."""
    row = conn.execute(
        "SELECT secret_id, name, category, sha256_fingerprint, created_at, "
        "updated_at, last_accessed_at, access_policy, notes FROM secrets WHERE name=?",
        (name,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def get_secret_encrypted(conn: sqlite3.Connection, name: str) -> Optional[tuple[str, str, str]]:
    """Return (secret_id, encrypted_value, fingerprint) or None. Touch last_accessed_at."""
    row = conn.execute(
        "SELECT secret_id, encrypted_value, sha256_fingerprint FROM secrets WHERE name=?",
        (name,),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE secrets SET last_accessed_at=? WHERE secret_id=?",
        (_now(), row["secret_id"]),
    )
    conn.commit()
    return row["secret_id"], row["encrypted_value"], row["sha256_fingerprint"]


def list_secrets(conn: sqlite3.Connection) -> list[dict]:
    """Return all secrets — metadata only, never encrypted_value."""
    rows = conn.execute(
        "SELECT secret_id, name, category, sha256_fingerprint, created_at, "
        "updated_at, last_accessed_at, access_policy, notes FROM secrets ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_secret(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM secrets WHERE name=?", (name,))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Access log
# --------------------------------------------------------------------------- #

def log_access(
    conn: sqlite3.Connection,
    secret_name: str,
    requester: str,
    action: str,
    purpose: Optional[str] = None,
    approved: Optional[bool] = None,
    fingerprint: Optional[str] = None,
) -> str:
    """Write an access log entry. Returns log_id."""
    log_id = _new_id()
    # Look up secret_id by name (may not exist if secret was deleted)
    row = conn.execute("SELECT secret_id FROM secrets WHERE name=?", (secret_name,)).fetchone()
    secret_id = row["secret_id"] if row else None

    approved_int: Optional[int] = None
    if approved is True:
        approved_int = 1
    elif approved is False:
        approved_int = 0

    conn.execute(
        """INSERT INTO secret_access_log
           (log_id, ts, secret_id, secret_name, requester, purpose, approved, action, fingerprint)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (log_id, _now(), secret_id, secret_name, requester, purpose, approved_int, action, fingerprint),
    )
    conn.commit()
    return log_id


def get_access_log(
    conn: sqlite3.Connection,
    secret_name: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    if secret_name:
        rows = conn.execute(
            "SELECT * FROM secret_access_log WHERE secret_name=? ORDER BY ts DESC LIMIT ?",
            (secret_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM secret_access_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_requests(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM secret_access_log WHERE action='request' AND approved IS NULL ORDER BY ts DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_request(conn: sqlite3.Connection, log_id: str, approved: bool) -> bool:
    """Approve or deny a pending request. Returns True if found."""
    cur = conn.execute(
        "UPDATE secret_access_log SET approved=? WHERE log_id=? AND action='request' AND approved IS NULL",
        (1 if approved else 0, log_id),
    )
    conn.commit()
    return cur.rowcount > 0
