#!/usr/bin/env python3
"""
Auto-triage pending client intelligence threads.

Classifies is_reviewed=-1 threads into triage buckets without changing
is_reviewed or creating profiles. Human approval is still required before
any thread becomes an approved profile source.

Usage:
    python3 scripts/auto_triage_client_threads.py                   # dry-run, live chat.db
    python3 scripts/auto_triage_client_threads.py --apply
    python3 scripts/auto_triage_client_threads.py --summary
    python3 scripts/auto_triage_client_threads.py --bucket high_value
    python3 scripts/auto_triage_client_threads.py --limit 500 --verbose
    python3 scripts/auto_triage_client_threads.py --chat-db data/client_intel/chatdb_snapshot/chat.db --apply

Triage buckets:
    high_value       Named contacts or strong smart_home signals
    ambiguous        GC suffix, restaurant_work, builder, mixed signals
    low_priority     Unnamed + weak/no tech signals, few messages
    hidden_personal  category == personal

Safety rules enforced:
    - is_reviewed is NEVER modified
    - No profiles are auto-created or auto-approved
    - No messages are sent
    - Phone numbers are masked in all output / logs
    - Personal threads are isolated (hidden_personal bucket only)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.review_client_threads as _rct

DB_PATH          = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"
_SNAPSHOT_DIR    = REPO_ROOT / "data" / "client_intel" / "chatdb_snapshot"
_LIVE_CHAT_DB    = Path.home() / "Library" / "Messages" / "chat.db"
_TRIAGE_STATS_PATH = REPO_ROOT / "data" / "client_intel" / "triage_stats.json"

TRIAGE_BUCKETS = frozenset({"high_value", "ambiguous", "low_priority", "hidden_personal"})

_TRIAGE_COLS = [
    ("triage_bucket",                "TEXT"),
    ("triage_reason",                "TEXT"),
    ("triage_confidence",            "REAL"),
    ("review_value_score",           "REAL"),
    ("review_reason_summary",        "TEXT"),
    ("review_next_action",           "TEXT"),
    ("evidence_categories",          "TEXT DEFAULT '[]'"),
    ("matched_terms",                "TEXT DEFAULT '[]'"),
    # Project context linking (v1)
    ("project_hint",                 "TEXT DEFAULT ''"),
    ("project_confidence",           "REAL DEFAULT 0.0"),
    ("repeat_contact",               "INTEGER DEFAULT 0"),
    ("previous_thread_count",        "INTEGER DEFAULT 0"),
    ("last_interaction_date",        "TEXT DEFAULT ''"),
    ("known_relationship",           "TEXT DEFAULT ''"),
    ("triage_suggested_relationship","TEXT"),
    ("triage_inferred_domain",       "TEXT"),
    ("triage_risk_flags",            "TEXT DEFAULT '[]'"),
    ("triage_contact_display",       "TEXT"),
    ("triage_debug",                 "TEXT"),
    ("triaged_at",                   "TEXT"),
]


# ── Schema migration (idempotent) ─────────────────────────────────────────────

def _ensure_triage_columns(conn: sqlite3.Connection) -> None:
    """Add triage columns to threads table if not already present."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
    for col, dtype in _TRIAGE_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE threads ADD COLUMN {col} {dtype}")
    conn.commit()


# ── Snapshot helpers ─────────────────────────────────────────────────────────

def _auto_snapshot() -> "Path | None":
    """Copy live chat.db + WAL/SHM into the snapshot dir.

    Returns the snapshot chat.db path, or None if the copy fails.
    Messages.app does not need to be closed — the copy succeeds even with an
    open write lock because macOS allows concurrent file reads.
    """
    try:
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        dest = _SNAPSHOT_DIR / "chat.db"
        shutil.copy2(str(_LIVE_CHAT_DB), str(dest))
        for ext in ("-wal", "-shm"):
            src = Path(str(_LIVE_CHAT_DB) + ext)
            if src.exists():
                shutil.copy2(str(src), str(_SNAPSHOT_DIR / f"chat.db{ext}"))
        print(f"  [snapshot] Copied chat.db → {dest}")
        return dest
    except Exception as exc:
        print(f"  [snapshot] WARNING: auto-snapshot failed: {exc}")
        print("  [snapshot] Falling back to live chat.db")
        return None


def _snapshot_diagnostics(chat_db_path: Path) -> dict[str, Any]:
    """Return health metrics for the snapshot: message counts and decode coverage."""
    try:
        conn = sqlite3.connect(
            f"file:{chat_db_path}?mode=ro&immutable=1", uri=True
        )
        total = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        text_count = conn.execute(
            "SELECT COUNT(*) FROM message WHERE text IS NOT NULL AND text != ''"
        ).fetchone()[0]
        attr_count = conn.execute(
            "SELECT COUNT(*) FROM message WHERE attributedBody IS NOT NULL"
        ).fetchone()[0]
        sample_rows = conn.execute(
            "SELECT text, attributedBody FROM message WHERE date > 0 LIMIT 100"
        ).fetchall()
        conn.close()
        readable = 0
        for row in sample_rows:
            t = (row[0] or "").strip()
            if not t and row[1]:
                t = _rct._decode_attr_body(row[1])
            if t:
                readable += 1
        coverage_ok = len(sample_rows) == 0 or readable >= len(sample_rows) * 0.5
        diag: dict[str, Any] = {
            "total_messages":           total,
            "text_messages":            text_count,
            "attributed_body_messages": attr_count,
            "readable_sample":          readable,
            "readable_sample_of":       len(sample_rows),
            "coverage_ok":              coverage_ok,
        }
        if not coverage_ok:
            print(
                f"  [snapshot] WARNING: low decode coverage "
                f"({readable}/{len(sample_rows)} readable) — results may be incomplete"
            )
        return diag
    except Exception as exc:
        return {"error": str(exc)[:200]}


# ── Review value scoring (separate from bucket confidence) ───────────────────

