#!/usr/bin/env python3
"""
Prompt T — One-shot pending_approvals drain.

Run once on the host:
    python3 scripts/prompt_t_drain.py [--dry-run]

State transitions applied
--------------------------
  pending → skipped   stale rows (>STALE_DAYS old)          reason: stale_auto_expire
  pending → skipped   GENERAL + confidence < threshold       reason: auto_low_value
  pending → skipped   duplicate email_id (keep first only)   reason: duplicate_entry
  pending → approved  Matt replied YES to iMessage batch     (future / interactive use)
  pending → rejected  Matt replied NO  to iMessage batch     (future / interactive use)

Rows already in 'expired' state are never touched.

For each pending_approval that transitions, the linked decisions row is also
updated: decisions.outcome = '<new_status>_by_prompt_t', decisions.outcome_at = now.

Usage
-----
  python3 scripts/prompt_t_drain.py            # live run
  python3 scripts/prompt_t_drain.py --dry-run  # print plan, touch nothing
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

# ── Config ─────────────────────────────────────────────────────────────────────

STALE_DAYS = 7
AUTO_SKIP_CONFIDENCE_THRESHOLD = 50.0   # confidence < this AND classification=GENERAL → skip
NOTIFICATION_HUB_URL = os.environ.get("NOTIFICATION_HUB_URL", "http://localhost:8095")
CORTEX_URL = os.environ.get("CORTEX_URL", "http://localhost:8102")

DB_CANDIDATES = [
    os.environ.get("DECISION_JOURNAL_DB_PATH", ""),
    "/Users/bob/AI-Server/data/openclaw/decision_journal.db",
    "data/openclaw/decision_journal.db",
    "/app/data/decision_journal.db",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s prompt_t %(levelname)s %(message)s",
)
logger = logging.getLogger("prompt_t")


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _find_db() -> str:
    for path in DB_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "decision_journal.db not found. Tried:\n"
        + "\n".join(f"  {p}" for p in DB_CANDIDATES if p)
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_find_db())
    conn.row_factory = sqlite3.Row
    # Ensure WAL mode so concurrent readers (openclaw container) are not blocked.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _http_post(url: str, payload: dict[str, Any], timeout: int = 5) -> bool:
    """POST JSON payload to url. Returns True on 2xx. Never raises."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                logger.warning("http_post non-2xx url=%s status=%d", url, resp.status)
            return ok
    except urllib.error.URLError as exc:
        logger.warning("http_post_failed url=%s error=%s", url, exc)
        return False
    except Exception as exc:
        logger.warning("http_post_error url=%s error=%s", url, exc)
        return False


def _send_imessage(subject: str, message: str) -> bool:
    """Send iMessage via notification-hub /api/send.

    NotificationRequest fields: recipient (required), message, channel, priority.
    Passing recipient='matt' leaves phone resolution to MATT_PHONE_NUMBER env var.
    """
    return _http_post(
        f"{NOTIFICATION_HUB_URL}/api/send",
        {
            "recipient": "matt",
            "message": f"{subject}\n\n{message}",
            "channel": "imessage",
            "priority": "normal",
        },
    )


def _post_cortex(title: str, content: str, tags: list[str] | None = None) -> bool:
    """Log an entry to Cortex memory."""
    return _http_post(
        f"{CORTEX_URL}/remember",
        {
            "category": "system",
            "title": title,
            "content": content,
            "importance": 5,
            "tags": tags or ["prompt_t", "approval_drain"],
        },
    )


# ── Core logic ─────────────────────────────────────────────────────────────────

def _apply_skip(
    conn: sqlite3.Connection,
    row_ids: list[int],
    decision_ids: list[int],
    reason: str,
    now_iso: str,
    dry_run: bool,
) -> int:
    """Update pending_approvals.status → 'skipped' and linked decisions.outcome.

    Returns count of rows affected.
    """
    if not row_ids:
        return 0
    placeholders = ",".join("?" * len(row_ids))
    dec_placeholders = ",".join("?" * len(decision_ids))

    if dry_run:
        logger.info("[DRY-RUN] would skip %d rows reason=%s ids=%s", len(row_ids), reason, row_ids[:5])
        return len(row_ids)

    conn.execute(
        f"UPDATE pending_approvals SET status='skipped' WHERE id IN ({placeholders})",
        row_ids,
    )
    conn.execute(
        f"UPDATE decisions SET outcome=?, outcome_at=? WHERE id IN ({dec_placeholders})",
        [f"skipped_by_prompt_t:{reason}", now_iso] + decision_ids,
    )
    conn.commit()
    logger.info("skipped count=%d reason=%s", len(row_ids), reason)
    return len(row_ids)


