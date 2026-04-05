#!/usr/bin/env bash
# =============================================================================
# fix-followup-tracker.sh
# Fixes the follow_ups 0-row starvation bug
# Run from AI-Server repo root on Bob:  bash fix-followup-tracker.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)"

echo "========================================"
echo "Follow-Up Tracker Fix — $(date)"
echo "Repo root: $REPO_ROOT"
echo "========================================"

# ------------------------------------------------------------------
# 0. Pre-flight checks
# ------------------------------------------------------------------
for f in openclaw/follow_up_tracker.py openclaw/orchestrator.py email-monitor/monitor.py; do
    if [[ ! -f "$REPO_ROOT/$f" ]]; then
        echo "ERROR: $f not found. Are you in the AI-Server repo root?"
        exit 1
    fi
done

echo "[✓] All target files found"

# ------------------------------------------------------------------
# 1. Backups
# ------------------------------------------------------------------
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$REPO_ROOT/.backups/$TS"
cp "$REPO_ROOT/openclaw/follow_up_tracker.py"  "$REPO_ROOT/.backups/$TS/follow_up_tracker.py"
cp "$REPO_ROOT/openclaw/orchestrator.py"        "$REPO_ROOT/.backups/$TS/orchestrator.py"
cp "$REPO_ROOT/email-monitor/monitor.py"        "$REPO_ROOT/.backups/$TS/monitor.py"
echo "[✓] Backups saved to .backups/$TS/"

# ------------------------------------------------------------------
# 2. Patch follow_up_tracker.py  (full rewrite — cleaner than sed)
# ------------------------------------------------------------------
echo "[…] Patching openclaw/follow_up_tracker.py"