def _compute_review_value_score(
    name: str,
    work_confidence: float,
    message_count: int,
    assist: dict[str, Any],
    project_ctx: "dict[str, Any] | None" = None,
) -> float:
    """Estimate how valuable it is for Matt to review this thread (0.0–1.0).

    Distinct from triage_confidence (certainty of bucket assignment).
    Higher = worth Matt's time sooner.
    project_ctx — optional dict from _build_project_context(); boosts score
    for repeat contacts, known relationships, and project-linked threads.
    """
    scores      = assist.get("_scores", {})
    tech_s      = scores.get("tech", 0)
    smart_home  = scores.get("smart_home", 0)
    service     = scores.get("service", 0)
    project     = scores.get("project", 0)
    quote       = scores.get("quote", 0)
    symphony    = scores.get("symphony", 0)
    assist_conf = assist.get("confidence", 0.0)

    score = 0.0
    if name:
        score += 0.35
    if symphony:
        score += 0.20
    score += min(smart_home * 0.07, 0.21)
    score += min(service * 0.04, 0.12)
    score += min(project * 0.05, 0.10)
    score += min(quote * 0.08, 0.08)
    score += min(message_count / 100.0, 0.20)
    score += work_confidence * 0.08
    if tech_s >= 1:
        score += min(assist_conf * 0.10, 0.08)

    # Project context bonuses
    if project_ctx:
        if project_ctx.get("known_relationship"):
            score += 0.15   # approved profile match — highest signal
        elif project_ctx.get("repeat_contact"):
            score += 0.08   # named + active history
        if project_ctx.get("project_confidence", 0.0) >= 0.70:
            score += 0.06   # strong location/address match
        elif project_ctx.get("project_confidence", 0.0) >= 0.35:
            score += 0.03   # weak project reference
    return round(min(score, 1.0), 3)


def _categorize_evidence(
    name: str,
    scores: dict[str, int],
    message_count: int,
    date_last: str,
    project_ctx: "dict[str, Any] | None" = None,
) -> list[str]:
    """Return list of evidence category tags for this thread."""
    from datetime import datetime as _dt
    cats: list[str] = []
    if name:
        cats.append("saved_contact")
    if scores.get("symphony", 0) >= 1:
        cats.append("symphony_intro")
    if scores.get("smart_home", 0) >= 1:
        cats.append("smart_home_terms")
    if scores.get("service", 0) >= 1:
        cats.append("service_terms")
    if scores.get("project", 0) >= 1:
        cats.append("project_terms")
    if scores.get("quote", 0) >= 1:
        cats.append("quote_proposal_terms")
    if scores.get("scheduling", 0) >= 1:
        cats.append("scheduling_terms")
    if scores.get("vendor", 0) >= 1:
        cats.append("vendor_terms")
    if scores.get("builder", 0) >= 1:
        cats.append("builder_terms")
    if scores.get("restaurant", 0) >= 1:
        cats.append("restaurant_terms")
    if message_count >= 50:
        cats.append("high_message_count")
    try:
        year = int((date_last or "")[:4])
        if year < 2023:
            cats.append("stale_thread")
    except (ValueError, TypeError):
        pass
    try:
        last_dt = _dt.fromisoformat(date_last[:10]) if date_last and len(date_last) >= 10 else None
        if last_dt and (_dt.now() - last_dt).days <= 90:
            cats.append("recent_activity")
    except Exception:
        pass
    # Project context categories
    if project_ctx:
        if project_ctx.get("known_relationship"):
            cats.append("known_client")
        elif project_ctx.get("repeat_contact"):
            cats.append("repeat_contact")
        if project_ctx.get("project_hint"):
            cats.append("project_location_hint")
    return cats


def _build_review_reason_summary(
    name: str,
    bucket: str,
    scores: dict[str, int],
    message_count: int,
    evidence_categories: list[str],
    assist: dict[str, Any],
    project_ctx: "dict[str, Any] | None" = None,
) -> str:
    """One human-readable sentence explaining why this thread landed in this bucket."""
    risk_flags = assist.get("risk_flags", [])
    gc = "gc_suffix_ambiguous" in risk_flags
    ev = assist.get("evidence", [])

    # Extract top matched terms from evidence strings
    def _ev_terms(prefix: str) -> str:
        for e in ev:
            if e.startswith(prefix + ":"):
                return e.split(":", 1)[1].strip()
        return ""

    # Who
    if name:
        who = f"GC contact {name!r}" if gc else f"Saved contact {name!r}"
    else:
        who = "Unnamed contact"

    # Signals
    signal_parts: list[str] = []
    if "symphony_intro" in evidence_categories:
        signal_parts.append("Symphony intro language")
    sh_terms = _ev_terms("smart_home_terms")
    svc_terms = _ev_terms("service_terms")
    proj_terms = _ev_terms("project_terms")
    quote_terms = _ev_terms("quote_proposal_terms")
    rest_terms = _ev_terms("restaurant_terms")
    build_terms = _ev_terms("builder_terms")

    if sh_terms:
        signal_parts.append(sh_terms)
    elif svc_terms:
        signal_parts.append(svc_terms)
    if proj_terms and "project_terms" in evidence_categories:
        signal_parts.append(proj_terms)
    if quote_terms:
        signal_parts.append("proposal/quote terms")
    if "scheduling_terms" in evidence_categories:
        signal_parts.append("scheduling signals")
    if rest_terms and "restaurant_terms" in evidence_categories:
        signal_parts.append(f"restaurant signals ({rest_terms})")
    if build_terms and "builder_terms" in evidence_categories and "restaurant_terms" not in evidence_categories:
        signal_parts.append("builder signals")

    msg_str = f"{message_count} message{'s' if message_count != 1 else ''}"

    if signal_parts:
        sig_str = "/".join(signal_parts[:2])
        if len(signal_parts) > 2:
            sig_str += f" +{len(signal_parts) - 2} more"
        body = f"{who} with {sig_str} and {msg_str}"
    else:
        body = f"{who} with {msg_str} and no strong work signals"

    # Project context prefix
    if project_ctx:
        known_rel = project_ctx.get("known_relationship", "")
        hint = project_ctx.get("project_hint", "")
        repeat = project_ctx.get("repeat_contact", False)
        if known_rel:
            body = f"[existing {known_rel}] {body}"
        elif repeat:
            body = f"[active contact] {body}"
        if hint:
            body += f" (project: {hint})"

    # Tail
    if bucket == "high_value":
        if "known_client" in evidence_categories:
            rel = (project_ctx or {}).get("known_relationship", "contact")
            tail = f"— known {rel}, likely repeat work."
        elif "symphony_intro" in evidence_categories:
            tail = "— Symphony client context."
        elif "quote_proposal_terms" in evidence_categories:
            tail = "— proposal/project context, likely smart-home work."
        elif "smart_home_terms" in evidence_categories or "service_terms" in evidence_categories:
            tail = "— likely smart-home work."
        elif name:
            tail = "— saved contact, worth reviewing."
        else:
            tail = "— strong work signals."
    elif bucket == "ambiguous":
        if gc and "restaurant_terms" in evidence_categories:
            tail = "— GC+restaurant, verify Game Creek venue vs contractor."
        elif gc:
            tail = "— GC suffix ambiguous, verify Game Creek vs General Contractor."
        elif "restaurant_terms" in evidence_categories and scores.get("tech", 0) >= 1:
            tail = "— restaurant+tech mix, verify AV client vs venue contact."
        elif "builder_terms" in evidence_categories:
            tail = "— builder/AV role unclear, review manually."
        elif name:
            tail = "— saved contact with weak signals, verify work relationship."
        else:
            tail = "— review manually."
    else:  # low_priority
        if "restaurant_terms" in evidence_categories and scores.get("tech", 0) == 0:
            tail = "— restaurant-only signals, likely not an AV client."
        elif not name and message_count < 5:
            tail = "— unnamed one-off, defer unless recognized."
        elif "stale_thread" in evidence_categories:
            tail = "— stale thread, low priority."
        else:
            tail = "— low priority, no meaningful work signals."

    return f"{body} {tail}"


