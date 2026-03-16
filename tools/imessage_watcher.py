#!/usr/bin/env python3
"""
iMessage Watcher for Symphony Smart Homes.

Monitors Messages chat.db, logs monitored conversations, and creates task-board tasks
from actionable work texts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from security_utils import hash_text, mask_contact, mask_name, redact_text


BASE_DIR = Path(__file__).resolve().parent.parent
MESSAGES_DB = Path.home() / "Library" / "Messages" / "chat.db"
STATE_FILE = BASE_DIR / "data" / "imessage_watcher_state.json"
LOG_FILE = BASE_DIR / "knowledge" / "imessages" / "work_talk.jsonl"
CONTACTS_INDEX_FILE = BASE_DIR / "data" / "contacts" / "contacts_index.json"
AUTOMATION_DIR = BASE_DIR / "data" / "imessage_automation"
INVOICE_DRAFTS_FILE = AUTOMATION_DIR / "service_invoice_drafts.jsonl"
APPOINTMENT_DRAFTS_FILE = AUTOMATION_DIR / "appointment_schedule_drafts.jsonl"
TASK_BOARD_DB = BASE_DIR / "orchestrator" / "task_board.db"

WORK_INCLUDE_KEYWORDS = [
    "project",
    "proposal",
    "quote",
    "bid",
    "install",
    "installer",
    "commission",
    "program",
    "service call",
    "service",
    "troubleshoot",
    "trouble",
    "down",
    "not working",
    "network",
    "wifi",
    "camera",
    "nvr",
    "control4",
    "lutron",
    "sonos",
    "speaker",
    "amp",
    "tv",
    "rack",
    "manual",
    "schedule",
    "appointment",
    "calendar",
    "invoice",
    "billing",
    "payment",
    "purchase",
    "po",
    "d-tools",
    "dtools",
    "change order",
    "site visit",
    "dispatch",
]

WORK_EXCLUDE_KEYWORDS = [
    "happy birthday",
    "birthday party",
    "dinner",
    "lunch",
    "breakfast",
    "vacation",
    "movie",
    "weekend plans",
    "family",
    "school pickup",
    "soccer practice",
    "party tonight",
]


@dataclass
class MessageItem:
    rowid: int
    text: str
    handle: str
    is_from_me: int
    date: Optional[int]


def now_iso() -> str:
    return datetime.now().isoformat()


def normalize_contact(value: str) -> str:
    raw = (value or "").strip()
    if "@" in raw:
        return raw.lower()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    return digits or raw.lower()


def normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_rowid": 0,
        "watchlist": [],
        "watchlist_normalized": [],
        "monitor_all": False,
        "processed_count": 0,
        "last_check": None,
        "last_processed_at": None,
        "last_error": None,
        "automation": {
            "create_service_invoice_drafts": True,
            "create_appointment_drafts": True,
        },
        "keyword_discovery_enabled": True,
        "work_signal_threshold": 2,
    }


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def set_watchlist(numbers: list[str], monitor_all: bool = False) -> dict[str, Any]:
    state = load_state()
    clean = [n.strip() for n in numbers if n and n.strip()]
    norm = sorted(set(normalize_contact(n) for n in clean))
    state["watchlist"] = clean
    state["watchlist_normalized"] = norm
    # Security hardening: scanner is always constrained to explicit watchlist.
    state["monitor_all"] = False
    save_state(state)
    return {
        "success": True,
        "watchlist_count": len(clean),
        "watchlist_normalized": norm,
        "monitor_all": False,
    }


def set_monitor_all(monitor_all: bool) -> dict[str, Any]:
    state = load_state()
    # Deprecated by policy: keep watchlist-only mode.
    state["monitor_all"] = False
    save_state(state)
    return {
        "success": True,
        "monitor_all": False,
        "watchlist_count": len(state.get("watchlist", [])),
        "warning": "monitor_all is disabled; watcher runs in watchlist-only mode.",
    }


def clear_watchlist() -> dict[str, Any]:
    state = load_state()
    state["watchlist"] = []
    state["watchlist_normalized"] = []
    state["monitor_all"] = False
    save_state(state)
    return {
        "success": True,
        "watchlist_count": 0,
        "monitor_all": False,
    }


def set_automation(
    create_service_invoice_drafts: Optional[bool] = None,
    create_appointment_drafts: Optional[bool] = None,
) -> dict[str, Any]:
    state = load_state()
    automation = state.setdefault("automation", {})
    if create_service_invoice_drafts is not None:
        automation["create_service_invoice_drafts"] = bool(create_service_invoice_drafts)
    if create_appointment_drafts is not None:
        automation["create_appointment_drafts"] = bool(create_appointment_drafts)
    save_state(state)
    return {
        "success": True,
        "automation": automation,
    }


def connect_messages_db() -> sqlite3.Connection:
    if not MESSAGES_DB.exists():
        raise FileNotFoundError(f"Messages DB not found at {MESSAGES_DB}")
    return sqlite3.connect(f"file:{MESSAGES_DB}?mode=ro", uri=True)


def apple_timestamp_from_datetime(dt: datetime) -> int:
    # macOS Messages uses Apple epoch (2001-01-01). Stored units can vary by OS build.
    apple_epoch = datetime(2001, 1, 1)
    seconds = (dt - apple_epoch).total_seconds()
    # Use nanosecond-scale threshold for modern chat.db values.
    return int(seconds * 1_000_000_000)


def fetch_new_messages(last_rowid: int, limit: int = 500) -> list[MessageItem]:
    conn = connect_messages_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            m.ROWID AS rowid,
            COALESCE(m.text, '') AS text,
            COALESCE(h.id, '') AS handle,
            COALESCE(m.is_from_me, 0) AS is_from_me,
            m.date AS date
        FROM message m
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE m.ROWID > ?
          AND COALESCE(m.text, '') != ''
        ORDER BY m.ROWID ASC
        LIMIT ?
        """,
        (int(last_rowid), int(limit)),
    ).fetchall()
    conn.close()
    return [
        MessageItem(
            rowid=int(r["rowid"]),
            text=str(r["text"]),
            handle=str(r["handle"]),
            is_from_me=int(r["is_from_me"]),
            date=r["date"],
        )
        for r in rows
    ]