cat > "$REPO_ROOT/openclaw/follow_up_tracker.py" << 'PYEOF'
"""Follow-up tracker for client response SLAs."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import redis

logger = logging.getLogger("openclaw.follow_up_tracker")

DB_PATH = os.environ.get("FOLLOW_UP_DB_PATH", "/data/email-monitor/follow_ups.db")
EMAIL_DB_PATH = os.environ.get("EMAIL_DB_PATH", "/data/emails.db")
JOBS_DB_PATH = os.environ.get("JOBS_DB_PATH", "/app/data/jobs.db")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
NOTIFY_CHANNEL = "notifications:email"
TZ = ZoneInfo("America/Denver")


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


def _is_business_hours(now_utc: datetime) -> bool:
    local = now_utc.astimezone(TZ)
    if local.weekday() >= 5:
        return False
    return 8 <= local.hour < 18


def _notify(title: str, body: str) -> None:
    payload = {"title": title, "body": body}
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        r.publish(NOTIFY_CHANNEL, json.dumps(payload))
    except Exception as exc:
        logger.warning("follow-up notification failed: %s", exc)


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_ups (
            client_email TEXT PRIMARY KEY,
            client_name TEXT DEFAULT '',
            last_client_ts TEXT DEFAULT '',
            last_client_subject TEXT DEFAULT '',
            last_matthew_ts TEXT DEFAULT '',
            last_matthew_subject TEXT DEFAULT '',
            last_overdue_alert_ts TEXT DEFAULT '',
            last_followup_alert_ts TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _upsert_client_email(
    conn: sqlite3.Connection, client_email: str, client_name: str, subject: str, received_at: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT client_email FROM follow_ups WHERE client_email = ?", (client_email,)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE follow_ups
            SET client_name = ?, last_client_ts = ?, last_client_subject = ?, updated_at = ?
            WHERE client_email = ?
            """,
            (client_name, received_at, subject, now, client_email),
        )
    else:
        conn.execute(
            """
            INSERT INTO follow_ups (
                client_email, client_name, last_client_ts, last_client_subject, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (client_email, client_name, received_at, subject, now),
        )


# ---------------------------------------------------------------
# NEW: Load known client emails from jobs.db for cross-referencing
# ---------------------------------------------------------------

def _load_known_client_emails(jobs_db_path: str = "") -> dict[str, str]:
    """Load client emails from jobs.db clients table.

    Returns dict of {email_lower: client_name}.
    """
    db = jobs_db_path or JOBS_DB_PATH
    if not os.path.exists(db):
        return {}
    try:
        jconn = sqlite3.connect(db)
        jconn.row_factory = sqlite3.Row
        rows = jconn.execute(
            "SELECT name, email FROM clients WHERE email != '' AND email IS NOT NULL"
        ).fetchall()
        result = {}
        for row in rows:
            email_addr = (row["email"] or "").strip().lower()
            name = (row["name"] or "").strip()
            if email_addr:
                result[email_addr] = name
        jconn.close()
        return result
    except Exception as exc:
        logger.warning("Could not load known client emails from jobs.db: %s", exc)
        return {}


# ---------------------------------------------------------------
# CHANGED: Widened category filter + cross-reference GENERAL emails
# ---------------------------------------------------------------

def sync_from_email_db(
    email_db_path: str = EMAIL_DB_PATH,
    db_path: str = DB_PATH,
    jobs_db_path: str = "",
) -> None:
    """Sync inbound client email activity from email monitor DB.

    Pulls from multiple client-relevant categories (not just ACTIVE_CLIENT).
    Also cross-references GENERAL emails against known job clients from jobs.db.
    """
    init_db(db_path)
    if not os.path.exists(email_db_path):
        return
    conn = sqlite3.connect(db_path)
    src = sqlite3.connect(email_db_path)

    # 1. Pull from explicitly client-relevant categories
    rows = src.execute(
        """
        SELECT sender, sender_name, subject, received_at
        FROM emails
        WHERE category IN (
            'ACTIVE_CLIENT', 'CLIENT_INQUIRY',
            'FOLLOW_UP_NEEDED', 'SCHEDULING'
        )
        ORDER BY received_at DESC
        LIMIT 500
        """
    ).fetchall()
    for sender, sender_name, subject, received_at in rows:
        if not sender:
            continue
        _upsert_client_email(
            conn=conn,
            client_email=sender.strip().lower(),
            client_name=(sender_name or "").strip(),
            subject=(subject or "").strip(),
            received_at=(received_at or datetime.now(timezone.utc).isoformat()),
        )

    # 2. Cross-reference GENERAL emails against known job client emails
    known_clients = _load_known_client_emails(jobs_db_path)
    if known_clients:
        general_rows = src.execute(
            """
            SELECT sender, sender_name, subject, received_at
            FROM emails
            WHERE category = 'GENERAL'
            ORDER BY received_at DESC
            LIMIT 500
            """
        ).fetchall()
        for sender, sender_name, subject, received_at in general_rows:
            if not sender:
                continue
            email_lower = sender.strip().lower()
            if email_lower in known_clients:
                _upsert_client_email(
                    conn=conn,
                    client_email=email_lower,
                    client_name=known_clients[email_lower] or (sender_name or "").strip(),
                    subject=(subject or "").strip(),
                    received_at=(received_at or datetime.now(timezone.utc).isoformat()),
                )

    conn.commit()
    src.close()
    conn.close()


# ---------------------------------------------------------------
# NEW: Seed follow_ups from active D-Tools jobs
# ---------------------------------------------------------------

def seed_from_jobs(db_path: str = DB_PATH, jobs_db_path: str = "") -> int:
    """Seed follow_ups with active job clients from jobs.db.

    Creates placeholder rows for clients with active jobs so the SLA
    tracker doesn't stay empty waiting for a perfectly-classified email.
    Idempotent — only inserts clients not already tracked.

    Returns number of new rows inserted.
    """
    init_db(db_path)
    db = jobs_db_path or JOBS_DB_PATH
    if not os.path.exists(db):
        logger.info("seed_from_jobs: jobs.db not found at %s", db)
        return 0

    try:
        conn = sqlite3.connect(db_path)
        jconn = sqlite3.connect(db)
        jconn.row_factory = sqlite3.Row

        # Get active jobs (not COMPLETED or WARRANTY)
        jobs = jconn.execute(
            """
            SELECT DISTINCT client_name FROM jobs
            WHERE phase NOT IN ('COMPLETED', 'WARRANTY')
              AND client_name != ''
            """
        ).fetchall()

        # Build client_name -> email lookup from clients table
        clients: dict[str, str] = {}
        try:
            for row in jconn.execute(
                "SELECT name, email FROM clients WHERE email != '' AND email IS NOT NULL"
            ).fetchall():
                clients[row["name"].strip().lower()] = row["email"].strip().lower()
        except Exception:
            pass  # clients table may not have data yet

        inserted = 0
        now = datetime.now(timezone.utc).isoformat()

        for job in jobs:
            client_name = job["client_name"].strip()
            if not client_name:
                continue
            client_email = clients.get(client_name.lower(), "")
            if not client_email:
                # Placeholder so the row exists for name-based matching later
                slug = client_name.lower().replace(" ", "_").replace("'", "")
                client_email = f"pending+{slug}@symphony.placeholder"

            existing = conn.execute(
                "SELECT client_email FROM follow_ups WHERE client_email = ?",
                (client_email,),
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO follow_ups (
                        client_email, client_name, updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (client_email, client_name, now),
                )
                inserted += 1
                logger.info("Seeded follow_up: %s (%s)", client_name, client_email)

        conn.commit()
        jconn.close()
        conn.close()
        logger.info("seed_from_jobs: inserted %d new rows", inserted)
        return inserted
    except Exception as exc:
        logger.error("seed_from_jobs failed: %s", exc)
        return 0


def list_overdue(db_path: str = DB_PATH) -> list[dict]:
    init_db(db_path)
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM follow_ups ORDER BY last_client_ts DESC").fetchall()
    conn.close()
    out: list[dict] = []
    for row in rows:
        last_client = _dt(row["last_client_ts"])
        last_matthew = _dt(row["last_matthew_ts"])
        if not last_client:
            continue
        waiting_on_matt = (last_matthew is None) or (last_client > last_matthew)
        if waiting_on_matt and (now - last_client).total_seconds() >= 4 * 3600:
            out.append(dict(row))
    return out


# ---------------------------------------------------------------
# CHANGED: run_cycle now accepts jobs_db_path, seeds + wider sync
# ---------------------------------------------------------------

def run_cycle(
    db_path: str = DB_PATH,
    email_db_path: str = EMAIL_DB_PATH,
    jobs_db_path: str = "",
) -> dict:
    """Run follow-up checks and publish overdue alerts."""
    # Seed from active jobs (idempotent — only inserts new clients)
    seed_from_jobs(db_path=db_path, jobs_db_path=jobs_db_path)

    sync_from_email_db(email_db_path=email_db_path, db_path=db_path, jobs_db_path=jobs_db_path)
    init_db(db_path)
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM follow_ups ORDER BY last_client_ts DESC").fetchall()
    overdue_alerts = 0
    followup_alerts = 0

    for row in rows:
        client = row["client_email"]
        client_name = row["client_name"] or client
        subject = row["last_client_subject"] or "(no subject)"
        last_client = _dt(row["last_client_ts"])
        last_matthew = _dt(row["last_matthew_ts"])
        last_overdue_alert = _dt(row["last_overdue_alert_ts"])
        last_followup_alert = _dt(row["last_followup_alert_ts"])
        if not last_client:
            continue

        # Rule 1: inbound unanswered for 4h during business hours.
        waiting_on_matt = (last_matthew is None) or (last_client > last_matthew)
        if waiting_on_matt and _is_business_hours(now) and (now - last_client).total_seconds() >= 4 * 3600:
            should_alert = not last_overdue_alert or (now - last_overdue_alert).total_seconds() >= 4 * 3600
            if should_alert:
                body = (
                    f"[OVERDUE] No response to {client_name} — {subject} "
                    f"from {last_client.astimezone(TZ).strftime('%Y-%m-%d %I:%M %p %Z')}"
                )
                _notify("[OVERDUE]", body)
                conn.execute(
                    "UPDATE follow_ups SET last_overdue_alert_ts = ?, updated_at = ? WHERE client_email = ?",
                    (now.isoformat(), now.isoformat(), client),
                )
                overdue_alerts += 1

        # Rule 2: sent by Matt, no reply in 48h.
        if last_matthew and (last_client is None or last_client < last_matthew):
            if (now - last_matthew).total_seconds() >= 48 * 3600:
                should_alert = not last_followup_alert or (now - last_followup_alert).total_seconds() >= 24 * 3600
                if should_alert:
                    body = (
                        f"[FOLLOW UP] {client_name} hasn't replied to "
                        f"'{row['last_matthew_subject'] or subject}' sent "
                        f"{last_matthew.astimezone(TZ).strftime('%Y-%m-%d')}"
                    )
                    _notify("[FOLLOW UP]", body)
                    conn.execute(
                        "UPDATE follow_ups SET last_followup_alert_ts = ?, updated_at = ? WHERE client_email = ?",
                        (now.isoformat(), now.isoformat(), client),
                    )
                    followup_alerts += 1

    conn.commit()
    conn.close()
    return {"overdue_alerts": overdue_alerts, "followup_alerts": followup_alerts}
PYEOF

echo "[✓] follow_up_tracker.py rewritten"

# ------------------------------------------------------------------
# 3. Patch orchestrator.py — check_followups() to pass jobs_db
# ------------------------------------------------------------------
echo "[…] Patching openclaw/orchestrator.py"

# Use Python for reliable multi-line replacement
python3 << 'PATCH_ORCH'
import re

path = "openclaw/orchestrator.py"
with open(path, "r") as f:
    content = f.read()

old = '''    async def check_followups(self):
        """Run follow-up SLA tracker (SQLite under DATA_DIR)."""
        try:
            from follow_up_tracker import run_cycle as run_followups

            email_db, follow_db, _ = self._tracker_db_paths()
            res = await asyncio.to_thread(run_followups, follow_db, email_db)
            if res and (res.get("overdue_alerts") or res.get("followup_alerts")):
                await self._redis_publish(
                    "events:clients",
                    {"type": "client.followup_alert", "data": res},
                )
        except Exception as e:
            logger.warning("check_followups failed: %s", e)'''

new = '''    async def check_followups(self):
        """Run follow-up SLA tracker (SQLite under DATA_DIR)."""
        try:
            from follow_up_tracker import run_cycle as run_followups

            email_db, follow_db, _ = self._tracker_db_paths()
            jobs_db = str(self._data_dir / "jobs.db")
            res = await asyncio.to_thread(run_followups, follow_db, email_db, jobs_db)
            if res and (res.get("overdue_alerts") or res.get("followup_alerts")):
                await self._redis_publish(
                    "events:clients",
                    {"type": "client.followup_alert", "data": res},
                )
        except Exception as e:
            logger.warning("check_followups failed: %s", e)'''

if old not in content:
    print("WARNING: Could not find exact check_followups block in orchestrator.py")
    print("         You may need to patch this manually.")
else:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("[✓] orchestrator.py patched — check_followups now passes jobs_db")
PATCH_ORCH

# ------------------------------------------------------------------
# 4. Patch email-monitor/monitor.py — add jobs_db_path to follow_up call
# ------------------------------------------------------------------
echo "[…] Patching email-monitor/monitor.py"

python3 << 'PATCH_MON'
path = "email-monitor/monitor.py"
with open(path, "r") as f:
    content = f.read()

old = '''                follow_up_result = await asyncio.to_thread(
                    follow_up_run_cycle,
                    os.environ.get("FOLLOW_UP_DB_PATH", "/data/email-monitor/follow_ups.db"),
                    DB_PATH,
                )'''

new = '''                follow_up_result = await asyncio.to_thread(
                    follow_up_run_cycle,
                    os.environ.get("FOLLOW_UP_DB_PATH", "/data/email-monitor/follow_ups.db"),
                    DB_PATH,
                    os.environ.get("JOBS_DB_PATH", "/app/data/jobs.db"),
                )'''

if old not in content:
    print("WARNING: Could not find exact follow_up_run_cycle block in monitor.py")
    print("         You may need to patch this manually.")
else:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("[✓] monitor.py patched — follow_up_run_cycle now passes jobs_db_path")
PATCH_MON

# ------------------------------------------------------------------
# 5. Commit changes
# ------------------------------------------------------------------
echo "[…] Committing changes"
cd "$REPO_ROOT"
git add openclaw/follow_up_tracker.py openclaw/orchestrator.py email-monitor/monitor.py
git commit -m "fix: follow_up tracker starvation — widen categories, seed from jobs.db

- sync_from_email_db now pulls ACTIVE_CLIENT + CLIENT_INQUIRY +
  FOLLOW_UP_NEEDED + SCHEDULING (was ACTIVE_CLIENT only)
- Cross-references GENERAL emails against known client emails in jobs.db
- New seed_from_jobs() bootstraps tracker rows from active D-Tools jobs
- orchestrator.py and monitor.py pass jobs_db_path to run_cycle()
- All changes additive, backward-compatible, idempotent" || echo "(nothing to commit)"

# ------------------------------------------------------------------
# 6. Restart openclaw (live mount picks up changes, no rebuild)
# ------------------------------------------------------------------
echo "[…] Restarting openclaw container"
docker restart openclaw
echo "[…] Waiting 15s for startup…"
sleep 15

# ------------------------------------------------------------------
# 7. Verify
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo "VERIFICATION"
echo "========================================"

echo ""
echo "--- OpenClaw health ---"
curl -sf http://127.0.0.1:8099/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (health check pending — may need more time)"

echo ""
echo "--- follow_ups row count ---"
sqlite3 ./data/openclaw/follow_ups.db "SELECT COUNT(*) as rows FROM follow_ups" 2>/dev/null || echo "  (DB not yet created — wait for first tick)"

echo ""
echo "--- follow_ups contents ---"
sqlite3 ./data/openclaw/follow_ups.db "SELECT client_email, client_name FROM follow_ups LIMIT 20" 2>/dev/null || echo "  (pending)"

echo ""
echo "--- Email categories in emails.db ---"
sqlite3 ./data/email-monitor/emails.db "SELECT category, COUNT(*) as n FROM emails GROUP BY category ORDER BY n DESC" 2>/dev/null || echo "  (email DB not found)"

echo ""
echo "--- Jobs by phase ---"
sqlite3 ./data/openclaw/jobs.db "SELECT phase, COUNT(*) FROM jobs GROUP BY phase" 2>/dev/null || echo "  (jobs DB not found)"

echo ""
echo "========================================"
echo "Done. If follow_ups shows 0 rows, wait for"
echo "the next orchestrator tick (~5 min) and re-check:"
echo "  sqlite3 ./data/openclaw/follow_ups.db 'SELECT COUNT(*) FROM follow_ups'"
echo "========================================"