def _build_review_next_action(
    bucket: str,
    name: str,
    scores: dict[str, int],
    evidence_categories: list[str],
    assist: dict[str, Any],
    project_ctx: "dict[str, Any] | None" = None,
) -> str:
    """Suggested next action for Matt when reviewing this thread."""
    risk_flags = assist.get("risk_flags", [])
    gc = "gc_suffix_ambiguous" in risk_flags
    rel = assist.get("suggested_relationship_type", "unknown")

    if bucket == "high_value":
        if "known_client" in evidence_categories and project_ctx:
            known_rel = project_ctx.get("known_relationship", "contact")
            hint = project_ctx.get("project_hint", "")
            suffix = f" ({hint})" if hint else ""
            return f"Review as existing {known_rel}{suffix} — likely repeat work, approve relationship type."
        if "repeat_contact" in evidence_categories:
            return "Review as active contact — saved + substantial history, likely ongoing work relationship."
        if "symphony_intro" in evidence_categories:
            return "Review and approve as client — Symphony intro language detected."
        if scores.get("smart_home", 0) >= 2 or scores.get("tech", 0) >= 3:
            return f"Review and likely approve as {rel} — strong smart-home signals."
        if "quote_proposal_terms" in evidence_categories:
            return "Review and likely approve as client — proposal/quote context detected."
        if name:
            return f"Review and likely approve as {rel} or trade partner."
        return "Review and approve if smart-home work context is confirmed."

    elif bucket == "ambiguous":
        if gc and "restaurant_terms" in evidence_categories:
            return "Review manually — GC suffix + restaurant signals; confirm if Game Creek (venue) or AV client."
        if gc:
            return "Review manually — GC suffix is ambiguous; confirm Game Creek vs General Contractor."
        if "restaurant_terms" in evidence_categories and scores.get("tech", 0) >= 1:
            return "Review manually — restaurant and tech signals conflict; verify AV client vs venue contact."
        if "builder_terms" in evidence_categories:
            return "Review manually — could be builder coordinating AV work or an AV client in build phase."
        if name:
            return "Review manually — saved contact with weak signals; verify work relationship."
        return "Defer unless you recognize the number."

    else:  # low_priority
        if "restaurant_terms" in evidence_categories and scores.get("tech", 0) == 0:
            return "Likely restaurant/personal-work context; do not extract smart-home profile unless confirmed."
        if "stale_thread" in evidence_categories:
            return "Defer — stale thread with no recent activity."
        return "Defer unless you recognize the number."


# ── Project context linking ───────────────────────────────────────────────────

def _build_project_context(
    conn: sqlite3.Connection,
    handle: str,
    name: str,
    message_count: int,
    date_last: str,
    texts: list[str],
) -> dict[str, Any]:
    """Build project context and repeat-contact signals for one thread.

    Looks up:
    - Whether any approved profile shares the same normalized phone
    - Whether the contact is named (in AddressBook)
    - Project/location hints in message texts
    - Message-count-based activity classification

    Returns dict: project_hint, project_confidence, repeat_contact,
                  previous_thread_count, last_interaction_date, known_relationship.

    Pure from a triage safety POV — never modifies is_reviewed or creates profiles.
    """
    norm_handle = _rct._norm_phone(handle) if handle else ""

    # Check approved profiles for the same normalized phone
    known_relationship = ""
    previous_thread_count = 0
    if norm_handle:
        try:
            approved_rows = conn.execute(
                "SELECT contact_handle, relationship_type FROM threads WHERE is_reviewed = 1"
            ).fetchall()
            for ar in approved_rows:
                if _rct._norm_phone(ar["contact_handle"] or "") == norm_handle:
                    known_relationship = ar["relationship_type"] or ""
                    previous_thread_count += 1
        except Exception:
            pass

    # repeat_contact: approved match OR named + substantial history
    is_named = bool(name)
    repeat_contact = (
        bool(known_relationship)
        or (is_named and message_count >= 20)
    )

    # Project/location hint from message texts
    project_hint, project_confidence = _rct._extract_project_hints(texts)

    return {
        "project_hint":         project_hint,
        "project_confidence":   project_confidence,
        "repeat_contact":       int(repeat_contact),
        "previous_thread_count": previous_thread_count,
        "last_interaction_date": (date_last or "")[:10],
        "known_relationship":   known_relationship,
    }


# ── Bucket determination (pure, no I/O) ──────────────────────────────────────