def fetch_messages_since(since_dt: datetime, limit: int = 5000) -> list[MessageItem]:
    conn = connect_messages_db()
    conn.row_factory = sqlite3.Row
    since_apple = apple_timestamp_from_datetime(since_dt)
    rows = conn.execute(
        """
        SELECT
            m.ROWID AS rowid,
            COALESCE(m.text, '') AS text,
            COALESCE(h.id, '') AS handle,
            COALESCE(m.is_from_me, 0) AS is_from_me,
            m.date AS date
        FROM message m
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE COALESCE(m.text, '') != ''
          AND COALESCE(m.date, 0) >= ?
        ORDER BY m.ROWID ASC
        LIMIT ?
        """,
        (int(since_apple), int(limit)),
    ).fetchall()
    conn.close()
    return [
        MessageItem(
            rowid=int(r["rowid"]),
            text=str(r["text"]),
            handle=str(r["handle"]),
            is_from_me=int(r["is_from_me"]),
            date=r["date"],
        )
        for r in rows
    ]


def is_monitored(handle: str, state: dict[str, Any]) -> bool:
    watchlist = set(state.get("watchlist_normalized", []))
    if not watchlist:
        return False
    return normalize_contact(handle) in watchlist


def work_signal_score(text: str, contact: Optional[dict[str, Any]]) -> int:
    low = (text or "").lower()
    score = 0
    for token in WORK_INCLUDE_KEYWORDS:
        if token in low:
            score += 1
    for token in WORK_EXCLUDE_KEYWORDS:
        if token in low:
            score -= 2
    if contact:
        linked_projects = contact.get("linked_projects", []) if isinstance(contact, dict) else []
        if linked_projects:
            score += 2
        name = str(contact.get("name", "")).strip().lower()
        if name and name in low:
            score += 1
    return score


