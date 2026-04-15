#!/usr/bin/env python3
"""
Apple Notes indexer — categorizes, scores, and exports data/notes_index.json.

Runs on the macOS host (Bob) with Notes.app; read-only toward Notes.

Usage:
  python3 integrations/apple_notes/notes_indexer.py --index
  python3 integrations/apple_notes/notes_indexer.py --index --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.apple_notes.notes_parser import (
    FolderInfo,
    NoteRecord,
    get_all_notes,
    get_folders,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("notes_indexer")

DATA_DIR = Path(os.environ.get("AI_SERVER_DATA", REPO_ROOT / "data")).resolve()
DEFAULT_OUTPUT = DATA_DIR / "notes_index.json"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("NOTES_INDEXER_OLLAMA_MODEL", "llama3.2:3b")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

CATEGORY_RULES: dict[str, list[str]] = {
    "access_codes": [
        r"wifi|ssid|password|passcode|alarm code|gate code|lock code|pin:|code:",
        r"\b\d{4,6}\b",
        r"\b192\.168\.\d+\.\d+\b",
    ],
    "project_reference": [],  # filled from project keywords
    "photo_log": [
        r"photo|picture|image|site photo|job site|install photo",
    ],
    "meeting_notes": [
        r"meeting|call|discussed|action item|follow up|next steps",
    ],
    "learning": [
        r"certification|exam|study|cedia|c4|control4|training|notes on|how to",
    ],
    "idea": [
        r"idea:|concept:|what if|could we|potential|brainstorm",
    ],
    "stale_draft": [],
}

ACCESS_CODE_PATTERNS = {
    "wifi_ssid": re.compile(r"(?:wifi|ssid|network)[:\s]+([^\n]+)", re.I),
    "wifi_password": re.compile(r"(?:wifi password|wpa|password)[:\s]+([^\n]+)", re.I),
    "alarm_code": re.compile(r"(?:alarm|security|disarm)[:\s#]*(\d{4,6})", re.I),
    "gate_code": re.compile(r"(?:gate|entry)[:\s#]*(\d{4,6})", re.I),
    "ip_address": re.compile(r"\b(192\.168\.\d{1,3}\.\d{1,3})\b"),
    "username": re.compile(r"(?:user|username|login)[:\s]+([^\n]+)", re.I),
}

_COMPILED: dict[str, list[re.Pattern[str]]] = {}


def _compile_rules(project_keywords: list[str]) -> None:
    global _COMPILED
    rules = {k: list(v) for k, v in CATEGORY_RULES.items()}
    rules["project_reference"] = [
        re.compile(p, re.I) for p in project_keywords if len(p) > 2
    ]
    _COMPILED = {}
    for cat, pats in rules.items():
        _COMPILED[cat] = []
        for p in pats:
            if isinstance(p, re.Pattern):
                _COMPILED[cat].append(p)
            else:
                _COMPILED[cat].append(re.compile(p, re.I))


def load_project_context() -> tuple[list[str], dict[str, str]]:
    """Return (keyword list for regex, project_slug -> display name)."""
    keywords: list[str] = []
    slug_names: dict[str, str] = {}
    kdir = REPO_ROOT / "knowledge"
    if not kdir.is_dir():
        return keywords, slug_names
    for cfg in kdir.glob("**/project-config.yaml"):
        try:
            raw = yaml.safe_load(cfg.read_text()) or {}
            proj = raw.get("project") or {}
            name = str(proj.get("name") or cfg.parent.name)
            addr = str(proj.get("address") or "")
            client = str(proj.get("client") or "")
            slug = cfg.parent.name.lower().replace(" ", "_")
            slug_names[slug] = name
            for part in (name, addr, client):
                if part and len(part) > 3:
                    keywords.append(re.escape(part))
            # road / property tokens
            for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", f"{name} {addr}"):
                if len(tok) > 4:
                    keywords.append(re.escape(tok))
        except Exception as exc:
            logger.warning("skip project config %s: %s", cfg, exc)
    # de-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq, slug_names


def load_client_names_from_sqlite(db_path: Path) -> list[str]:
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name, address FROM clients").fetchall()
        conn.close()
        out: list[str] = []
        for name, addr in rows:
            if name:
                out.append(re.escape(str(name)))
            if addr:
                out.append(re.escape(str(addr)))
        return out
    except Exception as exc:
        logger.warning("jobs.db read failed: %s", exc)
        return []


def match_project(text: str, slug_names: dict[str, str]) -> str | None:
    tl = text.lower()
    for slug, display in slug_names.items():
        if slug.replace("_", " ") in tl or display.lower() in tl:
            return display
        # last name heuristic
        parts = display.split()
        if parts and parts[-1].lower() in tl:
            return display
    return None


def keyword_category(note: NoteRecord) -> str | None:
    blob = f"{note.title}\n{note.body}"
    priority = [
        "access_codes",
        "photo_log",
        "meeting_notes",
        "learning",
        "idea",
        "project_reference",
    ]
    for cat in priority:
        for pat in _COMPILED.get(cat, []):
            try:
                if pat.search(blob):
                    return cat
            except re.error:
                continue
    return None


def classify_with_llm_sync(note: NoteRecord) -> str:
    prompt = f"""Classify this Apple Note into exactly one category.