def _determine_triage_bucket(
    category: str,
    work_confidence: float,
    message_count: int,
    date_last: str,
    name: str,
    assist: dict[str, Any],
    readable_message_count: int = 0,
) -> tuple[str, str, float]:
    """Return (bucket, reason, triage_confidence).

    Priority waterfall:
      hidden_personal → GC handling → named contact → strong signals
      → builder/restaurant/mixed conflicts → old/large ambiguous threads
      → low priority (default for uncategorized threads).

    Pure function — never touches the database or makes network calls.
    """
    risk_flags   = assist.get("risk_flags", [])
    assist_conf  = assist.get("confidence", 0.0)
    domain       = assist.get("inferred_domain", "smart_home_work")
    scores       = assist.get("_scores", {})
    tech_s       = scores.get("tech", 0)
    restaurant_s = scores.get("restaurant", 0)
    builder_s    = scores.get("builder", 0)
    smart_home_s = scores.get("smart_home", 0)
    service_s    = scores.get("service", 0)
    project_s    = scores.get("project", 0)
    quote_s      = scores.get("quote", 0)
    symphony_s   = scores.get("symphony", 0)

    # 1. Personal threads always hidden
    if category == "personal":
        return (
            "hidden_personal",
            "personal category — excluded from client profiles",
            0.95,
        )

    # 2. GC suffix — check signals before routing; 'GC' in Eagle County often = Game Creek
    if "gc_suffix_ambiguous" in risk_flags:
        if tech_s >= 3:
            return (
                "high_value",
                f"GC-suffix contact with strong smart-home signals (tech={tech_s}) — verify GC meaning",
                min(0.55 + 0.04 * tech_s, 0.78),
            )
        if tech_s >= 1 and restaurant_s == 0:
            return (
                "ambiguous",
                f"GC suffix + tech signals (tech={tech_s}) — verify if Game Creek or General Contractor",
                0.65,
            )
        if restaurant_s >= 1:
            return (
                "ambiguous",
                f"GC suffix + restaurant signals (rest={restaurant_s}) — likely Game Creek venue contact",
                0.70,
            )
        return (
            "ambiguous",
            "GC suffix with no clear signals — manual review required to determine GC meaning",
            0.75,
        )

    # 3. Named contact — always worth Matt's time; signals raise priority further
    if name:
        # 3a. Any tech/smart-home/service/quote signal → high_value
        if tech_s >= 1 or smart_home_s >= 1 or service_s >= 1 or quote_s >= 1:
            conf = max(assist_conf, 0.55 + 0.04 * min(tech_s, 5))
            return (
                "high_value",
                f"named contact with work signals (tech={tech_s}, smart_home={smart_home_s}, confidence={assist_conf:.0%})",
                min(conf, 0.90),
            )
        # 3b. High classifier + strong assist confidence
        if assist_conf >= 0.50:
            return (
                "high_value",
                f"named contact with strong signals (confidence={assist_conf:.0%})",
                max(assist_conf, 0.60),
            )
        # 3c. High work confidence from classifier + active thread
        if work_confidence >= 0.75 and message_count >= 5:
            return (
                "high_value",
                f"named contact with high work confidence ({work_confidence:.0%}) and {message_count} messages",
                max(work_confidence, 0.62),
            )
        # 3d. Active thread — named contact with substantial history
        if message_count >= 15 and work_confidence >= 0.50:
            return (
                "high_value",
                f"named contact with active thread ({message_count} messages) — worth reviewing",
                0.58,
            )
        # 3e. Weak work evidence — route to ambiguous, not low_priority
        if work_confidence < 0.40 or (message_count < 3 and assist_conf < 0.30):
            return (
                "ambiguous",
                "named contact with weak work signals — may be personal or one-off",
                0.52,
            )
        # 3f. Default for named contacts: high_value (worth review, but unclear signals)
        return (
            "high_value",
            f"named contact — potential client or trade partner relationship",
            max(assist_conf, 0.50),
        )

    # 3.5: Symphony intro language anywhere → always high_value
    if symphony_s >= 1:
        return (
            "high_value",
            "Symphony Smart Homes intro language detected — very strong client signal",
            0.92,
        )

    # 4. Strong AV/smart-home signals regardless of name
    if smart_home_s >= 2 or (tech_s >= 3) or (assist_conf >= 0.70 and tech_s >= 1):
        return (
            "high_value",
            f"strong smart-home signals (tech={tech_s}, smart_home={smart_home_s}, confidence={assist_conf:.0%})",
            max(assist_conf, 0.65),
        )

    # 4.5: Proposal/bid/estimate + install/prewire/project terms → high_value
    if quote_s >= 1 and (service_s >= 1 or project_s >= 1 or tech_s >= 1):
        return (
            "high_value",
            f"proposal/quote context with work signals — likely active project",
            0.72,
        )

    # 5. Moderate tech signals + substantial thread (likely important unnamed contact)
    if (tech_s >= 2 or smart_home_s >= 1) and message_count >= 10 and restaurant_s < 2:
        return (
            "high_value",
            f"moderate tech/smart-home signals (tech={tech_s}, smart_home={smart_home_s}) in substantial thread ({message_count} msgs)",
            max(assist_conf, 0.60),
        )

    # 6. Large active work thread with any tech signal
    if message_count >= 100 and category == "work" and tech_s >= 1:
        return (
            "high_value",
            f"large work thread ({message_count} msgs) with tech signals — likely important contact",
            max(assist_conf, 0.58),
        )

    # 7. Builder domain or tech+builder mix → ambiguous (verify AV client vs contractor)
    if domain == "builder_coordination" or (tech_s >= 1 and builder_s >= 1):
        return (
            "ambiguous",
            f"tech + builder signals — builder coordinating AV work or AV client in build phase",
            0.60,
        )

    # 8. Restaurant domain — verify AV client vs venue contact
    if domain == "restaurant_work" or restaurant_s >= 2:
        return (
            "ambiguous",
            f"restaurant signals ({restaurant_s}) — verify if AV client at venue or restaurant contact",
            0.60,
        )

    # 9. Mixed category with any substance → ambiguous
    if category == "mixed":
        if work_confidence >= 0.50 or message_count >= 10 or assist_conf >= 0.30:
            return (
                "ambiguous",
                "mixed work/personal signals — manual review needed",
                0.58,
            )

    # 10. Old thread with detectable signals → may be stale relationship
    try:
        year = int((date_last or "")[:4])
        if year < 2022 and assist_conf >= 0.30:
            dl = (date_last or "")[:10]
            return (
                "ambiguous",
                f"older thread (last active: {dl}) with work signals — may be stale relationship",
                0.52,
            )
    except (ValueError, TypeError):
        pass

    # 11. Large work thread with no clear signals but high classifier confidence
    if message_count >= 50 and category == "work" and work_confidence >= 0.70:
        return (
            "ambiguous",
            f"large active work thread ({message_count} msgs) — worth reviewing despite weak signals",
            0.52,
        )

    # 12. Low priority: unnamed + weak/no work evidence
    # Restaurant-only + unnamed → low_priority (not ambiguous)
    if restaurant_s >= 1 and tech_s == 0 and smart_home_s == 0 and not name:
        return (
            "low_priority",
            f"restaurant signals only (no tech/smart-home terms) — not an AV client",
            0.78,
        )
    if work_confidence < 0.45:
        return (
            "low_priority",
            f"low work confidence ({work_confidence:.0%}) — likely not a client contact",
            0.80,
        )
    if message_count < 5:
        return (
            "low_priority",
            f"unnamed contact with few messages ({message_count}) — likely one-off",
            0.80,
        )
    if tech_s == 0 and restaurant_s == 0 and builder_s == 0:
        return (
            "low_priority",
            "no work signals detected in message texts",
            0.75,
        )
    if assist_conf < 0.35:
        return (
            "low_priority",
            f"weak classification signals (confidence={assist_conf:.0%}) — insufficient for useful triage",
            0.72,
        )

    # 13. Default: low_priority (ambiguous should mean actual conflicts, not uncertainty)
    return (
        "low_priority",
        "insufficient signals for reliable classification",
        0.68,
    )