def classify_priority(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ["asap", "urgent", "today", "deadline", "down", "not working", "outage"]):
        return "high"
    return "medium"


def classify_task_type(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ["install", "setup", "program", "commission"]):
        return "commissioning"
    if any(x in low for x in ["fix", "broken", "issue", "not working", "error", "troubleshoot"]):
        return "troubleshooting"
    if any(x in low for x in ["quote", "proposal", "price", "bid"]):
        return "proposal"
    if any(x in low for x in ["research", "find", "look up"]):
        return "research"
    return "integration"


def should_create_service_invoice_draft(text: str, is_from_me: int) -> bool:
    if is_from_me:
        return False
    low = text.lower()
    invoice_tokens = ["invoice", "bill", "billing", "charge", "charged", "payment", "pay", "paid", "service call", "labor"]
    action_tokens = ["send", "need", "please", "can you", "create", "make"]
    return any(t in low for t in invoice_tokens) and any(t in low for t in action_tokens)


def should_create_appointment_draft(text: str, is_from_me: int) -> bool:
    if is_from_me:
        return False
    low = text.lower()
    schedule_tokens = ["schedule", "appointment", "book", "available", "availability", "tomorrow", "next week", "this week", "calendar"]
    action_tokens = ["can you", "please", "need", "set up", "confirm", "reschedule"]
    return any(t in low for t in schedule_tokens) and any(t in low for t in action_tokens)


def should_create_task(text: str, is_from_me: int) -> bool:
    # Create tasks only from incoming texts unless monitor-all parsing says otherwise.
    if is_from_me:
        return False
    low = text.lower()
    triggers = [
        "can you",
        "please",
        "need",
        "schedule",
        "install",
        "fix",
        "quote",
        "proposal",
        "follow up",
        "call",
        "text me",
    ]
    return any(t in low for t in triggers)