def run_drain(dry_run: bool = False) -> dict[str, Any]:
    """Execute the full drain pass. Returns a stats dict."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff_stale = (now - timedelta(days=STALE_DAYS)).isoformat()

    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "ran_at": now_iso,
        "stale_skipped": 0,
        "auto_low_value_skipped": 0,
        "duplicate_skipped": 0,
        "batched_to_matt": 0,
        "remaining_pending": 0,
        "already_expired": 0,
        "total_before": 0,
        "total_after": 0,
        "imessage_sent": False,
        "cortex_logged": False,
    }

    conn = _connect()
    try:
        # ── Baseline counts ─────────────────────────────────────────────────
        stats["total_before"] = conn.execute(
            "SELECT COUNT(*) FROM pending_approvals"
        ).fetchone()[0]
        stats["already_expired"] = conn.execute(
            "SELECT COUNT(*) FROM pending_approvals WHERE status='expired'"
        ).fetchone()[0]

        # ── Phase 1: Stale expiry (>STALE_DAYS) ───────────────────────────
        stale_rows = conn.execute(
            "SELECT id, decision_id FROM pending_approvals "
            "WHERE status='pending' AND created_at < ?",
            (cutoff_stale,),
        ).fetchall()
        stale_ids = [r["id"] for r in stale_rows]
        stale_dec_ids = [r["decision_id"] for r in stale_rows]
        stats["stale_skipped"] = _apply_skip(
            conn, stale_ids, stale_dec_ids, "stale_auto_expire", now_iso, dry_run
        )

        # ── Phase 2: Load remaining pending rows ───────────────────────────
        pending_rows = conn.execute(
            "SELECT id, decision_id, kind, context_json, created_at "
            "FROM pending_approvals WHERE status='pending' ORDER BY id ASC"
        ).fetchall()

        # ── Phase 3: Classify each pending row ────────────────────────────
        # Track first-seen email_id to detect duplicates.
        seen_email_ids: dict[int, int] = {}   # email_id → first pending_approval.id

        low_value_ids: list[int] = []
        low_value_dec_ids: list[int] = []
        duplicate_ids: list[int] = []
        duplicate_dec_ids: list[int] = []
        batch_rows: list[dict[str, Any]] = []   # rows that need Matt's review

        for row in pending_rows:
            pa_id = row["id"]
            dec_id = row["decision_id"]
            kind = row["kind"]
            try:
                ctx = json.loads(row["context_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                ctx = {}

            classification = ctx.get("classification", "")
            confidence = float(ctx.get("confidence", 100.0))
            email_id = ctx.get("email_id")

            # Duplicate detection: only the first occurrence of an email_id is kept.
            if email_id is not None:
                if email_id in seen_email_ids:
                    duplicate_ids.append(pa_id)
                    duplicate_dec_ids.append(dec_id)
                    continue
                seen_email_ids[email_id] = pa_id

            # Auto-skip: GENERAL + low confidence.
            if kind == "email_classification" and classification == "GENERAL" and confidence < AUTO_SKIP_CONFIDENCE_THRESHOLD:
                low_value_ids.append(pa_id)
                low_value_dec_ids.append(dec_id)
                continue

            # Anything else stays for Matt's review.
            batch_rows.append({
                "id": pa_id,
                "decision_id": dec_id,
                "kind": kind,
                "ctx": ctx,
                "created_at": row["created_at"],
            })

        # ── Phase 4: Apply duplicate skips ────────────────────────────────
        stats["duplicate_skipped"] = _apply_skip(
            conn, duplicate_ids, duplicate_dec_ids, "duplicate_entry", now_iso, dry_run
        )

        # ── Phase 5: Apply low-value auto-skips ───────────────────────────
        stats["auto_low_value_skipped"] = _apply_skip(
            conn, low_value_ids, low_value_dec_ids, "auto_low_value", now_iso, dry_run
        )

        # ── Phase 6: Batch remaining rows to Matt via iMessage ─────────────
        stats["batched_to_matt"] = len(batch_rows)
        if batch_rows:
            # Group by kind for a compact digest.
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in batch_rows:
                groups[r["kind"]].append(r)

            lines = ["⚠️ Approval Backlog — Matt review needed:", ""]
            for kind, items in sorted(groups.items()):
                lines.append(f"[{kind}] — {len(items)} item(s):")
                for item in items[:5]:
                    ctx = item["ctx"]
                    label = (
                        ctx.get("subject")
                        or ctx.get("title")
                        or ctx.get("action")
                        or kind
                    )
                    conf = ctx.get("confidence", "?")
                    cls_ = ctx.get("classification", "")
                    lines.append(f"  • {label[:60]} [{cls_} {conf}%]")
                if len(items) > 5:
                    lines.append(f"  … and {len(items) - 5} more")
                lines.append("")
            lines.append("Reply YES <id> or NO <id> to act on specific items.")
            batch_msg = "\n".join(lines)

            if not dry_run:
                ok = _send_imessage("Approval Batch — Prompt T", batch_msg)
                if ok:
                    logger.info("batch_imessage_sent count=%d", len(batch_rows))
                else:
                    logger.warning("batch_imessage_failed — Matt must review manually")
            else:
                logger.info("[DRY-RUN] would send iMessage with %d items", len(batch_rows))

        # ── Phase 7: Re-count after changes ───────────────────────────────
        stats["remaining_pending"] = conn.execute(
            "SELECT COUNT(*) FROM pending_approvals WHERE status='pending'"
        ).fetchone()[0]
        stats["total_after"] = conn.execute(
            "SELECT COUNT(*) FROM pending_approvals"
        ).fetchone()[0]

    finally:
        conn.close()

    # ── Phase 8: Summary iMessage to Matt ─────────────────────────────────
    total_drained = (
        stats["stale_skipped"]
        + stats["auto_low_value_skipped"]
        + stats["duplicate_skipped"]
    )
    summary_lines = [
        "✅ Prompt T drain complete.",
        "",
        f"Stale (>{STALE_DAYS}d) → skipped:   {stats['stale_skipped']}",
        f"Auto low-value → skipped:      {stats['auto_low_value_skipped']}",
        f"Duplicate entries → skipped:   {stats['duplicate_skipped']}",
        f"Batched to Matt (YES/NO):      {stats['batched_to_matt']}",
        f"Already-expired (untouched):   {stats['already_expired']}",
        "",
        f"Total drained this run:        {total_drained}",
        f"Remaining pending:             {stats['remaining_pending']}",
        "",
        "decision_journal.db is clean." if stats["remaining_pending"] == 0
        else f"⚠️  {stats['remaining_pending']} item(s) still pending — see batch above.",
    ]
    summary = "\n".join(summary_lines)

    print("\n" + summary)

    if not dry_run:
        ok = _send_imessage("Prompt T Drain — Summary", summary)
        stats["imessage_sent"] = ok

        cortex_content = (
            f"Prompt T one-shot drain ran at {now_iso}. "
            f"Stale-skipped: {stats['stale_skipped']}. "
            f"Auto-low-value-skipped: {stats['auto_low_value_skipped']}. "
            f"Duplicate-skipped: {stats['duplicate_skipped']}. "
            f"Batched-to-Matt: {stats['batched_to_matt']}. "
            f"Remaining pending after drain: {stats['remaining_pending']}. "
            f"Already-expired rows (untouched): {stats['already_expired']}. "
            f"DB: {_find_db()}."
        )
        ok2 = _post_cortex(
            title=f"Approval drain: {total_drained} items processed",
            content=cortex_content,
            tags=["prompt_t", "approval_drain", "decision_journal"],
        )
        stats["cortex_logged"] = ok2
    else:
        logger.info("[DRY-RUN] skipping iMessage + Cortex writes")

    return stats


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt T — one-shot pending_approvals drain")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; touch nothing")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY-RUN MODE — no DB writes, no notifications ===\n")

    try:
        stats = run_drain(dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nStats: {json.dumps(stats, indent=2)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