# ── Triage runner ─────────────────────────────────────────────────────────────

def run_triage(
    conn: sqlite3.Connection,
    limit: int = 500,
    dry_run: bool = True,
    bucket_filter: "str | None" = None,
    chat_db_path: "Path | None" = None,
    snapshot_diagnostics: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Classify pending threads into triage buckets.

    Only processes is_reviewed=-1 threads.
    is_reviewed is never modified.
    Returns {dry_run, processed, counts, results, snapshot_used}.

    chat_db_path — when provided, read message texts from this SQLite file
    instead of the live ~/Library/Messages/chat.db. Useful when Messages.app
    holds a write lock on the live DB. WAL/SHM files alongside the snapshot
    are handled transparently by SQLite.
    snapshot_diagnostics — pre-computed diagnostics dict from _snapshot_diagnostics();
    included in the return value and written to triage_stats.json.
    """
    _ensure_triage_columns(conn)

    # Temporarily redirect _fetch_sample_texts to the snapshot if provided.
    _orig_chat_db = _rct.CHAT_DB
    if chat_db_path is not None:
        _rct.CHAT_DB = Path(chat_db_path)

    rows = conn.execute(
        "SELECT thread_id, chat_guid, contact_handle, message_count, "
        "date_first, date_last, category, work_confidence, reason_codes "
        "FROM threads WHERE is_reviewed = -1 "
        "ORDER BY work_confidence DESC, message_count DESC "
        "LIMIT ?",
        (limit,),
    ).fetchall()

    now_iso = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {b: 0 for b in TRIAGE_BUCKETS}
    results: list[dict[str, Any]] = []

    try:
        for r in rows:
            handle = r["contact_handle"]
            name   = _rct._lookup_contact_name(handle)
            codes  = json.loads(r["reason_codes"] or "[]")
            texts  = _rct._fetch_sample_texts(r["chat_guid"])
            assist = _rct.analyze_thread_assist(name, texts, codes)

            readable_count = len(texts)
            bucket, reason, triage_conf = _determine_triage_bucket(
                category              = r["category"],
                work_confidence       = r["work_confidence"],
                message_count         = r["message_count"],
                date_last             = r["date_last"] or "",
                name                  = name,
                assist                = assist,
                readable_message_count= readable_count,
            )

            if bucket_filter and bucket != bucket_filter:
                continue

            counts[bucket] += 1
            contact_display = name if name else _rct._mask(handle)

            # Project context: repeat contact detection + location/project hint
            proj_ctx = _build_project_context(
                conn          = conn,
                handle        = handle,
                name          = name,
                message_count = r["message_count"],
                date_last     = r["date_last"] or "",
                texts         = texts,
            )

            review_value = _compute_review_value_score(
                name            = name,
                work_confidence = r["work_confidence"],
                message_count   = r["message_count"],
                assist          = assist,
                project_ctx     = proj_ctx,
            )
            ev_cats = _categorize_evidence(
                name=name,
                scores=assist.get("_scores", {}),
                message_count=r["message_count"],
                date_last=r["date_last"] or "",
                project_ctx=proj_ctx,
            )
            reason_summary = _build_review_reason_summary(
                name=name,
                bucket=bucket,
                scores=assist.get("_scores", {}),
                message_count=r["message_count"],
                evidence_categories=ev_cats,
                assist=assist,
                project_ctx=proj_ctx,
            )
            next_action = _build_review_next_action(
                bucket=bucket,
                name=name,
                scores=assist.get("_scores", {}),
                evidence_categories=ev_cats,
                assist=assist,
                project_ctx=proj_ctx,
            )
            # Build flat matched_terms list
            all_ev = assist.get("evidence", [])
            matched_terms: list[str] = []
            for e in all_ev:
                if ":" in e:
                    matched_terms.extend(t.strip() for t in e.split(":", 1)[1].split(","))
            matched_terms = matched_terms[:10]

            triage_debug = json.dumps({
                "scores":                assist.get("_scores", {}),
                "evidence":              assist.get("evidence", []),
                "evidence_categories":   ev_cats,
                "contact_name_found":    bool(name),
                "readable_message_count":readable_count,
                "inferred_domain":       assist["inferred_domain"],
                "risk_flags":            assist["risk_flags"],
                "review_reason":         assist.get("review_reason", ""),
                "review_value_score":    review_value,
                "review_reason_summary": reason_summary,
                "review_next_action":    next_action,
                "matched_terms":         matched_terms,
                "project_hint":          proj_ctx["project_hint"],
                "project_confidence":    proj_ctx["project_confidence"],
                "repeat_contact":        proj_ctx["repeat_contact"],
                "known_relationship":    proj_ctx["known_relationship"],
            })
            entry: dict[str, Any] = {
                "thread_id":                     r["thread_id"],
                "contact_masked":                _rct._mask(handle),
                "triage_bucket":                 bucket,
                "triage_reason":                 reason,
                "triage_confidence":             round(triage_conf, 3),
                "review_value_score":            review_value,
                "review_reason_summary":         reason_summary,
                "review_next_action":            next_action,
                "evidence_categories":           json.dumps(ev_cats),
                "matched_terms":                 json.dumps(matched_terms),
                "project_hint":                  proj_ctx["project_hint"],
                "project_confidence":            proj_ctx["project_confidence"],
                "repeat_contact":                proj_ctx["repeat_contact"],
                "previous_thread_count":         proj_ctx["previous_thread_count"],
                "last_interaction_date":         proj_ctx["last_interaction_date"],
                "known_relationship":            proj_ctx["known_relationship"],
                "triage_suggested_relationship": assist["suggested_relationship_type"],
                "triage_inferred_domain":        assist["inferred_domain"],
                "triage_risk_flags":             json.dumps(assist["risk_flags"]),
                "triage_contact_display":        contact_display,
                "triage_debug":                  triage_debug,
                "triaged_at":                    now_iso,
            }
            results.append(entry)

            if not dry_run:
                conn.execute(
                    "UPDATE threads SET "
                    "triage_bucket=?, triage_reason=?, triage_confidence=?, "
                    "review_value_score=?, "
                    "review_reason_summary=?, review_next_action=?, "
                    "evidence_categories=?, matched_terms=?, "
                    "project_hint=?, project_confidence=?, repeat_contact=?, "
                    "previous_thread_count=?, last_interaction_date=?, known_relationship=?, "
                    "triage_suggested_relationship=?, triage_inferred_domain=?, "
                    "triage_risk_flags=?, triage_contact_display=?, "
                    "triage_debug=?, triaged_at=? "
                    "WHERE thread_id=?",
                    (
                        entry["triage_bucket"],
                        entry["triage_reason"],
                        entry["triage_confidence"],
                        entry["review_value_score"],
                        entry["review_reason_summary"],
                        entry["review_next_action"],
                        entry["evidence_categories"],
                        entry["matched_terms"],
                        entry["project_hint"],
                        entry["project_confidence"],
                        entry["repeat_contact"],
                        entry["previous_thread_count"],
                        entry["last_interaction_date"],
                        entry["known_relationship"],
                        entry["triage_suggested_relationship"],
                        entry["triage_inferred_domain"],
                        entry["triage_risk_flags"],
                        entry["triage_contact_display"],
                        entry["triage_debug"],
                        entry["triaged_at"],
                        r["thread_id"],
                    ),
                )

        if not dry_run:
            conn.commit()

    finally:
        _rct.CHAT_DB = _orig_chat_db

    out: dict[str, Any] = {
        "dry_run":       dry_run,
        "processed":     len(rows),
        "counts":        counts,
        "results":       results,
        "snapshot_used": str(chat_db_path) if chat_db_path else None,
    }
    if snapshot_diagnostics:
        out["snapshot_diagnostics"] = snapshot_diagnostics

    # Write sidecar stats file so Cortex dashboard can report snapshot health.
    try:
        stats: dict[str, Any] = {
            "last_run":      now_iso,
            "dry_run":       dry_run,
            "processed":     len(rows),
            "counts":        counts,
            "snapshot_used": str(chat_db_path) if chat_db_path else None,
        }
        if snapshot_diagnostics and "error" not in snapshot_diagnostics:
            stats["snapshot_message_count"]    = snapshot_diagnostics.get("total_messages", 0)
            stats["attributed_body_count"]     = snapshot_diagnostics.get("attributed_body_messages", 0)
            stats["readable_sample_count"]     = snapshot_diagnostics.get("readable_sample", 0)
        _TRIAGE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TRIAGE_STATS_PATH.write_text(json.dumps(stats, indent=2))
    except Exception:
        pass

    return out


def get_triage_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return bucket counts and last triage timestamp from the DB."""
    try:
        _ensure_triage_columns(conn)
        summary: dict[str, Any] = {b: 0 for b in TRIAGE_BUCKETS}
        for r in conn.execute(
            "SELECT triage_bucket, COUNT(*) FROM threads "
            "WHERE is_reviewed=-1 AND triage_bucket IS NOT NULL "
            "GROUP BY triage_bucket"
        ).fetchall():
            if r[0] in TRIAGE_BUCKETS:
                summary[r[0]] = r[1]
        summary["untriaged"] = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=-1 AND triage_bucket IS NULL"
        ).fetchone()[0]
        summary["last_triaged"] = conn.execute(
            "SELECT MAX(triaged_at) FROM threads WHERE triaged_at IS NOT NULL"
        ).fetchone()[0]
        return summary
    except Exception as exc:
        return {"error": str(exc)[:200]}


