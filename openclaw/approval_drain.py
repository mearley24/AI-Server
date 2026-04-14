"""Approval drain — auto-expire stale pending approvals and surface a digest.

Usage (one-shot, run inside openclaw container or host):
    python approval_drain.py

Usage (from orchestrator tick):
    from approval_drain import drain_stale_approvals
    expired = await drain_stale_approvals()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis

logger = logging.getLogger("openclaw.approval_drain")

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = os.environ.get(
    "DECISION_JOURNAL_DB_PATH",
    "/app/data/decision_journal.db",
)
# Fallback paths for host or test
DB_CANDIDATES = [
    DB_PATH,
    "/data/openclaw/decision_journal.db",
    "data/openclaw/decision_journal.db",
]

REDIS_URL = os.environ.get(
    "REDIS_URL",
    "redis://redis:6379",
)
CORTEX_URL = os.environ.get("CORTEX_URL", "http://cortex:8102")

# Approvals older than this are auto-expired
STALE_DAYS = 7
# Alert threshold
ALERT_THRESHOLD = 20


# ── DB helpers ────────────────────────────────────────────────────────────────


def _find_db() -> str | None:
    """Return the first candidate DB path that exists on disk."""
    import os as _os

    for path in DB_CANDIDATES:
        if path and _os.path.isfile(path):
            return path
    return None


def _connect() -> sqlite3.Connection:
    """Open the decision journal DB with row_factory set."""
    db_path = _find_db()
    if db_path is None:
        raise FileNotFoundError(
            f"decision_journal.db not found; tried: {DB_CANDIDATES}"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Redis helper ─────────────────────────────────────────────────────────────


def _get_redis() -> redis.Redis | None:
    """Return a sync Redis client or None if unavailable."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
        r.ping()
        return r
    except Exception as exc:
        logger.warning("redis_unavailable: %s", exc)
        return None


# ── Cortex helper ─────────────────────────────────────────────────────────────


