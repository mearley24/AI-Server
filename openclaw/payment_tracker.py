"""Payment/deposit tracker with alerting."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import redis

logger = logging.getLogger("openclaw.payment_tracker")

DB_PATH = os.environ.get("PAYMENT_DB_PATH", "/data/email-monitor/payments.db")
EMAIL_DB_PATH = os.environ.get("EMAIL_DB_PATH", "/data/emails.db")
ROUTING_CONFIG_PATH = os.environ.get(
    "EMAIL_ROUTING_CONFIG",
    str(Path(__file__).resolve().parents[1] / "email-monitor" / "routing_config.json"),
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://:d1fff1065992d132b000c01d6012fa52@redis:6379")
NOTIFY_CHANNEL = "notifications:email"


def _notify(title: str, body: str) -> None:
    payload = {"title": title, "body": body}
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        r.publish(NOTIFY_CHANNEL, json.dumps(payload))
    except Exception as exc:
        logger.warning("payment notification failed: %s", exc)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_payments (
            project_key TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            deposit_due REAL DEFAULT 0,
            agreement_signed_at TEXT DEFAULT '',
            payment_received_at TEXT DEFAULT '',
            payment_status TEXT DEFAULT 'pending',
            last_due_alert_at TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _load_project_pricing(routing_config_path: str = ROUTING_CONFIG_PATH) -> list[tuple[str, str, float]]:
    projects: list[tuple[str, str, float]] = []
    try:
        from proposal_checker import CONFIRMED_DECISIONS
        for key, data in CONFIRMED_DECISIONS.items():
            pname = data.get("project_name", key)
            due = float(data.get("pricing", {}).get("deposit", 0) or 0)
            projects.append((key, pname, due))
    except Exception:
        pass

    try:
        with open(routing_config_path) as f:
            cfg = json.load(f)
        active_bids = cfg.get("active_bids", {})
        for name, bid in active_bids.items():
            key = name.lower().replace(" ", "_")
            projects.append((key, name, float(bid.get("deposit_due", 0) or 0)))
    except Exception:
        pass
    return projects


def _upsert_projects(projects: list[tuple[str, str, float]], db_path: str = DB_PATH) -> None:
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    for key, name, due in projects:
        row = conn.execute("SELECT project_key FROM project_payments WHERE project_key = ?", (key,)).fetchone()
        if row:
            conn.execute(
                "UPDATE project_payments SET project_name = ?, deposit_due = ?, updated_at = ? WHERE project_key = ?",
                (name, due, now, key),
            )
        else:
            conn.execute(
                """
                INSERT INTO project_payments (project_key, project_name, deposit_due, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, name, due, now),
            )
    conn.commit()
    conn.close()


def _project_match(project_name: str, text: str) -> bool:
    name = project_name.lower()
    text = text.lower()
    parts = [p for p in name.replace("-", " ").split() if len(p) > 3]
    return any(p in text for p in parts[:3]) if parts else False


def _scan_email_signals(email_db_path: str, db_path: str = DB_PATH) -> tuple[int, int]:
    """Detect agreement signed and payment received signals from emails DB."""
    if not os.path.exists(email_db_path):
        return 0, 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    src = sqlite3.connect(email_db_path)
    rows = src.execute(
        "SELECT sender, subject, snippet, received_at FROM emails ORDER BY received_at DESC LIMIT 1500"
    ).fetchall()
    projects = conn.execute("SELECT * FROM project_payments").fetchall()
    signed_updates = 0
    paid_updates = 0
    for sender, subject, snippet, received_at in rows:
        txt = f"{subject or ''} {snippet or ''} {sender or ''}".lower()
        is_signed = ("docusign" in txt and ("completed" in txt or "signed" in txt)) or "agreement signed" in txt
        is_payment = any(k in txt for k in ["payment received", "deposit received", "wire received", "ach credit", "receipt"])
        for prj in projects:
            if not _project_match(prj["project_name"], txt):
                continue
            if is_signed and not prj["agreement_signed_at"]:
                conn.execute(
                    """
                    UPDATE project_payments
                    SET agreement_signed_at = ?, payment_status = CASE WHEN payment_status='pending' THEN 'awaiting_deposit' ELSE payment_status END, updated_at = ?
                    WHERE project_key = ?
                    """,
                    (received_at, datetime.now(timezone.utc).isoformat(), prj["project_key"]),
                )
                signed_updates += 1
            if is_payment and not prj["payment_received_at"]:
                conn.execute(
                    """
                    UPDATE project_payments
                    SET payment_received_at = ?, payment_status = 'paid', updated_at = ?
                    WHERE project_key = ?
                    """,
                    (received_at, datetime.now(timezone.utc).isoformat(), prj["project_key"]),
                )
                _notify("[PAYMENT]", f"Payment confirmed for {prj['project_name']} ({prj['project_key']}).")
                paid_updates += 1
    conn.commit()
    src.close()
    conn.close()
    return signed_updates, paid_updates


def run_cycle(
    db_path: str = DB_PATH,
    email_db_path: str = EMAIL_DB_PATH,
    routing_config_path: str = ROUTING_CONFIG_PATH,
) -> dict:
    """Run payment tracker sync + alert cycle."""
    init_db(db_path)
    _upsert_projects(_load_project_pricing(routing_config_path), db_path=db_path)
    signed_updates, paid_updates = _scan_email_signals(email_db_path=email_db_path, db_path=db_path)

    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM project_payments").fetchall()
    due_alerts = 0
    for row in rows:
        signed_at = _dt(row["agreement_signed_at"])
        paid_at = _dt(row["payment_received_at"])
        last_alert = _dt(row["last_due_alert_at"])
        if not signed_at or paid_at:
            continue
        if (now - signed_at).total_seconds() < 7 * 24 * 3600:
            continue
        should_alert = not last_alert or (now - last_alert).total_seconds() >= 24 * 3600
        if not should_alert:
            continue
        _notify(
            "[DEPOSIT DUE]",
            f"Deposit overdue for {row['project_name']}: "
            f"${row['deposit_due']:.2f} due (agreement signed {signed_at.strftime('%Y-%m-%d')}).",
        )
        conn.execute(
            "UPDATE project_payments SET last_due_alert_at = ?, updated_at = ? WHERE project_key = ?",
            (now.isoformat(), now.isoformat(), row["project_key"]),
        )
        due_alerts += 1
    conn.commit()
    conn.close()
    return {"signed_updates": signed_updates, "paid_updates": paid_updates, "due_alerts": due_alerts}


def get_status_summary(db_path: str = DB_PATH) -> str:
    """Return human-readable payment status summary."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM project_payments ORDER BY updated_at DESC").fetchall()
    conn.close()
    if not rows:
        return "No payment tracking records found."
    lines = ["Payment status by project:"]
    for row in rows[:20]:
        status = row["payment_status"] or "pending"
        due = float(row["deposit_due"] or 0)
        lines.append(f"- {row['project_name']}: {status} | deposit ${due:.2f}")
    return "\n".join(lines)