def get_review_queue(
    conn: sqlite3.Connection,
    bucket: "str | None" = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return triaged threads for dashboard display. Phone numbers are masked."""
    try:
        _ensure_triage_columns(conn)
        where_parts = ["is_reviewed = -1", "triage_bucket IS NOT NULL"]
        params: list[Any] = []
        if bucket:
            where_parts.append("triage_bucket = ?")
            params.append(bucket)
        where = " AND ".join(where_parts)
        params.append(limit)
        rows = conn.execute(
            f"SELECT thread_id, contact_handle, message_count, date_last, "
            f"category, work_confidence, reason_codes, "
            f"triage_bucket, triage_reason, triage_confidence, "
            f"triage_suggested_relationship, triage_inferred_domain, "
            f"triage_risk_flags, triage_contact_display, triaged_at "
            f"FROM threads WHERE {where} "
            f"ORDER BY triage_confidence DESC, work_confidence DESC "
            f"LIMIT ?",
            params,
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "thread_id":              r["thread_id"],
                "contact_display":        r["triage_contact_display"] or _rct._mask(r["contact_handle"]),
                "contact_masked":         _rct._mask(r["contact_handle"]),
                "message_count":          r["message_count"],
                "date_last":              (r["date_last"] or "")[:10],
                "category":               r["category"],
                "work_confidence":        r["work_confidence"],
                "triage_bucket":          r["triage_bucket"],
                "triage_reason":          r["triage_reason"],
                "triage_confidence":      r["triage_confidence"],
                "suggested_relationship": r["triage_suggested_relationship"],
                "inferred_domain":        r["triage_inferred_domain"],
                "risk_flags":             json.loads(r["triage_risk_flags"] or "[]"),
            })
        return out
    except Exception:
        return []


def get_thread_explain(conn: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    """Return full triage debug detail for one thread. Phone numbers are masked."""
    _ensure_triage_columns(conn)
    r = conn.execute(
        "SELECT thread_id, contact_handle, message_count, date_last, "
        "category, work_confidence, reason_codes, "
        "triage_bucket, triage_reason, triage_confidence, "
        "triage_suggested_relationship, triage_inferred_domain, "
        "triage_risk_flags, triage_contact_display, triaged_at, triage_debug, "
        "review_reason_summary, review_next_action, evidence_categories "
        "FROM threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if not r:
        return {"error": f"thread_id not found: {thread_id}"}
    debug: dict[str, Any] = {}
    try:
        debug = json.loads(r["triage_debug"] or "{}")
    except Exception:
        pass
    return {
        "thread_id":              r["thread_id"],
        "contact_display":        r["triage_contact_display"] or _rct._mask(r["contact_handle"]),
        "contact_masked":         _rct._mask(r["contact_handle"]),
        "message_count":          r["message_count"],
        "date_last":              (r["date_last"] or "")[:10],
        "category":               r["category"],
        "work_confidence":        r["work_confidence"],
        "triage_bucket":          r["triage_bucket"],
        "triage_reason":          r["triage_reason"],
        "triage_confidence":      r["triage_confidence"],
        "suggested_relationship": r["triage_suggested_relationship"],
        "inferred_domain":        r["triage_inferred_domain"],
        "risk_flags":             json.loads(r["triage_risk_flags"] or "[]"),
        "triaged_at":             r["triaged_at"],
        "debug":                  debug,
        "review_reason_summary":  r["review_reason_summary"],
        "review_next_action":     r["review_next_action"],
        "evidence_categories":    r["evidence_categories"],
    }


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        print(f"[error] Thread index not found: {DB_PATH}")
        print("Run first: python3 scripts/client_intel_backfill.py --dry-run --limit 100")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _print_explain(info: dict[str, Any]) -> None:
    if "error" in info:
        print(f"[error] {info['error']}")
        return
    print(f"\n=== Explain: {info['thread_id']} ===")
    print(f"  Contact      : {info['contact_display']}")
    print(f"  Bucket       : {info['triage_bucket']}")
    print(f"  Reason       : {info['triage_reason']}")
    print(f"  Confidence   : {info['triage_confidence']}")
    print(f"  Relationship : {info['suggested_relationship']}")
    print(f"  Domain       : {info['inferred_domain']}")
    print(f"  Category     : {info['category']}")
    print(f"  Work conf    : {info['work_confidence']:.2f}")
    print(f"  Messages     : {info['message_count']}")
    print(f"  Last active  : {info['date_last']}")
    if info["risk_flags"]:
        print(f"  Risk flags   : {', '.join(info['risk_flags'])}")
    dbg = info.get("debug", {})
    if dbg:
        scores = dbg.get("scores", {})
        if scores:
            print(f"  Scores       : tech={scores.get('tech',0)}  restaurant={scores.get('restaurant',0)}"
                  f"  builder={scores.get('builder',0)}  vendor={scores.get('vendor',0)}")
        readable = dbg.get("readable_message_count", "?")
        print(f"  Readable msgs: {readable}")
        evidence = dbg.get("evidence", [])
        if evidence:
            print(f"  Evidence:")
            for e in evidence:
                print(f"    - {e}")
        review_reason = dbg.get("review_reason", "")
        if review_reason:
            print(f"  Review reason: {review_reason}")
    if info.get("review_reason_summary"):
        print(f"  Summary      : {info['review_reason_summary']}")
    if info.get("review_next_action"):
        print(f"  Next action  : {info['review_next_action']}")
    if info.get("evidence_categories"):
        print(f"  Ev. categories: {', '.join(json.loads(info['evidence_categories'] or '[]'))}")
    ph = info.get("project_hint", "")
    pc = info.get("project_confidence", 0.0)
    rc = info.get("repeat_contact", 0)
    kr = info.get("known_relationship", "")
    if ph or rc or kr:
        parts = []
        if ph:
            parts.append(f"project: {ph} (conf={pc:.2f})")
        if kr:
            parts.append(f"known: {kr}")
        elif rc:
            parts.append("repeat contact")
        print(f"  Context      : {' | '.join(parts)}")
    if info.get("triaged_at"):
        print(f"  Triaged at   : {info['triaged_at'][:19]}")


def _print_bucket_summary(conn: sqlite3.Connection, top: int = 3) -> None:
    """Print a human-readable per-bucket summary with diagnostic scores."""
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
    has_rvs       = "review_value_score"  in existing_cols
    has_summary   = "review_reason_summary" in existing_cols
    has_next_act  = "review_next_action"  in existing_cols
    has_proj      = "project_hint"        in existing_cols
    for bucket in ("high_value", "ambiguous", "low_priority", "hidden_personal"):
        extra_cols = ""
        if has_rvs:
            extra_cols += ", review_value_score"
        if has_summary:
            extra_cols += ", review_reason_summary"
        if has_next_act:
            extra_cols += ", review_next_action"
        if has_proj:
            extra_cols += ", project_hint, project_confidence, repeat_contact, known_relationship"
        rows = conn.execute(
            f"SELECT thread_id, triage_contact_display, contact_handle, "
            f"message_count, triage_reason, triage_confidence{extra_cols}, triage_debug "
            f"FROM threads WHERE is_reviewed=-1 AND triage_bucket=? "
            f"ORDER BY {'review_value_score' if has_rvs else 'triage_confidence'} DESC LIMIT ?",
            (bucket, top),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=-1 AND triage_bucket=?",
            (bucket,),
        ).fetchone()[0]
        print(f"\n{bucket.upper()} ({total}):")
        if not rows:
            print("  (none)")
            continue
        for r in rows:
            display  = r["triage_contact_display"] or _rct._mask(r["contact_handle"])
            dbg: dict[str, Any] = {}
            try:
                dbg = json.loads(r["triage_debug"] or "{}")
            except Exception:
                pass
            scores   = dbg.get("scores", {})
            flags    = dbg.get("risk_flags", [])
            evidence = dbg.get("evidence", [])
            readable = dbg.get("readable_message_count", "?")
            named    = "yes" if dbg.get("contact_name_found") else "no"
            tech     = scores.get("tech", "?")
            rest     = scores.get("restaurant", "?")
            build    = scores.get("builder", "?")
            bkt_conf = r["triage_confidence"]
            rvs      = r["review_value_score"] if has_rvs else None
            val_str  = f"  val={rvs:.2f}" if rvs is not None else ""
            print(
                f"  {display:28s}  bkt={bkt_conf:.2f}{val_str}  msgs={r['message_count']:4d}  "
                f"name={named}  tech={tech}  rest={rest}  build={build}  readable={readable}"
            )
            print(f"    → {r['triage_reason'][:75]}")
            if flags:
                print(f"    flags: {', '.join(flags)}")
            if evidence:
                print(f"    evidence: {'; '.join(evidence[:3])}")
            summary  = dbg.get("review_reason_summary", "")
            next_act = dbg.get("review_next_action", "")
            if summary:
                print(f"    summary: {summary}")
            if next_act:
                print(f"    action:  {next_act}")
            if has_proj:
                ph = r["project_hint"] or ""
                pc = r["project_confidence"] or 0.0
                rc = r["repeat_contact"] or 0
                kr = r["known_relationship"] or ""
                ctx_parts = []
                if ph:
                    ctx_parts.append(f"project: {ph} (conf={pc:.2f})")
                if kr:
                    ctx_parts.append(f"known: {kr}")
                elif rc:
                    ctx_parts.append("repeat contact")
                if ctx_parts:
                    print(f"    context: {' | '.join(ctx_parts)}")


def _print_run_summary(result: dict[str, Any], verbose: bool = False) -> None:
    mode = "DRY RUN" if result.get("dry_run") else "APPLIED"
    print(f"\n=== Auto-Triage Client Threads [{mode}] ===")
    print(f"  Processed : {result['processed']}")
    for bucket in ("high_value", "ambiguous", "low_priority", "hidden_personal"):
        n = result["counts"].get(bucket, 0)
        print(f"  {bucket:20s}: {n}")
    if verbose and result.get("results"):
        print("\n--- Examples (up to 2 per bucket) ---")
        seen: dict[str, int] = {}
        for r in result["results"]:
            b = r["triage_bucket"]
            if seen.get(b, 0) >= 2:
                continue
            seen[b] = seen.get(b, 0) + 1
            flags = json.loads(r.get("triage_risk_flags", "[]"))
            rvs = r.get("review_value_score")
            rvs_str = f"  val={rvs:.2f}" if rvs is not None else ""
            print(
                f"  [{b}] {r['contact_masked']}  "
                f"domain={r['triage_inferred_domain']}  "
                f"suggested={r['triage_suggested_relationship']}  "
                f"bkt={r['triage_confidence']:.2f}{rvs_str}"
            )
            print(f"         {r['triage_reason']}")
            if flags:
                print(f"         risk_flags: {', '.join(flags)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-triage pending client intelligence threads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python3 scripts/auto_triage_client_threads.py --limit 200 --verbose
  python3 scripts/auto_triage_client_threads.py --apply
  python3 scripts/auto_triage_client_threads.py --snapshot-auto --apply
  python3 scripts/auto_triage_client_threads.py --summary
  python3 scripts/auto_triage_client_threads.py --bucket-summary --top 5
  python3 scripts/auto_triage_client_threads.py --bucket high_value --verbose
  python3 scripts/auto_triage_client_threads.py --explain <thread_id>
  python3 scripts/auto_triage_client_threads.py --chat-db data/client_intel/chatdb_snapshot/chat.db --apply
""",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write triage fields to DB (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Explicit dry-run (default when --apply is absent)")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max threads to process (default 500)")
    parser.add_argument("--bucket", choices=sorted(TRIAGE_BUCKETS),
                        help="Only show/apply threads in this bucket")
    parser.add_argument("--summary", action="store_true",
                        help="Show DB bucket counts only; no processing")
    parser.add_argument("--bucket-summary", action="store_true",
                        help="Show per-bucket breakdown with top examples from DB")
    parser.add_argument("--top", type=int, default=3, metavar="N",
                        help="Examples per bucket for --bucket-summary (default 3)")
    parser.add_argument("--explain", metavar="THREAD_ID",
                        help="Show full triage debug for a specific thread")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print example entries from each bucket after triage run")
    parser.add_argument("--snapshot-auto", action="store_true",
                        help="Auto-copy ~/Library/Messages/chat.db → chatdb_snapshot/ and use it. "
                             "Avoids the Messages.app write lock without closing the app.")
    parser.add_argument("--chat-db", metavar="PATH",
                        help="Path to a chat.db snapshot to use instead of the live "
                             "~/Library/Messages/chat.db.")
    args = parser.parse_args()

    # Resolve chat_db_path
    chat_db_path: "Path | None" = None
    snap_diag: "dict[str, Any] | None" = None

    if args.snapshot_auto:
        chat_db_path = _auto_snapshot()
        if chat_db_path and chat_db_path.is_file():
            snap_diag = _snapshot_diagnostics(chat_db_path)
            msg_total = snap_diag.get("total_messages", "?")
            readable  = snap_diag.get("readable_sample", "?")
            of_total  = snap_diag.get("readable_sample_of", "?")
            print(f"  [snapshot] {msg_total} messages — readable sample: {readable}/{of_total}")
    elif args.chat_db:
        chat_db_path = Path(args.chat_db)
        if not chat_db_path.is_absolute():
            chat_db_path = REPO_ROOT / chat_db_path
        if not chat_db_path.is_file():
            print(f"[error] --chat-db path not found: {chat_db_path}")
            sys.exit(1)
        print(f"  Using chat.db snapshot: {chat_db_path}")
        snap_diag = _snapshot_diagnostics(chat_db_path)

    conn = _open_db()
    try:
        if args.explain:
            info = get_thread_explain(conn, args.explain)
            _print_explain(info)
            return

        if args.summary:
            s = get_triage_summary(conn)
            print("\n=== Triage Summary (from DB) ===")
            for k, v in s.items():
                print(f"  {k:25s}: {v}")
            return

        if args.bucket_summary:
            _ensure_triage_columns(conn)
            _print_bucket_summary(conn, top=args.top)
            return

        dry_run = not args.apply
        result = run_triage(
            conn,
            limit=args.limit,
            dry_run=dry_run,
            bucket_filter=args.bucket,
            chat_db_path=chat_db_path,
            snapshot_diagnostics=snap_diag,
        )
        _print_run_summary(result, verbose=args.verbose)
        if result.get("dry_run"):
            print("\n  (dry-run — re-run with --apply to persist triage fields)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