async def _post_to_cortex(payload: dict[str, Any]) -> None:
    """Fire-and-forget POST to Cortex /remember. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{CORTEX_URL}/remember", json=payload)
    except Exception as exc:
        logger.debug("cortex_post_failed: %s", exc)


# ── Core logic ────────────────────────────────────────────────────────────────


async def drain_stale_approvals(
    stale_days: int = STALE_DAYS,
) -> dict[str, Any]:
    """Expire approvals older than ``stale_days``, publish a digest, return stats.

    Returns a dict with keys:
        expired (int)  — rows just marked expired
        remaining (int) — still-pending rows after expiry
        groups (dict)  — kind -> {count, oldest, examples}
        summary (str)  — human-readable digest under 1500 chars
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    cutoff_iso = cutoff.isoformat()

    conn = _connect()
    try:
        # ── 1. Mark stale rows as expired ──────────────────────────────────
        stale_rows = conn.execute(
            "SELECT id, kind, context_json, created_at FROM pending_approvals "
            "WHERE status = 'pending' AND created_at < ?",
            (cutoff_iso,),
        ).fetchall()

        expired_ids = [row["id"] for row in stale_rows]
        expired_count = len(expired_ids)

        if expired_ids:
            conn.execute(
                f"UPDATE pending_approvals SET status = 'expired' "
                f"WHERE id IN ({','.join('?' * len(expired_ids))})",
                expired_ids,
            )
            conn.commit()
            logger.info("approval_drain_expired count=%d cutoff=%s", expired_count, cutoff_iso)

            # Notify Cortex about the bulk expiry.
            stale_kinds = defaultdict(int)
            for row in stale_rows:
                stale_kinds[row["kind"]] += 1
            await _post_to_cortex(
                {
                    "category": "system",
                    "title": f"Auto-expired {expired_count} stale approvals",
                    "content": (
                        f"Approvals older than {stale_days} days were expired automatically. "
                        f"Breakdown: {dict(stale_kinds)}. "
                        f"Cutoff date: {cutoff.strftime('%Y-%m-%d')}."
                    ),
                    "importance": 4,
                    "tags": ["approval_drain", "stale", "auto_expire"],
                }
            )

        # ── 2. Load remaining pending approvals ────────────────────────────
        remaining_rows = conn.execute(
            "SELECT id, kind, context_json, created_at FROM pending_approvals "
            "WHERE status = 'pending' ORDER BY created_at ASC",
        ).fetchall()

        remaining_count = len(remaining_rows)

        # ── 3. Group by kind ───────────────────────────────────────────────
        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "oldest": None, "examples": []}
        )
        for row in remaining_rows:
            kind = row["kind"]
            groups[kind]["count"] += 1
            if groups[kind]["oldest"] is None:
                groups[kind]["oldest"] = row["created_at"]
            if len(groups[kind]["examples"]) < 2:
                try:
                    ctx = json.loads(row["context_json"] or "{}")
                    title = (
                        ctx.get("subject")
                        or ctx.get("title")
                        or ctx.get("action")
                        or kind
                    )
                    groups[kind]["examples"].append(title[:60])
                except Exception:
                    pass

        # ── 4. Build summary message ───────────────────────────────────────
        summary_parts: list[str] = []
        for kind, info in sorted(groups.items(), key=lambda x: -x[1]["count"]):
            oldest_str = ""
            if info["oldest"]:
                try:
                    dt = datetime.fromisoformat(
                        info["oldest"].replace("Z", "+00:00")
                    )
                    oldest_str = f" (oldest: {dt.strftime('%Y-%m-%d')})"
                except Exception:
                    oldest_str = f" (oldest: {info['oldest'][:10]})"
            examples_str = ""
            if info["examples"]:
                examples_str = " — e.g. " + "; ".join(
                    f'"{e}"' for e in info["examples"]
                )
            part = (
                f"• {info['count']} {kind} approvals pending{oldest_str}{examples_str}"
            )
            summary_parts.append(part)

        header = (
            f"Approval backlog: {remaining_count} pending"
            + (f", {expired_count} auto-expired (>{stale_days}d old)." if expired_count else ".")
        )
        combined_summary = header + "\n" + "\n".join(summary_parts)
        if len(combined_summary) > 1500:
            combined_summary = combined_summary[:1497] + "..."

        # ── 5. Publish digest to Redis ──────────────────────────────────────
        r = _get_redis()
        if r is not None:
            try:
                r.publish(
                    "notifications:approval_digest",
                    json.dumps(
                        {
                            "type": "approval_digest",
                            "summary": combined_summary,
                            "total_pending": remaining_count,
                            "total_expired": expired_count,
                            "groups": {
                                k: {
                                    "count": v["count"],
                                    "oldest": v["oldest"],
                                    "examples": v["examples"],
                                }
                                for k, v in groups.items()
                            },
                        }
                    ),
                )
                logger.info(
                    "approval_digest_published pending=%d expired=%d",
                    remaining_count,
                    expired_count,
                )
            except Exception as exc:
                logger.warning("digest_publish_failed: %s", exc)

            # ── 6. Threshold alert ──────────────────────────────────────────
            if remaining_count > ALERT_THRESHOLD:
                try:
                    r.publish(
                        "notifications:high_priority",
                        json.dumps(
                            {
                                "type": "approval_backlog_alert",
                                "message": (
                                    f"Approval backlog at {remaining_count} items. "
                                    f"Review needed."
                                ),
                                "count": remaining_count,
                            }
                        ),
                    )
                    logger.warning(
                        "approval_backlog_alert count=%d", remaining_count
                    )
                except Exception as exc:
                    logger.warning("alert_publish_failed: %s", exc)

        result = {
            "expired": expired_count,
            "remaining": remaining_count,
            "groups": dict(groups),
            "summary": combined_summary,
        }

        # Always print so it's visible in docker logs / CLI runs.
        print(combined_summary)

        return result

    finally:
        conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    result = asyncio.run(drain_stale_approvals())
    import sys

    print(
        f"\nDone — expired: {result['expired']}, remaining: {result['remaining']}",
        file=sys.stderr,
    )