Title: {note.title}
Content (first 300 chars): {note.body[:300]}

Categories: access_codes, project_reference, photo_log, meeting_notes, learning, idea, stale_draft, unknown
Reply with only the category name."""
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 32},
                },
            )
            r.raise_for_status()
            text = (r.json().get("response") or "").strip().lower()
            for c in (
                "access_codes",
                "project_reference",
                "photo_log",
                "meeting_notes",
                "learning",
                "idea",
                "stale_draft",
                "unknown",
            ):
                if c in text.split()[0] if text else "":
                    return c
            for c in (
                "access_codes",
                "project_reference",
                "photo_log",
                "meeting_notes",
                "learning",
                "idea",
                "stale_draft",
            ):
                if c in text:
                    return c
    except Exception as exc:
        logger.warning("LLM classify failed: %s", exc)
    return "unknown"


def _days_since_modified(note: NoteRecord) -> float:
    for raw in (note.modified_at, note.created_at):
        if not raw:
            continue
        try:
            try:
                from dateutil import parser as dtp

                dt = dtp.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
            except ImportError:
                pass
            m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw)
            if m:
                dt = datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
                )
                return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        except Exception:
            continue
    return 400.0


def _is_duplicate(note: NoteRecord, all_notes: list[NoteRecord]) -> bool:
    for other in all_notes:
        if other.note_id == note.note_id:
            continue
        if other.title.strip().lower() == note.title.strip().lower() and note.title.strip():
            return True
        if len(note.body) < 200 and note.body.strip():
            words_a = set(note.body.lower().split())
            words_b = set(other.body.lower().split())
            if words_a and words_b:
                inter = len(words_a & words_b)
                union = len(words_a | words_b)
                if union and inter / union > 0.8:
                    return True
    return False


def has_codes(note: NoteRecord) -> bool:
    blob = f"{note.title}\n{note.body}"
    if _COMPILED.get("access_codes"):
        for pat in _COMPILED["access_codes"]:
            if pat.search(blob):
                return True
    return False


def extract_codes(note: NoteRecord) -> list[str]:
    blob = f"{note.title}\n{note.body}"
    found: list[str] = []
    for label, pat in ACCESS_CODE_PATTERNS.items():
        for m in pat.finditer(blob):
            val = (m.group(1) if m.lastindex else m.group(0)).strip()
            if val:
                found.append(f"{label}: {val[:120]}")
    return found[:20]


def compute_value_score(
    note: NoteRecord,
    category: str,
    project_match: str | None,
    is_dup: bool,
) -> int:
    score = 0
    if note.has_attachments:
        score += 20
    if category == "access_codes" or has_codes(note):
        score += 30
    if project_match:
        score += 25
    if _days_since_modified(note) < 90:
        score += 15
    if len(note.body) > 100:
        score += 10
    if is_dup:
        score -= 50
    return max(0, min(100, score))


def suggest_action(
    note: NoteRecord,
    category: str,
    score: int,
    is_dup: bool,
) -> str:
    if is_dup:
        return "flag_for_deletion"
    if len(note.body.strip()) < 20 and not note.has_attachments:
        return "flag_for_deletion"
    if category == "stale_draft" and score < 40:
        return "flag_for_deletion"
    days = _days_since_modified(note)
    if days > 365 and not note.has_attachments and category not in ("access_codes",):
        if score < 45:
            return "flag_for_deletion"
    if (note.folder or "").lower() == "previous work" and category != "access_codes":
        return "archive"
    if category in ("unknown",) or (35 <= score < 50):
        return "needs_review"
    if score >= 50:
        return "keep"
    return "archive"


def one_line_summary(note: NoteRecord, category: str) -> str:
    parts = [category.replace("_", " ")]
    if note.has_attachments:
        parts.append("attachments")
    if has_codes(note):
        parts.append("codes/IPs")
    b = note.body.strip()[:80].replace("\n", " ")
    if b:
        parts.append(b)
    return "; ".join(parts)[:200]


def write_access_codes_md(
    project_display: str,
    rows: list[dict[str, Any]],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Access Codes — {project_display}",
        f"## Last updated: {now} (extracted from Apple Notes)",
        "",
        "| System | Credential | Value | Notes |",
        "|--------|------------|-------|-------|",
    ]
    for r in rows:
        lines.append(
            f"| {r.get('system', '')} | {r.get('credential', '')} | {r.get('value', '')} | {r.get('notes', '')} |"
        )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out_path)


def extract_codes_to_projects(
    indexed: list[dict[str, Any]],
    slug_names: dict[str, str],
) -> int:
    """Write access_codes.md for project-matched access_code notes."""
    saved = 0
    by_project: dict[str, list[dict[str, Any]]] = {}
    for row in indexed:
        if row.get("category") != "access_codes" and not row.get("has_codes"):
            continue
        proj = row.get("project")
        if not proj:
            continue
        slug = None
        for s, disp in slug_names.items():
            if disp == proj:
                slug = s
                break
        if not slug:
            slug = proj.lower().replace(" ", "_").replace(".", "")
        pairs = row.get("extracted_codes") or []
        for line in pairs:
            if ":" in line:
                k, _, v = line.partition(":")
                by_project.setdefault(slug, []).append(
                    {
                        "system": k.strip().replace("_", " ").title(),
                        "credential": "",
                        "value": v.strip()[:200],
                        "notes": row.get("title", "")[:80],
                    }
                )
    for slug, table in by_project.items():
        disp = slug_names.get(slug, slug.replace("_", " ").title())
        legacy_dir = REPO_ROOT / "knowledge" / slug
        if legacy_dir.is_dir():
            out_path = legacy_dir / "access_codes.md"
        else:
            out_path = REPO_ROOT / "knowledge" / "projects" / slug / "access_codes.md"
        write_access_codes_md(disp, table, out_path)
        saved += 1
    return saved


def build_report_text(summary: dict[str, Any], extracted_sets: int = 0) -> str:
    ba = summary.get("by_action", {})
    bc = summary.get("by_category", {})
    lines = [
        f"Apple Notes Audit Complete — {summary.get('total_notes', 0)} notes scanned",
        "",
        f"Keep ({ba.get('keep', 0)} notes):",
        f"  • {summary.get('notes_with_photos', 0)} with site photos",
        f"  • {summary.get('notes_with_codes', 0)} with access codes/passwords",
        f"  • {bc.get('project_reference', 0)} project references",
        "",
        f"Archive ({ba.get('archive', 0)} notes):",
        f"  • {bc.get('learning', 0)} learning notes",
        "",
        f"Flag for Deletion ({ba.get('flag_for_deletion', 0)} notes):",
        "  • Includes empty/near-empty, stale drafts, and likely duplicates",
        "",
        f"Needs Review ({ba.get('needs_review', 0)} notes):",
        "  • Might contain codes or project references",
        "",
        f"Extracted: {extracted_sets} set(s) of access codes saved to project folders.",
        f"Full index: {DEFAULT_OUTPUT}",
    ]
    return "\n".join(lines)


def send_report_imessage(body: str) -> None:
    try:
        import redis

        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
        r.publish(
            "notifications:trading",
            json.dumps({"title": "Apple Notes index", "body": body[:4000]}),
        )
        logger.info("Published notes report to Redis")
    except Exception as exc:
        logger.warning("Redis report failed: %s", exc)


def write_delete_candidates(index_payload: dict[str, Any], out_path: Path) -> int:
    """
    Export deletion candidates for manual review.

    Safety: this never modifies Apple Notes; it only writes a review file.
    """
    rows = index_payload.get("notes", [])
    candidates = [r for r in rows if r.get("action") == "flag_for_deletion"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(candidates),
        "notes": [
            {
                "note_id": r.get("note_id", ""),
                "title": r.get("title", ""),
                "folder": r.get("folder", ""),
                "category": r.get("category", ""),
                "value_score": r.get("value_score", 0),
                "summary": r.get("summary", ""),
            }
            for r in candidates
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote delete-candidate review file: %s", out_path)
    return len(candidates)


def run_index(
    output: Path,
    use_llm: bool,
    dry_run: bool,
) -> dict[str, Any]:
    proj_kw, slug_names = load_project_context()
    db_path = Path(
        os.environ.get("JOBS_DB_PATH", DATA_DIR / "jobs.db")
    )
    extra_kw = load_client_names_from_sqlite(db_path)
    _compile_rules(proj_kw + extra_kw)

    notes = get_all_notes()
    if not notes:
        logger.warning("No notes returned — is this macOS with Notes.app?")

    indexed: list[dict[str, Any]] = []
    by_cat: dict[str, int] = {}
    by_action: dict[str, int] = {}

    for note in notes:
        cat = keyword_category(note)
        if cat is None:
            if use_llm and len(note.body) > 30:
                cat = classify_with_llm_sync(note)
            else:
                cat = "stale_draft" if len(note.body) < 40 else "unknown"

        is_dup = _is_duplicate(note, notes)
        proj = match_project(f"{note.title}\n{note.body}", slug_names)
        score = compute_value_score(note, cat, proj, is_dup)
        action = suggest_action(note, cat, score, is_dup)
        codes = extract_codes(note) if cat == "access_codes" or has_codes(note) else []
        hc = bool(codes)

        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1

        indexed.append(
            {
                "note_id": note.note_id,
                "title": note.title,
                "folder": note.folder,
                "modified_at": note.modified_at[:10] if note.modified_at else "",
                "created_at": note.created_at[:10] if note.created_at else "",
                "category": cat,
                "project": proj,
                "value_score": score,
                "has_attachments": note.has_attachments,
                "attachment_count": note.attachment_count,
                "has_codes": hc,
                "action": action,
                "extracted_codes": codes,
                "summary": one_line_summary(note, cat),
                # Store first 3000 chars of body so notes_to_cortex.py can ingest
                "body": note.body[:3000] if note.body else "",
            }
        )

    summary = {
        "total_notes": len(notes),
        "by_category": by_cat,
        "by_action": by_action,
        "notes_with_photos": sum(1 for n in notes if n.has_attachments),
        "notes_with_codes": sum(1 for row in indexed if row["has_codes"]),
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "notes": indexed,
    }

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Wrote index: %s", output)

    return payload


def cmd_search(term: str) -> None:
    path = DEFAULT_OUTPUT
    if not path.is_file():
        logger.error("No index at %s — run --index first", path)
        return
    data = json.loads(path.read_text())
    t = term.lower()
    for row in data.get("notes", []):
        blob = f"{row.get('title','')} {row.get('summary','')}".lower()
        if t in blob or t in json.dumps(row).lower():
            print(f"- {row.get('title')}: {row.get('folder')} [{row.get('category')}]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Apple Notes indexer (macOS host)")
    ap.add_argument("--index", action="store_true", help="Build notes index")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON output path")
    ap.add_argument("--report", action="store_true", help="Send summary via Redis/iMessage bridge")
    ap.add_argument("--extract-codes", action="store_true", help="Write access_codes.md under knowledge/projects/")
    ap.add_argument("--folders", action="store_true", help="List Notes folders")
    ap.add_argument("--search", type=str, metavar="TERM", help="Search existing index JSON")
    ap.add_argument("--dry-run", action="store_true", help="Index without writing file")
    ap.add_argument("--no-llm", action="store_true", help="Skip Ollama for ambiguous notes")
    ap.add_argument(
        "--delete-flagged",
        action="store_true",
        help="Review deletion candidates (non-destructive; exports candidate file only)",
    )
    ap.add_argument(
        "--confirm",
        action="store_true",
        help="Required with --delete-flagged (safety guard)",
    )
    args = ap.parse_args()

    if args.folders:
        for f in get_folders():
            print(f"{f.name}\t{f.note_count}")
        return 0

    if args.search:
        cmd_search(args.search)
        return 0

    if args.delete_flagged and not args.confirm:
        logger.error("--delete-flagged requires --confirm")
        return 2

    if args.index or args.extract_codes or args.report:
        use_llm = not args.no_llm
        extracted_n = 0
        if args.index:
            payload = run_index(args.output, use_llm=use_llm, dry_run=args.dry_run)
        else:
            path = args.output
            if not path.is_file():
                logger.error("No index at %s — run --index first", path)
                return 1
            payload = json.loads(path.read_text(encoding="utf-8"))
        proj_kw, slug_names = load_project_context()
        if args.extract_codes and not args.dry_run:
            extracted_n = extract_codes_to_projects(payload["notes"], slug_names)
            logger.info("Wrote access_codes.md for %d project(s)", extracted_n)
        if args.report:
            txt = build_report_text(payload["summary"], extracted_sets=extracted_n)
            print(txt)
            if not args.dry_run:
                send_report_imessage(txt)
        if args.delete_flagged and not args.dry_run:
            candidates_path = DATA_DIR / "notes_delete_candidates.json"
            n = write_delete_candidates(payload, candidates_path)
            logger.warning(
                "Deletion is read-only by design. Review %d candidate(s) at %s",
                n,
                candidates_path,
            )
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
