"""
Project health — jobs in WON phase, follow-ups, JSON for briefing.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openclaw.project_learner")


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/app/data"))


def _jobs_db() -> Path:
    return _data_dir() / "jobs.db"


def _followups_db() -> Path:
    p = os.environ.get("FOLLOW_UP_DB_PATH")
    if p:
        return Path(p)
    return _data_dir() / "follow_ups.db"


def _load_won_jobs() -> list[dict[str, Any]]:
    db = _jobs_db()
    if not db.is_file():
        return []
    con = sqlite3.connect(str(db))
    try:
        cur = con.execute(
            "SELECT job_id, client_name, project_name, phase, updated_at, notes FROM jobs WHERE UPPER(phase)=?",
            ("WON",),
        )
        rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
        return rows
    except Exception as e:
        logger.debug("project_learner jobs: %s", e)
        return []
    finally:
        con.close()


def _followup_stats_for_clients(clients: set[str]) -> dict[str, int]:
    db = _followups_db()
    if not db.is_file():
        return {}
    con = sqlite3.connect(str(db))
    out: dict[str, int] = {}
    try:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if "follow_ups" not in tables:
            return {}
        for c in clients:
            q = "SELECT COUNT(*) FROM follow_ups WHERE client_name LIKE ?"
            try:
                n = con.execute(q, (f"%{c}%",)).fetchone()[0]
            except Exception:
                n = 0
            out[c] = int(n)
    except Exception as e:
        logger.debug("project_learner followups: %s", e)
    finally:
        con.close()
    return out


def build_project_health_payload() -> dict[str, Any]:
    jobs = _load_won_jobs()
    clients = {j["client_name"] for j in jobs}
    fu = _followup_stats_for_clients(clients)

    projects_out: list[dict[str, Any]] = []
    alerts: list[str] = []

    for j in jobs:
        name = f"{j.get('client_name','')} — {j.get('project_name','')}".strip(" —")
        overdue = 0
        nfu = fu.get(j.get("client_name", ""), 0)
        if nfu > 5:
            overdue = max(0, nfu - 3)
            alerts.append(f"{j.get('client_name')}: {nfu} open follow-up rows (review queue)")

        health = "on_track"
        if overdue:
            health = "needs_attention"

        projects_out.append(
            {
                "name": name,
                "phase": j.get("phase"),
                "completion_pct": None,
                "overdue_issues": overdue,
                "last_client_email": None,
                "docs_stale": False,
                "health": health,
                "updated_at": j.get("updated_at"),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "projects": projects_out,
        "alerts": alerts,
        "meta": {
            "won_jobs": len(jobs),
            "follow_up_scan": "client_name LIKE match on follow_ups",
        },
    }
    return payload


def generate_project_health(redis_url: str | None = None) -> str:
    """Write project_health.json and return a short briefing block."""
    payload = build_project_health_payload()
    out = _data_dir() / "project_health.json"
    try:
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("project_learner: could not write %s: %s", out, e)

    rurl = redis_url or os.environ.get("REDIS_URL", "")
    if rurl:
        try:
            import event_bus

            event_bus.publish_and_log(
                rurl,
                "events:projects",
                {"type": "project_health", "data": payload},
            )
        except Exception as e:
            logger.debug("project_learner redis: %s", e)

    lines = [f"WON jobs tracked: {payload['meta']['won_jobs']}"]
    for p in payload["projects"][:6]:
        lines.append(f"  - {p['name']}: {p['health']}")
    for a in payload["alerts"][:5]:
        lines.append(f"  ! {a}")
    if not payload["projects"]:
        lines = ["No WON-phase jobs in jobs.db — nothing to report."]
    return "\n".join(lines)