def task_exists_for_message(rowid: int, action: str) -> bool:
    if not TASK_BOARD_DB.exists():
        return False
    try:
        conn = sqlite3.connect(TASK_BOARD_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT metadata FROM tasks
            WHERE source = 'imessage' AND source_id = ?
            """,
            (str(rowid),),
        ).fetchall()
        conn.close()
        for row in rows:
            meta = row["metadata"]
            if not meta:
                if action == "general_message":
                    return True
                continue
            try:
                parsed = json.loads(meta)
                if parsed.get("imessage_action") == action:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def create_task_from_message(msg: MessageItem) -> Optional[int]:
    if task_exists_for_message(msg.rowid, "general_message"):
        return None
    contact = lookup_contact(msg.handle)
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR / "orchestrator"))
        from task_board import add_task  # type: ignore

        task_type = classify_task_type(msg.text)
        priority = classify_priority(msg.text)
        sender = (contact or {}).get("name") or msg.handle
        safe_sender = mask_name(sender) if (contact or {}).get("name") else mask_contact(msg.handle)
        redacted_text = redact_text(msg.text)
        title = f"iMessage ({safe_sender}): {redacted_text[:80]}"
        linked_projects = (contact or {}).get("linked_projects", [])
        project_hint = linked_projects[0] if linked_projects else ""
        description = (
            f"Incoming iMessage from {safe_sender}\n\n"
            f"Message: {redacted_text}\n"
            f"Message ROWID: {msg.rowid}\n"
            f"{('Project hint: ' + project_hint + chr(10)) if project_hint else ''}"
            f"Captured at: {now_iso()}"
        )
        task_id = add_task(
            title=title,
            description=description,
            task_type=task_type,
            priority=priority,
            source="imessage",
            source_id=str(msg.rowid),
            metadata={
                "imessage_action": "general_message",
                "handle_masked": mask_contact(msg.handle),
                "handle_hash": hash_text(msg.handle),
                "rowid": msg.rowid,
                "contact_name_masked": mask_name((contact or {}).get("name", "")),
                "linked_projects": linked_projects,
            },
        )
        return int(task_id)
    except Exception:
        return None


def load_contacts_index() -> dict[str, Any]:
    if CONTACTS_INDEX_FILE.exists():
        try:
            return json.loads(CONTACTS_INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def lookup_contact(handle: str) -> Optional[dict[str, Any]]:
    idx = load_contacts_index()
    if not idx:
        return None
    norm_phone = normalize_contact(handle)
    norm_text = normalize_text(handle)
    by_phone = idx.get("by_phone", {})
    by_email = idx.get("by_email", {})
    if norm_phone in by_phone:
        return by_phone[norm_phone]
    if norm_text in by_email:
        return by_email[norm_text]
    return None


def append_log(entry: dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def draft_exists_for_rowid(path: Path, rowid: int) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if int(payload.get("rowid", -1)) == int(rowid):
                    return True
        return False
    except Exception:
        return False


def create_service_invoice_draft(msg: MessageItem, contact: Optional[dict[str, Any]]) -> Optional[tuple[str, int]]:
    if task_exists_for_message(msg.rowid, "service_invoice_draft"):
        return None
    if draft_exists_for_rowid(INVOICE_DRAFTS_FILE, msg.rowid):
        return None
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR / "orchestrator"))
        from task_board import add_task  # type: ignore
    except Exception:
        return None

    sender = (contact or {}).get("name") or msg.handle
    safe_sender = mask_name(sender) if (contact or {}).get("name") else mask_contact(msg.handle)
    redacted_text = redact_text(msg.text)
    linked_projects = (contact or {}).get("linked_projects", [])
    project_hint = linked_projects[0] if linked_projects else ""
    draft_id = f"inv_{msg.rowid}_{int(time.time())}"
    draft = {
        "draft_id": draft_id,
        "created_at": now_iso(),
        "source": "imessage",
        "rowid": msg.rowid,
        "handle_raw": msg.handle,
        "handle_masked": mask_contact(msg.handle),
        "contact_name_masked": mask_name((contact or {}).get("name", "")),
        "project_hint": project_hint,
        "linked_projects": linked_projects,
        "request_text_redacted": redacted_text,
        "status": "draft",
    }
    append_jsonl(INVOICE_DRAFTS_FILE, draft)

    title = f"Service invoice draft ({safe_sender})"
    description = (
        f"Create service invoice draft from iMessage.\n\n"
        f"Request: {redacted_text}\n"
        f"Draft ID: {draft_id}\n"
        f"Message ROWID: {msg.rowid}\n"
        f"{('Project hint: ' + project_hint + chr(10)) if project_hint else ''}"
        f"Draft file: {INVOICE_DRAFTS_FILE}"
    )
    task_id = add_task(
        title=title,
        description=description,
        task_type="proposal",
        priority="high",
        source="imessage",
        source_id=str(msg.rowid),
        metadata={
            "imessage_action": "service_invoice_draft",
            "draft_id": draft_id,
            "draft_file": str(INVOICE_DRAFTS_FILE),
            "linked_projects": linked_projects,
            "handle_hash": hash_text(msg.handle),
        },
    )
    return draft_id, int(task_id)


def create_appointment_draft(msg: MessageItem, contact: Optional[dict[str, Any]]) -> Optional[tuple[str, int]]:
    if task_exists_for_message(msg.rowid, "appointment_schedule_draft"):
        return None
    if draft_exists_for_rowid(APPOINTMENT_DRAFTS_FILE, msg.rowid):
        return None
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR / "orchestrator"))
        from task_board import add_task  # type: ignore
    except Exception:
        return None

    sender = (contact or {}).get("name") or msg.handle
    safe_sender = mask_name(sender) if (contact or {}).get("name") else mask_contact(msg.handle)
    redacted_text = redact_text(msg.text)
    linked_projects = (contact or {}).get("linked_projects", [])
    project_hint = linked_projects[0] if linked_projects else ""
    draft_id = f"appt_{msg.rowid}_{int(time.time())}"
    draft = {
        "draft_id": draft_id,
        "created_at": now_iso(),
        "source": "imessage",
        "rowid": msg.rowid,
        "handle_raw": msg.handle,
        "handle_masked": mask_contact(msg.handle),
        "contact_name_masked": mask_name((contact or {}).get("name", "")),
        "project_hint": project_hint,
        "linked_projects": linked_projects,
        "request_text_redacted": redacted_text,
        "status": "draft",
    }
    append_jsonl(APPOINTMENT_DRAFTS_FILE, draft)

    title = f"Appointment schedule draft ({safe_sender})"
    description = (
        f"Create appointment schedule draft from iMessage.\n\n"
        f"Request: {redacted_text}\n"
        f"Draft ID: {draft_id}\n"
        f"Message ROWID: {msg.rowid}\n"
        f"{('Project hint: ' + project_hint + chr(10)) if project_hint else ''}"
        f"Draft file: {APPOINTMENT_DRAFTS_FILE}"
    )
    task_id = add_task(
        title=title,
        description=description,
        task_type="integration",
        priority="high",
        source="imessage",
        source_id=str(msg.rowid),
        metadata={
            "imessage_action": "appointment_schedule_draft",
            "draft_id": draft_id,
            "draft_file": str(APPOINTMENT_DRAFTS_FILE),
            "linked_projects": linked_projects,
            "handle_hash": hash_text(msg.handle),
        },
    )
    return draft_id, int(task_id)


def process_messages(messages: list[MessageItem], state: dict[str, Any], update_rowid: bool = True, dry_run: bool = False) -> dict[str, Any]:
    last_rowid = int(state.get("last_rowid", 0))

    processed = 0
    logged = 0
    tasks_created = 0
    invoice_drafts_created = 0
    appointment_drafts_created = 0
    max_rowid = last_rowid
    monitored_messages = 0
    keyword_selected_messages = 0

    for msg in messages:
        max_rowid = max(max_rowid, msg.rowid)
        contact = lookup_contact(msg.handle)
        monitored = is_monitored(msg.handle, state)
        keyword_discovery_enabled = bool(state.get("keyword_discovery_enabled", True))
        threshold = max(1, int(state.get("work_signal_threshold", 2)))
        signal = work_signal_score(msg.text, contact) if keyword_discovery_enabled else 0
        keyword_selected = keyword_discovery_enabled and signal >= threshold
        if not (monitored or keyword_selected):
            continue

        monitored_messages += 1
        if keyword_selected and not monitored:
            keyword_selected_messages += 1
        entry = {
            "timestamp": now_iso(),
            "rowid": msg.rowid,
            "handle_masked": mask_contact(msg.handle),
            "handle_hash": hash_text(msg.handle),
            "direction": "outgoing" if msg.is_from_me else "incoming",
            "text_redacted": redact_text(msg.text)[:400],
            "text_hash": hash_text(msg.text),
            "work_signal_score": signal,
            "selected_by": "watchlist" if monitored else "keyword_discovery",
        }
        if contact:
            entry["contact_name_masked"] = mask_name(contact.get("name", ""))
            entry["linked_projects"] = contact.get("linked_projects", [])
        task_id = None
        if should_create_task(msg.text, msg.is_from_me):
            if dry_run:
                if not task_exists_for_message(msg.rowid, "general_message"):
                    tasks_created += 1
            else:
                task_id = create_task_from_message(msg)
                if task_id:
                    tasks_created += 1
                    entry["task_id"] = task_id
        automation = state.get("automation", {})
        if automation.get("create_service_invoice_drafts", True) and should_create_service_invoice_draft(msg.text, msg.is_from_me):
            if dry_run:
                if (
                    not task_exists_for_message(msg.rowid, "service_invoice_draft")
                    and not draft_exists_for_rowid(INVOICE_DRAFTS_FILE, msg.rowid)
                ):
                    invoice_drafts_created += 1
                    tasks_created += 1
            else:
                inv_result = create_service_invoice_draft(msg, contact)
                if inv_result:
                    invoice_drafts_created += 1
                    tasks_created += 1
                    entry["invoice_draft_id"] = inv_result[0]
                    entry["invoice_task_id"] = inv_result[1]
        if automation.get("create_appointment_drafts", True) and should_create_appointment_draft(msg.text, msg.is_from_me):
            if dry_run:
                if (
                    not task_exists_for_message(msg.rowid, "appointment_schedule_draft")
                    and not draft_exists_for_rowid(APPOINTMENT_DRAFTS_FILE, msg.rowid)
                ):
                    appointment_drafts_created += 1
                    tasks_created += 1
            else:
                appt_result = create_appointment_draft(msg, contact)
                if appt_result:
                    appointment_drafts_created += 1
                    tasks_created += 1
                    entry["appointment_draft_id"] = appt_result[0]
                    entry["appointment_task_id"] = appt_result[1]
        if not dry_run:
            append_log(entry)
            logged += 1
        processed += 1

    if update_rowid:
        state["last_rowid"] = max_rowid
    if not dry_run:
        state["processed_count"] = int(state.get("processed_count", 0)) + processed
        state["last_check"] = now_iso()
        state["last_processed_at"] = now_iso()
        state["last_error"] = None
        save_state(state)

    return {
        "success": True,
        "checked_at": now_iso(),
        "messages_seen": len(messages),
        "messages_monitored": monitored_messages,
        "messages_logged": logged,
        "tasks_created": tasks_created,
        "invoice_drafts_created": invoice_drafts_created,
        "appointment_drafts_created": appointment_drafts_created,
        "keyword_selected_messages": keyword_selected_messages,
        "last_rowid": max_rowid,
        "watchlist_count": len(state.get("watchlist", [])),
        "monitor_all": bool(state.get("monitor_all", False)),
        "dry_run": bool(dry_run),
    }


def process_once(limit: int = 500) -> dict[str, Any]:
    state = load_state()
    last_rowid = int(state.get("last_rowid", 0))
    messages = fetch_new_messages(last_rowid=last_rowid, limit=limit)
    return process_messages(messages=messages, state=state, update_rowid=True, dry_run=False)


def process_backfill(weeks: int = 4, limit: int = 5000, dry_run: bool = True) -> dict[str, Any]:
    weeks = max(1, min(int(weeks), 26))
    since = datetime.now() - timedelta(weeks=weeks)
    state = load_state()
    messages = fetch_messages_since(since_dt=since, limit=limit)
    result = process_messages(messages=messages, state=state, update_rowid=False, dry_run=dry_run)
    result["mode"] = "backfill"
    result["since"] = since.isoformat()
    result["weeks"] = weeks
    return result


def get_status() -> dict[str, Any]:
    state = load_state()
    automation = state.get("automation", {})
    return {
        "success": True,
        "messages_db_exists": MESSAGES_DB.exists(),
        "state_file": str(STATE_FILE),
        "log_file": str(LOG_FILE),
        "watchlist": state.get("watchlist", []),
        "watchlist_count": len(state.get("watchlist", [])),
        "monitor_all": bool(state.get("monitor_all", False)),
        "last_rowid": int(state.get("last_rowid", 0)),
        "processed_count": int(state.get("processed_count", 0)),
        "last_check": state.get("last_check"),
        "last_processed_at": state.get("last_processed_at"),
        "last_error": state.get("last_error"),
        "automation": {
            "create_service_invoice_drafts": bool(automation.get("create_service_invoice_drafts", True)),
            "create_appointment_drafts": bool(automation.get("create_appointment_drafts", True)),
        },
        "keyword_discovery_enabled": bool(state.get("keyword_discovery_enabled", True)),
        "work_signal_threshold": max(1, int(state.get("work_signal_threshold", 2))),
        "invoice_drafts_file": str(INVOICE_DRAFTS_FILE),
        "appointment_drafts_file": str(APPOINTMENT_DRAFTS_FILE),
    }


def watch_loop(interval: int) -> None:
    print(f"iMessage watcher running every {interval}s")
    while True:
        try:
            result = process_once(limit=1000)
            print(
                f"[{result['checked_at']}] monitored={result['messages_monitored']} "
                f"logged={result['messages_logged']} tasks={result['tasks_created']}"
            )
        except Exception as exc:
            state = load_state()
            state["last_error"] = str(exc)
            state["last_check"] = now_iso()
            save_state(state)
            print(f"watcher error: {exc}")
        time.sleep(max(15, interval))


def main() -> int:
    parser = argparse.ArgumentParser(description="iMessage watcher")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--check", action="store_true", help="Process new monitored messages once")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval seconds")
    parser.add_argument("--set-watchlist", type=str, default="", help="Comma-separated numbers/emails to monitor")
    parser.add_argument("--clear-watchlist", action="store_true", help="Clear the watchlist")
    parser.add_argument("--monitor-all", action="store_true", help="Monitor all contacts")
    parser.add_argument("--set-monitor-all", type=str, default="", help="Set monitor_all true/false")
    parser.add_argument("--backfill-weeks", type=int, default=0, help="Backfill and process messages from last N weeks")
    parser.add_argument("--limit", type=int, default=1000, help="Message limit for check/backfill")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without creating logs/tasks/drafts")
    parser.add_argument("--set-auto-invoice-drafts", type=str, default="", help="Set invoice draft automation true/false")
    parser.add_argument("--set-auto-appointment-drafts", type=str, default="", help="Set appointment draft automation true/false")
    args = parser.parse_args()

    if args.set_auto_invoice_drafts or args.set_auto_appointment_drafts:
        def _to_bool(value: str) -> Optional[bool]:
            if value == "":
                return None
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            return None
        inv = _to_bool(args.set_auto_invoice_drafts)
        appt = _to_bool(args.set_auto_appointment_drafts)
        print(json.dumps(set_automation(inv, appt), indent=2))
        return 0
    if args.set_monitor_all:
        normalized = args.set_monitor_all.strip().lower()
        value = normalized in {"1", "true", "yes", "on"}
        print(json.dumps(set_monitor_all(value), indent=2))
        return 0

    if args.set_watchlist:
        items = [x.strip() for x in args.set_watchlist.split(",") if x.strip()]
        print(json.dumps(set_watchlist(items, monitor_all=args.monitor_all), indent=2))
        return 0
    if args.clear_watchlist:
        print(json.dumps(clear_watchlist(), indent=2))
        return 0
    if args.status:
        print(json.dumps(get_status(), indent=2))
        return 0
    if args.check:
        if args.dry_run:
            state = load_state()
            messages = fetch_new_messages(last_rowid=int(state.get("last_rowid", 0)), limit=max(1, int(args.limit)))
            print(json.dumps(process_messages(messages, state, update_rowid=False, dry_run=True), indent=2))
        else:
            print(json.dumps(process_once(limit=max(1, int(args.limit))), indent=2))
        return 0
    if args.backfill_weeks > 0:
        print(json.dumps(process_backfill(weeks=args.backfill_weeks, limit=max(1, int(args.limit)), dry_run=args.dry_run), indent=2))
        return 0
    if args.watch:
        watch_loop(interval=args.interval)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
