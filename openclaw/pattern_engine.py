"""Weekly pattern extraction from decision journal + optional email DB timestamps."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openclaw.pattern_engine")

PATTERNS_VERSION = 2

from zoneinfo import ZoneInfo


def _parse_iso_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    s = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _analyze_clients_from_db(db_path: Path) -> dict[str, Any]:
    """Group inbound email timestamps by sender_name; best local hour/day (America/Denver)."""
    if not db_path.exists():
        return {}
    tz = ZoneInfo("America/Denver")
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT sender_name, received_at FROM emails
            WHERE received_at >= ? AND TRIM(COALESCE(sender_name, '')) != ''
            """,
            (since,),
        ).fetchall()
        conn.close()
    except Exception as e:
        logger.debug("pattern_engine email db: %s", e)
        return {}

    by_client: dict[str, list[datetime]] = defaultdict(list)
    for r in rows:
        name = (r["sender_name"] or "").strip()
        if len(name) < 2:
            continue
        key = name[:80]
        dt = _parse_iso_ts(r["received_at"])
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        by_client[key].append(dt)

    out: dict[str, Any] = {}
    for name, times in by_client.items():
        if len(times) < 3:
            continue
        hours: list[int] = []
        weekdays: list[str] = []
        for t in times:
            local = t.astimezone(tz)
            hours.append(local.hour)
            weekdays.append(local.strftime("%A"))
        h_ctr = Counter(hours)
        d_ctr = Counter(weekdays)
        best_h, h_cnt = h_ctr.most_common(1)[0]
        best_d, d_cnt = d_ctr.most_common(1)[0]
        out[name] = {
            "samples": len(times),
            "best_hour_local_mdt": best_h,
            "best_hour_count": h_cnt,
            "best_weekday": best_d,
            "weekday_count": d_cnt,
        }
    return out


def run_weekly(data_dir: Path, journal) -> dict[str, Any]:
    """Analyze last 7 days of decisions; optional client timing from email DB; write patterns.json."""
    since = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
    rows = journal.decisions_since(since)

    by_cat: dict[str, int] = {}
    conf_sum: dict[str, float] = {}
    for r in rows:
        c = r[0] or "unknown"
        by_cat[c] = by_cat.get(c, 0) + 1
        conf_sum[c] = conf_sum.get(c, 0.0) + float(r[2] or 0)

    patterns: dict[str, Any] = {
        "version": PATTERNS_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "window_days": 7,
        "category_counts": by_cat,
        "category_avg_confidence": {
            k: round(conf_sum[k] / by_cat[k], 1) for k in by_cat if by_cat[k]
        },
        "hints": [],
        "clients": {},
    }

    db_path = Path(os.getenv("EMAIL_MONITOR_DB_PATH", "/data/email-monitor/emails.db"))
    clients = _analyze_clients_from_db(db_path)
    if clients:
        patterns["clients"] = clients
        top = sorted(clients.items(), key=lambda x: -x[1].get("samples", 0))[:5]
        patterns["hints"].append(
            "Client email timing (MDT): "
            + "; ".join(f"{n} → ~{d['best_hour_local_mdt']}:00 {d['best_weekday']}" for n, d in top)
        )

    if by_cat.get("email", 0) > 20:
        patterns["hints"].append("High email volume — consider batching digests.")
    if by_cat.get("system", 0) > 5:
        patterns["hints"].append("Repeated system decisions — check health stability.")

    out_path = data_dir / "patterns.json"
    out_path.write_text(json.dumps(patterns, indent=2))
    logger.info(
        "pattern_engine wrote %s categories=%s clients=%d",
        out_path,
        list(by_cat.keys()),
        len(clients),
    )
    return patterns


def load_patterns(data_dir: Path) -> dict[str, Any]:
    p = data_dir / "patterns.json"
    if not p.exists():
        return {"version": 0, "hints": [], "category_counts": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"version": 0, "hints": [], "category_counts": {}, "error": "parse_failed"}
